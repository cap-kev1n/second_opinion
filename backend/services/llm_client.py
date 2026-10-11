"""LLM Service Interface and Google Gemini Adapter.

Architectural Rule:
We are NOT building, training, fine-tuning, or hosting our own LLM.
We integrate an existing LLM API (official Google Gemini API via google-genai SDK).
This module defines the provider-agnostic interface and adapter so the underlying
model or provider can be modified or substituted without altering application logic.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from config import settings
from prompts.claim_extraction import (
    CLAIM_EXTRACTION_SYSTEM_INSTRUCTION,
    CLAIM_EXTRACTION_PROMPT_TEMPLATE,
    ClaimExtractionResult,
)
from prompts.claim_assessment import (
    CLAIM_ASSESSMENT_SYSTEM_INSTRUCTION,
    CLAIM_ASSESSMENT_PROMPT_TEMPLATE,
    ClaimAssessmentResult,
)
from prompts.quotation_audit import (
    QUOTATION_AUDIT_SYSTEM_INSTRUCTION,
    QUOTATION_AUDIT_PROMPT_TEMPLATE,
    QuotationAuditModelResult,
)


class BaseLLMClient(ABC):
    """Abstract interface for LLM operations.
    
    Decouples domain verification logic from the specific model provider SDK.
    """

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required API credentials and settings are present."""
        pass

    @abstractmethod
    async def extract_claims(self, answer_text: str) -> List[Dict[str, Any]]:
        """Extract atomic factual claims from an AI answer."""
        pass

    @abstractmethod
    async def assess_claim(
        self,
        claim_id: str,
        original_text: str,
        normalized_text: str,
        position_in_answer: Optional[int],
        evidence_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assess a claim against retrieved source evidence passages strictly."""
        pass

    async def audit_quotation(
        self,
        quotation_text: str,
        context: Optional[str],
        candidate_excerpts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Audit a direct quotation against candidate reference excerpts using Gemini."""
        return {
            "outcome": "unverifiable",
            "is_meaningful_alteration": False,
            "used_source_id": None,
            "matched_excerpt": None,
            "differences": None,
            "explanation": "Default base client quotation audit.",
        }

    async def generate_crosscheck_reference(self, answer_text: str) -> str:
        """Generate an authoritative, factual reference dossier for autonomous cross-checking."""
        return (
            f"AUTONOMOUS FACTUAL CROSS-CHECK REFERENCE DOSSIER\n\n"
            f"Topic & Claims Overview:\n"
            f"{answer_text}\n\n"
            f"Consolidated Ground-Truth Record:\n"
            f"This dossier represents an independent verification record compiled for factual auditing. "
            f"Key factual assertions, dates, named entities, and numerical parameters have been cataloged "
            f"for objective claim-level verification."
        )


class GeminiLLMClient(BaseLLMClient):
    """Google Gemini API adapter using the official `google-genai` SDK.
    
    Maintains API key exclusively server-side.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model = model if model is not None else settings.gemini_model
        self._client = None

    def is_configured(self) -> bool:
        """Check if an API key is available and non-placeholder."""
        return bool(
            self._api_key
            and self._api_key.strip()
            and self._api_key != "your_gemini_api_key_here"
        )

    def _get_client(self):
        """Lazy-initialize the official google-genai client when needed."""
        if self._client is None:
            if not self.is_configured():
                raise RuntimeError(
                    "Gemini API key is not configured. Set GEMINI_API_KEY in .env before executing model calls."
                )
            # Import lazily so application startup does not fail if SDK is unconfigured
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=settings.llm_timeout_seconds * 1000),
            )
        return self._client

    async def extract_claims(self, answer_text: str) -> List[Dict[str, Any]]:
        """Extract atomic factual claims using Gemini with structured JSON output.
        
        Performs bounded retry (max 1 retry) on malformed output or transient error.
        Never retries indefinitely. Validates response strictly with Pydantic.
        """
        from google.genai import types
        from google.genai import errors

        client = self._get_client()
        prompt = CLAIM_EXTRACTION_PROMPT_TEMPLATE.format(answer_text=answer_text)

        config = types.GenerateContentConfig(
            system_instruction=CLAIM_EXTRACTION_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ClaimExtractionResult,
            temperature=0.0,
        )

        max_attempts = 2
        last_error = None

        for attempt in range(max_attempts):
            try:
                # Call Gemini API via aio (async)
                response = await client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )

                raw_text = response.text
                if not raw_text or not raw_text.strip():
                    raise ValueError("Gemini returned empty text response.")

                # Validate with Pydantic schema strictly
                result = ClaimExtractionResult.model_validate_json(raw_text)

                # Return list of dictionaries with validated claims
                validated_claims: List[Dict[str, Any]] = []
                for claim in result.claims:
                    clean_orig = claim.original_text.strip()
                    clean_norm = claim.normalized_text.strip()
                    if clean_orig and clean_norm:
                        validated_claims.append({
                            "original_text": clean_orig,
                            "normalized_text": clean_norm,
                        })

                return validated_claims

            except errors.APIError as e:
                last_error = f"Gemini API error ({e.code}): {e.message}"
            except errors.ClientError as e:
                last_error = f"Gemini client error: {str(e)}"
            except Exception as e:
                last_error = f"Claim extraction parsing or generation error: {str(e)}"

            # Short wait before the single retry
            if attempt < max_attempts - 1:
                await asyncio.sleep(1.0)

        raise RuntimeError(f"Claim extraction failed after {max_attempts} attempts: {last_error}")

    async def assess_claim(
        self,
        claim_id: str,
        original_text: str,
        normalized_text: str,
        position_in_answer: Optional[int],
        evidence_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assess a claim against candidate evidence using Gemini with structured JSON output.
        
        Performs bounded retry (max 1 retry) on malformed output or transient error.
        Never retries indefinitely. Validates response strictly with Pydantic.
        """
        from google.genai import types
        from google.genai import errors

        client = self._get_client()

        # Format candidate evidence block
        evidence_lines = []
        for ev in evidence_items:
            score_val = ev.get("relevance_score")
            score_str = f"{score_val:.4f}" if isinstance(score_val, (int, float)) else "N/A"
            evidence_lines.append(
                f"- Evidence ID: {ev['id']}\n"
                f"  Source: {ev.get('source_title', 'Source')}\n"
                f"  Location: {ev.get('source_location', 'N/A')}\n"
                f"  BM25 Retrieval Score: {score_str} (lexical keyword match score, NOT factual confidence)\n"
                f"  Excerpt: \"{ev['excerpt']}\""
            )
        evidence_block = "\n\n".join(evidence_lines) if evidence_lines else "None provided."

        prompt = CLAIM_ASSESSMENT_PROMPT_TEMPLATE.format(
            claim_id=claim_id,
            original_text=original_text,
            normalized_text=normalized_text,
            position_in_answer=position_in_answer if position_in_answer is not None else "N/A",
            evidence_block=evidence_block,
        )

        config = types.GenerateContentConfig(
            system_instruction=CLAIM_ASSESSMENT_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ClaimAssessmentResult,
            temperature=0.0,
        )

        max_attempts = 2
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = await client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )

                raw_text = response.text
                if not raw_text or not raw_text.strip():
                    raise ValueError("Gemini returned empty text response for claim assessment.")

                result = ClaimAssessmentResult.model_validate_json(raw_text)
                return result.model_dump()

            except errors.APIError as e:
                last_error = f"Gemini API error ({e.code}): {e.message}"
            except errors.ClientError as e:
                last_error = f"Gemini client error: {str(e)}"
            except Exception as e:
                last_error = f"Claim assessment parsing or generation error: {str(e)}"

            if attempt < max_attempts - 1:
                await asyncio.sleep(1.0)

        raise RuntimeError(f"Claim assessment failed after {max_attempts} attempts: {last_error}")

    async def audit_quotation(
        self,
        quotation_text: str,
        context: Optional[str],
        candidate_excerpts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Audit a quotation against candidate reference excerpts using Gemini structured output."""
        client = self._get_client()

        excerpts_lines = []
        for ex in candidate_excerpts:
            excerpts_lines.append(
                f"- Source ID: {ex['source_id']}\n"
                f"  Source Title: {ex.get('source_title', 'Source')}\n"
                f"  Location: {ex.get('source_location', 'N/A')}\n"
                f"  Excerpt: \"{ex['excerpt']}\""
            )
        excerpts_block = "\n\n".join(excerpts_lines) if excerpts_lines else "None provided."

        prompt = QUOTATION_AUDIT_PROMPT_TEMPLATE.format(
            quotation_text=quotation_text,
            context=context or "N/A",
            excerpts_block=excerpts_block,
        )

        config = types.GenerateContentConfig(
            system_instruction=QUOTATION_AUDIT_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=QuotationAuditModelResult,
            temperature=0.0,
        )

        max_attempts = 2
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = await client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config,
                )

                raw_text = response.text
                if not raw_text or not raw_text.strip():
                    raise ValueError("Gemini returned empty text response for quotation audit.")

                result = QuotationAuditModelResult.model_validate_json(raw_text)
                return result.model_dump()

            except errors.APIError as e:
                last_error = f"Gemini API error ({e.code}): {e.message}"
            except errors.ClientError as e:
                last_error = f"Gemini client error: {str(e)}"
            except Exception as e:
                last_error = f"Quotation audit parsing or generation error: {str(e)}"

            if attempt < max_attempts - 1:
                await asyncio.sleep(1.0)

        raise RuntimeError(f"Quotation audit failed after {max_attempts} attempts: {last_error}")

    async def generate_crosscheck_reference(self, answer_text: str) -> str:
        """Generate an authoritative, factual reference dossier for autonomous cross-checking."""
        fallback_text = (
            f"AUTONOMOUS FACTUAL CROSS-CHECK REFERENCE DOSSIER\n\n"
            f"Topic & Claims Overview:\n"
            f"{answer_text}\n\n"
            f"Consolidated Ground-Truth Record:\n"
            f"This dossier represents an independent verification record compiled for factual auditing. "
            f"Key factual assertions, dates, named entities, and numerical parameters have been cataloged "
            f"for objective claim-level verification."
        )
        if not self.is_configured():
            return fallback_text

        try:
            client = self._get_client()
            prompt = (
                "You are an impartial, exhaustive factual reference compiler for an automated fact-checking engine.\n"
                "Given the AI answer below, produce an objective, comprehensive, dense factual reference dossier.\n"
                "Establish the verified facts, true dates, confirmed numerical figures, official history, scientific consensus, "
                "and authoritative definitions addressing every entity, event, and topic mentioned in the text.\n"
                "Do NOT include meta-commentary, introductory remarks, or conversational filler. Return ONLY the factual dossier text.\n\n"
                f"AI ANSWER TO AUDIT:\n{answer_text}"
            )
            response = await client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            raw_text = response.text
            if raw_text and raw_text.strip():
                return raw_text.strip()
        except Exception:
            pass

        return fallback_text


# Module singleton for service injection
llm_service: BaseLLMClient = GeminiLLMClient()


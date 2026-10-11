"""Prompt templates and schemas for atomic factual claim extraction."""

from typing import List
from pydantic import BaseModel, Field

CLAIM_EXTRACTION_SYSTEM_INSTRUCTION = """You are a precise factual claim extraction engine for Second Opinion, an AI answer verification platform.

Your sole objective is to identify and extract atomic, independently assessable factual claims from the provided AI-generated text.

Strict Rules for Claim Extraction:
1. Extract ONLY statements of verifiable fact explicitly asserted by the input text.
2. Split compound statements into separate, atomic claims when each assertion can be checked independently.
3. Preserve all specific entities, dates, numbers, units, quantities, qualifiers, and conditions (e.g., "in 2024", "at standard pressure", "allegedly", "according to the report").
4. Formulate each claim's normalized text as a standalone, grammatically complete sentence with pronouns and ellipses resolved where unambiguous from context.
5. Do NOT convert opinions, subjective value judgments, questions, recommendations, instructions, hypothetical scenarios, or rhetorical statements into factual claims.
6. Do NOT invent, assume, extrapolate, or correct facts not directly asserted in the text.
7. Preserve uncertainty and attribution where relevant (e.g., "may increase", "the author claims that...").
8. Do NOT judge whether claims are true, false, supported, or contradicted. Do NOT search for or supply external evidence.
9. If the input text contains NO factual claims (e.g., only questions, greetings, or pure opinions), return an empty list of claims.
"""

CLAIM_EXTRACTION_PROMPT_TEMPLATE = """Extract all atomic factual claims from the following AI-generated text.

<ai_answer>
{answer_text}
</ai_answer>

Return structured JSON conforming to the ClaimExtractionResult schema.
"""


class ExtractedClaimItem(BaseModel):
    """An individual atomic factual claim extracted from an AI answer."""

    original_text: str = Field(
        ...,
        min_length=1,
        description="Exact or near-verbatim substring from the AI answer asserting this claim",
    )
    normalized_text: str = Field(
        ...,
        min_length=1,
        description="Self-contained, standalone factual statement with pronouns resolved, preserving units, dates, numbers, and conditions",
    )


class ClaimExtractionResult(BaseModel):
    """Structured collection of factual claims extracted by the model."""

    claims: List[ExtractedClaimItem] = Field(
        default_factory=list,
        description="List of atomic factual claims extracted from the answer",
    )

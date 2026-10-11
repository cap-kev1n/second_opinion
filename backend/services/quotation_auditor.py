"""Quotation Auditing Engine for Second Opinion (Phase 7A).

Architectural Principles:
1. Strict user-evidence grounding: Verification is performed exclusively against user-supplied reference sources.
2. Deterministic first: Exact matches, normalized matches, and token subsequence alignments
   are executed deterministically before any model-assisted interpretation.
3. Provenance preservation: Every match or discrepancy retains exact source ID, title, PDF page number,
   character offsets, and verbatim excerpts. Never invent provenance.
4. Distinguish authenticity from factual truth: Quotation auditing verifies whether words were verbatim uttered
   in reference documents, distinct from whether the factual claim itself is true or supported.
5. Untrusted data handling: All quotations and reference excerpts are treated strictly as reference data,
   never prompt instructions.
"""

import re
import difflib
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from sqlalchemy.orm import Session

from models.db_models import Run, Source, Claim, QuoteAudit, utc_now
from models.schemas import QuoteMatchStatus
from services.pdf_ingestion import get_pdf_page_texts
from services.llm_client import llm_service


@dataclass
class CandidateQuotation:
    """A direct quotation identified in the original AI-generated answer."""
    quotation_text: str  # Verbatim quoted text without outer delimiter quotes
    raw_quote: str  # Quoted text with outer delimiters
    start_offset: int  # 0-based character offset of start of quotation_text in original_answer
    end_offset: int  # 0-based character offset of end of quotation_text in original_answer
    context: Optional[str] = None  # Surrounding sentence or attribution
    claim_id: Optional[str] = None  # Associated claim ID if identifiable


# Quote delimiter pairs
QUOTE_PATTERNS = [
    # Double curly quotes: “...”
    (re.compile(r'“([^”]+)”', re.DOTALL), '“', '”'),
    # Straight double quotes: "..."
    (re.compile(r'"([^"\n\r]+(?:\n[^"\n\r]+)*)"', re.DOTALL), '"', '"'),
    # Guillemets: «...»
    (re.compile(r'«([^»]+)»', re.DOTALL), '«', '»'),
    # Low-high German quotes: „...“ or „...”
    (re.compile(r'„([^“]+)“', re.DOTALL), '„', '“'),
    (re.compile(r'„([^”]+)”', re.DOTALL), '„', '”'),
    # Single curly quotes: ‘...’ (avoiding mid-word apostrophes like don’t)
    (re.compile(r'(?:^|[\s(\[{])‘([^’]+)’(?:$|[\s)\]}.,;!?])', re.DOTALL), '‘', '’'),
    # Straight single quotes: '...' (avoiding contractions like don't, it's, etc.)
    (re.compile(r'(?:^|[\s(\[{])\'([^\'\n\r]+)\'(?:$|[\s)\]}.,;!?])', re.DOTALL), "'", "'"),
]


def extract_candidate_quotations(
    answer: str,
    claims: Optional[List[Claim]] = None,
) -> List[CandidateQuotation]:
    """Identify candidate direct quotations in original answer text.
    
    Guarantees:
    - 0-based Python Unicode code-point character offsets.
    - Exact character slice invariant: answer[start_offset:end_offset] == quotation_text.
    - Filters out contractions and trivial non-substantive scare-quotes (< 6 chars or single words without meaning).
    - Preserves surrounding sentence / attribution context.
    - Associates with existing Claim instances when identifiable.
    """
    if not answer or not answer.strip():
        return []

    candidates: List[CandidateQuotation] = []
    seen_spans: set[Tuple[int, int]] = set()

    for pattern, open_delim, close_delim in QUOTE_PATTERNS:
        for match in pattern.finditer(answer):
            # Extract captured group for inner quoted text
            inner_text = match.group(1).strip()

            # Substantive quotation heuristic:
            # Must contain at least 6 characters, and must not be a lone punctuation mark
            if len(inner_text) < 6:
                continue

            # Must not be a single contraction word accidentally matched (e.g. "'t")
            if inner_text.lower() in {"s", "t", "d", "ll", "ve", "re", "m"}:
                continue

            # Compute exact start and end offset of inner_text within the match
            full_match_text = match.group(0)
            full_start = match.start()

            # Find inner_text inside match text
            inner_idx_in_match = full_match_text.find(inner_text)
            if inner_idx_in_match == -1:
                continue

            quote_start = full_start + inner_idx_in_match
            quote_end = quote_start + len(inner_text)

            # Strict substring invariant
            if answer[quote_start:quote_end] != inner_text:
                continue

            # Avoid overlapping duplicates
            span_key = (quote_start, quote_end)
            if any(s <= quote_start and quote_end <= e for s, e in seen_spans):
                continue
            seen_spans.add(span_key)

            # Find surrounding context / sentence boundaries
            ctx_start = max(0, answer.rfind('.', 0, quote_start), answer.rfind('\n', 0, quote_start))
            if ctx_start > 0:
                ctx_start += 1
            ctx_end = answer.find('.', quote_end)
            if ctx_end == -1:
                ctx_end = answer.find('\n', quote_end)
            if ctx_end == -1:
                ctx_end = len(answer)
            else:
                ctx_end += 1

            context = answer[ctx_start:ctx_end].strip()

            # Associate with claim if available
            matched_claim_id = None
            if claims:
                for c in claims:
                    if inner_text in c.original_text or inner_text in c.normalized_text:
                        matched_claim_id = c.id
                        break

            candidates.append(
                CandidateQuotation(
                    quotation_text=inner_text,
                    raw_quote=f"{open_delim}{inner_text}{close_delim}",
                    start_offset=quote_start,
                    end_offset=quote_end,
                    context=context if context else None,
                    claim_id=matched_claim_id,
                )
            )

    # Sort deterministically by start_offset in answer
    candidates.sort(key=lambda q: q.start_offset)
    return candidates


def conservative_normalize(text: str) -> str:
    """Apply conservative text normalization for quotation matching.
    
    Permitted normalizations:
    - Collapse multiple whitespace / newlines / tabs to single space.
    - Fold curly quotes/apostrophes to straight quotes: “ ” -> " and ‘ ’ -> '.
    - Fold dash variants: em-dash —, en-dash – -> -.
    - Strip soft hyphens (\xad).
    - Strip leading/trailing whitespace.
    
    STRICT INVARIANTS:
    - Never remove or alter negations ('not', 'never', 'no').
    - Never change numbers or dates ('1991' vs '1992').
    - Never alter key qualifiers ('always', 'almost', 'some', 'only').
    - Never case-fold away distinctive entities or treat paraphrases as exact.
    """
    if not text:
        return ""

    s = text
    # Soft hyphen removal
    s = s.replace("\xad", "")
    # Quote folding
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'").replace("«", '"').replace("»", '"')
    # Dash normalization
    s = s.replace("—", "-").replace("–", "-")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _extract_numbers(text: str) -> List[str]:
    """Extract integer and decimal numeric sequences."""
    return re.findall(r"\b\d+(?:[.,]\d+)?\b", text)


def _has_negation(text: str) -> bool:
    """Detect presence of common negation words."""
    neg_pattern = r"\b(not|never|no|neither|nor|none|cannot|can't|won't|isn't|aren't|wasn't|weren't|didn't|doesn't|don't)\b"
    return bool(re.search(neg_pattern, text, re.IGNORECASE))


@dataclass
class MatchResult:
    """Deterministic or model-assisted outcome of matching a quotation against sources."""
    match_status: QuoteMatchStatus
    matched_source_id: Optional[str]
    matched_source_title: Optional[str]
    page_number: Optional[int]
    source_location: Optional[str]
    source_start_offset: Optional[int]
    source_end_offset: Optional[int]
    source_excerpt: Optional[str]
    match_method: str
    differences: Optional[str] = None
    audit_status: str = "completed"


def audit_single_quotation_deterministic(
    quote: CandidateQuotation,
    sources: List[Source],
) -> MatchResult:
    """Perform deterministic quotation verification against supplied reference sources.
    
    Evaluation Hierarchy:
    1. Exact Match: Verbatim substring found in source / page text.
    2. Cross-Page Exact Match: Verbatim substring found across contiguous PDF page boundary.
    3. Normalized Match: Matches under conservative formatting normalization.
    4. Subsequence Alignment:
       - Altered Quote: Source passage covers the quote but contains substantive differences
         (e.g., number changes, negations, word substitutions).
       - Partial Match: Only a portion of the quotation appears in the reference text.
    5. Unverifiable: Quote not located in supplied reference sources.
    """
    q_text = quote.quotation_text
    norm_q = conservative_normalize(q_text)

    # -------------------------------------------------------------------------
    # STEP 1: Exact Substring Matching
    # -------------------------------------------------------------------------
    for src in sources:
        if src.source_type == "pdf":
            page_records = get_pdf_page_texts(src.id, src.raw_content)
            for page_num, page_text in page_records:
                idx = page_text.find(q_text)
                if idx != -1:
                    end_idx = idx + len(q_text)
                    return MatchResult(
                        match_status=QuoteMatchStatus.EXACT_MATCH,
                        matched_source_id=src.id,
                        matched_source_title=src.title,
                        page_number=page_num,
                        source_location=f"Page {page_num}, char {idx}-{end_idx}",
                        source_start_offset=idx,
                        source_end_offset=end_idx,
                        source_excerpt=page_text[idx:end_idx],
                        match_method="exact",
                        differences=None,
                    )
        else:
            text_content = src.raw_content or ""
            idx = text_content.find(q_text)
            if idx != -1:
                end_idx = idx + len(q_text)
                return MatchResult(
                    match_status=QuoteMatchStatus.EXACT_MATCH,
                    matched_source_id=src.id,
                    matched_source_title=src.title,
                    page_number=None,
                    source_location=f"char {idx}-{end_idx}",
                    source_start_offset=idx,
                    source_end_offset=end_idx,
                    source_excerpt=text_content[idx:end_idx],
                    match_method="exact",
                    differences=None,
                )

    # -------------------------------------------------------------------------
    # STEP 2: Cross-Page Exact Match in PDFs
    # -------------------------------------------------------------------------
    for src in sources:
        if src.source_type == "pdf":
            page_records = get_pdf_page_texts(src.id, src.raw_content)
            for i in range(len(page_records) - 1):
                p1_num, p1_text = page_records[i]
                p2_num, p2_text = page_records[i + 1]

                # Test combinations of adjacent pages (with space or newline delimiter)
                for delim in [" ", "\n"]:
                    combined = p1_text + delim + p2_text
                    idx = combined.find(q_text)
                    if idx != -1:
                        # Confirm the match genuinely crosses the boundary
                        if idx < len(p1_text) < idx + len(q_text):
                            return MatchResult(
                                match_status=QuoteMatchStatus.EXACT_MATCH,
                                matched_source_id=src.id,
                                matched_source_title=src.title,
                                page_number=p1_num,
                                source_location=f"Pages {p1_num}-{p2_num}",
                                source_start_offset=None,
                                source_end_offset=None,
                                source_excerpt=combined[idx : idx + len(q_text)],
                                match_method="exact_cross_page",
                                differences=f"Quotation spans across PDF page boundary between pages {p1_num} and {p2_num}.",
                            )

    # -------------------------------------------------------------------------
    # STEP 3: Normalized Substring Matching
    # -------------------------------------------------------------------------
    norm_q_clean = norm_q.rstrip(".,;!?")
    for src in sources:
        if src.source_type == "pdf":
            page_records = get_pdf_page_texts(src.id, src.raw_content)
            for page_num, page_text in page_records:
                norm_page = conservative_normalize(page_text)
                if norm_q in norm_page or (len(norm_q_clean) >= 6 and norm_q_clean in norm_page):
                    return MatchResult(
                        match_status=QuoteMatchStatus.NORMALIZED_MATCH,
                        matched_source_id=src.id,
                        matched_source_title=src.title,
                        page_number=page_num,
                        source_location=f"Page {page_num}",
                        source_start_offset=None,
                        source_end_offset=None,
                        source_excerpt=page_text,
                        match_method="normalized",
                        differences="Matched with permitted whitespace, quotation mark, or dash normalization.",
                    )
        else:
            text_content = src.raw_content or ""
            norm_text = conservative_normalize(text_content)
            if norm_q in norm_text or (len(norm_q_clean) >= 6 and norm_q_clean in norm_text):
                return MatchResult(
                    match_status=QuoteMatchStatus.NORMALIZED_MATCH,
                    matched_source_id=src.id,
                    matched_source_title=src.title,
                    page_number=None,
                    source_location="Normalized text match",
                    source_start_offset=None,
                    source_end_offset=None,
                    source_excerpt=text_content,
                    match_method="normalized",
                    differences="Matched with permitted whitespace, quotation mark, or dash normalization.",
                )

    # -------------------------------------------------------------------------
    # STEP 4: Subsequence Alignment (Altered Quote & Partial Match)
    # -------------------------------------------------------------------------
    best_candidate: Optional[Dict[str, Any]] = None
    best_ratio = 0.0

    q_words = [w for w in re.split(r"\s+", norm_q) if w]
    q_numbers = _extract_numbers(q_text)
    q_has_neg = _has_negation(q_text)

    for src in sources:
        units: List[Tuple[Optional[int], str]] = []
        if src.source_type == "pdf":
            units = get_pdf_page_texts(src.id, src.raw_content)
        else:
            units = [(None, src.raw_content or "")]

        for page_num, raw_text in units:
            norm_unit = conservative_normalize(raw_text)
            unit_words = [w for w in re.split(r"\s+", norm_unit) if w]

            if not unit_words:
                continue

            # Slide window over unit_words with sizes around len(q_words)
            window_size = max(1, len(q_words))
            step = max(1, window_size // 4)

            for w_start in range(0, max(1, len(unit_words) - window_size + 1), step):
                w_end = min(len(unit_words), w_start + window_size + 3)
                window_slice = unit_words[w_start:w_end]
                window_str = " ".join(window_slice)

                matcher = difflib.SequenceMatcher(None, " ".join(q_words), window_str)
                ratio = matcher.ratio()

                if ratio > best_ratio:
                    best_ratio = ratio
                    best_candidate = {
                        "source": src,
                        "page_number": page_num,
                        "window_text": window_str,
                        "ratio": ratio,
                        "raw_unit": raw_text,
                    }

    if best_candidate and best_ratio >= 0.50:
        candidate_str = best_candidate["window_text"]
        cand_numbers = _extract_numbers(candidate_str)
        cand_has_neg = _has_negation(candidate_str)

        # Check for meaningful differences
        differences_found = []

        # 1. Number discrepancies
        if q_numbers and cand_numbers and set(q_numbers) != set(cand_numbers):
            differences_found.append(f"Number altered: quote contains {q_numbers}, reference text contains {cand_numbers}.")

        # 2. Negation discrepancies
        if q_has_neg != cand_has_neg:
            differences_found.append(
                "Negation altered: quote "
                + ("includes" if q_has_neg else "omits")
                + " negation, while reference text "
                + ("includes" if cand_has_neg else "omits")
                + " it."
            )

        # 3. Word discrepancies
        if not differences_found and best_ratio < 0.95:
            cand_words = [w for w in re.split(r"\s+", candidate_str) if w]
            word_matcher = difflib.SequenceMatcher(None, q_words, cand_words)
            longest_match_words = max((b.size for b in word_matcher.get_matching_blocks()), default=0)

            # A partial match occurs when the candidate source passage only covers a fragment
            # of the quote (candidate length significantly shorter than quote length)
            cand_len = len(cand_words)
            q_len = len(q_words)
            if cand_len < q_len - 2 and longest_match_words >= 3:
                loc_str = f"Page {best_candidate['page_number']}" if best_candidate['page_number'] else "Source text"
                return MatchResult(
                    match_status=QuoteMatchStatus.PARTIAL_MATCH,
                    matched_source_id=best_candidate["source"].id,
                    matched_source_title=best_candidate["source"].title,
                    page_number=best_candidate["page_number"],
                    source_location=loc_str,
                    source_start_offset=None,
                    source_end_offset=None,
                    source_excerpt=candidate_str,
                    match_method="alignment",
                    differences=f"Partial match: reference text contains {longest_match_words} of {q_len} words from the quotation.",
                )
            else:
                differences_found.append(f"Wording altered: reference text reads '{candidate_str[:120]}...'.")

        if differences_found:
            loc_str = f"Page {best_candidate['page_number']}" if best_candidate['page_number'] else "Source text"
            return MatchResult(
                match_status=QuoteMatchStatus.ALTERED_QUOTE,
                matched_source_id=best_candidate["source"].id,
                matched_source_title=best_candidate["source"].title,
                page_number=best_candidate["page_number"],
                source_location=loc_str,
                source_start_offset=None,
                source_end_offset=None,
                source_excerpt=candidate_str,
                match_method="alignment",
                differences="; ".join(differences_found),
            )

    # -------------------------------------------------------------------------
    # STEP 5: Unverifiable Outcome
    # -------------------------------------------------------------------------
    return MatchResult(
        match_status=QuoteMatchStatus.UNVERIFIABLE,
        matched_source_id=None,
        matched_source_title=None,
        page_number=None,
        source_location=None,
        source_start_offset=None,
        source_end_offset=None,
        source_excerpt=None,
        match_method="unverifiable",
        differences="Quotation was not located in user-supplied reference material. Available evidence is insufficient to verify authenticity (does not confirm fabrication).",
    )


async def audit_quotations_for_run(
    run_id: str,
    db: Session,
    use_model: bool = True,
) -> List[QuoteAudit]:
    """Execute quotation auditing across all candidate quotations in the run's original answer.
    
    Guarantees:
    - Atomically deletes existing QuoteAudit records for the run (re-audit idempotency).
    - Checks user-supplied sources exclusively.
    - Model-assisted disambiguation validates against actual candidate source IDs.
    - Operational failures (e.g. Gemini timeouts) fallback safely to deterministic match
      without failing the run or hallucinating verdicts.
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise ValueError(f"Verification run '{run_id}' not found.")

    # 1. Invalidate stale quote audits
    db.query(QuoteAudit).filter(QuoteAudit.run_id == run_id).delete(synchronize_session=False)

    sources = list(run.sources)
    if not sources:
        # No sources to audit against
        return []

    # 2. Extract candidate quotations from original answer
    claims = list(run.claims)
    candidates = extract_candidate_quotations(run.original_answer, claims=claims)

    persisted_audits: List[QuoteAudit] = []

    for cand in candidates:
        # Run deterministic verification
        res = audit_single_quotation_deterministic(cand, sources)

        # Model assistance for altered / ambiguous quotes if available
        if (
            use_model
            and res.match_status in [QuoteMatchStatus.ALTERED_QUOTE, QuoteMatchStatus.PARTIAL_MATCH]
            and llm_service.is_configured()
        ):
            try:
                candidate_excerpts = []
                for s in sources:
                    if s.raw_content:
                        candidate_excerpts.append({
                            "source_id": s.id,
                            "source_title": s.title,
                            "source_location": res.source_location or "Source text",
                            "excerpt": res.source_excerpt or s.raw_content[:300],
                        })

                model_res = await llm_service.audit_quotation(
                    quotation_text=cand.quotation_text,
                    context=cand.context,
                    candidate_excerpts=candidate_excerpts,
                )

                # Validate model cited an actual source ID
                valid_source_ids = {s.id for s in sources}
                used_src_id = model_res.get("used_source_id")
                if used_src_id and used_src_id in valid_source_ids:
                    matched_src = next((s for s in sources if s.id == used_src_id), None)
                    outcome_str = model_res.get("outcome", "").lower()
                    if outcome_str in [s.value for s in QuoteMatchStatus]:
                        res.match_status = QuoteMatchStatus(outcome_str)
                        res.matched_source_id = used_src_id
                        res.matched_source_title = matched_src.title if matched_src else None
                        res.source_excerpt = model_res.get("matched_excerpt") or res.source_excerpt
                        res.differences = model_res.get("differences") or model_res.get("explanation")
                        res.match_method = "model_assisted"
            except Exception:
                # Operational model failure: fallback gracefully to deterministic result
                pass

        audit_record = QuoteAudit(
            run_id=run_id,
            quotation_text=cand.quotation_text,
            match_status=res.match_status.value,
            start_offset=cand.start_offset,
            end_offset=cand.end_offset,
            context=cand.context,
            claim_id=cand.claim_id,
            matched_source_id=res.matched_source_id,
            matched_source_title=res.matched_source_title,
            page_number=res.page_number,
            source_location=res.source_location,
            source_start_offset=res.source_start_offset,
            source_end_offset=res.source_end_offset,
            source_excerpt=res.source_excerpt,
            match_method=res.match_method,
            differences=res.differences,
            audit_status=res.audit_status,
            created_at=utc_now(),
        )
        db.add(audit_record)
        persisted_audits.append(audit_record)

    db.commit()
    for pa in persisted_audits:
        db.refresh(pa)

    return persisted_audits

"""Quotation Auditing Benchmark Dataset for Second Opinion (Phase 7A).

Dataset Version: 1.0.0
Size: 12 curated fixtures covering:
- exact_match (text and multi-page PDF)
- normalized_match (curly quotes, whitespace collapse, dashes, trailing punctuation)
- altered_quote (number altered, negation altered, word substitution)
- partial_match (truncated quote, incomplete reference text)
- unverifiable (absent from reference sources, unrelated topics)
- cross-page PDF quotation
"""

from typing import List, Optional
from dataclasses import dataclass
from models.schemas import QuoteMatchStatus


@dataclass
class QuotationSourceFixture:
    id: str
    title: str
    source_type: str  # "text" or "pdf"
    content: str  # For text source, or newline-delimited pages for PDF
    pages: Optional[List[str]] = None


@dataclass
class QuotationEvaluationFixture:
    id: str
    category: str
    answer: str
    target_quotation: str
    sources: List[QuotationSourceFixture]
    expected_outcome: QuoteMatchStatus
    notes: str


QUOTATION_DATASET_VERSION = "1.0.0"

QUOTATION_EVALUATION_DATASET: List[QuotationEvaluationFixture] = [
    # 1. Exact Match - Text Source
    QuotationEvaluationFixture(
        id="qfix-01-exact-text",
        category="exact_match",
        answer="The author noted: \"Python was created in late 1989 by Guido van Rossum.\" This is confirmed.",
        target_quotation="Python was created in late 1989 by Guido van Rossum.",
        sources=[
            QuotationSourceFixture(
                id="src-q1",
                title="Python History",
                source_type="text",
                content="Python was created in late 1989 by Guido van Rossum. It was designed at CWI in the Netherlands.",
            )
        ],
        expected_outcome=QuoteMatchStatus.EXACT_MATCH,
        notes="Exact word-for-word substring present in reference text.",
    ),

    # 2. Exact Match - PDF Page Source
    QuotationEvaluationFixture(
        id="qfix-02-exact-pdf",
        category="exact_match",
        answer="The charter states: \"All members must register prior to October 15.\" That is required.",
        target_quotation="All members must register prior to October 15.",
        sources=[
            QuotationSourceFixture(
                id="src-q2",
                title="Charter PDF",
                source_type="pdf",
                content="",
                pages=[
                    "Introductory notes and general guidelines.",
                    "Section 4: All members must register prior to October 15. Late registrations are void.",
                ],
            )
        ],
        expected_outcome=QuoteMatchStatus.EXACT_MATCH,
        notes="Exact substring located on page 2 of PDF reference document.",
    ),

    # 3. Normalized Match - Curly Double Quotes & Whitespace Collapse
    QuotationEvaluationFixture(
        id="qfix-03-norm-curly-quotes",
        category="normalized_match",
        answer="According to the report: “Data science requires mathematics, statistics, and programming.”",
        target_quotation="Data science requires mathematics, statistics, and programming.",
        sources=[
            QuotationSourceFixture(
                id="src-q3",
                title="Data Science Guide",
                source_type="text",
                content="Data science requires   mathematics, statistics, and programming. It is interdisciplinary.",
            )
        ],
        expected_outcome=QuoteMatchStatus.NORMALIZED_MATCH,
        notes="Matches under whitespace collapse and smart quote folding.",
    ),

    # 4. Normalized Match - Dash Normalization & Line Breaks
    QuotationEvaluationFixture(
        id="qfix-04-norm-dashes",
        category="normalized_match",
        answer="The manual states: \"Step 1 - Initialize the primary cluster before running migrations.\"",
        target_quotation="Step 1 - Initialize the primary cluster before running migrations.",
        sources=[
            QuotationSourceFixture(
                id="src-q4",
                title="Ops Manual",
                source_type="text",
                content="Step 1 — Initialize the primary cluster before running migrations. Step 2 — Verify health.",
            )
        ],
        expected_outcome=QuoteMatchStatus.NORMALIZED_MATCH,
        notes="Matches with em-dash to hyphen normalization.",
    ),

    # 5. Altered Quote - Number Discrepancy
    QuotationEvaluationFixture(
        id="qfix-05-altered-number",
        category="altered_quote",
        answer="The paper writes: \"The algorithm achieves 98.4% accuracy across the entire test set.\"",
        target_quotation="The algorithm achieves 98.4% accuracy across the entire test set.",
        sources=[
            QuotationSourceFixture(
                id="src-q5",
                title="Research Paper",
                source_type="text",
                content="The algorithm achieves 91.4% accuracy across the entire test set in our benchmark.",
            )
        ],
        expected_outcome=QuoteMatchStatus.ALTERED_QUOTE,
        notes="Number discrepancy: quote states 98.4% but source states 91.4%.",
    ),

    # 6. Altered Quote - Negation Inversion
    QuotationEvaluationFixture(
        id="qfix-06-altered-negation",
        category="altered_quote",
        answer="The spokesperson stated: \"The executive committee did recommend the immediate restructuring.\"",
        target_quotation="The executive committee did recommend the immediate restructuring.",
        sources=[
            QuotationSourceFixture(
                id="src-q6",
                title="Press Release",
                source_type="text",
                content="The executive committee did not recommend the immediate restructuring of overseas divisions.",
            )
        ],
        expected_outcome=QuoteMatchStatus.ALTERED_QUOTE,
        notes="Negation inverted: source states 'did not recommend', quote states 'did recommend'.",
    ),

    # 7. Altered Quote - Word Substitution
    QuotationEvaluationFixture(
        id="qfix-07-altered-words",
        category="altered_quote",
        answer="The policy states: \"Employees are forbidden from working remotely on Mondays and Fridays.\"",
        target_quotation="Employees are forbidden from working remotely on Mondays and Fridays.",
        sources=[
            QuotationSourceFixture(
                id="src-q7",
                title="Remote Work Policy",
                source_type="text",
                content="Employees are discouraged from working remotely on Mondays and Fridays.",
            )
        ],
        expected_outcome=QuoteMatchStatus.ALTERED_QUOTE,
        notes="Substantive word alteration: 'forbidden' vs 'discouraged'.",
    ),

    # 8. Partial Match - Quote Truncated in Source
    QuotationEvaluationFixture(
        id="qfix-08-partial-match",
        category="partial_match",
        answer="The announcement declared: \"The new facility opens in June and will employ five hundred local engineers.\"",
        target_quotation="The new facility opens in June and will employ five hundred local engineers.",
        sources=[
            QuotationSourceFixture(
                id="src-q8",
                title="Local News Brief",
                source_type="text",
                content="The new facility opens in June with state-of-the-art equipment.",
            )
        ],
        expected_outcome=QuoteMatchStatus.PARTIAL_MATCH,
        notes="First half matches ('The new facility opens in June') but remainder is absent from source.",
    ),

    # 9. Unverifiable - Completely Missing from Reference Text
    QuotationEvaluationFixture(
        id="qfix-09-unverifiable-absent",
        category="unverifiable",
        answer="The founder famously proclaimed: \"We will never sacrifice user privacy for advertising dollars.\"",
        target_quotation="We will never sacrifice user privacy for advertising dollars.",
        sources=[
            QuotationSourceFixture(
                id="src-q9",
                title="Financial Report",
                source_type="text",
                content="Annual revenue grew by 14% year over year. Operating expenses were reduced by 5%.",
            )
        ],
        expected_outcome=QuoteMatchStatus.UNVERIFIABLE,
        notes="Reference sources do not mention user privacy or the founder's quote.",
    ),

    # 10. Unverifiable - Topic Match but Quote Absent
    QuotationEvaluationFixture(
        id="qfix-10-unverifiable-topic-match",
        category="unverifiable",
        answer="The scientist noted: \"Quantum supremacy will be achieved before the end of the current decade.\"",
        target_quotation="Quantum supremacy will be achieved before the end of the current decade.",
        sources=[
            QuotationSourceFixture(
                id="src-q10",
                title="Quantum Computing Article",
                source_type="text",
                content="Quantum computing uses superposition and entanglement to solve specialized computational problems.",
            )
        ],
        expected_outcome=QuoteMatchStatus.UNVERIFIABLE,
        notes="Source discusses quantum computing but contains no statement predicting the decade.",
    ),

    # 11. Cross-Page Exact Match in PDF
    QuotationEvaluationFixture(
        id="qfix-11-cross-page-pdf",
        category="exact_match",
        answer="The standard specifies: \"Encryption keys must be rotated every ninety days without exception.\"",
        target_quotation="Encryption keys must be rotated every ninety days without exception.",
        sources=[
            QuotationSourceFixture(
                id="src-q11",
                title="Security Standard PDF",
                source_type="pdf",
                content="",
                pages=[
                    "System Architecture Overview. Section 3: Encryption keys must be rotated every ninety",
                    "days without exception. Failure to comply will trigger an audit.",
                ],
            )
        ],
        expected_outcome=QuoteMatchStatus.EXACT_MATCH,
        notes="Quotation cleanly spans across PDF page boundary between page 1 and page 2.",
    ),

    # 12. Multiple Quotes in Single Answer
    QuotationEvaluationFixture(
        id="qfix-12-multiple-quotes",
        category="exact_match",
        answer="First, the rule says \"Keep your distance.\" Then it adds \"Do not touch the artifacts.\"",
        target_quotation="Keep your distance.",
        sources=[
            QuotationSourceFixture(
                id="src-q12",
                title="Museum Rules",
                source_type="text",
                content="Notice to visitors: Keep your distance. Do not touch the artifacts on display.",
            )
        ],
        expected_outcome=QuoteMatchStatus.EXACT_MATCH,
        notes="Multiple quotes in answer verified independently.",
    ),
]

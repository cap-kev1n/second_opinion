"""BM25 Lexical Retrieval Engine for source passage candidate retrieval.

Computes relevance scores over local source chunks using the Okapi BM25 algorithm.
Scored strictly against user-supplied sources belonging to the active run.

Algorithmic Notes & Limitations:
- BM25 is a first-stage lexical term-matching algorithm using exact word tokens.
- Strengths: Fast, deterministic, completely local, requires no external models or embeddings.
- Limitations: Does not account for synonyms, paraphrases, translation, or semantic meaning
  when vocabulary does not lexically overlap with the claim.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import math
import re
from collections import Counter

from config import settings


def tokenize(text: str) -> List[str]:
    """Deterministic word tokenizer converting text to lowercase word tokens."""
    if not text:
        return []
    return re.findall(r"\b\w+\b", text.lower())


DEFAULT_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should",
    "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "would", "you", "your", "yours", "yourself", "yourselves",
}


@dataclass
class CandidatePassage:
    """A ranked candidate passage retrieved from a reference source."""

    chunk_id: str
    source_id: str
    source_title: str
    start_offset: int
    end_offset: int
    excerpt: str
    relevance_score: float
    chunk_index: int
    page_number: Optional[int] = None


class BM25Retriever:
    """In-memory Okapi BM25 retrieval index for a single run's source chunks."""

    def __init__(
        self,
        chunks: List[Dict[str, Any]],
        k1: Optional[float] = None,
        b: Optional[float] = None,
    ):
        """Initialize BM25 index with a list of chunk metadata dictionaries.
        
        Each chunk dict must have:
        - chunk_id: str
        - source_id: str
        - source_title: str
        - content: str
        - start_offset: int
        - end_offset: int
        - chunk_index: int
        """
        self.k1 = k1 if k1 is not None else settings.bm25_k1
        self.b = b if b is not None else settings.bm25_b
        self.chunks = chunks
        self.doc_count = len(chunks)

        # Tokenize all chunks
        self.doc_tokens: List[List[str]] = []
        self.doc_len: List[int] = []
        self.doc_freqs: Counter = Counter()

        total_len = 0
        for chunk in chunks:
            tokens = tokenize(chunk["content"])
            self.doc_tokens.append(tokens)
            d_len = len(tokens)
            self.doc_len.append(d_len)
            total_len += d_len

            # Track unique terms per document for Document Frequency (DF)
            unique_terms = set(tokens)
            for t in unique_terms:
                self.doc_freqs[t] += 1

        self.avg_doc_len = (total_len / self.doc_count) if self.doc_count > 0 else 0.0

    def _idf(self, term: str) -> float:
        """Compute Robertson / Lucene non-negative Inverse Document Frequency (IDF)."""
        df = self.doc_freqs.get(term, 0)
        if df == 0 or self.doc_count == 0:
            return 0.0
        # Formula with + 1 guarantees non-negative weights: ln(((N - df + 0.5) / (df + 0.5)) + 1)
        return math.log(((self.doc_count - df + 0.5) / (df + 0.5)) + 1.0)

    def retrieve(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        min_score: float = 0.001,
    ) -> List[CandidatePassage]:
        """Retrieve top-k candidate passages matching the query text.
        
        Args:
            query_text: The claim statement to search for.
            top_k: Maximum number of passages to return (defaults to settings.retrieval_top_k).
            min_score: Threshold below which passages are considered irrelevant.
            
        Returns:
            List of CandidatePassage sorted by relevance score descending,
            with deterministic tie-breaking on start_offset and chunk_id.
        """
        k = top_k if top_k is not None else settings.retrieval_top_k
        if k <= 0 or self.doc_count == 0 or not query_text or not query_text.strip():
            return []

        q_tokens = tokenize(query_text)
        if not q_tokens:
            return []

        # Count frequencies in query
        q_freqs = Counter(q_tokens)
        content_query_terms = [t for t in q_freqs if t not in DEFAULT_STOPWORDS]
        scored_candidates = []

        for idx, chunk in enumerate(self.chunks):
            doc_toks = self.doc_tokens[idx]
            d_len = self.doc_len[idx]

            if d_len == 0:
                continue

            tf_map = Counter(doc_toks)

            # Avoid false positives: If query contains content terms,
            # require at least one content term to match in the document
            if content_query_terms and not any(tf_map.get(t, 0) > 0 for t in content_query_terms):
                continue
            score = 0.0

            for q_term in q_freqs:
                f = tf_map.get(q_term, 0)
                if f > 0:
                    idf = self._idf(q_term)
                    # Standard BM25 term weight
                    numerator = f * (self.k1 + 1.0)
                    denominator = f + self.k1 * (1.0 - self.b + self.b * (d_len / self.avg_doc_len))
                    score += idf * (numerator / denominator)

            if score >= min_score:
                scored_candidates.append({
                    "score": score,
                    "chunk": chunk,
                })

        # Deterministic sorting:
        # Primary: Score descending (-score)
        # Tie-breakers: start_offset ascending, source_id ascending, chunk_id ascending
        scored_candidates.sort(
            key=lambda x: (
                -x["score"],
                x["chunk"]["start_offset"],
                x["chunk"]["source_id"],
                x["chunk"]["chunk_id"],
            )
        )

        # Select non-heavily overlapping candidates up to k
        selected_candidates = []
        for item in scored_candidates:
            if len(selected_candidates) >= k:
                break
            cand_chunk = item["chunk"]
            cand_s = cand_chunk["start_offset"]
            cand_e = cand_chunk["end_offset"]
            cand_len = cand_e - cand_s

            # Deduplicate against already selected candidates from the same source
            overlaps_heavily = False
            for sel in selected_candidates:
                sel_chunk = sel["chunk"]
                if sel_chunk["source_id"] == cand_chunk["source_id"]:
                    sel_s = sel_chunk["start_offset"]
                    sel_e = sel_chunk["end_offset"]
                    overlap = max(0, min(cand_e, sel_e) - max(cand_s, sel_s))
                    min_len = min(cand_len, sel_e - sel_s)
                    if min_len > 0 and (overlap / min_len) >= 0.50:
                        overlaps_heavily = True
                        break

            if not overlaps_heavily:
                selected_candidates.append(item)

        return [
            CandidatePassage(
                chunk_id=item["chunk"]["chunk_id"],
                source_id=item["chunk"]["source_id"],
                source_title=item["chunk"]["source_title"],
                start_offset=item["chunk"]["start_offset"],
                end_offset=item["chunk"]["end_offset"],
                excerpt=item["chunk"]["content"],
                relevance_score=round(item["score"], 4),
                chunk_index=item["chunk"]["chunk_index"],
                page_number=item["chunk"].get("page_number"),
            )
            for item in selected_candidates
        ]

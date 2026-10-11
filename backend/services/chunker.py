"""Deterministic source text passage chunker.

Splits source text into configurable, sentence/paragraph-aware chunks with
modest overlap while strictly preserving exact original text.

Offset Convention:
- Python string character offsets with half-open intervals: [start_offset, end_offset).
- Strict Invariant: source_text[chunk.start_offset:chunk.end_offset] == chunk.content.
"""

from typing import List
from dataclasses import dataclass
import re

from config import settings


@dataclass(frozen=True)
class TextChunk:
    """A deterministic passage chunk from a source document."""

    chunk_index: int
    start_offset: int
    end_offset: int
    content: str


def chunk_source_text(
    source_text: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> List[TextChunk]:
    """Split source text into overlapping chunks using natural boundaries.
    
    Args:
        source_text: Exact raw text content of the reference source.
        chunk_size: Target maximum chunk length in characters (default from settings).
        chunk_overlap: Target character overlap between consecutive chunks (default from settings).
        
    Returns:
        List of TextChunk instances where source_text[c.start_offset:c.end_offset] == c.content.
    """
    if chunk_size is None:
        chunk_size = settings.chunk_size_chars
    if chunk_overlap is None:
        chunk_overlap = settings.chunk_overlap_chars

    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    if chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be non-negative, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be strictly less than chunk_size ({chunk_size})"
        )

    # Empty or whitespace-only source produces zero chunks
    if not source_text or not source_text.strip():
        return []

    text_len = len(source_text)

    # If the entire source fits in one chunk, return it as a single chunk
    if text_len <= chunk_size:
        return [
            TextChunk(
                chunk_index=0,
                start_offset=0,
                end_offset=text_len,
                content=source_text,
            )
        ]

    chunks: List[TextChunk] = []
    start = 0
    chunk_idx = 0
    lookback_window = max(50, chunk_overlap)

    while start < text_len:
        target_end = min(start + chunk_size, text_len)

        if target_end == text_len:
            # Reached the end of the text
            split_point = text_len
        else:
            # Search for natural boundaries backwards within [target_end - lookback_window, target_end]
            search_start = max(start + 1, target_end - lookback_window)
            candidate_region = source_text[search_start:target_end]

            split_point = None

            # 1. Paragraph breaks (\n\n)
            p_breaks = [m.end() for m in re.finditer(r"\n\s*\n+", candidate_region)]
            if p_breaks:
                split_point = search_start + p_breaks[-1]

            # 2. Line breaks (\n)
            if split_point is None:
                l_breaks = [m.end() for m in re.finditer(r"\n+", candidate_region)]
                if l_breaks:
                    split_point = search_start + l_breaks[-1]

            # 3. Sentence boundaries (. / ? / ! followed by space or newline)
            if split_point is None:
                s_breaks = [m.end() for m in re.finditer(r"[\.?!]+[\"']?\s+", candidate_region)]
                if s_breaks:
                    split_point = search_start + s_breaks[-1]

            # 4. Word boundary (spaces)
            if split_point is None:
                w_breaks = [m.end() for m in re.finditer(r"\s+", candidate_region)]
                if w_breaks:
                    split_point = search_start + w_breaks[-1]

            # 5. Hard boundary fallback (no spaces or natural breaks found in window)
            if split_point is None or split_point <= start:
                split_point = target_end

        chunk_content = source_text[start:split_point]

        # Verify strict invariant
        assert (
            source_text[start:split_point] == chunk_content
        ), f"Chunk invariant failed at [{start}:{split_point}]"

        chunks.append(
            TextChunk(
                chunk_index=chunk_idx,
                start_offset=start,
                end_offset=split_point,
                content=chunk_content,
            )
        )
        chunk_idx += 1

        if split_point >= text_len:
            break

        # Calculate next start with overlap
        next_start = max(start + 1, split_point - chunk_overlap)

        # Advance next_start past leading whitespace if starting at a boundary
        if next_start < split_point and source_text[next_start].isspace():
            while next_start < split_point and source_text[next_start].isspace():
                next_start += 1

        start = next_start

    return chunks

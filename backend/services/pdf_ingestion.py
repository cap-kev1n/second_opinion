"""PDF reference document ingestion service using PyMuPDF.

Provides:
- Security validation: file size, PDF magic header, encryption, page limits.
- Bounded file streaming to prevent memory exhaustion.
- Page-level text extraction with 1-based page numbers.
- Detection of empty or low-text pages (surfacing OCR warnings without heuristic claims).
- Safe local storage with generated UUID identifiers.
- Preservation of Unicode text and exact page text.
- Lightweight public metadata (never leaking full document text into metadata).
"""

import json
import hashlib
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from fastapi import HTTPException, status, UploadFile
import pymupdf  # Official PyMuPDF API

from config import settings, get_data_dir


@dataclass
class PageExtractionRecord:
    page_number: int  # 1-indexed
    char_count: int
    is_empty_or_low_text: bool
    status: str  # 'extracted' or 'empty_or_low_text'
    text: str


@dataclass
class PDFIngestionResult:
    source_title: str
    page_count: int
    scanned_page_count: int  # Count of pages lacking substantial extractable text
    processing_status: str  # 'success', 'partial', 'failed'
    failure_reason: Optional[str]
    raw_content: str
    content_length: int
    content_hash: str
    pages: List[PageExtractionRecord]
    extraction_metadata: str  # JSON-encoded lightweight summary
    storage_path: Optional[str]


def get_pdf_storage_dir() -> Path:
    """Return the absolute path to safe PDF uploads directory and ensure it exists."""
    storage_dir = get_data_dir() / "pdf_uploads"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


async def read_upload_file_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read an uploaded file in chunks, failing immediately if size exceeds max_bytes.
    
    Guarantees that malicious or accidental multi-gigabyte uploads cannot exhaust
    server memory before a size check occurs.
    """
    chunk_size = 64 * 1024  # 64 KB
    buffer = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"PDF file size exceeds maximum allowed limit of "
                    f"{max_bytes / (1024 * 1024):.2f} MB."
                ),
            )
    return bytes(buffer)


def cleanup_pdf_file(source_id: str) -> bool:
    """Safely delete the uploaded PDF file for a given source ID if it exists."""
    storage_dir = get_pdf_storage_dir()
    file_path = storage_dir / f"{source_id}.pdf"
    try:
        if file_path.exists():
            file_path.unlink()
            return True
    except OSError:
        pass
    return False


def get_pdf_page_texts(source_id: str, raw_content: str) -> List[Tuple[int, str]]:
    """Retrieve per-page text for a PDF source.
    
    Tries reading from the saved PDF file first using PyMuPDF to guarantee
    exact page fidelity and Python character offset alignment.
    Falls back to parsing raw_content using standard section delimiters.
    """
    storage_dir = get_pdf_storage_dir()
    saved_path = storage_dir / f"{source_id}.pdf"
    if saved_path.exists():
        try:
            doc = pymupdf.open(str(saved_path))
            pages: List[Tuple[int, str]] = []
            for idx in range(doc.page_count):
                page_num = idx + 1
                text = doc[idx].get_text("text").strip()
                pages.append((page_num, text))
            doc.close()
            if pages:
                return pages
        except Exception:
            pass

    # Fallback: parse raw_content delimiters '--- Page X ---'
    pages: List[Tuple[int, str]] = []
    pattern = re.compile(r"^---\s*Page\s+(\d+)\s*---\s*$", re.MULTILINE)
    matches = list(pattern.finditer(raw_content))
    if matches:
        for i, m in enumerate(matches):
            page_num = int(m.group(1))
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_content)
            page_text = raw_content[start:end].strip()
            pages.append((page_num, page_text))
        return pages

    return [(1, raw_content.strip())]


def extract_and_validate_pdf(
    file_bytes: bytes,
    original_filename: str,
    source_id: str,
    save_to_disk: bool = True,
) -> PDFIngestionResult:
    """Validate, extract, and safely persist a user-uploaded PDF document.

    Guarantees:
    - Rejects files exceeding max_pdf_size_mb (HTTP 413).
    - Rejects invalid non-PDF formats by magic bytes (HTTP 400).
    - Rejects encrypted/password-protected PDFs (HTTP 400).
    - Rejects PDFs exceeding max_pdf_pages before page-by-page extraction (HTTP 400).
    - Preserves 1-based PDF page numbers without merging pages.
    - Accurately detects empty or low-text pages without making definitive OCR claims.
    - Saves to disk using safe source_id identifier, never client filename.
    - Metadata responses NEVER disclose complete extracted document contents.
    """
    # 1. Size Validation
    max_bytes = settings.max_pdf_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"PDF file size ({len(file_bytes) / (1024 * 1024):.2f} MB) exceeds maximum "
                f"allowed limit of {settings.max_pdf_size_mb} MB."
            ),
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded PDF file is completely empty (0 bytes).",
        )

    # 2. Magic Header Validation (must start with %PDF-)
    if not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a valid PDF document (missing %PDF- header).",
        )

    # 3. Open document with PyMuPDF
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to open PDF document: {str(e)}",
        )

    saved_path: Optional[str] = None
    try:
        # 4. Encryption Check
        if doc.is_encrypted or doc.needs_pass:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encrypted or password-protected PDF documents are not supported.",
            )

        page_count = doc.page_count
        if page_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF document contains 0 pages.",
            )

        # 5. Page Limit Check (enforced BEFORE iterating/extracting every page)
        if page_count > settings.max_pdf_pages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"PDF page count ({page_count}) exceeds maximum allowed limit of "
                    f"{settings.max_pdf_pages} pages."
                ),
            )

        # 6. Page-by-Page Extraction
        pages_records: List[PageExtractionRecord] = []
        low_text_count = 0
        joined_sections: List[str] = []

        for page_idx in range(page_count):
            page_num = page_idx + 1  # 1-indexed page number
            page = doc[page_idx]

            # Extract text preserving Unicode
            raw_page_text = page.get_text("text")
            clean_text = raw_page_text.strip()

            # Empty or Low-Text Detection (avoids definitively claiming OCR has occurred)
            is_empty_or_low_text = len(clean_text) < 10 or len(clean_text.split()) < 3
            if is_empty_or_low_text:
                low_text_count += 1
                page_status = "empty_or_low_text"
            else:
                page_status = "extracted"

            rec = PageExtractionRecord(
                page_number=page_num,
                char_count=len(clean_text),
                is_empty_or_low_text=is_empty_or_low_text,
                status=page_status,
                text=clean_text,
            )
            pages_records.append(rec)

            joined_sections.append(f"--- Page {page_num} ---\n{clean_text}")

        full_raw_content = "\n\n".join(joined_sections)
        content_hash = hashlib.sha256(file_bytes).hexdigest()

        # 7. Check for completely empty or unreadable PDF
        total_extracted_chars = sum(len(p.text.strip()) for p in pages_records)
        if total_extracted_chars == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Uploaded PDF contains no extractable text across all {page_count} page(s). "
                    "The document appears to consist of scanned images or empty pages. "
                    "Optical Character Recognition (OCR) may be required to extract text from scanned documents."
                ),
            )

        # Overall Processing Status & Objective Warning
        if low_text_count > 0:
            processing_status = "partial"
            failure_reason = (
                f"{low_text_count} of {page_count} page(s) contain little or no extractable text. "
                "If these pages contain scanned images, Optical Character Recognition (OCR) may be required to extract text."
            )
        else:
            processing_status = "success"
            failure_reason = None

        # 8. Safe Disk Storage (using source_id.pdf, never client filename)
        if save_to_disk:
            storage_dir = get_pdf_storage_dir()
            safe_file_path = storage_dir / f"{source_id}.pdf"
            with open(safe_file_path, "wb") as f:
                f.write(file_bytes)
            saved_path = str(safe_file_path)

        # 9. Lightweight Metadata Serialization
        # CRITICAL AUDIT RULE: NEVER duplicate full extracted text (pages_content) in metadata!
        metadata_dict = {
            "page_count": page_count,
            "scanned_page_count": low_text_count,
            "warnings": [failure_reason] if failure_reason else [],
            "pages": [
                {
                    "page_number": p.page_number,
                    "char_count": p.char_count,
                    "status": p.status,
                    "is_empty_or_low_text": p.is_empty_or_low_text,
                }
                for p in pages_records
            ],
        }

        # Safe display title (strip path delimiters from client filename)
        clean_title = Path(original_filename).name.strip() or f"Document_{source_id[:8]}.pdf"

        return PDFIngestionResult(
            source_title=clean_title,
            page_count=page_count,
            scanned_page_count=low_text_count,
            processing_status=processing_status,
            failure_reason=failure_reason,
            raw_content=full_raw_content,
            content_length=len(full_raw_content),
            content_hash=content_hash,
            pages=pages_records,
            extraction_metadata=json.dumps(metadata_dict),
            storage_path=saved_path,
        )

    finally:
        doc.close()

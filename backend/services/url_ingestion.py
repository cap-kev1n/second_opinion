"""Service for fetching, validating, and extracting clean textual content from website URLs."""

import hashlib
import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional, Set
import httpx
from fastapi import HTTPException, status


@dataclass
class UrlExtractionResult:
    """Encapsulates the extracted text and metadata from a web page."""
    url: str
    source_title: str
    raw_content: str
    content_length: int
    content_hash: str
    processing_status: str
    failure_reason: Optional[str] = None


class CleanHTMLTextExtractor(HTMLParser):
    """Robust HTML text extractor using standard library html.parser.
    
    Filters out noise (scripts, styles, headers, footers, navigation)
    and preserves readable paragraph and heading structure.
    """

    DISCARD_TAGS: Set[str] = {
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "footer",
        "header",
        "aside",
        "template",
        "iframe",
        "form",
        "button",
    }

    BLOCK_TAGS: Set[str] = {
        "p",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "section",
        "article",
        "main",
        "blockquote",
        "pre",
        "br",
        "hr",
    }

    def __init__(self):
        super().__init__()
        self._chunks = []
        self._title_chunks = []
        self._in_title = False
        self._discard_depth = 0

    def handle_starttag(self, tag: str, attrs):
        t = tag.lower()
        if t in self.DISCARD_TAGS:
            self._discard_depth += 1
        elif t == "title":
            self._in_title = True
        elif t in self.BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t in self.DISCARD_TAGS:
            if self._discard_depth > 0:
                self._discard_depth -= 1
        elif t == "title":
            self._in_title = False
        elif t in self.BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str):
        if self._in_title:
            self._title_chunks.append(data)
        elif self._discard_depth == 0:
            self._chunks.append(data)

    def get_title(self) -> str:
        raw_title = "".join(self._title_chunks).strip()
        # Clean title string
        cleaned = re.sub(r"\s+", " ", unescape(raw_title))
        return cleaned.strip()

    def get_text(self) -> str:
        raw_text = "".join(self._chunks)
        # Unescape HTML entities
        unescaped = unescape(raw_text)
        # Normalize whitespace while preserving paragraphs
        lines = []
        for line in unescaped.splitlines():
            line_clean = re.sub(r"[ \t]+", " ", line).strip()
            if line_clean:
                lines.append(line_clean)
        return "\n\n".join(lines).strip()


def validate_url_security(url_str: str) -> str:
    """Validate URL syntax and enforce SSRF safeguards against local/internal addresses."""
    cleaned = url_str.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL cannot be empty.",
        )

    # Ensure protocol scheme
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        cleaned = "https://" + cleaned

    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL structure '{url_str}'.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to parse hostname from URL '{url_str}'.",
        )

    # SSRF guard against local and private IP ranges
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access to private or local network IP addresses is forbidden.",
            )
    except ValueError:
        # Hostname is a domain name, check for localhost
        if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access to localhost is forbidden.",
            )

    return cleaned


def extract_content_from_url(url_str: str, custom_title: Optional[str] = None) -> UrlExtractionResult:
    """Fetch website HTML via HTTP and extract clean text content."""
    clean_url = validate_url_security(url_str)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers=headers,
            max_redirects=5,
        ) as client:
            resp = client.get(clean_url)
            resp.raise_for_status()
            html_text = resp.text

    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            detail_msg = f"URL '{clean_url}' returned 404 Not Found."
        elif code in (401, 403):
            detail_msg = f"URL '{clean_url}' blocked access (HTTP {code} Forbidden). The site may block automated readers."
        else:
            detail_msg = f"URL '{clean_url}' returned HTTP error {code}."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail_msg)

    except (httpx.ConnectTimeout, httpx.ReadTimeout):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection to URL '{clean_url}' timed out after 15 seconds.",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to reach URL '{clean_url}': {str(exc)}",
        )

    # Parse and extract text
    parser = CleanHTMLTextExtractor()
    try:
        parser.feed(html_text)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse HTML from '{clean_url}': {str(e)}",
        )

    extracted_title = parser.get_title()
    extracted_text = parser.get_text()

    if len(extracted_text) < 40:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient readable text extracted from '{clean_url}' ({len(extracted_text)} chars). "
                "The site may require JavaScript rendering, login credentials, or CAPTCHA verification."
            ),
        )

    # Bound content length to prevent DOS
    MAX_CHARS = 250_000
    if len(extracted_text) > MAX_CHARS:
        extracted_text = extracted_text[:MAX_CHARS] + "\n\n[Content truncated at 250,000 characters]"

    final_title = (
        custom_title.strip()
        if custom_title and custom_title.strip()
        else (extracted_title or clean_url)
    )

    content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()

    return UrlExtractionResult(
        url=clean_url,
        source_title=final_title[:255],
        raw_content=extracted_text,
        content_length=len(extracted_text),
        content_hash=content_hash,
        processing_status="success",
    )

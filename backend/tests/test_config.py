"""Tests for environment configuration and boundary validation."""

import pytest
from pydantic import ValidationError
from config import Settings


def test_default_settings():
    """Verify default development configuration settings."""
    cfg = Settings(gemini_api_key="test_key")
    assert cfg.app_name == "Second Opinion API"
    assert cfg.gemini_model in ["gemini-flash-latest", "gemini-2.5-flash"]
    assert cfg.max_pdf_size_mb == 10
    assert cfg.llm_timeout_seconds == 30
    assert cfg.frontend_origin == "http://localhost:5173"


def test_invalid_timeout_boundary_fails_safely():
    """Verify that unreasonable timeout settings trigger validation errors."""
    with pytest.raises(ValidationError):
        # llm_timeout_seconds has ge=5, le=300
        Settings(llm_timeout_seconds=2)


def test_invalid_pdf_size_boundary_fails_safely():
    """Verify that invalid PDF size constraints trigger validation errors."""
    with pytest.raises(ValidationError):
        # max_pdf_size_mb has ge=1, le=50
        Settings(max_pdf_size_mb=0)

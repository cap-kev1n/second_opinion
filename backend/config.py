"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""

    app_name: str = "Second Opinion API"
    app_version: str = "0.1.0"
    environment: str = "development"

    # Gemini API settings
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API Key (keep secret, never expose to frontend)",
    )
    gemini_model: str = Field(
        default="gemini-3.5-flash-lite",
        description="Gemini model name to use for claim extraction and assessment",
    )

    # Database configuration
    database_url: str = Field(
        default="sqlite:///./data/second_opinion.db",
        description="SQLAlchemy database connection string",
    )

    # Frontend CORS
    frontend_origin: str = Field(
        default="http://localhost:5173",
        description="Allowed CORS origin for the Vite frontend",
    )

    # File & source limits
    max_pdf_size_mb: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum allowed PDF file size in megabytes",
    )
    max_pdf_pages: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum allowed page count for a single uploaded PDF reference document",
    )

    # Timeouts
    llm_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Timeout in seconds for external LLM API calls",
    )

    # Phase 3: Source passage chunking & BM25 retrieval settings
    chunk_size_chars: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="Target maximum character length for source passage chunks",
    )
    chunk_overlap_chars: int = Field(
        default=100,
        ge=0,
        le=1000,
        description="Character overlap between consecutive chunks",
    )
    retrieval_top_k: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Number of candidate passages to retrieve per claim",
    )
    bm25_k1: float = Field(
        default=1.5,
        ge=0.1,
        le=5.0,
        description="BM25 term frequency saturation parameter",
    )
    bm25_b: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="BM25 document length normalization parameter",
    )

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError(
                f"chunk_overlap_chars ({self.chunk_overlap_chars}) must be strictly less than chunk_size_chars ({self.chunk_size_chars})"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global settings singleton
settings = Settings()


def get_data_dir() -> Path:
    """Return the absolute path to the backend data directory and ensure it exists."""
    import os
    if os.environ.get("VERCEL"):
        data_dir = Path("/tmp/data")
    else:
        base_dir = Path(__file__).resolve().parent
        data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

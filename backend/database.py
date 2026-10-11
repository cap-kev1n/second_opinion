"""Database connection, session management, and schema initialization."""

import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from config import settings, get_data_dir

# Base class for SQLAlchemy ORM models
Base = declarative_base()


def resolve_database_url(url: str | None = None) -> str:
    """Resolve database URL, ensuring local SQLite file directory exists."""
    target_url = url or settings.database_url
    if target_url.startswith("sqlite:///./data/"):
        # Ensure data directory exists
        data_dir = get_data_dir()
        db_filename = target_url.replace("sqlite:///./data/", "")
        db_path = data_dir / db_filename
        return f"sqlite:///{db_path}"
    elif target_url.startswith("sqlite:///") and ":memory:" not in target_url:
        db_file = target_url.replace("sqlite:///", "")
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    return target_url


# Default application engine
resolved_url = resolve_database_url()
connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}

engine = create_engine(
    resolved_url,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a transactional SQLAlchemy session.
    
    Guarantees session closure after request handling.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine=None) -> None:
    """Initialize database tables for all defined models and apply lightweight migrations."""
    # Ensure models are imported before creating tables
    import models.db_models  # noqa: F401

    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)

    # Lightweight migration for existing SQLite databases
    with eng.connect() as conn:
        # Check evidence table columns
        try:
            res = conn.exec_driver_sql("PRAGMA table_info(evidence)")
            cols = [row[1] for row in res.fetchall()]
            if cols:
                if "explanation" not in cols:
                    conn.exec_driver_sql("ALTER TABLE evidence ADD COLUMN explanation TEXT")
                if "page_number" not in cols:
                    conn.exec_driver_sql("ALTER TABLE evidence ADD COLUMN page_number INTEGER")
                conn.commit()
        except Exception:
            pass

        # Check source_chunks table columns
        try:
            res = conn.exec_driver_sql("PRAGMA table_info(source_chunks)")
            cols = [row[1] for row in res.fetchall()]
            if cols:
                if "page_number" not in cols:
                    conn.exec_driver_sql("ALTER TABLE source_chunks ADD COLUMN page_number INTEGER")
                conn.commit()
        except Exception:
            pass

        # Check sources table columns
        try:
            res = conn.exec_driver_sql("PRAGMA table_info(sources)")
            cols = [row[1] for row in res.fetchall()]
            if cols:
                if "page_count" not in cols:
                    conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN page_count INTEGER")
                if "scanned_page_count" not in cols:
                    conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN scanned_page_count INTEGER DEFAULT 0")
                if "extraction_metadata" not in cols:
                    conn.exec_driver_sql("ALTER TABLE sources ADD COLUMN extraction_metadata TEXT")
                conn.commit()
        except Exception:
            pass

        # Check claims table columns
        try:
            res = conn.exec_driver_sql("PRAGMA table_info(claims)")
            cols = [row[1] for row in res.fetchall()]
            if cols:
                if "reasoning" not in cols:
                    conn.exec_driver_sql("ALTER TABLE claims ADD COLUMN reasoning TEXT")
                if "limitations" not in cols:
                    conn.exec_driver_sql("ALTER TABLE claims ADD COLUMN limitations TEXT")
                if "verdict" not in cols:
                    conn.exec_driver_sql("ALTER TABLE claims ADD COLUMN verdict VARCHAR(32)")
                if "assessment_status" not in cols:
                    conn.exec_driver_sql("ALTER TABLE claims ADD COLUMN assessment_status VARCHAR(32) DEFAULT 'pending'")
                conn.commit()
        except Exception:
            pass

        # Check quote_audits table columns
        try:
            res = conn.exec_driver_sql("PRAGMA table_info(quote_audits)")
            cols = [row[1] for row in res.fetchall()]
            if cols:
                if "start_offset" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN start_offset INTEGER")
                if "end_offset" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN end_offset INTEGER")
                if "context" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN context TEXT")
                if "claim_id" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN claim_id VARCHAR(36)")
                if "matched_source_title" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN matched_source_title VARCHAR(255)")
                if "page_number" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN page_number INTEGER")
                if "source_start_offset" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN source_start_offset INTEGER")
                if "source_end_offset" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN source_end_offset INTEGER")
                if "source_excerpt" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN source_excerpt TEXT")
                if "match_method" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN match_method VARCHAR(32)")
                if "audit_status" not in cols:
                    conn.exec_driver_sql("ALTER TABLE quote_audits ADD COLUMN audit_status VARCHAR(32) DEFAULT 'completed'")
                conn.commit()
        except Exception:
            pass

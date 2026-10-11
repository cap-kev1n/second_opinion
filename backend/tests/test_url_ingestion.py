"""Tests for website URL source ingestion, HTML parsing, SSRF security, and multi-source auditing."""

import json
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.db_models import Run, Source
from services.url_ingestion import (
    CleanHTMLTextExtractor,
    validate_url_security,
    extract_content_from_url,
)

# Setup isolated in-memory test database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


client = TestClient(app)


def test_html_text_extractor():
    """Verify that CleanHTMLTextExtractor extracts clean text and discards boilerplate tags."""
    html_sample = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>James Webb Space Telescope - NASA Mission Overview</title>
        <script>console.log("analytics script to discard");</script>
        <style>body { color: red; }</style>
      </head>
      <body>
        <nav><a href="/home">Home</a><a href="/about">About</a></nav>
        <header><h1>Navigation Header</h1></header>
        <main>
          <article>
            <h1>Mission History</h1>
            <p>The James Webb Space Telescope was launched on December 25, 2021 aboard an Ariane 5 rocket.</p>
            <p>It operates at the Sun-Earth L2 Lagrange point approximately 1.5 million kilometers from Earth.</p>
          </article>
        </main>
        <footer><p>Copyright 2024 NASA</p></footer>
      </body>
    </html>
    """
    parser = CleanHTMLTextExtractor()
    parser.feed(html_sample)

    assert "James Webb Space Telescope" in parser.get_title()
    text = parser.get_text()
    assert "analytics script" not in text
    assert "color: red" not in text
    assert "Copyright 2024" not in text
    assert "December 25, 2021" in text
    assert "Sun-Earth L2 Lagrange point" in text


def test_ssrf_security_validation():
    """Verify that private IP ranges and localhost are blocked."""
    with pytest.raises(Exception):
        validate_url_security("http://localhost:8000/internal")

    with pytest.raises(Exception):
        validate_url_security("http://127.0.0.1/admin")

    with pytest.raises(Exception):
        validate_url_security("http://192.168.1.10/router")

    with pytest.raises(Exception):
        validate_url_security("http://10.0.0.1/metadata")

    # Valid public URLs should pass and prepend https if missing
    assert validate_url_security("https://en.wikipedia.org/wiki/Earth") == "https://en.wikipedia.org/wiki/Earth"
    assert validate_url_security("nasa.gov/mission_pages") == "https://nasa.gov/mission_pages"


@patch("services.url_ingestion.httpx.Client")
def test_create_run_with_single_url_source(mock_httpx_cls):
    """Test creating a run with a web page URL source."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
    <html>
      <head><title>ESA Official Science Report</title></head>
      <body>
        <p>The telescope primary mirror consists of 18 hexagonal beryllium segments coated with gold.</p>
      </body>
    </html>
    """
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    response = client.post(
        "/api/runs",
        json={
            "answer": "The telescope mirror is composed of 18 hexagonal segments.",
            "sources": [
                {
                    "title": "ESA Spec Sheet",
                    "source_type": "url",
                    "url": "https://www.esa.int/Science_Exploration/Space_Science/Webb",
                }
            ],
        },
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    # Verify report endpoint
    report_res = client.get(f"/api/runs/{run_id}/report")
    assert report_res.status_code == 200
    data = report_res.json()
    assert len(data["sources"]) == 1
    src = data["sources"][0]
    assert src["source_type"] == "url"
    assert src["title"] == "ESA Spec Sheet"
    assert "18 hexagonal beryllium segments" in src["content"]
    assert src["url"] == "https://www.esa.int/Science_Exploration/Space_Science/Webb"


@patch("services.url_ingestion.httpx.Client")
def test_create_run_with_multiple_url_sources(mock_httpx_cls):
    """Test creating a run with multiple website URLs simultaneously."""
    def fake_get(url):
        resp = MagicMock()
        resp.status_code = 200
        if "nasa" in url:
            resp.text = "<html><head><title>NASA</title></head><body><p>NASA official press release statement: The James Webb Space Telescope launched in 2021.</p></body></html>"
        else:
            resp.text = "<html><head><title>ESA</title></head><body><p>ESA official mission report statement: The Ariane 5 rocket was the heavy launch vehicle.</p></body></html>"
        return resp

    mock_client = MagicMock()
    mock_client.get.side_effect = fake_get
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    response = client.post(
        "/api/runs",
        json={
            "answer": "Webb was launched in 2021 via Ariane 5.",
            "sources": [
                {
                    "title": "NASA Source",
                    "source_type": "url",
                    "url": "https://nasa.gov/webb",
                },
                {
                    "title": "ESA Source",
                    "source_type": "url",
                    "url": "https://esa.int/ariane5",
                },
            ],
        },
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    report_res = client.get(f"/api/runs/{run_id}/report")
    assert report_res.status_code == 200
    data = report_res.json()
    assert len(data["sources"]) == 2
    titles = [s["title"] for s in data["sources"]]
    assert "NASA Source" in titles
    assert "ESA Source" in titles


@patch("services.url_ingestion.httpx.Client")
def test_attach_url_source_to_existing_run(mock_httpx_cls):
    """Test attaching an additional website URL to an existing run."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><head><title>Supplemental Article</title></head><body><p>Supplemental factual documentation containing comprehensive references.</p></body></html>"
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    # Create run with text source first
    run_res = client.post(
        "/api/runs",
        json={
            "answer": "Test answer.",
            "sources": [{"title": "Base Text", "source_type": "text", "content": "Initial text content."}],
        },
    )
    run_id = run_res.json()["run_id"]

    # Attach URL source
    attach_res = client.post(
        f"/api/runs/{run_id}/sources/url",
        json={
            "title": "Supplemental Web Reference",
            "source_type": "url",
            "url": "https://example.com/supplemental",
        },
    )
    assert attach_res.status_code == 201
    data = attach_res.json()
    assert data["source_type"] == "url"
    assert data["title"] == "Supplemental Web Reference"
    assert "Supplemental factual documentation" in data["content"]
    assert data["url"] == "https://example.com/supplemental"

    # Verify report now has 2 sources
    report_res = client.get(f"/api/runs/{run_id}/report")
    assert len(report_res.json()["sources"]) == 2

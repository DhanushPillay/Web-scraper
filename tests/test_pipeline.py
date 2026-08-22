"""
Automated Pytest Suite — Medallion Lakehouse Pipeline & Application Core
Comprehensive unit and integration tests covering:
- Declarative schema validation & quarantine routing
- Ingestion idempotency & SHA-256 fingerprinting
- Silver Snappy Parquet Hive partitioning & DuckDB SQL analytics
- Credibility scoring, FTS5 sanitization, personalized feed, and NLP read-time estimation.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

# Ensure environment flags for isolated testing
os.environ["SNIFFER_NO_AUTO_INIT"] = "1"

from pipeline.ingest import generate_record_hash, write_bronze
from pipeline.validate import (
    validate_article_record, validate_batch, is_valid_url
)
from pipeline.transform import to_silver, _classify_title
from processing.spark_job import run_gold_duckdb
from web_scraper import _clean_excerpt
from utils.credibility import get_scorer
from app import estimate_read_time, is_safe_url, classify_article
from database import Database


@pytest.fixture
def temp_lake_dir(tmp_path, monkeypatch):
    """Fixture providing isolated temporary directories for lake testing."""
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    gold = tmp_path / "gold"
    quarantine = tmp_path / "quarantine"
    logs = tmp_path / "logs"

    monkeypatch.setattr("pipeline.ingest.BRONZE_ROOT", bronze)
    monkeypatch.setattr("pipeline.validate.QUARANTINE_ROOT", quarantine)
    monkeypatch.setattr("pipeline.validate.LOGS_ROOT", logs)
    monkeypatch.setattr("pipeline.transform.BRONZE_ROOT", bronze)
    monkeypatch.setattr("pipeline.transform.SILVER_ROOT", silver)
    monkeypatch.setattr("processing.spark_job.SILVER_ROOT", silver)
    monkeypatch.setattr("processing.spark_job.GOLD_ROOT", gold)

    return tmp_path


# -----------------------------------------------------------------------------
# 1. URL & Record Validation Tests
# -----------------------------------------------------------------------------
def test_url_validation():
    assert is_valid_url("https://techcrunch.com/article-1") is True
    assert is_valid_url("http://news.ycombinator.com/item?id=123") is True
    assert is_valid_url("ftp://invalid-protocol.com") is False
    assert is_valid_url("not-a-url") is False
    assert is_valid_url("") is False


def test_safe_url_security():
    assert not is_safe_url("http://localhost/test")
    assert not is_safe_url("http://127.0.0.1:8000")
    assert not is_safe_url("http://169.254.169.254/latest/meta-data/")
    assert is_safe_url("https://techcrunch.com/article")
    assert not is_safe_url("ftp://example.com/file")
    assert not is_safe_url("https://example.com:8080/")


def test_article_validation_valid():
    valid_record = {
        "title": "OpenAI Releases Next Generation Transformer Architecture",
        "link": "https://example.com/openai-transformer",
        "source": "TechCrunch",
        "score": 150,
    }
    errors = validate_article_record(valid_record)
    assert len(errors) == 0


def test_article_validation_invalid_rules():
    # Missing required field
    missing_title = {"link": "https://example.com/1", "source": "Hacker News"}
    assert any("missing_required_field: title" in e for e in validate_article_record(missing_title))

    # Short title
    short_title = {"title": "Short", "link": "https://example.com/2", "source": "Reddit"}
    assert any("title_too_short" in e for e in validate_article_record(short_title))

    # Negative score
    negative_score = {
        "title": "A Valid Long Article Title for Testing",
        "link": "https://example.com/3",
        "source": "Reddit",
        "score": -10,
    }
    assert any("negative_score" in e for e in validate_article_record(negative_score))


def test_validate_batch_and_quarantine():
    batch = [
        {"title": "Valid Article Title One With Length", "link": "https://example.com/1", "source": "Hacker News", "score": 10},
        {"title": "Too Short", "link": "https://example.com/2", "source": "Reddit", "score": 0},
        {"title": "Valid Article Title Two With Length", "link": "https://example.com/3", "source": "TechCrunch", "score": 50},
        {"title": "Duplicate Link Record", "link": "https://example.com/1", "source": "Hacker News", "score": 20},
    ]
    valid, quarantined, metrics = validate_batch(batch, day="2026-08-22")

    assert len(valid) == 2
    assert len(quarantined) == 2
    assert metrics["data_quality_pass_rate_percent"] == 50.0
    assert metrics["total_records_evaluated"] == 4


# -----------------------------------------------------------------------------
# 2. Ingestion & Idempotency Tests
# -----------------------------------------------------------------------------
def test_deterministic_hashing():
    h1 = generate_record_hash("https://example.com/test", "Hacker News")
    h2 = generate_record_hash("https://example.com/test", "Hacker News")
    h3 = generate_record_hash("https://example.com/different", "Hacker News")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_bronze_idempotent_writes(temp_lake_dir):
    records = [
        {"title": "Article Number One Long Title", "link": "https://example.com/1", "source": "HN", "score": 10},
        {"title": "Article Number Two Long Title", "link": "https://example.com/2", "source": "HN", "score": 20},
    ]
    out_file = write_bronze(records, source="HN", day="2026-08-22")
    assert out_file.exists()
    lines_first = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_first) == 2

    # Second write with same records
    write_bronze(records, source="HN", day="2026-08-22")
    lines_second = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines_second) == 2


# -----------------------------------------------------------------------------
# 3. Silver & Gold Layer Analytical Tests
# -----------------------------------------------------------------------------
def test_classification():
    assert classify_article("OpenAI releases GPT-5 with transformer") == "AI & ML"
    assert classify_article("New quantum chip from Intel") == "Hardware"
    assert classify_article("Air quality improves in city") != "AI & ML"


def test_lakehouse_end_to_end(temp_lake_dir):
    import duckdb

    test_articles = [
        {"title": "Breakthrough in Generative LLMs and AI", "link": "https://example.com/ai-1", "source": "Hacker News", "score": 100, "sentiment_score": 0.8},
        {"title": "Critical Security Breach Patched in Cloud Provider", "link": "https://example.com/sec-1", "source": "TechCrunch", "score": 75, "sentiment_score": -0.5},
        {"title": "High Performance Computing GPU Benchmarks", "link": "https://example.com/hw-1", "source": "Ars Technica", "score": 40, "sentiment_score": 0.2},
    ]

    # Transform to Silver Parquet
    silver_path = to_silver(test_articles, day="2026-08-22")
    assert silver_path is not None

    # Verify Silver via DuckDB
    con = duckdb.connect(database=":memory:")
    pattern = f"{str(silver_path).replace('\\', '/')}/**/*.parquet"
    count = con.execute(f"SELECT count(*) FROM read_parquet('{pattern}', hive_partitioning=1)").fetchone()[0]
    assert count == 3

    # Run Gold Analytics Marts
    gold_dir = run_gold_duckdb(day="2026-08-22")
    assert (gold_dir / "category_metrics.parquet").exists()
    assert (gold_dir / "daily_stats.json").exists()

    stats = json.loads((gold_dir / "daily_stats.json").read_text(encoding="utf-8"))
    assert stats["total_articles"] == 3
    assert "AI & ML" in stats["by_category"]


# -----------------------------------------------------------------------------
# 4. Utilities & Database Core Tests
# -----------------------------------------------------------------------------
def test_excerpt_cleaning():
    assert _clean_excerpt("<p>Hello &amp; world</p>") == "Hello & world"
    t = "word " * 100
    assert len(_clean_excerpt(t)) <= 281


def test_credibility_boundaries():
    s = get_scorer()
    _, d1 = s.score("New secretary appointed", "https://example.com/a")
    _, d2 = s.score("Secret revealed in leaked report", "https://example.com/b")
    assert d1["title_penalty"] < d2["title_penalty"]


def test_estimate_read_time():
    assert estimate_read_time("short", "word " * 100) == 7
    assert estimate_read_time("short title") == 3


def test_fts_and_database_operations(tmp_path):
    db_path = str(tmp_path / "test_sniffer.db")
    db = Database(db_path)

    # Sanitize FTS
    assert db._sanitize_fts_query('hello OR "world" *') != ""
    assert db._sanitize_fts_query("   ") == ""

    # Add articles
    db.add_articles([{
        "title": "Quantum Computing Breakthrough",
        "link": "https://example.com/quantum",
        "source": "Hacker News",
        "author": "Researcher",
        "time": "Today",
        "comments": "12",
        "excerpt": "A major breakthrough in quantum computing.",
        "image_url": "",
        "score": 100,
    }])

    # Search
    results = db.search_articles("Quantum", limit=5)
    assert isinstance(results, list)
    assert len(results) >= 1

    # Bookmarking & Personalized feed
    arts = db.get_articles(limit=1)
    assert len(arts) > 0
    db.toggle_bookmark(arts[0]["id"])

    feed = db.get_personalized_feed(limit=5)
    assert isinstance(feed, list)

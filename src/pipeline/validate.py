"""
Data Validation & Quality Gate — Medallion Lakehouse Pipeline
Enforces declarative schema contracts, isolates corrupt/invalid records into
a Quarantine layer, and calculates data quality observability metrics.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pipeline.ingest import canonical_link

logger = logging.getLogger(__name__)

QUARANTINE_ROOT = Path("data/quarantine")
LOGS_ROOT = Path("data/logs")

# Schema contract rules
REQUIRED_FIELDS = ["title", "link", "source"]
MIN_TITLE_LENGTH = 10
MAX_TITLE_LENGTH = 500


def is_valid_url(url: str) -> bool:
    """Validate that the string is a well-formed HTTP/HTTPS URL."""
    if not url:
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def validate_article_record(article: dict[str, Any]) -> list[str]:
    """
    Validate a single raw article dictionary against declarative schema constraints.
    Returns a list of error descriptions (empty list if valid).
    """
    errors: list[str] = []

    if not isinstance(article, dict):
        return ["record is not a dictionary"]

    # 1. Null / Empty checks for required fields
    for field in REQUIRED_FIELDS:
        value = article.get(field)
        if value is None or not str(value).strip():
            errors.append(f"missing_required_field: {field}")

    # 2. Title length boundary validation
    title = str(article.get("title", "")).strip()
    if title:
        if len(title) < MIN_TITLE_LENGTH:
            errors.append(f"title_too_short: len={len(title)} < {MIN_TITLE_LENGTH}")
        elif len(title) > MAX_TITLE_LENGTH:
            errors.append(f"title_too_long: len={len(title)} > {MAX_TITLE_LENGTH}")

    # 3. URL format validation
    link = str(article.get("link", "")).strip()
    if link and not is_valid_url(link):
        errors.append("invalid_url_format")

    # 4. Numeric boundary validation for engagement score
    raw_score = article.get("score", 0)
    try:
        score_val = int(raw_score)
        if score_val < 0:
            errors.append(f"negative_score: {score_val}")
    except (ValueError, TypeError):
        errors.append(f"score_not_integer: {raw_score}")

    return errors


def validate_batch(
    articles: list[dict[str, Any]],
    day: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """
    Validates a batch of articles, separates valid vs. quarantined records,
    deduplicates by canonical link, and computes observability quality metrics.

    Returns: (valid_records, quarantined_records, quality_summary)
    """
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    seen_links: set[str] = set()
    valid_records: list[dict[str, Any]] = []
    quarantined_records: list[dict[str, Any]] = []
    rule_failure_counts: dict[str, int] = {}

    for record in articles:
        errors = validate_article_record(record)
        # A Bronze line can hold any JSON value, so .get() is not safe here
        is_mapping = isinstance(record, dict)
        link = canonical_link(str(record.get("link", ""))) if is_mapping else ""

        # Duplicate link detection within batch (canonical: www/trailing-slash/tracker-proof)
        if link and link in seen_links:
            errors.append("duplicate_link_in_batch")

        if errors:
            for err in errors:
                rule_name = err.split(":")[0]
                rule_failure_counts[rule_name] = rule_failure_counts.get(rule_name, 0) + 1

            quarantined_item = {
                **(record if is_mapping else {"raw_record": record}),
                "_quarantine_timestamp": datetime.now(timezone.utc).isoformat(),
                "_validation_errors": errors,
            }
            quarantined_records.append(quarantined_item)
        else:
            valid_records.append(record)
            if link:
                seen_links.add(link)

    total_input = len(articles)
    total_valid = len(valid_records)
    total_quarantined = len(quarantined_records)
    pass_rate = round((total_valid / total_input * 100), 2) if total_input > 0 else 100.0

    quality_summary = {
        "execution_date": day,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_records_evaluated": total_input,
        "valid_records_passed": total_valid,
        "quarantined_records_count": total_quarantined,
        "data_quality_pass_rate_percent": pass_rate,
        "rule_failure_breakdown": rule_failure_counts,
        "status": "PASS" if pass_rate >= 80.0 else "WARNING",
    }

    return valid_records, quarantined_records, quality_summary


def save_quarantine_records(quarantined_records: list[dict[str, Any]], day: str | None = None) -> Path:
    """Writes quarantined records with validation failure reasons to JSONL."""
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = QUARANTINE_ROOT / day
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "quarantined_records.jsonl"

    # Snapshot of the day, not an append-only log: rewrite it so re-runs do not duplicate
    tmp_file = out_file.with_name(out_file.name + ".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        for record in quarantined_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp_file, out_file)

    logger.info(f"Saved {len(quarantined_records)} quarantined records to {out_file}")
    return out_file


def save_quality_metrics(quality_summary: dict[str, Any]) -> Path:
    """Appends quality summary statistics to data/logs/quality_metrics.json."""
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)
    metrics_file = LOGS_ROOT / "quality_metrics.json"

    history: list[dict[str, Any]] = []
    if metrics_file.exists():
        try:
            history = json.loads(metrics_file.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = [history]
        except Exception as e:
            # The CI quality artifact is this file; a silent [] would erase the run trend
            logger.error(f"Quality metrics file {metrics_file} is corrupt ({e}); moved aside, history restarted")
            try:
                metrics_file.replace(metrics_file.with_name(metrics_file.name + f".corrupt.{int(time.time())}"))
            except OSError as mv:
                logger.error(f"Could not move corrupt metrics file aside: {mv}")
            history = []

    history.append(quality_summary)
    # Keep last 30 runs
    tmp_file = metrics_file.with_name(metrics_file.name + ".tmp")
    tmp_file.write_text(json.dumps(history[-30:], indent=2), encoding="utf-8")
    os.replace(tmp_file, metrics_file)
    logger.info(f"Data quality metrics updated: {quality_summary['data_quality_pass_rate_percent']}% pass rate")
    return metrics_file

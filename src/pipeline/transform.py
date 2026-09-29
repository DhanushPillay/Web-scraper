"""
Transform — Medallion Lakehouse Silver Layer
Transforms Bronze raw data into clean, typed, Hive-partitioned Snappy Parquet tables.
Handles schema normalization, category auto-classification, and partition pruning.
"""
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BRONZE_ROOT = Path("data/bronze")
SILVER_ROOT = Path("data/silver")


def read_bronze_records(day: str | None = None) -> list[dict[str, Any]]:
    """Reads all Bronze JSONL records for a given partition date."""
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    candidates = [
        BRONZE_ROOT / day,
        BRONZE_ROOT / f"day={day}",
    ]
    articles: list[dict[str, Any]] = []

    for base in candidates:
        if not base.exists():
            continue
        for p in base.glob("*.jsonl"):
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, start=1):
                    if not line.strip():
                        continue
                    try:
                        articles.append(json.loads(line))
                    except ValueError as e:
                        logger.warning(f"Skipping unparsable Bronze line {p}:{lineno}: {e}")

    return articles


from categories import classify_article


def to_silver(articles: list[dict[str, Any]], day: str | None = None) -> Path:
    """
    Transforms validated article records into structured Hive-partitioned Snappy Parquet.
    Partition structure: data/silver/day=YYYY-MM-DD/source=<source>/
    """
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    if not articles:
        raise ValueError(f"to_silver: no records supplied for day={day}; Silver partition not written")

    # Normalize fields and data types
    normalized: list[dict[str, Any]] = []
    for a in articles:
        rec = dict(a)
        title = str(rec.get("title", "")).strip()
        cat = str(rec.get("category", "")).strip()
        if not cat or cat.lower() == "general":
            cat = classify_article(title)

        # Standardize schema types
        try:
            score = int(rec.get("score") or 0)
        except (ValueError, TypeError):
            score = 0

        try:
            sent_score = float(rec.get("sentiment_score") or 0.0)
        except (ValueError, TypeError):
            sent_score = 0.0

        try:
            read_time = int(rec.get("read_time") or 3)
        except (ValueError, TypeError):
            read_time = 3

        raw_bullets = rec.get("bullets") or []
        if not isinstance(raw_bullets, list):
            raw_bullets = [raw_bullets]

        normalized_rec = {
            "record_hash": str(rec.get("record_hash", "")),
            "title": title,
            "link": str(rec.get("link", "")).strip(),
            "author": str(rec.get("author", "Unknown")),
            "source": str(rec.get("source", "unknown")),
            "score": score,
            "comments": str(rec.get("comments", "") or "0"),
            "category": cat,
            "sentiment": str(rec.get("sentiment", "neutral")),
            "sentiment_score": sent_score,
            "read_time": read_time,
            "time_posted": str(rec.get("time", "Recent")),
            "excerpt": str(rec.get("excerpt", "")),
            "image_url": str(rec.get("image_url", "")),
            "dek": str(rec.get("dek", "")),
            "bullets": [str(b) for b in raw_bullets],
            "credibility": json.dumps(rec.get("credibility") or {}, ensure_ascii=False),
            "day": day,
        }
        normalized.append(normalized_rec)

    # Write as partitioned Snappy Parquet via PyArrow
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        schema = pa.schema([
            ("record_hash", pa.string()),
            ("title", pa.string()),
            ("link", pa.string()),
            ("author", pa.string()),
            ("source", pa.string()),
            ("score", pa.int64()),
            ("comments", pa.string()),
            ("category", pa.string()),
            ("sentiment", pa.string()),
            ("sentiment_score", pa.float64()),
            ("read_time", pa.int64()),
            ("time_posted", pa.string()),
            ("excerpt", pa.string()),
            ("image_url", pa.string()),
            ("dek", pa.string()),
            ("bullets", pa.list_(pa.string())),
            ("credibility", pa.string()),
            ("day", pa.string()),
        ])

        table = pa.Table.from_pylist(normalized, schema=schema)
        SILVER_ROOT.mkdir(parents=True, exist_ok=True)

        # overwrite_or_ignore writes a new randomly-named file per call, so a re-run
        # would append a second copy of every row and inflate the Gold marts
        for part in SILVER_ROOT.glob(f"day={day}/*"):
            shutil.rmtree(part, ignore_errors=True)

        pq.write_to_dataset(
            table,
            root_path=str(SILVER_ROOT),
            partition_cols=["day", "source"],
            compression="snappy",
            existing_data_behavior="delete_matching",
        )
        logger.info(f"[Silver] Successfully wrote {len(normalized)} records to {SILVER_ROOT}")
        return SILVER_ROOT

    except Exception as e:
        logger.warning(f"Parquet write failed ({type(e).__name__}: {e}); falling back to partitioned JSONL")
        out_dir = SILVER_ROOT / f"day={day}"
        out_dir.mkdir(parents=True, exist_ok=True)
        by_src: dict[str, list[dict[str, Any]]] = {}
        for r in normalized:
            src = r.get("source", "unknown")
            by_src.setdefault(src, []).append(r)

        for src, records in by_src.items():
            p = out_dir / f"source={src}.jsonl"
            with p.open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info(f"[Silver] Fallback wrote partitioned JSONL to {out_dir}")
        return out_dir

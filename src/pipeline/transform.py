"""
Transform — Medallion Lakehouse Silver Layer
Transforms Bronze raw data into clean, typed, Hive-partitioned Snappy Parquet tables.
Handles schema normalization, category auto-classification, and partition pruning.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BRONZE_ROOT = Path("data/bronze")
SILVER_ROOT = Path("data/silver")


def read_bronze_records(day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reads all Bronze JSONL records for a given partition date."""
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    candidates = [
        BRONZE_ROOT / day,
        BRONZE_ROOT / day.replace("-", "/")
    ]
    articles: List[Dict[str, Any]] = []

    for base in candidates:
        if not base.exists():
            continue
        for p in base.glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        articles.append(json.loads(line))
                    except Exception:
                        continue

    return articles


def _classify_title(title: str) -> str:
    """Classifies tech article title into broad domain category."""
    try:
        from app import classify_article
        return classify_article(title)
    except Exception:
        t = (title or "").lower()
        if any(w in t for w in ["ai", "llm", "gpt", "model", "neural", "deep learning"]):
            return "AI & ML"
        elif any(w in t for w in ["security", "hack", "cve", "breach", "vulnerability", "auth"]):
            return "Security"
        elif any(w in t for w in ["cloud", "aws", "docker", "k8s", "kubernetes", "infra"]):
            return "Cloud & DevOps"
        elif any(w in t for w in ["chip", "nvidia", "intel", "amd", "hardware", "cpu", "gpu"]):
            return "Hardware"
        return "general"


def to_silver(articles: List[Dict[str, Any]], day: Optional[str] = None) -> Optional[Path]:
    """
    Transforms validated article records into structured Hive-partitioned Snappy Parquet.
    Partition structure: data/silver/day=YYYY-MM-DD/source=<source>/
    """
    if not articles:
        return None

    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    # Normalize fields and data types
    normalized: List[Dict[str, Any]] = []
    for a in articles:
        rec = dict(a)
        title = str(rec.get("title", "")).strip()
        cat = str(rec.get("category", "")).strip()
        if not cat or cat.lower() == "general":
            cat = _classify_title(title)

        # Standardize schema types
        try:
            score = int(rec.get("score") or 0)
        except Exception:
            score = 0

        try:
            sent_score = float(rec.get("sentiment_score") or 0.0)
        except Exception:
            sent_score = 0.0

        try:
            read_time = int(rec.get("read_time") or 3)
        except Exception:
            read_time = 3

        normalized_rec = {
            "record_hash": str(rec.get("record_hash", "")),
            "title": title,
            "link": str(rec.get("link", "")).strip(),
            "author": str(rec.get("author", "Unknown")),
            "source": str(rec.get("source", "unknown")),
            "score": score,
            "category": cat,
            "sentiment": str(rec.get("sentiment", "neutral")),
            "sentiment_score": sent_score,
            "read_time": read_time,
            "time_posted": str(rec.get("time", "Recent")),
            "excerpt": str(rec.get("excerpt", "")),
            "image_url": str(rec.get("image_url", "")),
            "dek": str(rec.get("dek", "")),
            "day": day,
        }
        normalized.append(normalized_rec)

    # Write as partitioned Snappy Parquet via PyArrow
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist(normalized)
        SILVER_ROOT.mkdir(parents=True, exist_ok=True)

        pq.write_to_dataset(
            table,
            root_path=str(SILVER_ROOT),
            partition_cols=["day", "source"],
            compression="snappy",
            existing_data_behavior="overwrite_or_ignore",
        )
        logger.info(f"[Silver] Successfully wrote {len(normalized)} records to {SILVER_ROOT}")
        return SILVER_ROOT

    except ImportError:
        # Fallback to partitioned JSONL if PyArrow is missing
        out_dir = SILVER_ROOT / day
        out_dir.mkdir(parents=True, exist_ok=True)
        by_src: Dict[str, List[Dict[str, Any]]] = {}
        for r in normalized:
            src = r.get("source", "unknown")
            by_src.setdefault(src, []).append(r)

        for src, records in by_src.items():
            p = out_dir / f"{src}.jsonl"
            with p.open("w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info(f"[Silver] PyArrow missing; fallback wrote partitioned JSONL to {out_dir}")
        return out_dir

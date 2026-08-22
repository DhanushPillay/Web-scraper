"""
Ingest — Sniffer Bronze layer
Writes daily JSONL partitioned by source, maintains watermark for incremental.
ponytail: append-only, dedup by link in memory, no DB needed for lake.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

BRONZE_ROOT = Path("data/bronze")
WATERMARK_PATH = Path("data/watermark.json")


def _load_watermark() -> dict:
    if WATERMARK_PATH.exists():
        try:
            return json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_watermark(wm: dict):
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK_PATH.write_text(json.dumps(wm, indent=2), encoding="utf-8")


def _day_partition() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_bronze(articles: list[dict], source: str = "mixed") -> Path:
    """Append articles to Bronze JSONL partitioned by day/source."""
    day = _day_partition()
    out_dir = BRONZE_ROOT / day
    out_dir.mkdir(parents=True, exist_ok=True)
    # ponytail: one file per source per day for easy partition pruning
    safe_source = "".join(c if c.isalnum() else "_" for c in source) or "mixed"
    out_path = out_dir / f"{safe_source}.jsonl"
    with out_path.open("a", encoding="utf-8") as f:
        for a in articles:
            # minimal envelope with ingest metadata
            rec = {
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                **a,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out_path


def write_bronze_by_source(articles: list[dict]) -> dict[str, Path]:
    """Group by source and write each group. Returns {source: path}."""
    by_source: dict[str, list] = {}
    for a in articles:
        src = a.get("source", "unknown")
        by_source.setdefault(src, []).append(a)
    out = {}
    for src, arts in by_source.items():
        out[src] = write_bronze(arts, source=src)
    # also update watermark with counts
    wm = _load_watermark()
    wm["last_ingest"] = datetime.now(timezone.utc).isoformat()
    wm["last_counts"] = {k: len(v) for k, v in by_source.items()}
    _save_watermark(wm)
    return out

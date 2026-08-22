"""
Ingest — Medallion Lakehouse Bronze Layer
Appends raw heterogeneous data feeds to partitioned JSONL files with deterministic
SHA-256 fingerprinting and persistent watermark state for incremental loading.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)

BRONZE_ROOT = Path("data/bronze")
WATERMARK_PATH = Path("data/watermark.json")


def generate_record_hash(link: str, source: str = "") -> str:
    """Computes a deterministic SHA-256 checksum for deduplication and lineage."""
    canonical = f"{source.strip().lower()}:{link.strip().lower()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_watermark() -> Dict[str, Any]:
    """Loads incremental pipeline watermark state."""
    if WATERMARK_PATH.exists():
        try:
            return json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read watermark: {e}")
            return {}
    return {}


def save_watermark(state: Dict[str, Any]) -> None:
    """Persists incremental pipeline watermark state."""
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _get_existing_hashes_for_day(day: str, source: str) -> Set[str]:
    """Reads existing record hashes for a given day/source partition to enforce idempotency."""
    safe_source = "".join(c if c.isalnum() else "_" for c in source) or "mixed"
    partition_file = BRONZE_ROOT / day / f"{safe_source}.jsonl"
    existing_hashes: Set[str] = set()

    if partition_file.exists():
        try:
            for line in partition_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    h = item.get("record_hash")
                    if h:
                        existing_hashes.add(h)
        except Exception as e:
            logger.warning(f"Error reading existing partition {partition_file}: {e}")

    return existing_hashes


def write_bronze(articles: List[Dict[str, Any]], source: str = "mixed", day: str = None) -> Path:
    """
    Appends articles to Bronze JSONL partitioned by day/source.
    Enforces idempotency using deterministic record hashes.
    """
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out_dir = BRONZE_ROOT / day
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_source = "".join(c if c.isalnum() else "_" for c in source) or "mixed"
    out_path = out_dir / f"{safe_source}.jsonl"

    existing_hashes = _get_existing_hashes_for_day(day, source)
    new_records: List[Dict[str, Any]] = []

    ingest_time = datetime.now(timezone.utc).isoformat()
    for art in articles:
        link = str(art.get("link", ""))
        rec_hash = generate_record_hash(link, source)

        if rec_hash in existing_hashes:
            continue

        envelope = {
            "record_hash": rec_hash,
            "ingested_at": ingest_time,
            "schema_version": "1.0",
            **art,
        }
        new_records.append(envelope)
        existing_hashes.add(rec_hash)

    if new_records:
        with out_path.open("a", encoding="utf-8") as f:
            for rec in new_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        logger.info(f"[Bronze] Wrote {len(new_records)} new records to {out_path}")
    else:
        logger.info(f"[Bronze] All {len(articles)} records already present in {out_path} (idempotent skip)")

    return out_path


def write_bronze_by_source(articles: List[Dict[str, Any]], day: str = None) -> Dict[str, Path]:
    """
    Partitions raw articles by source, writes to Bronze JSONL, and updates watermark state.
    """
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for a in articles:
        src = str(a.get("source", "unknown"))
        by_source.setdefault(src, []).append(a)

    out_paths: Dict[str, Path] = {}
    for src, arts in by_source.items():
        out_paths[src] = write_bronze(arts, source=src, day=day)

    # Update persistent watermark
    wm = load_watermark()
    total_previous = wm.get("total_records_ingested", 0)
    wm["last_ingest_timestamp"] = datetime.now(timezone.utc).isoformat()
    wm["last_partition_day"] = day
    wm["last_counts_by_source"] = {k: len(v) for k, v in by_source.items()}
    wm["total_records_ingested"] = total_previous + len(articles)
    save_watermark(wm)

    return out_paths

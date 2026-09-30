"""
Ingest — Medallion Lakehouse Bronze Layer
Appends raw heterogeneous data feeds to partitioned JSONL files with deterministic
SHA-256 fingerprinting and persistent watermark state for incremental loading.
"""
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BRONZE_ROOT = Path("data/bronze")
WATERMARK_PATH = Path("data/watermark.json")

# Only these are dropped from a link; every other param carries identity
TRACKER_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "mc_cid", "mc_eid",
})
DEFAULT_PORTS = {"http": "80", "https": "443"}

LOCK_TIMEOUT_S = 0.5
LOCK_MAX_ATTEMPTS = 20
LOCK_STALE_S = 300


def canonical_link(link: str) -> str:
    """Canonical URL for dedup: IDNA host, no default port, sorted params, no trackers."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    if not isinstance(link, str):
        # A scraper can hand us a BeautifulSoup Tag or None. Coercing it would
        # silently store junk as a URL, and attribute access on a Tag returns
        # None for names like .strip, which turns into a confusing TypeError.
        return ""
    s = link.strip()
    if not s:
        return ""
    try:
        p = urlsplit(s)
        scheme = p.scheme.lower()
        host = (p.hostname or "").lower()
        if host:
            host = host.encode("idna").decode("ascii")
        if host.startswith("www.") and host.count(".") > 1:
            # A bare "www.com" is a real host, not a www prefix on a domain
            host = host[len("www."):]
        port = p.port
        netloc = host if port is None or str(port) == DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
        path = p.path.rstrip("/") or ""
        q = sorted(
            (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in TRACKER_PARAMS
        )
        return urlunsplit((scheme, netloc, path, urlencode(q), ""))
    except Exception:
        return s.lower()


def generate_record_hash(link: str, source: str = "") -> str:
    """Deterministic SHA-256 over canonical link for dedup and lineage."""
    canonical = f"{source.strip().lower()}:{canonical_link(link)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_watermark() -> dict[str, Any]:
    """Loads incremental pipeline watermark state."""
    if WATERMARK_PATH.exists():
        try:
            return json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            # A silent {} here would reset total_records_ingested on the next save
            logger.error(f"Watermark {WATERMARK_PATH} is corrupt ({e}); moved aside, counters will restart")
            try:
                WATERMARK_PATH.replace(WATERMARK_PATH.with_suffix(f".corrupt.{int(time.time())}.json"))
            except OSError as mv:
                logger.error(f"Could not move corrupt watermark aside: {mv}")
            return {}
    return {}


def save_watermark(state: dict[str, Any]) -> None:
    """Persists incremental pipeline watermark state."""
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WATERMARK_PATH.with_name(WATERMARK_PATH.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, WATERMARK_PATH)


def _get_existing_hashes_for_day(day: str, source: str) -> set[str]:
    """Reads existing record hashes for a given day/source partition to enforce idempotency."""
    safe_source = "".join(c if c.isalnum() else "_" for c in source) or "mixed"
    partition_file = BRONZE_ROOT / day / f"{safe_source}.jsonl"
    existing_hashes: set[str] = set()

    if partition_file.exists():
        # errors="replace": a mangled byte becomes an unparsable line, not a crash that
        # would hide every hash and let the whole partition be re-appended
        with partition_file.open("r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except ValueError as e:
                    # One bad line must not discard every hash read before it,
                    # which would make the whole partition look empty and get re-appended
                    logger.warning(f"Corrupt line {partition_file}:{lineno} ({e}); hash skipped, line kept")
                    continue
                if isinstance(item, dict):
                    h = item.get("record_hash")
                    if h:
                        existing_hashes.add(h)

    return existing_hashes


def _acquire_partition_lock(lock_path: Path) -> bool:
    """O_EXCL sentinel so a concurrent writer cannot interleave its read and append."""
    for _ in range(LOCK_MAX_ATTEMPTS):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > LOCK_STALE_S:
                # Holder died without releasing; reclaim or the partition is wedged forever
                logger.warning(f"Reclaiming stale Bronze lock {lock_path} (age {age:.0f}s)")
                try:
                    lock_path.unlink()
                except OSError as e:
                    # Cannot reclaim, so stop retrying instead of spinning to the timeout
                    logger.debug(f"Stale Bronze lock {lock_path} still held: {e}")
                    return False
                continue
            time.sleep(LOCK_TIMEOUT_S)
            continue
        os.close(fd)
        return True
    return False


def write_bronze(articles: list[dict[str, Any]], source: str = "mixed", day: str | None = None) -> Path:
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
    lock_path = out_dir / f".{safe_source}.lock"

    if not _acquire_partition_lock(lock_path):
        logger.error(
            f"Could not acquire lock {lock_path} after {LOCK_MAX_ATTEMPTS} attempts; "
            f"{len(articles)} records for source={source} NOT written to {out_path}"
        )
        return out_path

    try:
        # Re-read inside the lock: the previous holder may have appended since we last looked
        existing_hashes = _get_existing_hashes_for_day(day, source)
        new_records: list[dict[str, Any]] = []

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
            with out_path.open("a+b") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    # A crash mid-append can leave no trailing newline, which would
                    # glue the next record onto the half-written line
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        f.write(b"\n")
                for rec in new_records:
                    f.write(json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n")
            logger.info(f"[Bronze] Wrote {len(new_records)} new records to {out_path}")
        else:
            logger.info(f"[Bronze] All {len(articles)} records already present in {out_path} (idempotent skip)")
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as e:
            logger.error(f"Failed to release Bronze lock {lock_path}: {e}")

    return out_path


def write_bronze_by_source(articles: list[dict[str, Any]], day: str | None = None) -> dict[str, Path]:
    """
    Partitions raw articles by source, writes to Bronze JSONL, and updates watermark state.
    """
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    by_source: dict[str, list[dict[str, Any]]] = {}
    for a in articles:
        src = str(a.get("source", "unknown"))
        by_source.setdefault(src, []).append(a)

    out_paths: dict[str, Path] = {}
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

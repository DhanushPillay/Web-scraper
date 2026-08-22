"""
Transform — Bronze (JSONL) → Silver (Parquet partitioned)
ponytail: pyarrow if available, else fallback to JSONL Silver (still partitioned)
"""
import json
from pathlib import Path
from datetime import datetime, timezone

BRONZE_ROOT = Path("data/bronze")
SILVER_ROOT = Path("data/silver")


def _read_bronze_day(day: str = None) -> list[dict]:
    """Read all Bronze JSONL for a given day (or today if None)."""
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # support both hyphen and slash partitions
    candidates = [BRONZE_ROOT / day]
    if "-" in day:
        # also check legacy slash path
        candidates.append(BRONZE_ROOT / day.replace("-", "/"))
    articles = []
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


def to_silver(articles: list[dict], day: str = None) -> Path | None:
    """Write Silver Parquet partitioned by source/day. Returns dir path."""
    if not articles:
        return None
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # normalize slash to hyphen for lake partition
    day = day.replace("/", "-")

    # Try pyarrow, else fallback to partitioned JSONL
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        import pyarrow.dataset as ds

        # normalize + enrich category if missing
        # ponytail: reuse app classification without importing heavy app at import time
        def _classify(t: str) -> str:
            try:
                from app import classify_article
                return classify_article(t)
            except Exception:
                return "general"

        for a in articles:
            a.setdefault("score", 0)
            a.setdefault("source", "unknown")
            cat = a.get("category", "general")
            if not cat or cat.lower() == "general":
                cat = _classify(a.get("title", ""))
            a["category"] = cat
            # ensure partition cols
            a["day"] = day

        table = pa.Table.from_pylist(articles)
        out = SILVER_ROOT
        out.mkdir(parents=True, exist_ok=True)
        # ponytail: one write per day, partitioned by source for pruning
        pq.write_to_dataset(
            table,
            root_path=str(out),
            partition_cols=["day", "source"],
            existing_data_behavior="overwrite_or_ignore",
        )
        return out
    except ImportError:
        # fallback: partitioned JSONL
        out = SILVER_ROOT / day
        out.mkdir(parents=True, exist_ok=True)
        by_src: dict[str, list] = {}
        for a in articles:
            by_src.setdefault(a.get("source", "unknown"), []).append(a)
        for src, arts in by_src.items():
            p = out / f"{src}.jsonl"
            with p.open("w", encoding="utf-8") as f:
                for r in arts:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return out

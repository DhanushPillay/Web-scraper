"""
Processing — Medallion Lakehouse Gold Layer
Transforms Silver Parquet datasets into analytical marts and aggregated metrics.
DuckDB executes the window rankings and aggregations in-process; no JVM, no cluster.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GOLD_ROOT = Path("data/gold")
SILVER_ROOT = Path("data/silver")


def _resolve_day(day: str | None) -> str:
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return day.replace("/", "-")


def load_records_for_day(day: str | None = None) -> list[dict[str, Any]]:
    """
    Loads the Silver Parquet partition for a date. Returns [] when no Silver data
    exists for that day. Bronze is deliberately never substituted here: raw records
    carry no category, sentiment or read_time, so a Bronze fallback yields a
    plausible-looking Gold mart built entirely on default values.
    """
    day = _resolve_day(day)
    silver_pattern = str(SILVER_ROOT).replace("\\", "/") + "/**/*.parquet"

    try:
        import duckdb
        # union_by_name: days written by different code versions carry different
        # columns, and without it DuckDB fails to bind the files as one schema.
        query = (
            f"SELECT * FROM read_parquet('{silver_pattern}', hive_partitioning=1, union_by_name=true)"
            f" WHERE day = '{day}'"
        )
        df = duckdb.query(query).df()
        if not df.empty:
            return df.to_dict(orient="records")
    except Exception as e:
        logger.warning(
            f"[Gold] DuckDB read of Silver failed for day={day}, falling back to pyarrow: "
            f"{type(e).__name__}: {e}"
        )

    try:
        import pyarrow.dataset as ds
        if SILVER_ROOT.exists():
            dataset = ds.dataset(str(SILVER_ROOT), format="parquet", partitioning="hive")
            records = dataset.to_table(filter=ds.field("day") == day).to_pylist()
            if records:
                return records
    except Exception as e:
        logger.warning(
            f"[Gold] pyarrow read of Silver failed for day={day}: {type(e).__name__}: {e}"
        )

    logger.warning(
        f"[Gold] No Silver records for day={day} under {SILVER_ROOT}. Gold marts cannot be "
        "built; raw Bronze is not a substitute because it has no category or sentiment fields."
    )
    return []


def _load_or_raise(day: str) -> list[dict[str, Any]]:
    records = load_records_for_day(day)
    if not records:
        raise ValueError(f"No records found for partition day={day}")
    return records


def run_gold_duckdb(
    day: str | None = None,
    records: list[dict[str, Any]] | None = None,
) -> Path:
    """
    DuckDB analytical path: builds the category, source and window-ranked marts
    over a Silver partition in-process. Pass `records` to reuse an already-loaded
    partition instead of re-reading the lake.
    """
    import duckdb
    import pandas as pd

    day = _resolve_day(day)
    if records is None:
        records = _load_or_raise(day)

    out_dir = GOLD_ROOT / day
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=":memory:")
    try:
        df = pd.DataFrame(records)
        for column, fallback in (
            ("category", "general"),
            ("source", "unknown"),
            ("score", 0),
            ("sentiment_score", 0.0),
            ("read_time", 3),
        ):
            if column not in df.columns:
                df[column] = fallback
            else:
                df[column] = df[column].fillna(fallback)

        con.register("silver_stage", df)

        cat_df = con.execute("""
            SELECT
                category,
                COUNT(*) AS article_count,
                ROUND(AVG(score), 2) AS avg_score,
                MAX(score) AS max_score,
                ROUND(AVG(sentiment_score), 3) AS avg_sentiment_score,
                ROUND(AVG(read_time), 1) AS avg_read_time_mins
            FROM silver_stage
            GROUP BY category
            ORDER BY article_count DESC
        """).df()
        cat_df.to_parquet(out_dir / "category_metrics.parquet", index=False)

        src_df = con.execute("""
            SELECT
                source,
                COUNT(*) AS total_articles,
                ROUND(AVG(score), 2) AS avg_engagement,
                SUM(score) AS total_engagement_score
            FROM silver_stage
            GROUP BY source
            ORDER BY total_articles DESC
        """).df()
        src_df.to_parquet(out_dir / "source_metrics.parquet", index=False)

        ranked_df = con.execute("""
            WITH ranked AS (
                SELECT
                    title,
                    link,
                    source,
                    category,
                    score,
                    DENSE_RANK() OVER (PARTITION BY category ORDER BY score DESC) as category_rank
                FROM silver_stage
            )
            SELECT * FROM ranked WHERE category_rank <= 5
        """).df()
        ranked_df.to_parquet(out_dir / "top_ranked_articles.parquet", index=False)

        stats = {
            "execution_date": day,
            "engine": "duckdb",
            "total_articles": len(df),
            "by_category": dict(zip(cat_df["category"], cat_df["article_count"])),
            "by_source": dict(zip(src_df["source"], src_df["total_articles"])),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        (out_dir / "daily_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        logger.info(f"[Gold] DuckDB analytics completed for day={day}")

        return out_dir
    finally:
        con.close()


def run_gold(day: str | None = None) -> Path:
    """
    Gold entry point. Loads the Silver partition once, fails loudly when the
    partition is empty, and builds the marts with DuckDB. Errors are not
    swallowed, so a failed Gold build can never be reported as a success.
    """
    day = _resolve_day(day)
    return run_gold_duckdb(day=day, records=_load_or_raise(day))

"""
Processing — Medallion Lakehouse Gold Layer
Transforms Silver Parquet datasets into analytical marts and aggregated metrics.
Supports distributed processing via PySpark with high-performance DuckDB/Pandas fallback.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GOLD_ROOT = Path("data/gold")
SILVER_ROOT = Path("data/silver")
BRONZE_ROOT = Path("data/bronze")


def load_silver_records(day: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Loads records from Silver Parquet layer (or Bronze fallback) for a target date partition.
    """
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    records: List[Dict[str, Any]] = []

    # 1. Try reading via DuckDB (fastest, supports Hive partition pruning)
    try:
        import duckdb
        silver_pattern = f"{str(SILVER_ROOT).replace('\\', '/')}/**/*.parquet"
        query = f"SELECT * FROM read_parquet('{silver_pattern}', hive_partitioning=1)"
        if day:
            query += f" WHERE day = '{day}'"
        df = duckdb.query(query).df()
        if not df.empty:
            return df.to_dict(orient="records")
    except Exception:
        pass

    # 2. Try PyArrow dataset
    try:
        import pyarrow.dataset as ds
        if SILVER_ROOT.exists():
            dataset = ds.dataset(str(SILVER_ROOT), format="parquet", partitioning="hive")
            if day:
                table = dataset.to_table(filter=ds.field("day") == day)
            else:
                table = dataset.to_table()
            records = table.to_pylist()
            if records:
                return records
    except Exception:
        pass

    # 3. Fallback to Bronze JSONL if Silver is not yet written
    candidates = [
        BRONZE_ROOT / day,
        BRONZE_ROOT / day.replace("-", "/")
    ]
    for base in candidates:
        if base.exists():
            for p in base.glob("*.jsonl"):
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            continue

    return records


def run_gold_spark(day: Optional[str] = None) -> Path:
    """
    PySpark execution path: Computes window rankings, sentiment aggregates,
    and category engagement marts using PySpark DataFrame APIs.
    """
    try:
        from pyspark.sql import SparkSession, Window
        import pyspark.sql.functions as F
        from pyspark.sql.types import (
            DoubleType, IntegerType, StringType, StructField, StructType
        )
    except ImportError as e:
        raise RuntimeError("PySpark is not installed in the current environment") from e

    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    rows = load_silver_records(day)
    if not rows:
        raise ValueError(f"No records found for partition day={day}")

    spark = (
        SparkSession.builder
        .master("local[*]")
        .appName("Lakehouse-Gold-Analytics")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    try:
        # Standardize schema
        for r in rows:
            r["score"] = int(r.get("score") or 0)
            r["category"] = str(r.get("category") or "general")
            r["source"] = str(r.get("source") or "unknown")
            r["sentiment"] = str(r.get("sentiment") or "neutral")
            r["sentiment_score"] = float(r.get("sentiment_score") or 0.0)
            r["read_time"] = int(r.get("read_time") or 3)

        df = spark.createDataFrame(rows)

        # Repartition by source for balanced processing
        df = df.repartition(2, "source")

        # 1. Window Function: Rank top articles per category by engagement score
        cat_window = Window.partitionBy("category").orderBy(F.col("score").desc())
        ranked_df = df.withColumn("category_rank", F.dense_rank().over(cat_window))

        # 2. Mart 1: Category engagement and sentiment distribution
        category_marts = (
            df.groupBy("category")
            .agg(
                F.count("link").alias("article_count"),
                F.avg("score").alias("avg_score"),
                F.max("score").alias("max_score"),
                F.avg("sentiment_score").alias("avg_sentiment_score"),
                F.avg("read_time").alias("avg_read_time_mins"),
            )
            .orderBy(F.desc("article_count"))
        )

        # 3. Mart 2: Source reliability & volume distribution
        source_marts = (
            df.groupBy("source")
            .agg(
                F.count("link").alias("total_articles"),
                F.avg("score").alias("avg_engagement"),
                F.sum("score").alias("total_engagement_score"),
            )
            .orderBy(F.desc("total_articles"))
        )

        out_dir = GOLD_ROOT / day
        out_dir.mkdir(parents=True, exist_ok=True)

        # Save marts as Snappy Parquet
        category_marts.toPandas().to_parquet(out_dir / "category_metrics.parquet", index=False)
        source_marts.toPandas().to_parquet(out_dir / "source_metrics.parquet", index=False)
        ranked_df.filter(F.col("category_rank") <= 5).toPandas().to_parquet(
            out_dir / "top_ranked_articles.parquet", index=False
        )

        # Generate combined JSON telemetry for the web dashboard
        cat_summary = {r["category"]: r["article_count"] for r in category_marts.collect()}
        src_summary = {r["source"]: r["total_articles"] for r in source_marts.collect()}

        stats = {
            "execution_date": day,
            "engine": "Apache Spark (PySpark 3.5)",
            "total_articles": df.count(),
            "by_category": cat_summary,
            "by_source": src_summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        (out_dir / "daily_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        logger.info(f"[Gold] Spark job completed successfully for day={day}")

        return out_dir
    finally:
        spark.stop()


def run_gold_duckdb(day: Optional[str] = None) -> Path:
    """
    DuckDB analytical path: High-performance, zero-JVM SQL execution
    generating identical analytical marts over Silver Parquet partitions.
    """
    import duckdb

    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    rows = load_silver_records(day)
    if not rows:
        raise ValueError(f"No records found for partition day={day}")

    out_dir = GOLD_ROOT / day
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=":memory:")
    try:
        # Load records into in-memory table
        import pandas as pd
        df = pd.DataFrame(rows)
        if "category" not in df.columns:
            df["category"] = "general"
        if "source" not in df.columns:
            df["source"] = "unknown"
        if "score" not in df.columns:
            df["score"] = 0
        if "sentiment_score" not in df.columns:
            df["sentiment_score"] = 0.0
        if "read_time" not in df.columns:
            df["read_time"] = 3

        con.register("silver_stage", df)

        # 1. Category Metrics Mart
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

        # 2. Source Metrics Mart
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

        # 3. Top Ranked Articles per Category (Window function)
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
            "engine": "DuckDB In-Memory Analytical Engine",
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


def run_gold(day: Optional[str] = None) -> Path:
    """
    Main Gold orchestrator: Attempts PySpark first; seamlessly falls back
    to DuckDB in non-Java/local developer environments.
    """
    try:
        return run_gold_spark(day=day)
    except Exception as spark_err:
        logger.info(f"PySpark engine unavailable or bypassed ({spark_err}). Using DuckDB engine.")
        return run_gold_duckdb(day=day)

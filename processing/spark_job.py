"""
Gold — Sniffer aggregates
run_gold: PySpark local[*] if available, else run_gold_pandas
Output: data/gold/<day>/daily_stats.parquet (or .json)
ponytail: pandas fallback keeps pipeline green without Java/Spark; Spark path proves distributed skill.
"""
from pathlib import Path
from datetime import datetime, timezone
import json

GOLD_ROOT = Path("data/gold")
SILVER_ROOT = Path("data/silver")


def _load_silver(day: str = None) -> list[dict]:
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")
    # try parquet via pyarrow / duckdb, else jsonl fallback
    rows = []
    # parquet path (pyarrow dataset)
    try:
        import pyarrow.dataset as ds
        dataset = ds.dataset(str(SILVER_ROOT), format="parquet", partitioning="hive")
        # filter by day if possible
        table = dataset.to_table(filter=ds.field("day") == day) if day else dataset.to_table()
        rows = table.to_pylist()
        if rows:
            return rows
    except Exception:
        pass

    # jsonl fallback (check both hyphen and slash layouts)
    for cand in [f"data/silver/{day}", f"data/silver/{day.replace('-', '/')}"]:
        for p in Path(cand).glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    # also try bronze fallback
    if not rows:
        for cand in [f"data/bronze/{day}", f"data/bronze/{day.replace('-', '/')}"]:
            for p in Path(cand).glob("*.jsonl"):
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            rows.append(json.loads(line))
                        except:
                            pass
    return rows


def run_gold_pandas(day: str = None) -> Path:
    """Pandas fallback — no Spark/Java needed."""
    try:
        import pandas as pd
    except ImportError:
        # minimal pure-python aggregate
        rows = _load_silver(day)
        from collections import Counter
        by_cat = Counter(r.get("category", "general") for r in rows)
        by_src = Counter(r.get("source", "unknown") for r in rows)
        out = GOLD_ROOT / (day or datetime.now(timezone.utc).strftime("%Y/%m/%d"))
        out.mkdir(parents=True, exist_ok=True)
        Path(out / "daily_stats.json").write_text(
            json.dumps({"by_category": dict(by_cat), "by_source": dict(by_src), "total": len(rows)}, indent=2),
            encoding="utf-8",
        )
        return out

    rows = _load_silver(day)
    if not rows:
        raise ValueError(f"no silver rows for day {day}")
    df = pd.DataFrame(rows)
    # normalize
    if "category" not in df.columns:
        df["category"] = "general"
    if "source" not in df.columns:
        df["source"] = "unknown"
    by_cat = df.groupby("category").size().reset_index(name="count")
    by_src = df.groupby("source").size().reset_index(name="count")

    day = (day or datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("/", "-")
    out = GOLD_ROOT / day
    out.mkdir(parents=True, exist_ok=True)

    # try parquet, else json
    try:
        by_cat.to_parquet(out / "by_category.parquet", index=False)
        by_src.to_parquet(out / "by_source.parquet", index=False)
    except Exception:
        by_cat.to_json(out / "by_category.json", orient="records", indent=2)
        by_src.to_json(out / "by_source.json", orient="records", indent=2)

    # also write combined stats json for Flask
    stats = {
        "day": day,
        "total": len(df),
        "by_category": dict(zip(by_cat["category"], by_cat["count"])),
        "by_source": dict(zip(by_src["source"], by_src["count"])),
    }
    (out / "daily_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return out


def run_gold(day: str = None) -> Path:
    """PySpark path — requires Java + pyspark."""
    try:
        from pyspark.sql import SparkSession
        import pyspark.sql.functions as F
    except ImportError as e:
        raise RuntimeError("pyspark not installed") from e

    rows = _load_silver(day)
    if not rows:
        raise ValueError(f"no silver rows for day {day}")

    spark = SparkSession.builder.master("local[*]").appName("sniffer-gold").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    df = spark.createDataFrame(rows)
    # ponytail: repartition proves distributed, but keep 2 partitions for small data
    df = df.repartition(2, "source") if "source" in df.columns else df.repartition(2)

    # normalize category
    if "category" not in df.columns:
        df = df.withColumn("category", F.lit("general"))
    else:
        df = df.withColumn("category", F.coalesce(F.col("category"), F.lit("general")))

    by_cat = df.groupBy("category").count().orderBy(F.desc("count"))
    by_src = df.groupBy("source").count().orderBy(F.desc("count")) if "source" in df.columns else None

    day = (day or datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("/", "-")
    out = GOLD_ROOT / day
    out.mkdir(parents=True, exist_ok=True)

    # write via pandas for simplicity (spark write needs hadoop)
    by_cat.toPandas().to_parquet(out / "by_category.parquet", index=False)
    if by_src is not None:
        by_src.toPandas().to_parquet(out / "by_source.parquet", index=False)

    # stats json
    total = df.count()
    cat_dict = {r["category"]: r["count"] for r in by_cat.collect()}
    src_dict = {r["source"]: r["count"] for r in by_src.collect()} if by_src else {}
    (out / "daily_stats.json").write_text(
        json.dumps({"day": day, "total": total, "by_category": cat_dict, "by_source": src_dict}, indent=2),
        encoding="utf-8",
    )

    spark.stop()
    return out

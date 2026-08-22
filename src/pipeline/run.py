"""
Pipeline Runner — Medallion Lakehouse Build
Orchestrates end-to-end execution:
Ingestion (Bronze) -> Validation & Quarantine -> Enrichment -> Silver Parquet -> Gold Analytics Marts.
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.ingest import write_bronze_by_source
from pipeline.validate import (
    validate_batch, save_quarantine_records, save_quality_metrics
)
from pipeline.enrich import enrich_batch
from pipeline.transform import to_silver, read_bronze_records
from processing.spark_job import run_gold

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pipeline.run")


def scrape_sources(hn_pages: int = 1, force: bool = True):
    """Executes heterogeneous scraping across all enabled sources."""
    from web_scraper import NewsAggregator
    aggregator = NewsAggregator()
    aggregator.scrape_all(hn_pages=hn_pages, force=force)
    return aggregator.get_articles()


def run_pipeline(no_scrape: bool = False, day: str = None) -> dict:
    """Executes the complete Medallion Lakehouse data pipeline."""
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = day.replace("/", "-")

    logger.info(f"=== Starting Lakehouse Pipeline for Partition: day={day} ===")

    # 1. BRONZE LAYER: Ingestion
    if not no_scrape:
        logger.info("[1/5] Ingesting raw records from heterogeneous feeds...")
        articles = scrape_sources()
        logger.info(f"Scraped {len(articles)} raw articles.")
        bronze_outputs = write_bronze_by_source(articles, day=day)
        logger.info(f"Bronze layer updated across {len(bronze_outputs)} source partitions.")
    else:
        logger.info(f"[1/5] Reusing existing Bronze records for day={day} (--no-scrape)")
        articles = read_bronze_records(day=day)
        logger.info(f"Loaded {len(articles)} existing Bronze records.")

    if not articles:
        logger.warning(f"No records available to process for day={day}. Exiting.")
        return {"status": "EMPTY", "day": day}

    # 2. DATA QUALITY GATE: Validation & Quarantine Isolation
    logger.info("[2/5] Running declarative data quality checks...")
    valid_records, quarantined_records, quality_summary = validate_batch(articles, day=day)
    save_quality_metrics(quality_summary)

    if quarantined_records:
        q_path = save_quarantine_records(quarantined_records, day=day)
        logger.warning(
            f"Quarantined {len(quarantined_records)} bad records (saved to {q_path}). "
            f"Pass rate: {quality_summary['data_quality_pass_rate_percent']}%"
        )
    else:
        logger.info(f"100% data quality pass rate ({len(valid_records)} records).")

    # 3. ENRICHMENT: NLP Extractive Summaries & Metadata
    logger.info("[3/5] Enriching articles with extractive deks and bullets...")
    enriched_records = enrich_batch(valid_records, fetch=False)

    # 4. SILVER LAYER: Hive-Partitioned Snappy Parquet
    logger.info("[4/5] Transforming to Silver Snappy Parquet layer...")
    silver_path = to_silver(enriched_records, day=day)
    logger.info(f"Silver Parquet written to: {silver_path}")

    # 5. GOLD LAYER: Analytical Marts (PySpark / DuckDB)
    logger.info("[5/5] Building Gold analytical marts & window rankings...")
    gold_path = run_gold(day=day)
    logger.info(f"Gold analytical marts generated at: {gold_path}")

    logger.info("=== Lakehouse Pipeline Completed Successfully ===")
    return {
        "status": "SUCCESS",
        "day": day,
        "valid_count": len(valid_records),
        "quarantined_count": len(quarantined_records),
        "quality_pass_rate": quality_summary["data_quality_pass_rate_percent"],
    }


def main():
    parser = argparse.ArgumentParser(description="Medallion Lakehouse Pipeline Runner")
    parser.add_argument("--no-scrape", action="store_true", help="Reprocess existing Bronze records without scraping")
    parser.add_argument("--day", default=None, help="Target partition date (format: YYYY-MM-DD)")
    args = parser.parse_args()

    run_pipeline(no_scrape=args.no_scrape, day=args.day)


if __name__ == "__main__":
    main()

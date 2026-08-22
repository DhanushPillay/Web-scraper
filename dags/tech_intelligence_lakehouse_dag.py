"""
Apache Airflow DAG — Tech Intelligence Lakehouse Orchestrator
Demonstrates production workflow orchestration, task dependencies, retry policies,
and data quality gates for enterprise Data Platform Engineering.
"""
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("airflow.task")

# Default arguments for enterprise reliability
DEFAULT_ARGS = {
    "owner": "data_platform_team",
    "depends_on_past": False,
    "start_date": datetime(2026, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
    "execution_timeout": timedelta(minutes=15),
}

try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
    from airflow.operators.bash import BashOperator

    def task_check_sources(**context):
        """Pre-flight check: verifies network reachability of data feeds."""
        import requests
        feeds = [
            "https://hnrss.org/frontpage",
            "https://techcrunch.com/feed/",
            "https://api.github.com/zen"
        ]
        healthy = 0
        for f in feeds:
            try:
                r = requests.head(f, timeout=5)
                if r.status_code < 400:
                    healthy += 1
            except Exception:
                pass
        logger.info(f"Source pre-flight check: {healthy}/{len(feeds)} sources online.")
        return healthy > 0

    def task_ingest_bronze(**context):
        """Ingests heterogeneous feeds and writes append-only Bronze JSONL."""
        from pipeline.ingest import write_bronze_by_source
        from web_scraper import NewsAggregator
        
        exec_date = context.get("ds", datetime.now().strftime("%Y-%m-%d"))
        agg = NewsAggregator()
        agg.scrape_all(force=True)
        articles = agg.get_articles()
        outputs = write_bronze_by_source(articles, day=exec_date)
        return len(articles)

    def task_validate_and_quarantine(**context):
        """Evaluates declarative data contracts and quarantines bad records."""
        from pipeline.transform import read_bronze_records
        from pipeline.validate import validate_batch, save_quarantine_records, save_quality_metrics
        
        exec_date = context.get("ds", datetime.now().strftime("%Y-%m-%d"))
        raw = read_bronze_records(day=exec_date)
        valid, quarantined, metrics = validate_batch(raw, day=exec_date)
        
        save_quality_metrics(metrics)
        if quarantined:
            save_quarantine_records(quarantined, day=exec_date)
            
        if metrics["data_quality_pass_rate_percent"] < 70.0:
            raise ValueError(f"Data quality alert: Pass rate dropped to {metrics['data_quality_pass_rate_percent']}%")
        return len(valid)

    def task_transform_silver(**context):
        """Converts validated data into Hive-partitioned Snappy Parquet."""
        from pipeline.transform import read_bronze_records, to_silver
        from pipeline.validate import validate_batch
        from pipeline.enrich import enrich_batch
        
        exec_date = context.get("ds", datetime.now().strftime("%Y-%m-%d"))
        raw = read_bronze_records(day=exec_date)
        valid, _, _ = validate_batch(raw, day=exec_date)
        enriched = enrich_batch(valid, fetch=False)
        out_path = to_silver(enriched, day=exec_date)
        return str(out_path)

    def task_spark_gold_marts(**context):
        """Runs PySpark/DuckDB analytical aggregations and window rankings."""
        from processing.spark_job import run_gold
        exec_date = context.get("ds", datetime.now().strftime("%Y-%m-%d"))
        out_dir = run_gold(day=exec_date)
        return str(out_dir)

    with DAG(
        dag_id="tech_intelligence_lakehouse_pipeline",
        default_args=DEFAULT_ARGS,
        description="Daily Medallion Lakehouse ETL (Bronze -> Silver -> Gold Marts)",
        schedule_interval="0 2 * * *",  # Daily at 02:00 UTC (07:30 IST)
        catchup=False,
        max_active_runs=1,
        tags=["lakehouse", "pyspark", "duckdb", "parquet", "finops_zero_cost"],
    ) as dag:

        check_sources = PythonOperator(
            task_id="check_sources_connectivity",
            python_callable=task_check_sources,
        )

        ingest_bronze = PythonOperator(
            task_id="ingest_heterogeneous_bronze",
            python_callable=task_ingest_bronze,
        )

        validate_quarantine = PythonOperator(
            task_id="validate_and_quarantine_records",
            python_callable=task_validate_and_quarantine,
        )

        transform_silver = PythonOperator(
            task_id="transform_silver_snappy_parquet",
            python_callable=task_transform_silver,
        )

        build_gold_marts = PythonOperator(
            task_id="build_gold_analytical_marts",
            python_callable=task_spark_gold_marts,
        )

        # Define DAG Task Dependencies
        check_sources >> ingest_bronze >> validate_quarantine >> transform_silver >> build_gold_marts

except ImportError:
    # Airflow is not installed locally (running in lightweight developer mode)
    dag = None

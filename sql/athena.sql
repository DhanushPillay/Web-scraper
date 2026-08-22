-- Sniffer — Athena / DuckDB query on S3 Gold (lakehouse demo)
-- ponytail: same SQL works on DuckDB read_parquet and Athena external table; shows warehouse thinking without Redshift cost.

-- Gold daily stats (written by processing/spark_job.py)
-- S3 layout: s3://sniffer-lake/gold/day=2026/08/22/by_category.parquet
SELECT category, count
FROM read_parquet('data/gold/**/by_category.parquet', hive_partitioning=1)
ORDER BY count DESC;

SELECT source, count
FROM read_parquet('data/gold/**/by_source.parquet', hive_partitioning=1)
ORDER BY count DESC;

-- Athena DDL (if you later create external table)
-- CREATE EXTERNAL TABLE gold_daily (
--   category string,
--   count int
-- ) PARTITIONED BY (day string)
-- STORED AS PARQUET LOCATION 's3://sniffer-lake/gold/';
-- MSCK REPAIR TABLE gold_daily;

-- ============================================================================
-- Lakehouse Analytical SQL Suite & DDL
-- Compatible with both DuckDB (Local/CI - ₹0 cost) and AWS Athena (Cloud Lake)
-- Demonstrates partition pruning, window functions, CTEs, and aggregation marts.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- SECTION 1: AWS Athena / Glue Data Catalog External Table Definitions
-- ----------------------------------------------------------------------------

-- Silver Layer External Table (Partitioned by day and source)
-- CREATE EXTERNAL TABLE IF NOT EXISTS tech_intelligence.silver_articles (
--     record_hash STRING,
--     title STRING,
--     link STRING,
--     author STRING,
--     score INT,
--     category STRING,
--     sentiment STRING,
--     sentiment_score DOUBLE,
--     read_time INT,
--     time_posted STRING,
--     excerpt STRING,
--     dek STRING
-- )
-- PARTITIONED BY (day STRING, source STRING)
-- STORED AS PARQUET
-- LOCATION 's3://sniffer-lake/silver/'
-- TBLPROPERTIES (
--     'parquet.compression'='SNAPPY',
--     'projection.enabled'='true',
--     'projection.day.type'='date',
--     'projection.day.range'='2026-01-01,NOW',
--     'projection.day.format'='yyyy-MM-dd',
--     'projection.source.type'='enum',
--     'projection.source.values'='Hacker News,TechCrunch,Reddit,The Verge,Ars Technica,GitHub Trending,arXiv'
-- );

-- ----------------------------------------------------------------------------
-- SECTION 2: Production Analytical Queries (DuckDB / Athena Compatible)
-- ----------------------------------------------------------------------------

-- Query 1: Source Credibility & Engagement Matrix
-- Identifies highest-signal content sources by normalizing engagement scores across categories.
WITH source_stats AS (
    SELECT
        source,
        category,
        COUNT(*) AS total_articles,
        ROUND(AVG(score), 2) AS avg_engagement,
        ROUND(AVG(sentiment_score), 3) AS avg_sentiment,
        ROUND(AVG(read_time), 1) AS avg_reading_time_mins
    FROM read_parquet('data/silver/**/*.parquet', hive_partitioning=1)
    GROUP BY source, category
)
SELECT
    source,
    category,
    total_articles,
    avg_engagement,
    avg_sentiment,
    avg_reading_time_mins,
    DENSE_RANK() OVER (PARTITION BY category ORDER BY avg_engagement DESC) AS source_category_rank
FROM source_stats
ORDER BY category, source_category_rank;


-- Query 2: Category Momentum & Sentiment Trends
-- Analyzes topic velocity and emotional distribution across the tech landscape.
SELECT
    category,
    COUNT(*) AS total_volume,
    ROUND(SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS pct_positive,
    ROUND(SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS pct_negative,
    ROUND(AVG(sentiment_score), 3) AS net_sentiment_score,
    MAX(score) AS peak_engagement
FROM read_parquet('data/silver/**/*.parquet', hive_partitioning=1)
GROUP BY category
ORDER BY total_volume DESC;


-- Query 3: Top Trending Articles with Deduplicated Window Ranking
-- Finds the top 3 most impactful stories per category for executive briefing.
WITH ranked_articles AS (
    SELECT
        title,
        link,
        source,
        category,
        score,
        sentiment,
        ROW_NUMBER() OVER (
            PARTITION BY category 
            ORDER BY score DESC, sentiment_score DESC
        ) AS category_rank
    FROM read_parquet('data/silver/**/*.parquet', hive_partitioning=1)
)
SELECT
    category,
    category_rank,
    title,
    source,
    score,
    sentiment,
    link
FROM ranked_articles
WHERE category_rank <= 3
ORDER BY category, category_rank;

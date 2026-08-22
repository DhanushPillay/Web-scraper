# Cloud-Native Lakehouse Platform — Technical Architecture

This document provides a comprehensive technical breakdown of the **Cloud-Native Lakehouse & Automated Tech Intelligence Ingestion Platform**.

---

## 1. Architectural Philosophy: Medallion Lakehouse

The platform decouples ingestion, validation, distributed transformation, and analytical serving into a **Medallion Data Lakehouse** architecture running at **₹0 / $0 cloud infrastructure cost**:

```text
                           [ DATA SOURCES ]
            ┌───────────────────────────┬───────────────────────────┐
            │  RSS / Atom Feeds         │  REST / JSON APIs         │  XML Feeds
            │  (HN, TechCrunch, Verge)  │  (Reddit, GitHub Trends)  │  (arXiv CS)
            └─────────────┬─────────────┴─────────────┬─────────────┴─────┬─────┘
                          │                           │                   │
                          ▼                           ▼                   ▼
                  ┌───────────────────────────────────────────────────────────┐
                  │            BaseScraper (HTTP Retry 3x Backoff)            │
                  │       Async HTTP + Bounded Concurrency (Semaphore 8)      │
                  │       Credibility Filter + Deduplication (by Link)        │
                  └─────────────────────────────┬─────────────────────────────┘
                                                │
                                                ▼
     ┌─────────────────────────────────────────────────────────────────────────────────────┐
     │                             MEDALLION DATA PIPELINE                                 │
     │                                                                                     │
     │  1. BRONZE LAYER (Raw Ingestion)                                                    │
     │     └── Output: data/bronze/YYYY-MM-DD/<source>.jsonl (Append-only + SHA-256 Hash)  │
     │                                                                                     │
     │  2. DATA QUALITY GATE & QUARANTINE                                                  │
     │     ├── validate.py: Evaluates declarative schema contracts                         │
     │     ├── Quarantine: Corrupted records saved to data/quarantine/                     │
     │     └── Metrics: Observability summary saved to data/logs/quality_metrics.json      │
     │                                                                                     │
     │  3. SILVER LAYER (Structured & Cleaned)                                             │
     │     └── transform.py: PyArrow Snappy Parquet partitioned by [day, source]           │
     │                                                                                     │
     │  4. GOLD LAYER (Analytical Marts via PySpark & DuckDB)                              │
     │     └── spark_job.py: PySpark local[*] / DuckDB in-memory analytical engine         │
     │         - Window Ranking: DENSE_RANK() top stories per category                     │
     │         - Aggregation Marts: category_metrics.parquet, source_metrics.parquet       │
     └──────────────────────────────────────────┬──────────────────────────────────────────┘
                                                │
                 ┌──────────────────────────────┴──────────────────────────────┐
                 ▼                                                             ▼
    [ SERVING & OLTP LAYER ]                                      [ ORCHESTRATION & IAC ]
    ├── Flask Mobile PWA (Gunicorn, Port 7860)                    ├── GitHub Actions CI/CD (Test & Build)
    ├── SQLite WAL (Local) / Neon Postgres (Prod)                 ├── Apache Airflow DAG (Local/Prod)
    ├── DuckDB (Direct SQL on Gold Parquet Marts)                 ├── Docker & Docker Compose
    └── FTS5 Full-Text Search + REST APIs                         └── Terraform (AWS S3 + Athena Stub)
```

---

## 2. Ingestion Layer (`web_scraper.py` & `pipeline/ingest.py`)

### 2.1 Heterogeneous Protocols
The ingestion engine extracts from 7 heterogeneous sources across 3 protocol standards:
* **RSS Feeds**: Hacker News, TechCrunch, The Verge, Ars Technica.
* **REST APIs (JSON)**: Reddit (`/r/technology/top.json`), GitHub Search API (trending repositories with `stars:>5000`).
* **XML Atom API**: arXiv CS research paper repository (`cs.AI`, `cs.LG`, `cs.DC`).

### 2.2 Idempotency & Checksumming
Each raw record is assigned a deterministic SHA-256 fingerprint:
$$\text{record\_hash} = \text{SHA-256}(\text{source} + ":" + \text{canonical\_link})$$
Bronze JSONL appends check for existing hashes in the partition boundary to guarantee that repeated ingestion runs are **100% idempotent**.

---

## 3. Data Quality Gate (`pipeline/validate.py`)

Every ingested record passes through a declarative schema contract:
* **Required Field Integrity**: `title`, `link`, `source` must be non-null and non-empty.
* **Length Constraints**: $10 \le \text{len(title)} \le 500$.
* **URL Format**: Strictly validated HTTP/HTTPS syntax.
* **Score Bounds**: Integer scores $\ge 0$.

### Quarantine Routing
Records failing validation are isolated into `data/quarantine/YYYY-MM-DD/quarantined_records.jsonl` with structured diagnostic error tags. Pass rate metrics are logged to `data/logs/quality_metrics.json`.

---

## 4. Transformation & Analytical Marts

### 4.1 Silver Layer (`pipeline/transform.py`)
Converts validated records into columnar **Snappy Parquet** tables Hive-partitioned by `day=YYYY-MM-DD/source=<source>/`. This enables partition pruning and dictionary compression (reducing disk storage by 60–80%).

### 4.2 Gold Layer (`processing/spark_job.py`)
Executes analytical transformations with dual-engine support:
* **Apache Spark (PySpark 3.5)**: Distributed DataFrame operations, repartitioning, and window functions (`DENSE_RANK() OVER (PARTITION BY category ORDER BY score DESC)`).
* **DuckDB (Zero-JVM Fallback)**: Embedded vectorized SQL engine executing analytical views with zero external cloud infrastructure costs.

---

## 5. Storage & Serving Layer

| Storage Layer | Technology | Primary Job |
| :--- | :--- | :--- |
| **Data Lake** | Hive-Partitioned Parquet | Columnar analytical storage for multi-source trend analysis |
| **OLTP Database** | SQLite WAL / Neon PostgreSQL | High-concurrency transactional storage for user bookmarks and search |
| **Analytics Engine**| DuckDB In-Memory | Real-time vectorized SQL querying over Parquet partitions |
| **Search Engine** | SQLite FTS5 | Full-text indexing over titles and article previews |

---

## 6. Orchestration, IaC & CI/CD

* **Apache Airflow (`dags/`)**: Production DAG definition mapping `check_sources >> ingest_bronze >> validate_quarantine >> transform_silver >> build_gold_marts`.
* **Terraform (`infrastructure/main.tf`)**: Infrastructure-as-Code specification defining S3 lifecycle transitions (Standard $\to$ IA $\to$ Expiration), Glue Data Catalog, and Athena Workgroup with FinOps query scan limits (500 MB max scan).
* **GitHub Actions (`.github/workflows/daily.yml`)**: Automated Pytest execution on pull requests and daily scheduled pipeline builds publishing quality telemetry.

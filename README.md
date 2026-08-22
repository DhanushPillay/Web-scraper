# Cloud-Native Lakehouse & Automated Tech Intelligence Ingestion Platform

![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![PySpark](https://img.shields.io/badge/Apache%20Spark-3.5-E25A1C?logo=apachespark&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-In--Memory%20OLAP-FFF000?logo=duckdb&logoColor=black)
![Pytest](https://img.shields.io/badge/tests-13%20passed%20(100%25)-brightgreen)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-orange)

An automated **Medallion Lakehouse Data Platform** ingesting 7 heterogeneous sources across RSS, JSON REST, and XML Atom protocols into a partitioned Snappy Parquet data lake. Processes analytics via **PySpark** and **DuckDB**, enforces declarative data contracts with quarantine isolation, and serves real-time intelligence via an accessible mobile PWA dashboard — **100% Free / ₹0 Infrastructure Cost**.

---

## 🏛️ Medallion Lakehouse Architecture (₹0 / No Hyperscaler Billing)

```text
[RSS Feeds] HN · TechCrunch · Verge · Ars  +  [JSON APIs] Reddit · GitHub Trends  +  [XML] arXiv CS
                               │
                               ▼
Bronze Layer       data/bronze/YYYY-MM-DD/<source>.jsonl  (Append-only + SHA-256 Checksum)
                               │
                               ▼
Data Quality Gate  pipeline/validate.py  (Declarative Schema Contracts)
                   ├── Valid Records ──► Silver Layer
                   └── Quarantined   ──► data/quarantine/ + data/logs/quality_metrics.json
                               │
                               ▼
Silver Layer       data/silver/day=.../source=.../*.parquet  (PyArrow Snappy Parquet)
                               │
                               ▼
Gold Layer         data/gold/YYYY-MM-DD/  (PySpark local[*] / DuckDB Vectorized SQL)
                   ├── category_metrics.parquet (Category Volume, Engagement, Sentiment)
                   ├── source_metrics.parquet   (Source Credibility & Volume Distribution)
                   └── top_ranked_articles.parquet (DENSE_RANK Window Ranking)
                               │
                               ▼
Serving & OLAP     Flask Mobile PWA + Neon Serverless Postgres (OLTP) + DuckDB (OLAP)
```

---

## 🌟 Key Engineering Capabilities

* **Heterogeneous Multi-Protocol Ingestion**: Ingests across 3 protocol standards (RSS, JSON REST API, XML Atom API) with exponential backoff and bounded async concurrency (`Semaphore(8)`).
* **Idempotent Checksumming**: Computes deterministic SHA-256 fingerprint hashes (`source + canonical_link`) to guarantee zero duplicate records on pipeline re-runs.
* **Declarative Data Quality Gate**: Validates incoming batches against strict schema contracts. Corrupted or invalid records are isolated to `data/quarantine/`, and observability metrics are tracked in `data/logs/quality_metrics.json`.
* **Columnar Storage & Partition Pruning**: Stores Silver datasets in Hive-partitioned Snappy Parquet (`day=YYYY-MM-DD/source=<source>/`), enabling columnar dictionary compression and predicate pushdown.
* **Dual-Engine Transformations**:
  * **PySpark 3.5**: Distributed window ranking (`DENSE_RANK() OVER (PARTITION BY category ORDER BY score DESC)`), rolling metrics, and repartitioning.
  * **DuckDB**: Embedded in-process vectorized analytical SQL engine providing sub-millisecond execution locally and in CI runners.
* **Workflow Orchestration & IaC**:
  * **Apache Airflow (`dags/`)**: Production DAG definition mapping ingestion, validation, Silver Parquet transformations, and Gold mart aggregation.
  * **Terraform (`infrastructure/main.tf`)**: Infrastructure-as-Code declaring S3 storage tiering, AWS Glue Data Catalog, and Athena Workgroup with FinOps query scan limits (500 MB max scan cutoff).
* **Automated Pytest Suite**: 13 unit and integration tests verifying validation, idempotency, transformations, DuckDB queries, and database integrity (**100% passing**).

---

## 🚀 Quick Start (Local Setup)

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/DhanushPillay/Web-scraper.git
cd Web-scraper
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python -c "import nltk; [nltk.download(r, quiet=True) for r in ['punkt','punkt_tab','vader_lexicon','stopwords']]"
```

### 2. Run Automated Test Suite
```bash
pytest tests/ -v
```

### 3. Build Lakehouse Pipeline (Bronze ➔ Silver ➔ Gold)
```bash
# Full ingestion and lakehouse build
python pipeline/run.py

# Or reprocess existing Bronze records without scraping
python pipeline/run.py --no-scrape
```

### 4. Start Web Application Dashboard
```bash
python app.py
# Open http://localhost:7860 in your browser
```

### 5. Run with Docker Compose
```bash
docker compose up --build
```

---

## 📊 Analytical SQL Queries (DuckDB / Athena Compatible)

Query the local Parquet data lake directly using DuckDB in-memory SQL:

```python
import duckdb

con = duckdb.connect()

# Category Momentum & Sentiment Trends
df = con.execute("""
    SELECT
        category,
        COUNT(*) AS article_count,
        ROUND(AVG(score), 2) AS avg_engagement,
        ROUND(AVG(sentiment_score), 3) AS avg_sentiment
    FROM read_parquet('data/silver/**/*.parquet', hive_partitioning=1)
    GROUP BY category
    ORDER BY article_count DESC;
""").df()

print(df)
```

---

## ⚙️ Configuration & Environment Variables

All settings are optional and default to zero-config local operation:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DATABASE_URL` | SQLite (`sniffer.db`) | Neon Serverless PostgreSQL DSN (`postgresql://.../neondb`) |
| `SECRET_KEY` | Auto-generated | Flask session encryption key |
| `GITHUB_TOKEN` | — | Raises GitHub API rate limits from 60 to 5,000 req/hr |
| `ALLOWED_ORIGINS` | — | Comma-separated CORS allowlist |
| `RATE_LIMIT_STORAGE` | `memory://` | Storage backend for rate limiting (supports Redis) |

---

## 🆓 ₹0 / $0 Free-Tier Deployment Topology

| Component | Platform | Free Quota / Limits |
| :--- | :--- | :--- |
| **Compute & CI/CD** | GitHub Actions | Unlimited runner minutes on public repos (2 vCPU, 7 GB RAM) |
| **Transactional DB**| Neon PostgreSQL | 0.5 GB permanent storage, auto-suspend (No 30-day auto-delete) |
| **Analytics Engine**| DuckDB In-Memory | Embedded C++ engine — zero external cloud infrastructure costs |
| **Web Service** | Render (Free Web Service) / Local Docker | 750 free instance hours/month |
| **IaC Portfolio** | Terraform | Static specification (`infrastructure/main.tf`) for portfolio review |

---

## 📁 Repository Structure

```text
Web-scraper/
├── .github/
│   └── workflows/
│       └── daily.yml              # CI/CD automated testing & daily lakehouse cron
├── configs/
│   └── sources.yaml               # Declarative feed configuration
├── dags/
│   └── tech_intelligence_lakehouse_dag.py # Apache Airflow orchestration DAG
├── data/                          # Data Lake (Git-ignored)
│   ├── bronze/                    # Raw append-only JSONL
│   ├── silver/                    # Hive-partitioned Snappy Parquet
│   ├── gold/                      # Analytical Parquet marts & JSON summaries
│   ├── quarantine/                # Corrupted/invalid records with diagnostic tags
│   └── logs/                      # Data quality metrics & run history
├── doc/
│   └── project_explanation.md     # In-depth architectural technical specification
├── infrastructure/
│   └── main.tf                    # Terraform IaC (S3, Glue Catalog, Athena Workgroup)
├── pipeline/
│   ├── enrich.py                  # NLP extractive summary & bullet generation
│   ├── ingest.py                  # Bronze ingestion & SHA-256 fingerprinting
│   ├── run.py                     # Medallion lakehouse orchestrator
│   ├── transform.py               # Silver Snappy Parquet transformation
│   └── validate.py                # Declarative data quality contracts & quarantine
├── processing/
│   └── spark_job.py               # PySpark & DuckDB Gold analytical marts
├── sql/
│   └── athena.sql                 # Athena DDL & production analytical SQL queries
├── static/                        # CSS design tokens, JS PWA service worker
├── templates/                     # Mobile-first PWA dashboard UI
├── tests/
│   └── test_pipeline.py           # 13 automated unit & integration Pytest tests
├── utils/
│   └── credibility.py             # Clickbait & credibility scoring filter
├── app.py                         # Flask API & analytical dashboard
├── database.py                    # PostgreSQL connection pooling & SQLite WAL
├── web_scraper.py                 # Async heterogeneous scrapers & NewsAggregator
├── Dockerfile                     # Multi-stage production container definition
├── docker-compose.yml             # Local multi-service orchestration
├── render.yaml                    # Render Web Service deployment blueprint
└── requirements.txt               # Locked production dependencies
```

---

## 📜 License

Distributed under the MIT License.
# Sniffer: The Zero-Cost Cloud-Native Data Lakehouse

![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![Flask](https://img.shields.io/badge/Flask-3.1%2B-000000?logo=flask&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-In--Memory%20OLAP-FFF000?logo=duckdb&logoColor=black)
![Pytest](https://img.shields.io/badge/tests-15%20passed%20(100%25)-brightgreen)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-orange)

## What is Sniffer?

The tech industry moves faster than anyone can read. Between Hacker News, Reddit, arXiv papers, and a dozen different tech blogs, finding the actual signal through the noise is practically a full-time job. 

Sniffer is a personal solution to information overload. 

It is an automated data engineering pipeline that scrapes multiple tech sources across the web, standardizes the unstructured data into a clean Data Lakehouse, runs analytical ranking algorithms, and serves the best stories of the day through a premium editorial web dashboard. Best of all, it achieves this entire pipeline on a strictly zero-cost cloud budget.

---

## How it Works: The Split-Layer Architecture

To keep NLTK sentiment analysis, the article body fetches and the analytical marts off the free-tier web host, I split the work across two runtimes. 

This keeps the web application small and stable while the memory-intensive work runs in GitHub Actions. Here is how the data flows from the messy internet down to the clean dashboard:

```mermaid
flowchart TD
    %% Styling
    classDef source fill:#141415,stroke:#242426,stroke-width:1px,color:#F2F2F2
    classDef bronze fill:#b08d57,stroke:#8B5A2B,stroke-width:2px,color:#111
    classDef silver fill:#C0C0C0,stroke:#808080,stroke-width:2px,color:#111
    classDef gold fill:#FFD700,stroke:#DAA520,stroke-width:2px,color:#111
    classDef serve fill:#0B0B0C,stroke:#3B82F6,stroke-width:2px,color:#F2F2F2
    classDef error fill:#331111,stroke:#EF4444,stroke-width:1px,color:#EF4444,stroke-dasharray: 5 5

    %% Sources
    subgraph Sources ["1. The Internet (Heterogeneous Sources)"]
        RSS[RSS Feeds<br/>HN, TechCrunch]:::source
        REST[JSON APIs<br/>Reddit, GitHub]:::source
        XML[XML Atom<br/>arXiv]:::source
    end

    %% Ingestion (GitHub Actions)
    Ingest[GitHub Actions Worker<br/>Scraping & Extraction]:::source
    
    RSS & REST & XML --> Ingest
    Ingest -->|0 articles from every source| FailRun([Fail the run red<br/>exit 1 — a dead feed must not look healthy]):::error
    
    %% Bronze
    Ingest -->|Raw JSONL| Bronze[(Bronze Layer<br/>Raw Data)]:::bronze
    
    %% Validation
    Validate{Data Quality Gate<br/>Schema Contracts}
    Bronze --> Validate
    Validate -->|Fails Contract| Quarantine([Quarantine / Dead Letter Queue]):::error
    
    %% Silver
    Validate -->|Passes| Silver[(Silver Layer<br/>Snappy Parquet)]:::silver
    
    %% Gold
    GoldJob[DuckDB<br/>Window Rankings & Aggregates]:::source
    Silver --> GoldJob
    GoldJob --> Gold[(Gold Layer<br/>Analytical Marts)]:::gold
    
    %% Serving
    Gold --> DB[(Neon Postgres<br/>Serverless Database)]:::serve
    DB <--> App[Render Web Service<br/>Lightweight Flask Dashboard]:::serve
```

### 1. The Heavy Lifter: GitHub Actions (Background Worker)
Every hour a scheduled GitHub Action spins up a hosted Ubuntu runner, free on a public repository. It executes the background scraping routine which:
- Scrapes the latest articles from Hacker News and six other sources.
- Uses Trafilatura to extract the full text of articles.
- Runs NLTK Vader to perform sentiment analysis and computes reading times.
- Writes that metadata back in one connection and one `executemany`, not one transaction per row.
- Fails loudly (`exit 1`) when zero articles scrape from every source, so a dead feed turns the run red instead of passing silently.
- Logs honest accounting (`Inserted N new, skipped M duplicates`). `inserted` comes from `cursor.rowcount` after the write, so rows that another session inserted first are not counted as new.
- Runs retention and the metadata backlog drain on every run, including a zero-article one. Prune is the only thing that deletes rows, so skipping it during a feed outage let the table grow without bound.
- Raises if an NLTK resource cannot be downloaded, before anything is written to the database, and aborts on a broken VADER lexicon instead of stamping `neutral/0.0` and marking the row processed for good.
- Sets `SNIFFER_REQUIRE_POSTGRES=1`, so an unreachable database fails the run instead of writing to an ephemeral runner-local SQLite file that vanishes with the runner.
- Initializes NLTK lazily, only when there is metadata to compute, so empty runs exit before downloading data or loading the lexicon.
- Logs per-phase timings (`Phase scrape/enrich/db-write+prune took …s`) so the hourly run's cost breakdown is visible in every log.

### 2. The Presentation Layer: Render (Web Dashboard)
The web application runs on Render and is decoupled from the scraping process. It is a read-only presentation layer over the database, and it serves the pre-computed NLP metadata. On-demand summaries come from an offline extractive summarizer: a normalized first-sentence dek plus word-frequency bullets, with Jaccard dedup so the dek is not repeated as a bullet. No LLM, no extra dependency.

---

## Key Engineering Features

1. **Heterogeneous Multi-Protocol Ingestion**: Not all APIs are created equal. Sniffer pulls data simultaneously from RSS, JSON REST APIs, and XML Atom feeds using async Python with built-in retry logic.
2. **Decoupled Architecture for Stability**: By separating scraping, enrichment and the analytical marts into GitHub Actions and keeping the web app lightweight, the system avoids memory crashes entirely on free-tier platforms.
3. **Resilient Database Connections**: The Postgres pool is sized for the gunicorn thread count (`SNIFFER_PG_POOL_MIN`, default 4) so warm connections are actually reused, and a transient failure degrades to a local SQLite file for that one request instead of pinning the worker to it for the life of the process.
4. **Columnar Storage**: Data is saved as Hive-partitioned Snappy Parquet files. This compresses data heavily and allows an embedded engine like DuckDB to query it directly from disk. A Silver partition is wiped and rewritten on every run, so re-running the same day no longer appends a second copy of every row.
5. **Idempotent Bronze Appends**: Each Bronze partition is written under an `O_CREAT|O_EXCL` lock sentinel that is reclaimed after 300 seconds, and every line is parsed independently, so one corrupt line or a crashed run cannot duplicate or wedge a partition.
6. **Premium Editorial UI**: The front-end is not a generic template. It has a bespoke high-contrast dark mode with micro-animations and a slide-out drawer for Quick Reads. The template carries no inline event handlers, which lets the CSP ship `script-src 'self'` with `script-src-attr 'none'`.

---

## The Zero-Cost Infrastructure Setup

Building a Data Lakehouse usually means spending hundreds of dollars on AWS or GCP. I wanted to prove that modern data engineering can be done efficiently on the free tier.

| Component | Technology | Cost |
| :--- | :--- | :--- |
| **Compute / Pipeline** | GitHub Actions (Unlimited public runner minutes) | $0 |
| **Transactional Database**| Neon Serverless PostgreSQL | $0 |
| **Analytics Engine**| DuckDB (Embedded C++ engine, no servers needed) | $0 |
| **Web Hosting** | Render (Free Web Service tier) | $0 |

> **Live path vs. showcase**: The Flask app, the two GitHub Actions workflows and DuckDB are the live stack. `infrastructure/main.tf` (S3, Glue, Athena), `sql/athena.sql` and `dags/` are portfolio material: they show what the same pipeline maps to on AWS and on a managed orchestrator, and nothing in the free stack runs them. The optional `HF_DATASET` lookup is only a fallback the app tries when no local Gold partition exists.

---

## Quick Start (Run it Locally)

Want to run the pipeline yourself? It is incredibly easy to spin up locally.

### 1. Clone and Install
```bash
git clone https://github.com/DhanushPillay/Web-scraper.git
cd Web-scraper
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# Mac/Linux:
source .venv/bin/activate

# Install the lightweight web dependencies
pip install -r requirements.txt
# Add nltk, which only the scraper's sentiment pass needs
pip install -r requirements-actions.txt
```

### 2. Run the Background Scraper
```bash
# Export your database URL (Neon Postgres or local SQLite/Postgres)
export DATABASE_URL="postgresql://user:pass@host/dbname"

# Run the scraper (exits 1 if DATABASE_URL is unset or no feed returns an article)
python scripts/github_scrape.py
```

### 3. Start the Web Dashboard
```bash
# From the root directory (make sure your DATABASE_URL is set)
python src/app.py
# Open http://localhost:7860 to see the UI.
```

### 4. Build the Lakehouse Locally
```bash
pip install -r requirements-actions.txt
# Bronze -> validation -> Silver Parquet -> Gold marts for today
python src/pipeline/run.py
# Reprocess an existing day without hitting the feeds again
python src/pipeline/run.py --no-scrape --day 2026-08-22
```

---

## Project Structure

```text
Web-scraper/
├── .github/workflows/       # CI/CD: hourly scrape job, daily tests + lakehouse build
├── dags/                    # Apache Airflow DAG (showcase, not run by CI)
├── data/                    # The Data Lake (Bronze JSONL, Silver/Gold Parquet, quarantine, logs)
├── doc/                     # Deep-dive technical documentation
├── infrastructure/          # Terraform (AWS showcase, not deployed)
├── scripts/                 # Background worker (github_scrape.py)
├── sql/                     # Athena/Glue DDL + queries for the AWS showcase path
├── src/
│   ├── app.py               # Flask Web Application (routes, SSE scrape, API)
│   ├── categories.py        # Single category keyword map + classifier
│   ├── database.py          # SQLite / PostgreSQL connection manager + queries
│   ├── pipeline/            # Core ETL logic (ingest, validate, transform, enrich, run)
│   ├── processing/          # DuckDB Gold marts
│   ├── static/ & templates/ # HTML, CSS, JS, service worker for the UI
│   ├── utils/               # Credibility scoring
│   └── web_scraper.py       # Core scraping logic
├── tests/                   # Pytest suite (15 tests)
├── requirements.txt         # Web server dependencies (flask>=3.1)
└── requirements-actions.txt # requirements.txt plus nltk, for the Action
```

---

## License
Distributed under the MIT License.
# Sniffer: The Zero-Cost Cloud-Native Data Lakehouse

![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![PySpark](https://img.shields.io/badge/Apache%20Spark-3.5-E25A1C?logo=apachespark&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-In--Memory%20OLAP-FFF000?logo=duckdb&logoColor=black)
![Pytest](https://img.shields.io/badge/tests-13%20passed%20(100%25)-brightgreen)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-orange)

## What is Sniffer?

The tech industry moves faster than anyone can read. Between Hacker News, Reddit, arXiv papers, and a dozen different tech blogs, finding the actual signal through the noise is practically a full-time job. 

Sniffer is a personal solution to information overload. 

It is an automated data engineering pipeline that scrapes multiple tech sources across the web, standardizes the unstructured data into a clean Data Lakehouse, runs analytical ranking algorithms, and serves the best stories of the day through a premium editorial web dashboard. Best of all, it achieves this entire pipeline on a strictly zero-cost cloud budget.

---

## How it Works: The Split-Layer Architecture

To process heavy Natural Language Processing tasks (like NLTK sentiment analysis and Sumy summarization) without crashing free-tier web hosts, I designed a split-layer architecture. 

This guarantees absolute stability for the web application while pushing all the memory-intensive compute to GitHub Actions. Here is how the data flows from the messy internet down to the clean dashboard:

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
    Ingest[GitHub Actions Background Worker<br/>Heavy NLP & Extraction]:::source
    
    RSS & REST & XML --> Ingest
    
    %% Bronze
    Ingest -->|Raw JSONL| Bronze[(Bronze Layer<br/>Raw Data)]:::bronze
    
    %% Validation
    Validate{Data Quality Gate<br/>Schema Contracts}
    Bronze --> Validate
    Validate -->|Fails Contract| Quarantine([Quarantine / Dead Letter Queue]):::error
    
    %% Silver
    Validate -->|Passes| Silver[(Silver Layer<br/>Snappy Parquet)]:::silver
    
    %% Gold
    Spark[PySpark / DuckDB<br/>Aggregations & Ranking]:::source
    Silver --> Spark
    Spark --> Gold[(Gold Layer<br/>Analytical Marts)]:::gold
    
    %% Serving
    Gold --> DB[(Neon Postgres<br/>Serverless Database)]:::serve
    DB <--> App[Render Web Service<br/>Lightweight Flask Dashboard]:::serve
```

### 1. The Heavy Lifter: GitHub Actions (Background Worker)
Every hour, a scheduled GitHub Action spins up an Ubuntu runner, giving the pipeline access to roughly 7GB of RAM for free. It executes the background scraping routine which:
- Scrapes the latest articles from Hacker News and other tech sources.
- Uses Trafilatura to extract the full text of articles.
- Runs NLTK Vader to perform sentiment analysis and computes reading times.
- Connects to the database and upserts this rich metadata.

### 2. The Presentation Layer: Render (Web Dashboard)
The web application runs on Render and is completely decoupled from the scraping process. It acts as a highly optimized, read-only presentation layer. It connects to the database to serve the pre-computed NLP metadata. If a user requests a summary on the fly, it relies on a custom, lightweight TF-IDF word frequency algorithm to generate summaries without needing heavy dependencies.

---

## Key Engineering Features

1. **Heterogeneous Multi-Protocol Ingestion**: Not all APIs are created equal. Sniffer pulls data simultaneously from RSS, JSON REST APIs, and XML Atom feeds using async Python with built-in retry logic.
2. **Decoupled Architecture for Stability**: By separating the heavy NLP processing into GitHub Actions and keeping the web app lightweight, the system avoids memory crashes entirely on free-tier platforms.
3. **Resilient Database Connections**: Incorporates exponential backoff retry logic to handle serverless database "cold starts" gracefully.
4. **Columnar Storage**: Data is saved as Hive-partitioned Snappy Parquet files. This compresses data heavily and allows embedded engines like DuckDB to query gigabytes of data in milliseconds.
5. **Premium Editorial UI**: The front-end is not just a generic template. It features a bespoke, high-contrast dark mode with tactile micro-animations and a slide-out drawer for "Quick Reads" to create a premium reading experience.

---

## The Zero-Cost Infrastructure Setup

Building a Data Lakehouse usually means spending hundreds of dollars on AWS or GCP. I wanted to prove that modern data engineering can be done efficiently on the free tier.

| Component | Technology | Cost |
| :--- | :--- | :--- |
| **Compute / Pipeline** | GitHub Actions (Unlimited public runner minutes) | $0 |
| **Transactional Database**| Neon Serverless PostgreSQL | $0 |
| **Analytics Engine**| DuckDB (Embedded C++ engine, no servers needed) | $0 |
| **Web Hosting** | Render (Free Web Service tier) | $0 |

> **Note on Enterprise IaC**: You will notice an `infrastructure/main.tf` and `sql/athena.sql` file in this repository. While this project runs on a free stack, I have included the Terraform code necessary to deploy this pipeline onto a highly-scalable AWS environment (S3, Glue, Athena) to demonstrate enterprise readiness.

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
# Install the heavy NLP dependencies (if you want to run the scraper locally)
pip install -r requirements-actions.txt
```

### 2. Run the Background Scraper
```bash
# Export your database URL (Neon Postgres or local SQLite/Postgres)
export DATABASE_URL="postgresql://user:pass@host/dbname"

# Run the heavy scraper
python scripts/github_scrape.py
```

### 3. Start the Web Dashboard
```bash
# From the root directory (make sure your DATABASE_URL is set)
python src/app.py
# Open http://localhost:7860 to see the UI.
```

---

## Project Structure

```text
Web-scraper/
├── .github/workflows/       # CI/CD and daily automated scraping
├── dags/                    # Apache Airflow orchestration DAGs
├── data/                    # The Data Lake (Bronze JSONL, Silver/Gold Parquet)
├── doc/                     # Deep-dive technical documentation
├── infrastructure/          # Terraform (AWS Enterprise architecture stubs)
├── pipeline/                # Core ETL logic (ingest, validate, transform)
├── processing/              # PySpark analytical jobs
├── scripts/                 # Heavy background workers (github_scrape.py)
├── src/                     
│   ├── app.py               # Lightweight Flask Web Application
│   ├── database.py          # Resilient PostgreSQL connection manager
│   ├── pipeline/            # Enrichment and processing logic
│   └── web_scraper.py       # Core scraping logic
├── static/ & templates/     # HTML, CSS, and JS for the Premium Editorial UI
├── tests/                   # Pytest suite (100% passing)
├── requirements.txt         # Lightweight dependencies for the web server
└── requirements-actions.txt # Heavy NLP dependencies for the GitHub Action
```

---

## License
Distributed under the MIT License.
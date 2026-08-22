# Sniffer: The Zero-Cost Cloud-Native Data Lakehouse 🐕‍🦺

![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![PySpark](https://img.shields.io/badge/Apache%20Spark-3.5-E25A1C?logo=apachespark&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-In--Memory%20OLAP-FFF000?logo=duckdb&logoColor=black)
![Pytest](https://img.shields.io/badge/tests-13%20passed%20(100%25)-brightgreen)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-orange)

## What is Sniffer?

The tech industry moves faster than anyone can read. Between Hacker News, Reddit, arXiv papers, and a dozen different tech blogs, finding the actual *signal* through the noise is a full-time job. 

**Sniffer is my solution to information overload.** 

It's an automated Data Engineering pipeline that scrapes 7 different tech sources across the web, standardizes the messy data into a clean Data Lakehouse, runs analytical ranking algorithms, and serves the best stories of the day through a **Premium Editorial Web Dashboard**—and it does all of this on a **₹0 / $0 cloud budget**.

---

## 🏗️ How it Works (The Architecture)

I built this project to demonstrate a production-grade **Medallion Lakehouse Architecture**. Here is how data flows from the messy internet to the clean dashboard:

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

    %% Ingestion
    Ingest[Async Ingestion Engine<br/>Exponential Backoff + Checksums]:::source
    
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
    Gold --> App[Flask Dashboard<br/>Render Web Service]:::serve
    App <--> DB[(Neon Postgres<br/>User Data & Search)]:::serve
```

---

## 🌟 Key Engineering Features

1. **Heterogeneous Multi-Protocol Ingestion**: Not all APIs are created equal. Sniffer pulls data simultaneously from RSS, JSON REST APIs, and XML Atom feeds using async Python (`Semaphore(8)`) with built-in retry logic.
2. **Idempotency & Checksumming**: To ensure we never ingest the same article twice (even if the pipeline fails and restarts), every record gets a deterministic SHA-256 fingerprint.
3. **Declarative Data Quality Gate**: Bad data happens. Instead of crashing the pipeline, invalid records are routed to a `quarantine/` folder, while passing records move forward.
4. **Columnar Storage**: Data is saved as Hive-partitioned Snappy Parquet files (`day=YYYY-MM-DD/source=.../`). This compresses data heavily and allows engines like DuckDB to query gigabytes of data in milliseconds.
5. **Dual-Engine Processing**:
   - **PySpark**: Used for heavy distributed transformations and ranking (`DENSE_RANK`).
   - **DuckDB**: Embedded directly in the app to run lightning-fast SQL analytics on the Parquet files.
6. **Premium Editorial UI**: The front-end isn't just a generic template. It features a bespoke, high-contrast dark mode with tactile micro-animations and a slide-out drawer for "Quick Reads" to create a premium reading experience.

---

## 🆓 The ₹0 Infrastructure Setup

Building a Data Lakehouse usually means spending hundreds of dollars on AWS or GCP. I wanted to prove that modern data engineering can be done efficiently on the free tier.

| Component | Technology | Cost |
| :--- | :--- | :--- |
| **Compute / Pipeline** | GitHub Actions (Unlimited public runner minutes) | $0 |
| **Transactional Database**| Neon Serverless PostgreSQL | $0 |
| **Analytics Engine**| DuckDB (Embedded C++ engine, no servers needed) | $0 |
| **Web Hosting** | Render (Free Web Service tier) | $0 |

> **Note on Enterprise IaC**: You will notice an `infrastructure/main.tf` and `sql/athena.sql` file in this repo. While this project runs on a $0 stack, I've included the Terraform code necessary to deploy this pipeline onto a highly-scalable AWS environment (S3, Glue, Athena) to demonstrate enterprise readiness.

---

## 🚀 Quick Start (Run it Locally)

Want to run the pipeline yourself? It's incredibly easy to spin up locally.

### 1. Clone & Install
```bash
git clone https://github.com/DhanushPillay/Web-scraper.git
cd Web-scraper
python -m venv .venv
# Windows:
.\.venv\Scripts\Activate.ps1
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Run the Data Pipeline (Bronze ➔ Silver ➔ Gold)
```bash
# This will scrape the web, validate data, and build the Parquet files
python pipeline/run.py
```

### 3. Start the Web Dashboard
```bash
python app.py
# Open http://localhost:7860 to see the UI!
```

---

## 📂 Project Structure

```text
Web-scraper/
├── .github/workflows/       # CI/CD and daily automated scraping
├── dags/                    # Apache Airflow orchestration DAGs
├── data/                    # The Data Lake (Bronze JSONL, Silver/Gold Parquet)
├── doc/                     # Deep-dive technical documentation
├── infrastructure/          # Terraform (AWS Enterprise architecture stubs)
├── pipeline/                # Core ETL logic (ingest, validate, transform)
├── processing/              # PySpark analytical jobs
├── templates/ & static/     # HTML and CSS for the Premium Editorial UI
├── tests/                   # Pytest suite (100% passing)
├── app.py                   # Flask Application
└── database.py              # PostgreSQL / SQLite resilient connection manager
```

---

## 📜 License
Distributed under the MIT License.
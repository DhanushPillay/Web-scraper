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

It's an automated Data Engineering pipeline that scrapes multiple tech sources across the web, enriches the data using NLP (Sentiment Analysis & Summarization), and serves the best stories of the day through a **Premium Editorial Web Dashboard**—and it does all of this on a **₹0 / $0 cloud budget**.

---

## 🏗️ How it Works (The Architecture)

To run heavy NLP processing (like NLTK and Sumy) without crashing free-tier web hosts (which usually cap out at 512MB RAM), I built a **Split-Layer Architecture**.

### 1. The Heavy Lifter: GitHub Actions (Background Worker)
Every hour, a GitHub Action spins up (giving us access to ~7GB of RAM for free). It executes `scripts/github_scrape.py` which:
- Scrapes the latest articles from Hacker News and other tech sources.
- Uses **Trafilatura** to extract the full text of articles.
- Runs **NLTK Vader** to perform sentiment analysis.
- Connects to the database and upserts all this rich metadata.

### 2. The Presentation Layer: Render (Web Dashboard)
The web application (`src/app.py`) runs on Render. 
- It is completely decoupled from the scraping process.
- It acts as a highly optimized, read-only presentation layer. 
- It connects to the database to serve the pre-computed NLP metadata.
- If a user requests a summary on the fly, it uses a custom, lightweight TF-IDF word frequency algorithm to generate summaries without needing heavy libraries.

---

## 🌟 Key Engineering Features

1. **Decoupled Architecture for Stability**: By separating the heavy NLP processing into GitHub Actions and keeping the web app lightweight, the system avoids Out-Of-Memory (OOM) crashes entirely on free-tier platforms.
2. **Deep Text Extraction**: Extracts the actual article content rather than just relying on RSS excerpts using `sumy` and `trafilatura`.
3. **Resilient Database Connections**: Incorporates exponential backoff retry logic to handle serverless database "cold starts" gracefully.
4. **NLP Enrichment**: Analyzes sentiment (positive/neutral/negative) and calculates read times automatically.
5. **Premium Editorial UI**: The front-end isn't just a generic template. It features a bespoke, high-contrast dark mode with tactile micro-animations and a slide-out drawer for "Quick Reads" to create a premium reading experience.

---

## 🆓 The ₹0 Infrastructure Setup

Building a Data Pipeline with NLP usually means spending money on AWS or GCP. I wanted to prove that modern data engineering can be done efficiently on the free tier.

| Component | Technology | Cost |
| :--- | :--- | :--- |
| **Compute / Pipeline** | GitHub Actions (Unlimited public runner minutes) | $0 |
| **Transactional Database**| Neon Serverless PostgreSQL | $0 |
| **Web Hosting** | Render (Free Web Service tier) | $0 |

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
# Open http://localhost:7860 to see the UI!
```

---

## 📂 Project Structure

```text
Web-scraper/
├── .github/workflows/       # CI/CD and daily automated scraping
├── scripts/                 # Heavy background workers (github_scrape.py)
├── src/                     
│   ├── app.py               # Lightweight Flask Web Application
│   ├── database.py          # Resilient PostgreSQL connection manager
│   ├── pipeline/            # Enrichment and processing logic
│   └── web_scraper.py       # Core scraping logic
├── static/ & templates/     # HTML, CSS, and JS for the Premium Editorial UI
├── requirements.txt         # Lightweight dependencies for the web server
└── requirements-actions.txt # Heavy NLP dependencies for the GitHub Action
```

---

## 📜 License
Distributed under the MIT License.
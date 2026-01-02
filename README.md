
# Hacker News Web Scraper & Summarizer

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Flask Version](https://img.shields.io/badge/flask-2.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

This project is a full-featured Python application for scraping, filtering, viewing, and summarizing technology news from [Hacker News](https://news.ycombinator.com/). It offers both a modern web dashboard and a robust command-line interface (CLI).

## Features

- **Multi-Page Scraping**: Efficiently collects stories from multiple pages.
- **Rich Article Data**: Extracts headlines, scores, authors, timestamps, and comment counts.
- **Smart Filtering & Sorting**: Filter by keyword; sort by score, comment count, or recency.
- **Performance Caching**: 10-minute cache to minimize redundant requests and respect server load.
- **Modern Web UI**:
    - Responsive Bootstrap 5 design.
    - Dark Mode support.
    - AI-powered article summarization (popup modal).
    - CSV Export.
- **CLI Mode**: Quick terminal-based scraping and data export.

## Prerequisites

- Python 3.8 or higher
- Internet connection (for scraping and NLTK data download)

## Installation

1. **Clone the repository**
    ```bash
    git clone https://github.com/DhanushPillay/Web-scraper.git
    cd Web-scraper
    ```

2. **Install Python dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **(Optional) Manual NLTK Setup**
    The app attempts to download necessary NLTK data automatically. If you encounter issues, run:
    ```python
    import nltk
    nltk.download('punkt')
    ```

## Usage

### 1. Web Interface (Recommended)

1. Start the server:
   ```bash
   python app.py
   ```
2. Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your browser.
3. Use the dashboard to scrape, filter, summarize, and export news.

### 2. Command Line Interface (CLI)

1. Run the script:
   ```bash
   python web_scraper.py
   ```
2. Follow the interactive prompts to scrape and manage data.

## Project Structure

- **`web_scraper.py`**: The core logic. Handles HTML parsing (BeautifulSoup), HTTP requests, and data processing.
- **`app.py`**: Flask application. Manages routes, API endpoints, caching, and the summarization feature.
- **`templates/index.html`**: The frontend. A responsive HTML5/Bootstrap template.
- **`tech_news.csv`**: generated output file for exported data.

## Troubleshooting

- **`LookupError` (NLTK)**: If you see an error about missing NLTK resources, run `python -c "import nltk; nltk.download('punkt')"` in your terminal.
- **Timeout/Connection Errors**: Hacker News may rate-limit aggressive scraping. The scraper includes a 1-second delay between pages to mitigate this.

## Future Improvements

- Add database support (SQLite/PostgreSQL) for long-term data storage.
- Implement user accounts to save favorite articles.
- Add "Sentiment Analysis" to the summary feature.


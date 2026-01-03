# Tech News Aggregator & Scraper

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Flask Version](https://img.shields.io/badge/flask-2.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

A full-featured Python application for aggregating, filtering, and viewing technology news from **5 major sources**: Hacker News, TechCrunch, Reddit, The Verge, and Ars Technica. Features a modern web dashboard with bookmarking, dark mode, and AI-powered article summarization.

## Features

### Multi-Source Aggregation
- **Hacker News**: Top stories with scores and comments
- **TechCrunch**: Latest tech industry news
- **Reddit** (r/technology): Community-driven discussions
- **The Verge**: Tech culture and reviews
- **Ars Technica**: In-depth technical analysis

### Core Functionality
- **SQLite Database**: Persistent storage for all articles
- **Bookmarking**: Save articles for later reading
- **Smart Filtering**: Filter by source, keyword, or view saved articles only
- **Sorting Options**: Sort by score, comments, or recency
- **Email Digest**: Subscribe to daily news updates (skeleton implementation)

### Modern Web Interface
- Responsive Bootstrap 5 design
- **Dark Mode** support with persistent preferences
- AI-powered article summarization (popup modal)
- CSV Export for data analysis
- Source-specific badges (color-coded)

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

### Web Interface (Recommended)

1. Start the server:
   ```bash
   python app.py
   ```
2. Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your browser.
3. Click **Refresh** to scrape articles from all sources.
4. Use filters, bookmarks, and the summarize feature.

### Command Line Interface (CLI)

Run the legacy scraper:
```bash
python web_scraper.py
```

## Project Structure

- **`web_scraper.py`**: Core scraping logic with `BaseScraper` pattern for each source
- **`database.py`**: SQLite database management (articles, bookmarks)
- **`app.py`**: Flask application with routes, API endpoints, and summarization
- **`templates/index.html`**: Responsive web UI with dark mode and bookmark functionality
- **`tech_news.db`**: SQLite database (auto-generated)

## Database Schema

```sql
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    link TEXT UNIQUE NOT NULL,
    score INTEGER DEFAULT 0,
    author TEXT,
    time_posted TEXT,
    comments TEXT,
    source TEXT,
    created_at REAL,
    is_saved INTEGER DEFAULT 0
);
```

## Troubleshooting

- **`LookupError` (NLTK)**: Run `python -c "import nltk; nltk.download('punkt')"` 
- **Timeout/Connection Errors**: Scrapers include delays to respect rate limits
- **Empty Results**: Some sources may temporarily block requests; try again later

## License

MIT License - feel free to use and modify.

## Contributing

Pull requests are welcome! For major changes, please open an issue first.

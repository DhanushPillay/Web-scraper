# Tech News Aggregator & Scraper

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Flask Version](https://img.shields.io/badge/flask-2.0%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

A modern, professional web application for aggregating and viewing technology news from **5 major sources**. Features a clean SaaS-style dashboard with real-time statistics, bookmarking, and AI-powered article summarization.

## Features

### 🌐 Multi-Source Aggregation
- **Hacker News**: Top stories with scores and comments
- **TechCrunch**: Latest tech industry news
- **Reddit** (r/technology): Community-driven discussions
- **The Verge**: Tech culture and product reviews
- **Ars Technica**: In-depth technical analysis
- **High-Performance Concurrency**: Scraping engine uses `concurrent.futures.ThreadPoolExecutor` to fetch from all sources simultaneously.
- **Resilient Network Connections**: Implements `urllib3.util.retry.Retry` with exponential backoff to recover from transient HTTP failures.

### 📊 Dashboard & Analytics
- **Real-time Statistics**: Total articles, new today, saved count, top source
- **Auto-refresh**: Stats update on every page load
- **Clean SaaS Design**: Modern minimal interface with professional typography

### 💾 Data Management
- **SQLite Database**: Persistent storage for all articles
- **FTS5 Full-Text Search**: O(1) text search implemented using SQLite's FTS5 extension.
- **Personalized Feed Algorithm**: Custom SQL scoring and ranking logic based on individual user bookmarking behavior.
- **Automatic Deduplication**: Prevents duplicate articles
- **Bookmark System**: Save articles for later reading
- **Advanced Filtering**: Filter by source, keyword, or view saved articles only
- **Sorting Options**: Sort by score, comments, or recency

### 🎨 Modern Interface & AI NLP Data Enrichment
- **Clean Design**: Professional SaaS-style dashboard
- **Monochrome Theme**: Professional black/gray/white interface (no distractions)
- **Responsive Layout**: Works on desktop and mobile
- **AI Summarization**: Extractive summarization via `newspaper3k`
- **CSV Export**: Streamed download of high-volume datasets via Flask's `stream_with_context`
- **Sentiment Analysis**: NLTK VADER sentiment compound scoring (Positive/Negative/Neutral)
- **Trending Topics**: TF-IDF alternatives extracting contextually relevant bigrams

### 📧 Email Digest (Beta)
- Subscribe to daily news updates (skeleton implementation)
- Ready for SMTP integration

## Prerequisites

- Python 3.8 or higher
- Internet connection

## Installation

1. **Clone the repository**
    ```bash
    git clone https://github.com/DhanushPillay/Web-scraper.git
    cd Web-scraper
    ```

2. **Install dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3. **(Optional) NLTK Setup**
    The app downloads NLTK data automatically. If issues occur:
    ```python
    import nltk
    nltk.download('punkt')
    ```

## Usage

### Start the Application

```bash
python app.py
```

Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your browser.

### Using the Dashboard

1. **View Statistics**: See total articles, new today, saved articles, and top source
2. **Scrape Articles**: Click **"Scrape Now"** in the top navbar to fetch latest news
3. **Filter Content**: Use source dropdown or keyword search
4. **Save Articles**: Click the star icon to bookmark articles
5. **View Summaries**: Click "Summarize" on any article
6. **Export Data**: Download results as CSV

## Project Structure

```
Web-scraper/
├── app.py              # Flask application with background metadata/scheduling loops
├── web_scraper.py      # Scraping logic (BaseScraper pattern with caching)
├── database.py         # SQLite database management with idempotent migrations
├── templates/
│   └── index.html      # Modern SaaS dashboard UI
├── technews.db         # SQLite database (auto-generated)
├── requirements.txt    # Python dependencies
└── doc/
    └── project_explanation.md # Deep Technical Architecture documentation
```

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

## API Endpoints

- `GET /` - Main dashboard
- `GET /saved` - View bookmarked articles
- `POST /bookmark/<id>` - Toggle bookmark status
- `GET /api/stats` - Get dashboard statistics (JSON)
- `POST /summarize` - Get AI summary of an article
- `POST /subscribe` - Subscribe to email digest

## Technologies Used

- **Backend**: Flask, SQLite3
- **Scraping**: BeautifulSoup4, Requests
- **AI/NLP**: Newspaper3k, NLTK
- **Frontend**: Bootstrap 5, Inter Font, Vanilla JavaScript
- **Data**: SQLite3, CSV (built-in)

## Troubleshooting

- **NLTK Errors**: Run `python -c "import nltk; nltk.download('punkt')"`
- **Rate Limiting**: Scrapers include delays to respect server limits
- **Empty Results**: Some sources may block requests temporarily

## Future Enhancements

- Complete email digest with SMTP integration
- User authentication and profiles
- More sources (Dev.to, Product Hunt, Slashdot)
- Complete email digest with SMTP integration
- User authentication and profiles
- More sources (Dev.to, Product Hunt, Slashdot)

## License

MIT License - Use and modify freely.

## Contributing

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

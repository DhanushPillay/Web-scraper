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

### 📊 Dashboard & Analytics
- **Real-time Statistics**: Total articles, new today, saved count, top source
- **Auto-refresh**: Stats update on every page load
- **Clean SaaS Design**: Modern minimal interface with professional typography

### 💾 Data Management
- **SQLite Database**: Persistent storage for all articles
- **Automatic Deduplication**: Prevents duplicate articles
- **Bookmark System**: Save articles for later reading
- **Advanced Filtering**: Filter by source, keyword, or view saved articles only
- **Sorting Options**: Sort by score, comments, or recency

### 🎨 Modern Interface
- **Clean Design**: Professional SaaS-style dashboard
- **Dark Mode**: Full theme support with persistent preferences
- **Responsive Layout**: Works on desktop and mobile
- **AI Summarization**: Popup modal with article summaries
- **CSV Export**: Download filtered results for analysis
- **Sentiment Analysis**: AI-powered sentiment detection (Positive/Negative/Neutral)
- **Trending Topics**: Visual tracking of popular keywords

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
2. **Scrape Articles**: Click "Refresh" to fetch latest news from all sources
3. **Filter Content**: Use source dropdown or keyword search
4. **Save Articles**: Click the star icon to bookmark articles
5. **View Summaries**: Click "Summarize" on any article
6. **Export Data**: Download results as CSV

## Project Structure

```
Web-scraper/
├── app.py              # Flask application (routes, API endpoints)
├── web_scraper.py      # Scraping logic (BaseScraper pattern)
├── database.py         # SQLite database management
├── templates/
│   └── index.html      # Modern SaaS dashboard UI
├── technews.db         # SQLite database (auto-generated)
└── requirements.txt    # Python dependencies
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

Pull requests welcome! For major changes, open an issue first.

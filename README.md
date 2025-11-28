
# Hacker News Web Scraper & Summarizer

This project is a full-featured Python application for scraping, filtering, viewing, and summarizing technology news from [Hacker News](https://news.ycombinator.com/). It provides both a modern web dashboard and a command-line interface (CLI).


## Features

- **Multi-Page Scraping**: Collects news from multiple pages of Hacker News in one go.
- **Rich Article Data**: Extracts headline, score, author, time posted, comment count, and direct link for each article.
- **Smart Filtering & Sorting**: Instantly filter by keyword and sort by score, comments, or newest.
- **Performance Caching**: Results are cached for 10 minutes to avoid redundant scraping and speed up the user experience.
- **Modern Web UI**:
    - Responsive, mobile-friendly design using Bootstrap 5
    - Dark Mode toggle (remembers your preference)
    - Loading spinner overlay for long operations
    - Download CSV button for instant export
    - Summarize button for each article: get an AI-generated summary and top image in a modal popup
- **Article Summarization**: Uses NLP (via `newspaper3k` and `nltk`) to fetch and summarize the content of any news link directly from the web interface.
- **CLI Mode**: Use the terminal for quick scraping, filtering, and CSV export.


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
    This will install Flask, BeautifulSoup, requests, newspaper3k, nltk, and other required libraries.

3. **(First time only) Download NLTK data**
    The app will attempt to download required NLTK data automatically. If you see errors, run:
    ```python
    import nltk
    nltk.download('punkt')
    ```


## Usage

### 1. Web Interface (Recommended)

1. Start the Flask app:
   ```bash
   python app.py
   ```
2. Open your browser and go to: [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
3. Use the dashboard:
   - **Pages**: Choose how many pages to scrape (1-10)
   - **Keyword**: Filter articles by keyword (optional)
   - **Sort By**: Sort by score, comments, or newest
   - **Force Refresh**: Bypass cache and fetch fresh data
   - **Scrape**: Click to start scraping (shows a loading spinner)
   - **Download CSV**: Export the current filtered/sorted view
   - **Dark Mode**: Toggle for a comfortable viewing experience
   - **Summarize**: Click the "Summarize" button next to any article to get a summary and top image in a popup modal

### 2. Command Line Interface (CLI)

1. Run the script:
   ```bash
   python web_scraper.py
   ```
2. Follow the prompts:
   - Enter the number of pages to scrape
   - View the top trending articles
   - Enter a keyword to filter
   - Type `save` to export to `tech_news.csv`
   - Type `options` to configure which columns to display


## Project Structure

- `web_scraper.py`: Core scraping logic and CLI interface. Handles fetching, parsing, and filtering Hacker News articles.
- `app.py`: Flask web server. Handles all web routes, caching, CSV export, and article summarization.
- `templates/index.html`: Responsive Bootstrap-based HTML template for the dashboard, including modals and JavaScript for UI features.
- `requirements.txt`: Python dependencies for the project.
- `tech_news.csv`: Output file for exported news data (created after using the download/save feature).


## How Article Summarization Works

- When you click "Summarize" on any article, the app sends the article's URL to the Flask backend.
- The backend uses `newspaper3k` to download and parse the article, then uses NLP to generate a summary and extract the top image.
- The summary and image are displayed in a modal popup, so you can quickly get the gist of any news story without leaving the dashboard.

## Ethical Use

- Please scrape responsibly. The app waits between requests and caches results to avoid overloading Hacker News.
- For personal and educational use only.

## License

This project is open source and available for personal and educational use.

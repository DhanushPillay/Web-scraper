# Hacker News Web Scraper

A Python-based tool to scrape, filter, and view technology news from [Hacker News](https://news.ycombinator.com/). This project offers both a Command Line Interface (CLI) and a modern Web Interface.

## Features

- **Scrape Multiple Pages**: Fetch news from multiple pages of Hacker News at once.
- **Detailed Info**: Extracts Title, Score, Author, Time Posted, Comment Count, and Link.
- **Smart Filtering & Sorting**: Filter by keyword and sort by Score, Comments, or Newest.
- **Performance Caching**: Intelligent caching system to prevent redundant requests and speed up results.
- **Modern Web UI**: Features Dark Mode, Loading States, and a responsive design.
- **CSV Export**: Download data directly from the Web UI or save via CLI.
- **CLI Mode**: A robust terminal interface for quick scraping tasks.

## Installation

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone https://github.com/DhanushPillay/Web-scraper.git
    cd Web-scraper
    ```

2.  **Install Dependencies**:
    Make sure you have Python installed, then run:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

### 1. Web Interface (Recommended)
The web interface provides a nice visual way to interact with the scraper.

1.  Run the Flask app:
    ```bash
    python app.py
    ```
2.  Open your browser and go to: `http://127.0.0.1:5000/`
3.  Configure your scrape:
    -   **Pages**: Number of pages to fetch (1-10).
    -   **Keyword**: Optional filter (e.g., "AI").
    -   **Sort By**: Choose Highest Score, Most Comments, or Newest.
4.  Click "Scrape" to see the results.
    -   *Note: Subsequent requests are cached for 10 minutes for instant loading.*
    -   *Use "Force Refresh" to fetch fresh data immediately.*
5.  Click "Download CSV" to save the current view.
6.  Toggle "Dark Mode" in the top right corner for a better viewing experience.

### 2. Command Line Interface (CLI)
If you prefer working in the terminal:

1.  Run the script:
    ```bash
    python web_scraper.py
    ```
2.  Follow the on-screen prompts:
    -   Enter the number of pages to scrape.
    -   View the top trending articles.
    -   Enter a keyword to filter specific topics.
    -   Type `save` to export data to `tech_news.csv`.
    -   Type `options` to configure which columns to display.

## Project Structure

-   `web_scraper.py`: Core scraping logic and CLI implementation.
-   `app.py`: Flask application server for the web interface.
-   `templates/index.html`: HTML template for the web dashboard.
-   `requirements.txt`: List of Python dependencies.
-   `tech_news.csv`: Output file for scraped data (generated after running 'save').

## License

This project is open source and available for personal and educational use.

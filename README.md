# Hacker News Web Scraper

A Python-based tool to scrape, filter, and view technology news from [Hacker News](https://news.ycombinator.com/). This project offers both a Command Line Interface (CLI) and a modern Web Interface.

## Features

- **Scrape Multiple Pages**: Fetch news from multiple pages of Hacker News at once.
- **Detailed Info**: Extracts Title, Score, Author, Time Posted, Comment Count, and Link.
- **Smart Filtering**: Filter articles by keyword (e.g., "python", "AI").
- **CSV Export**: Save your scraped data to a CSV file for analysis.
- **Web Interface**: A user-friendly web dashboard to browse and filter news.
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
3.  Enter the number of pages to scrape and an optional keyword filter.
4.  Click "Scrape News" to see the results.

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

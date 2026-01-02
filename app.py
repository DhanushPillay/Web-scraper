from flask import Flask, render_template, request, Response, stream_with_context, jsonify
from web_scraper import NewsAggregator
from database import Database
import time
import io
import csv
from newspaper import Article
import nltk

# Ensure NLTK data is downloaded
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
    nltk.download('punkt_tab')

app = Flask(__name__)

# Initialize Database
db = Database()

@app.route('/download')
def download_csv() -> Response:
    """Generates and downloads a CSV file of the articles."""
    # Get current filter params
    keyword = request.args.get('keyword', '').strip().lower()
    sort_by = request.args.get('sort', 'score')
    
    # Fetch from DB (get all for download, let's limit to 500 for sanity)
    articles = db.get_articles(limit=500, keyword=keyword)
    
    # Sort in memory for download flexibility
    if sort_by == 'comments':
        articles = sorted(articles, key=lambda x: int(x['comments']) if str(x['comments']).isdigit() else 0, reverse=True)
    elif sort_by == 'newest':
        # DB already returns sorted by created_at (newest first discovery)
        pass 
    else: # score
        articles = sorted(articles, key=lambda x: x['score'] if isinstance(x['score'], int) else 0, reverse=True)

    # Generate CSV
    def generate():
        data = io.StringIO()
        w = csv.DictWriter(data, fieldnames=["title", "score", "link", "author", "time", "comments", "source"])
        w.writeheader()
        data.seek(0)
        yield data.read()
        data.truncate(0)
        data.seek(0)
        
        for article in articles:
            # Ensure safe access to all fields
            safe_article = {k: article.get(k, '') for k in ["title", "score", "link", "author", "time", "comments", "source"]}
            w.writerow(safe_article)
            data.seek(0)
            yield data.read()
            data.truncate(0)
            data.seek(0)

    return Response(stream_with_context(generate()), mimetype='text/csv', headers={"Content-Disposition": "attachment; filename=tech_news.csv"})

@app.route('/', methods=['GET', 'POST'])
def index() -> str:
    """Main route for the dashboard. Handles scraping, filtering, and sorting."""
    pages = 1
    keyword = ""
    sort_by = "score"
    source_filter = "all"
    
    if request.method == 'POST':
        try:
            pages = int(request.form.get('pages', 1))
            keyword = request.form.get('keyword', '').strip()
            sort_by = request.form.get('sort', 'score')
            source_filter = request.form.get('source', 'all')
            force_refresh = request.form.get('refresh') == 'true'
            
            # Scrape only if requested (Force Refresh) or if DB is empty (implicit first run logic)
            # For this UI, "Scrape" button implies "Get fresh data".
            # So we effectively always scrape on POST unless we want to be very strict.
            # But the user might just be filtering. 
            # Logic: If pages/keyword/source changes but 'Scrape' button was effectively clicked...
            # Actually, the form submit is the only way to filter right now.
            # Let's say: If 'refresh' is checked OR db is empty, we scrape. 
            # Otherwise we just query DB.
            
            should_scrape = force_refresh or (db.get_article_count() == 0)
            
            if should_scrape:
                print("Scraping fresh data and saving to DB...")
                aggregator = NewsAggregator()
                aggregator.scrape_all(hn_pages=pages)
                new_articles = aggregator.get_articles()
                db.add_articles(new_articles)
            else:
                 print("Querying existing data...")

        except Exception as e:
            print(f"Error: {e}")

    # Always fetch result to display
    # Default limit to 100 for display
    articles = db.get_articles(limit=100, source_filter=source_filter, keyword=keyword)
    
    # Sort in memory for display adjustments
    if sort_by == 'comments':
        articles = sorted(articles, key=lambda x: int(x['comments']) if str(x['comments']).isdigit() else 0, reverse=True)
    elif sort_by == 'score':
         articles = sorted(articles, key=lambda x: x['score'] if isinstance(x['score'], int) else 0, reverse=True)
    # default or 'newest' uses DB order (created_at DESC)

    return render_template('index.html', articles=articles, pages=pages, keyword=keyword, sort_by=sort_by, source=source_filter)

@app.route('/summarize', methods=['POST'])
def summarize() -> Response:
    """API endpoint to summarize a given URL."""
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
        
    try:
        article = Article(url)
        article.download()
        article.parse()
        article.nlp()
        
        return jsonify({
            'title': article.title,
            'summary': article.summary,
            'top_image': article.top_image
        })
    except Exception as e:
        return jsonify({'error': f"Failed to summarize: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
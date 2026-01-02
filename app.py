from flask import Flask, render_template, request, Response, stream_with_context, jsonify
from web_scraper import NewsAggregator
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

# Simple in-memory cache
# Use type hinting for better clarity
CACHE: dict = {
    "articles": [],
    "last_updated": 0,
    "pages_scraped": 0
}
CACHE_DURATION: int = 600  # 10 minutes

@app.route('/download')
def download_csv() -> Response:
    """Generates and downloads a CSV file of the articles."""
    # Get current filter params
    keyword = request.args.get('keyword', '').strip().lower()
    sort_by = request.args.get('sort', 'score')
    
    # Use cached data if available, otherwise empty (or could trigger scrape, but let's rely on cache)
    articles = CACHE['articles']
    
    # Filter
    if keyword:
        articles = [art for art in articles if keyword in art['title'].lower()]
    
    # Sort
    if sort_by == 'comments':
        articles = sorted(articles, key=lambda x: int(x['comments']) if str(x['comments']).isdigit() else 0, reverse=True)
    elif sort_by == 'newest':
        # Simple heuristic for 'newest' based on 'time' string is hard without parsing, 
        # but we can assume the scraper order (page 1 top) is roughly newest.
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
    articles = []
    pages = 1
    keyword = ""
    sort_by = "score"
    source_filter = "all"
    
    global CACHE

    if request.method == 'POST':
        try:
            pages = int(request.form.get('pages', 1))
            keyword = request.form.get('keyword', '').strip()
            sort_by = request.form.get('sort', 'score')
            source_filter = request.form.get('source', 'all')
            force_refresh = request.form.get('refresh') == 'true'
            
            current_time = time.time()
            
            # Check Cache
            if (not force_refresh and 
                (current_time - CACHE['last_updated'] < CACHE_DURATION) and 
                CACHE['pages_scraped'] >= pages and
                CACHE['articles']):
                
                print("Using cached data...")
                articles = CACHE['articles']
            else:
                print("Scraping fresh data...")
                aggregator = NewsAggregator()
                
                # Scrape data (HN pages + 1 page for others)
                aggregator.scrape_all(hn_pages=pages)
                
                # Update Cache
                CACHE['articles'] = aggregator.get_articles()
                CACHE['pages_scraped'] = pages
                CACHE['last_updated'] = current_time
                
                articles = CACHE['articles']
            
            # Filter by keyword
            if keyword:
                articles = [art for art in articles if keyword.lower() in art['title'].lower()]
            
            # Filter by Source
            if source_filter and source_filter != 'all':
                # Fuzzy match or exact match depending on scraper naming
                # Our sources: 'Hacker News', 'TechCrunch', 'Reddit'
                articles = [art for art in articles if source_filter in art.get('source', '')]

            # Sort
            if sort_by == 'comments':
                articles = sorted(articles, key=lambda x: int(x['comments']) if str(x['comments']).isdigit() else 0, reverse=True)
            elif sort_by == 'newest':
                pass
            else: # score
                articles = sorted(articles, key=lambda x: x['score'] if isinstance(x['score'], int) else 0, reverse=True)
            
        except Exception as e:
            print(f"Error: {e}")

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
"""
Flask Application — Tech News Aggregator
Routes, background scheduler, sentiment analysis, trending topics,
auto-tagging, charts, export, personalized feed, and webhook/email stubs.
"""
import os
import re
import time
import io
import csv
import json
import logging
import smtplib
from email.mime.text import MIMEText
from collections import Counter
from urllib.parse import urlparse

from flask import (Flask, render_template, request, Response,
                   stream_with_context, jsonify, send_file)
from web_scraper import NewsAggregator
from database import Database
from utils.cluster_utils import NewsClusterer
from newspaper import Article
import nltk

# Attempt to import optional dependencies
try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    _vader_available = True
except (ImportError, LookupError):
    _vader_available = False

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler_available = True
except ImportError:
    _scheduler_available = False

logger = logging.getLogger(__name__)

# Ensure NLTK data is downloaded
for resource in ['tokenizers/punkt', 'tokenizers/punkt_tab',
                 'sentiment/vader_lexicon.zip', 'corpora/stopwords']:
    try:
        nltk.data.find(resource)
    except LookupError:
        nltk.download(resource.split('/')[-1].replace('.zip', ''), quiet=True)

app = Flask(__name__)

# Initialize Database & Aggregator (shared instance for caching)
db = Database()
aggregator = NewsAggregator()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def sort_articles(articles: list[dict], sort_by: str) -> list[dict]:
    """Sort articles by the given criteria. Extracted to avoid duplication."""
    if sort_by == 'comments':
        return sorted(articles, key=lambda x: int(x['comments']) if str(x['comments']).isdigit() else 0, reverse=True)
    elif sort_by == 'score':
        return sorted(articles, key=lambda x: x['score'] if isinstance(x['score'], int) else 0, reverse=True)
    return articles


EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email))


BLOCKED_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '169.254.169.254'}


def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return False
    if parsed.hostname in BLOCKED_HOSTS:
        return False
    return True


# ──────────────────────────────────────────────
# Auto-Tagging (Keyword-based category classification)
# ──────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    'AI & ML': ['ai', 'artificial intelligence', 'machine learning', 'deep learning', 'gpt',
                'chatgpt', 'llm', 'neural', 'openai', 'gemini', 'claude', 'copilot',
                'transformer', 'diffusion', 'generative'],
    'Security': ['security', 'hack', 'breach', 'vulnerability', 'malware', 'ransomware',
                 'phishing', 'cyber', 'exploit', 'privacy', 'encryption', 'zero-day'],
    'Hardware': ['chip', 'processor', 'gpu', 'cpu', 'nvidia', 'amd', 'intel', 'apple silicon',
                 'semiconductor', 'quantum', 'hardware', 'laptop', 'phone', 'device'],
    'Software': ['software', 'app', 'update', 'release', 'version', 'framework', 'library',
                 'programming', 'developer', 'code', 'open source', 'github', 'linux', 'windows'],
    'Business': ['startup', 'funding', 'acquisition', 'ipo', 'revenue', 'layoff', 'market',
                 'company', 'ceo', 'billion', 'million', 'valuation', 'investor'],
    'Science': ['science', 'research', 'study', 'discovery', 'space', 'nasa', 'climate',
                'physics', 'biology', 'medicine', 'vaccine', 'health'],
    'Gaming': ['game', 'gaming', 'xbox', 'playstation', 'nintendo', 'steam', 'esports',
               'console', 'vr', 'ar', 'metaverse'],
    'Social Media': ['twitter', 'facebook', 'instagram', 'tiktok', 'youtube', 'reddit',
                     'social media', 'meta', 'bluesky', 'mastodon', 'threads'],
}


def classify_article(title: str) -> str:
    """Classifies an article into a category based on keyword matching."""
    title_lower = title.lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in title_lower)
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)
    return 'General'


def estimate_read_time(title: str) -> int:
    """Estimates read time in minutes based on typical article length.
    Uses word count as a rough proxy — typical tech article = 3-8 min."""
    word_count = len(title.split())
    # Rough heuristic: longer titles usually mean more in-depth articles
    if word_count > 15:
        return 7
    elif word_count > 10:
        return 5
    return 3


# ──────────────────────────────────────────────
# Sentiment Analysis
# ──────────────────────────────────────────────

def analyze_sentiment(title: str) -> dict:
    """Uses VADER to analyze sentiment of a title."""
    if not _vader_available:
        return {'label': 'neutral', 'score': 0.0}

    try:
        sia = SentimentIntensityAnalyzer()
        scores = sia.polarity_scores(title)
        compound = scores['compound']

        if compound >= 0.05:
            label = 'positive'
        elif compound <= -0.05:
            label = 'negative'
        else:
            label = 'neutral'

        return {'label': label, 'score': compound}
    except Exception:
        return {'label': 'neutral', 'score': 0.0}


# ──────────────────────────────────────────────
# Trending Topics (TF-IDF-like word frequency)
# ──────────────────────────────────────────────

STOP_WORDS = set()
try:
    from nltk.corpus import stopwords
    STOP_WORDS = set(stopwords.words('english'))
except LookupError:
    pass

# Additional stop words for tech news
STOP_WORDS.update({
    'new', 'says', 'first', 'get', 'one', 'two', 'could', 'would', 'also',
    'may', 'use', 'using', 'make', 'like', 'much', 'us', 'now', 'just',
    'want', 'still', 'year', 'years', 'going', 'big', 'best', 'way',
    '—', '–', '-', "'s", "n't", 'the', 'a', 'an', 'is', 'are', 'was',
    'will', 'can', 'has', 'its', 'it', 'how', 'why', 'what'
})


def extract_trending_topics(titles: list[str], limit: int = 10) -> list[dict]:
    """Extracts trending topics from article titles using word frequency."""
    word_counts: Counter = Counter()

    for title in titles:
        words = re.findall(r'[a-zA-Z]{3,}', title.lower())
        meaningful = [w for w in words if w not in STOP_WORDS and len(w) > 2]
        word_counts.update(meaningful)

    # Also extract 2-word phrases (bigrams) for better topics
    for title in titles:
        words = re.findall(r'[a-zA-Z]{3,}', title.lower())
        meaningful = [w for w in words if w not in STOP_WORDS]
        for i in range(len(meaningful) - 1):
            bigram = f"{meaningful[i]} {meaningful[i + 1]}"
            word_counts[bigram] += 1

    topics = []
    for word, count in word_counts.most_common(limit):
        if count >= 2:  # Only show if appears 2+ times
            topics.append({'topic': word, 'count': count})

    return topics


# ──────────────────────────────────────────────
# Background Processing
# ──────────────────────────────────────────────

def process_articles_metadata():
    """Background job: assigns sentiment, category, and read time to unprocessed articles."""
    unprocessed = db.get_unprocessed_articles(limit=100)
    for article in unprocessed:
        title = article.get('title', '')
        sentiment = analyze_sentiment(title)
        category = classify_article(title)
        read_time = estimate_read_time(title)

        db.update_article_metadata(
            article_id=article['id'],
            sentiment=sentiment['label'],
            sentiment_score=sentiment['score'],
            category=category,
            read_time=read_time
        )
    if unprocessed:
        logger.info(f"Processed metadata for {len(unprocessed)} articles")


def background_scrape():
    """Background job: scrapes all sources and saves to DB."""
    logger.info("[Scheduler] Running background scrape...")
    try:
        aggregator.scrape_all(hn_pages=1, force=True)
        new_articles = aggregator.get_articles()
        if new_articles:
            db.add_articles(new_articles)
            logger.info(f"[Scheduler] Added {len(new_articles)} articles")
            # Process metadata for new articles
            process_articles_metadata()
    except Exception as e:
        logger.error(f"[Scheduler] Scrape failed: {e}")


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route('/download')
def download_csv() -> Response:
    """Generates and downloads a CSV file of the articles."""
    sort_by = request.args.get('sort', 'score')
    keyword = request.args.get('keyword', '')

    articles = db.get_articles(limit=500, keyword=keyword)
    articles = sort_articles(articles, sort_by)

    def generate():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            'title', 'score', 'link', 'author', 'time', 'comments', 'source', 'category', 'sentiment'
        ], extrasaction='ignore')
        writer.writeheader()
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for article in articles:
            writer.writerow(article)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return Response(stream_with_context(generate()),
                    mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=tech_news.csv'})


@app.route('/saved')
def saved_articles():
    """Shows only bookmarked articles."""
    page = request.args.get('page', 1, type=int)
    per_page = 30
    offset = (page - 1) * per_page

    articles = db.get_articles(limit=per_page, offset=offset, saved_only=True)
    total = db.get_total_count(saved_only=True)
    total_pages = max(1, (total + per_page - 1) // per_page)

    stats = db.get_stats()

    return render_template('index.html',
                           articles=[],
                           clustered_articles=[articles],
                           stats=stats,
                           total_count=total,
                           page=page,
                           total_pages=total_pages,
                           showing_saved=True)


@app.route('/', methods=['GET', 'POST'])
def index():
    """Main dashboard route with scraping, filtering, and pagination."""
    keyword = request.form.get('keyword', request.args.get('keyword', ''))
    pages = request.form.get('pages', request.args.get('pages', 1, type=int), type=int)
    sort_by = request.form.get('sort', request.args.get('sort', 'score'))
    source_filter = request.form.get('source', request.args.get('source', 'all'))
    category_filter = request.args.get('category', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 30
    offset = (page - 1) * per_page

    try:
        if request.method == 'POST':
            force_refresh = request.form.get('refresh', 'false') == 'true'
            should_scrape = force_refresh or (db.get_article_count() == 0)

            if should_scrape:
                logger.info("Scraping fresh data and saving to DB...")
                aggregator.scrape_all(hn_pages=pages, force=force_refresh)
                new_articles = aggregator.get_articles()
                db.add_articles(new_articles)
                # Process metadata for new articles
                process_articles_metadata()
            else:
                logger.info("Querying existing data...")

    except Exception as e:
        logger.error(f"Error during scrape/filter: {e}")

    # Fetch articles with pagination
    articles = db.get_articles(
        limit=per_page, offset=offset,
        source_filter=source_filter, keyword=keyword,
        category=category_filter
    )
    articles = sort_articles(articles, sort_by)

    total = db.get_total_count(source_filter=source_filter, keyword=keyword, category=category_filter)
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Apply Clustering
    clusterer = NewsClusterer(similarity_threshold=0.2)
    clustered_articles = clusterer.cluster_articles(articles)

    # Get stats
    stats = db.get_stats()

    # Source health
    health = aggregator.get_health()

    return render_template('index.html',
                           articles=articles,
                           clustered_articles=clustered_articles,
                           stats=stats,
                           total_count=total,
                           page=page,
                           total_pages=total_pages,
                           showing_saved=False,
                           source_health=health,
                           keyword=keyword,
                           sort_by=sort_by,
                           source_filter=source_filter,
                           category_filter=category_filter)


# ──────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────

@app.route('/bookmark', methods=['POST'])
def bookmark() -> Response:
    """Toggles article bookmark status."""
    data = request.get_json()
    article_id = data.get('article_id')
    if article_id:
        new_status = db.toggle_bookmark(article_id)
        return jsonify({'status': 'saved' if new_status else 'removed'})
    return jsonify({'error': 'Missing article_id'}), 400


@app.route('/toggle_read', methods=['POST'])
def toggle_read() -> Response:
    """Toggles article read status."""
    data = request.get_json()
    article_id = data.get('article_id')
    if article_id:
        new_status = db.toggle_read(article_id)
        return jsonify({'status': 'read' if new_status else 'unread'})
    return jsonify({'error': 'Missing article_id'}), 400


@app.route('/subscribe', methods=['POST'])
def subscribe() -> Response:
    """Handle email subscription."""
    data = request.get_json()
    email = data.get('email', '').strip()
    if not email or not is_valid_email(email):
        return jsonify({'error': 'Please enter a valid email address'}), 400

    logger.info(f"New subscriber: {email}")
    return jsonify({'message': 'Subscribed successfully!'})


@app.route('/api/stats')
def api_stats() -> Response:
    """API endpoint for dashboard statistics."""
    stats = db.get_stats()
    return jsonify(stats)


@app.route('/api/search')
def api_search() -> Response:
    """Full-text search endpoint using FTS5."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Search query required'}), 400

    results = db.search_articles(query, limit=50)
    return jsonify({'results': results, 'count': len(results)})


@app.route('/api/trending')
def api_trending() -> Response:
    """Returns trending topics from recent articles."""
    title_rows = db.get_trending_words()
    titles = [row.get('title', '') for row in title_rows]
    topics = extract_trending_topics(titles, limit=12)
    return jsonify({'topics': topics})


@app.route('/api/charts')
def api_charts() -> Response:
    """Returns chart data for the dashboard."""
    stats = db.get_stats()
    daily = db.get_articles_per_day(days=7)

    return jsonify({
        'by_source': stats.get('by_source', {}),
        'by_category': stats.get('by_category', {}),
        'by_sentiment': stats.get('by_sentiment', {}),
        'daily': daily
    })


@app.route('/api/health')
def api_health() -> Response:
    """Returns scraper health status for all sources."""
    return jsonify({'sources': aggregator.get_health()})


@app.route('/api/personalized')
def api_personalized() -> Response:
    """Returns personalized feed based on user bookmarks."""
    articles = db.get_personalized_feed(limit=30)
    return jsonify({'articles': articles})


@app.route('/api/summarize', methods=['POST'])
def summarize() -> Response:
    """Summarizes a given URL using newspaper3k."""
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    if not is_safe_url(url):
        return jsonify({'error': 'URL not allowed'}), 400

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
        logger.warning(f"Failed to summarize {url}: {e}")
        return jsonify({'error': f"Failed to summarize: {str(e)}"}), 500


@app.route('/export/json')
def export_json() -> Response:
    """Exports bookmarked articles as JSON download."""
    json_data = db.export_bookmarks_json()
    return Response(json_data, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment;filename=bookmarks.json'})


@app.route('/export/markdown')
def export_markdown() -> Response:
    """Exports bookmarked articles as Markdown download."""
    md_data = db.export_bookmarks_markdown()
    return Response(md_data, mimetype='text/markdown',
                    headers={'Content-Disposition': 'attachment;filename=bookmarks.md'})


@app.route('/api/webhook/test', methods=['POST'])
def test_webhook() -> Response:
    """Tests a webhook by sending a sample payload.
    Configure WEBHOOK_URL environment variable to use."""
    import requests as req

    webhook_url = os.getenv('WEBHOOK_URL', '').strip()
    if not webhook_url:
        return jsonify({'error': 'No WEBHOOK_URL configured. Set it as an environment variable.'}), 400

    stats = db.get_stats()
    payload = {
        'text': f"📰 *Tech News Digest*\n"
                f"- Total articles: {stats['total']}\n"
                f"- New today: {stats['today']}\n"
                f"- Saved: {stats['saved']}",
        'username': 'Tech News Aggregator'
    }

    try:
        resp = req.post(webhook_url, json=payload, timeout=10)
        if resp.status_code < 300:
            return jsonify({'status': 'Webhook sent successfully'})
        return jsonify({'error': f'Webhook returned {resp.status_code}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/digest', methods=['POST'])
def send_email_digest() -> Response:
    """Sends an email digest of top articles.
    Configure SMTP_* environment variables to use."""
    smtp_host = os.getenv('SMTP_HOST', '')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_pass = os.getenv('SMTP_PASS', '')

    if not all([smtp_host, smtp_user, smtp_pass]):
        return jsonify({
            'error': 'Email not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASS environment variables.',
            'hint': 'Example: set SMTP_HOST=smtp.gmail.com'
        }), 400

    data = request.get_json()
    recipient = data.get('email', '').strip()
    if not recipient or not is_valid_email(recipient):
        return jsonify({'error': 'Valid recipient email required'}), 400

    # Build digest content
    articles = db.get_articles(limit=10)
    digest_lines = ["<h2>📰 Your Tech News Digest</h2><ul>"]
    for a in articles:
        digest_lines.append(f"<li><a href='{a.get('link')}'>{a.get('title')}</a> [{a.get('source')}]</li>")
    digest_lines.append("</ul>")

    body = '\n'.join(digest_lines)
    msg = MIMEText(body, 'html')
    msg['Subject'] = 'Your Daily Tech News Digest'
    msg['From'] = smtp_user
    msg['To'] = recipient

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return jsonify({'status': 'Digest sent successfully'})
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return jsonify({'error': f'Failed to send: {str(e)}'}), 500


# ──────────────────────────────────────────────
# PWA Support
# ──────────────────────────────────────────────

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Tech News Aggregator",
        "short_name": "TechNews",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a2e",
        "theme_color": "#6c5ce7",
        "description": "Aggregate tech news from multiple sources",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    })


@app.route('/service-worker.js')
def service_worker():
    return app.send_static_file('service-worker.js')


# ──────────────────────────────────────────────
# Start Background Scheduler
# ──────────────────────────────────────────────

if _scheduler_available:
    scheduler = BackgroundScheduler()
    # Scrape every 15 minutes
    scheduler.add_job(background_scrape, 'interval', minutes=15, id='scrape_job',
                      replace_existing=True, max_instances=1)
    scheduler.start()
    logger.info("Background scheduler started (scraping every 15 minutes)")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # Process any unprocessed articles on startup
    process_articles_metadata()
    app.run(debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
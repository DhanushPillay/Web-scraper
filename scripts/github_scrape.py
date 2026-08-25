import os
import sys
import time
import logging

# Make sure src is in pythonpath
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from database import Database
from web_scraper import NewsAggregator
from pipeline.enrich import enrich_batch as _enrich_batch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("github_scrape")

def ensure_nltk_data():
    for resource in ['tokenizers/punkt', 'tokenizers/punkt_tab', 'sentiment/vader_lexicon', 'corpora/stopwords']:
        try:
            nltk.data.find(resource)
        except LookupError:
            nltk.download(resource.split('/')[-1], quiet=True)

def estimate_read_time(title: str, excerpt: str = '') -> int:
    text = excerpt.strip() if excerpt and excerpt.strip() else title
    word_count = len(text.split())
    if word_count > 80: return 7
    elif word_count > 40: return 5
    elif word_count > 20: return 4
    return 3

def main():
    logger.info("Starting automated background scrape...")
    ensure_nltk_data()
    sia = SentimentIntensityAnalyzer()
    
    # Check DB URI
    db_uri = os.environ.get('DATABASE_URL')
    if not db_uri:
        logger.error("DATABASE_URL not set in environment!")
        sys.exit(1)
        
    db = Database(db_uri)
    agg = NewsAggregator()
    
    # Scrape with deep fetch (will use sumy and trafilatura)
    agg.scrape_all(hn_pages=2, force=True)
    new_articles = agg.get_articles()
    
    if new_articles:
        logger.info(f"Enriching {len(new_articles)} articles with fetch=True (Deep Extract)...")
        new_articles = _enrich_batch(new_articles, fetch=True)
        db.add_articles(new_articles)
        db.upsert_images(new_articles)
        logger.info(f"Successfully added {len(new_articles)} new articles to DB.")
        
        # Process metadata for unprocessed articles
        from app import classify_article
        unprocessed = db.get_unprocessed_articles(limit=2000)
        
        if unprocessed:
            processed_at = time.time()
            for article in unprocessed:
                title = article.get('title', '')
                excerpt = article.get('excerpt', '')
                
                # Sentiment Analysis
                try:
                    scores = sia.polarity_scores(title)
                    compound = scores['compound']
                    if compound >= 0.05: label = 'positive'
                    elif compound <= -0.05: label = 'negative'
                    else: label = 'neutral'
                except Exception:
                    label, compound = 'neutral', 0.0
                    
                category = classify_article(title)
                read_time = estimate_read_time(title, excerpt)
                
                db.update_article_metadata(
                    article_id=article['id'],
                    sentiment=label,
                    sentiment_score=compound,
                    category=category,
                    read_time=read_time,
                    metadata_processed_at=processed_at
                )
            logger.info(f"Processed NLP metadata for {len(unprocessed)} articles.")
    else:
        logger.info("No new articles found.")

    logger.info("Automated scrape complete.")

if __name__ == '__main__':
    main()

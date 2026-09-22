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
from categories import classify_article
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

    # Check DB URI
    db_uri = os.environ.get('DATABASE_URL')
    if not db_uri:
        logger.error("DATABASE_URL not set in environment!")
        sys.exit(1)
        
    # Database reads DATABASE_URL itself.  Do not pass a connection URI as the
    # SQLite fallback filename in case PostgreSQL is temporarily unavailable.
    db = Database()
    agg = NewsAggregator()
    
    # Scrape with deep fetch (will use sumy and trafilatura)
    t_scrape = time.perf_counter()
    agg.scrape_all(hn_pages=2, force=True)
    logger.info(f"Phase scrape took {time.perf_counter() - t_scrape:.1f}s.")
    new_articles = agg.get_articles()

    if new_articles:
        logger.info(f"Enriching {len(new_articles)} articles with fetch=True (Deep Extract)...")
        t_enrich = time.perf_counter()
        new_articles = _enrich_batch(new_articles, fetch=True)
        logger.info(f"Phase enrich took {time.perf_counter() - t_enrich:.1f}s.")
        t_db = time.perf_counter()
        inserted, skipped = db.add_articles(new_articles)
        db.upsert_images(new_articles)
        try:
            retention = int(os.environ.get('RETENTION_DAYS', '2'))
        except ValueError:
            retention = 2
        removed = db.prune_old_articles(max_age_days=retention)
        logger.info(f"Phase db-write+prune took {time.perf_counter() - t_db:.1f}s.")
        logger.info(f"Pruned {removed} articles older than {retention}d.")
        logger.info(f"Inserted {inserted} new articles, skipped {skipped} duplicates.")
        
        # Process metadata for unprocessed articles
        unprocessed = db.get_unprocessed_articles(limit=2000)
        
        if unprocessed:
            # Lazy NLTK: only needed when there is metadata to compute, so
            # empty runs exit before touching downloads or the lexicon.
            ensure_nltk_data()
            sia = SentimentIntensityAnalyzer()
            t_nlp = time.perf_counter()
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
            logger.info(f"Processed NLP metadata for {len(unprocessed)} articles in {time.perf_counter() - t_nlp:.1f}s.")
    else:
        logger.error("Scraped 0 articles from all sources — failing loud so a dead feed turns the run red.")
        sys.exit(1)

    logger.info("Automated scrape complete.")

if __name__ == '__main__':
    main()

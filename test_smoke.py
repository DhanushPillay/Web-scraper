"""Smoke tests — ponytail minimal: fails if core logic breaks."""
import os
os.environ['SNIFFER_NO_AUTO_INIT'] = '1'

def test_classify():
    from app import classify_article
    assert classify_article("OpenAI releases GPT-5 with transformer") == "AI & ML"
    assert classify_article("New quantum chip from Intel") == "Hardware"
    # short-word boundary: 'ai' should not match 'air'
    assert classify_article("Air quality improves in city") != "AI & ML"
    print("classify ok")

def test_safe_url():
    from app import is_safe_url
    assert not is_safe_url("http://localhost/test")
    assert not is_safe_url("http://127.0.0.1:8000")
    assert not is_safe_url("http://169.254.169.254/latest/meta-data/")
    assert is_safe_url("https://techcrunch.com/article")
    assert not is_safe_url("ftp://example.com/file")
    assert not is_safe_url("https://example.com:8080/")
    print("safe_url ok")

def test_excerpt():
    from web_scraper import _clean_excerpt
    assert _clean_excerpt("<p>Hello &amp; world</p>") == "Hello & world"
    t = "a " * 200
    assert len(_clean_excerpt(t)) <= 281
    print("excerpt ok")

def test_fts_sanitize():
    import tempfile, os
    from database import Database
    path = tempfile.mktemp(suffix='.db')
    try:
        db = Database(path)
        # should not raise
        assert db._sanitize_fts_query('hello OR "world" *') != ""
        assert db._sanitize_fts_query("   ") == ""
        # search should fallback gracefully
        res = db.search_articles("test", limit=5)
        assert isinstance(res, list)
        print("fts ok")
    finally:
        try: os.remove(path)
        except: pass

def test_personalized_no_crash():
    import tempfile, os
    from database import Database
    path = tempfile.mktemp(suffix='.db')
    try:
        db = Database(path)
        # no bookmarks -> should not crash with IN ()
        feed = db.get_personalized_feed(limit=5)
        assert isinstance(feed, list)
        # add one bookmark with only source, no category match
        db.add_articles([{"title": "t", "link": "https://example.com/a", "source": "Hacker News", "author": "x", "time": "now", "comments": "0", "excerpt": "", "image_url": ""}])
        # bookmark it
        arts = db.get_articles(limit=1)
        if arts:
            db.toggle_bookmark(arts[0]['id'])
            feed2 = db.get_personalized_feed(limit=5)
            assert isinstance(feed2, list)
        print("personalized ok")
    finally:
        try: os.remove(path)
        except: pass

def test_credibility_boundaries():
    from utils.credibility import get_scorer
    s = get_scorer()
    # secretary should not trigger secret
    _, d1 = s.score("New secretary appointed", "https://example.com/a")
    _, d2 = s.score("Secret revealed in leaked report", "https://example.com/b")
    assert d1['title_penalty'] < d2['title_penalty']
    print("credibility ok")

def test_estimate_read_time():
    from app import estimate_read_time
    assert estimate_read_time("short", "a " * 100) == 7
    assert estimate_read_time("short title") == 3
    print("read_time ok")

if __name__ == "__main__":
    test_classify()
    test_safe_url()
    test_excerpt()
    test_fts_sanitize()
    test_personalized_no_crash()
    test_credibility_boundaries()
    test_estimate_read_time()
    print("ALL SMOKE TESTS PASSED")

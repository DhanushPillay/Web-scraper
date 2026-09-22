"""Categories — single keyword classifier shared by app, pipeline, workers."""
import re

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

CATEGORY_FILTER_LOOKUP = {'all': 'all', 'general': 'general'}
for _category in CATEGORY_KEYWORDS:
    CATEGORY_FILTER_LOOKUP[_category.lower()] = _category


def normalize_category_filter(category: str) -> str:
    value = (category or '').strip().lower()
    return CATEGORY_FILTER_LOOKUP.get(value, 'all')


def classify_article(title: str) -> str:
    """Keyword category, word-boundary aware for short terms like 'ai'."""
    title_lower = title.lower()
    words = set(re.findall(r'[a-z0-9]+', title_lower))
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if ' ' in kw:
                if kw in title_lower:
                    score += 1
            elif len(kw) <= 3:
                if kw in words:
                    score += 1
            elif kw in title_lower:
                score += 1
        if score > 0:
            scores[category] = score
    return max(scores, key=scores.get) if scores else 'General'

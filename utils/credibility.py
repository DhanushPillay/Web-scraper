"""
Credibility Scoring Module — Sniffer
Loads MediaBiasFactCheck CSV and provides domain credibility scoring.
"""
import csv
import os
import re
import logging
from functools import lru_cache
from urllib.parse import urlparse
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Clickbait patterns (regex for common clickbait phrases)
CLICKBAIT_PATTERNS = [
    r"you won't believe",
    r"shocking",
    r"mind.?blowing",
    r"this one trick",
    r"what happens next",
    r"goes viral",
    r"destroys?",
    r"slams?",
    r"one weird trick",
    r"is this the end",
    r"secret",
    r"they don't want you to know",
    r"doctors hate",
    r"will change your life",
    r"number \d+ will (shock|surprise)",
    r"wait until you see",
    r"you need to see",
    r"this is (insane|crazy|unbelievable)",
    r"(real|true) story",
    r"exposed",
    r"revealed",
    r"leaked",
]

CLICKBAIT_REGEX = re.compile('|'.join(CLICKBAIT_PATTERNS), re.IGNORECASE)

# Excessive punctuation check
EXCESSIVE_PUNCT_REGEX = re.compile(r'[!?]{2,}|[.]{3,}')


class CredibilityScorer:
    """Scores articles based on domain credibility and title heuristics."""

    def __init__(self, csv_path: Optional[str] = None):
        self.domain_scores: Dict[str, Dict] = {}
        self._load_csv(csv_path)

    def _load_csv(self, csv_path: Optional[str] = None):
        """Load MediaBiasFactCheck CSV into memory."""
        if csv_path is None:
            # Try multiple locations
            base = os.path.dirname(os.path.dirname(__file__))
            candidates = [
                os.path.join(base, 'data', 'mediabiasfactcheck.csv'),
                os.path.join(base, 'mediabiasfactcheck.csv'),
                '/app/data/mediabiasfactcheck.csv',
            ]
            for c in candidates:
                if os.path.exists(c):
                    csv_path = c
                    break

        if not csv_path or not os.path.exists(csv_path):
            logger.warning(f"Credibility CSV not found at {csv_path}. Using defaults only.")
            return

        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    domain = row.get('domain', '').strip().lower()
                    if not domain:
                        continue
                    # Normalize domain (remove www.)
                    domain = domain.replace('www.', '')
                    try:
                        score = int(row.get('credibility_score', 50))
                    except ValueError:
                        score = 50
                    bias = row.get('bias', 'unknown').strip().lower()
                    factual = row.get('factual_reporting', 'mixed').strip().lower()

                    self.domain_scores[domain] = {
                        'score': max(0, min(100, score)),  # clamp 0-100
                        'bias': bias,
                        'factual_reporting': factual,
                    }
            logger.info(f"Loaded credibility data for {len(self.domain_scores)} domains")
        except Exception as e:
            logger.error(f"Failed to load credibility CSV: {e}")

    def _extract_domain(self, url: str) -> str:
        """Extract and normalize domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace('www.', '')
            # Remove port if present
            if ':' in domain:
                domain = domain.split(':')[0]
            return domain
        except Exception:
            return ''

    def _get_domain_match(self, domain: str) -> Optional[Dict]:
        """Find best domain match (exact, then parent domain)."""
        if domain in self.domain_scores:
            return self.domain_scores[domain]

        # Try parent domains (e.g., news.google.com -> google.com)
        parts = domain.split('.')
        for i in range(1, len(parts)):
            parent = '.'.join(parts[i:])
            if parent in self.domain_scores:
                return self.domain_scores[parent]
        return None

    def _analyze_title(self, title: str) -> Dict[str, any]:
        """Analyze title for clickbait signals."""
        if not title:
            return {'clickbait_score': 0, 'excessive_punct': False}

        # Clickbait pattern match
        clickbait_matches = len(CLICKBAIT_REGEX.findall(title))
        clickbait_score = min(clickbait_matches * 15, 60)  # max 60 penalty

        # Excessive punctuation
        excessive_punct = bool(EXCESSIVE_PUNCT_REGEX.search(title))
        punct_penalty = 15 if excessive_punct else 0

        # ALL CAPS words (more than 2 words fully capitalized)
        words = title.split()
        caps_words = sum(1 for w in words if w.isupper() and len(w) > 2)
        caps_penalty = min(caps_words * 5, 25)

        total_penalty = clickbait_score + punct_penalty + caps_penalty
        return {
            'clickbait_score': total_penalty,
            'excessive_punct': excessive_punct,
            'caps_words': caps_words,
        }

    def score(self, title: str, url: str) -> Tuple[int, Dict]:
        """
        Score an article (0-100). Higher = more credible.
        Returns (final_score, details_dict).
        """
        domain = self._extract_domain(url)
        domain_data = self._get_domain_match(domain)

        # Base score from domain credibility (default 50 if unknown)
        if domain_data:
            base_score = domain_data['score']
            bias = domain_data['bias']
            factual = domain_data['factual_reporting']
        else:
            base_score = 50
            bias = 'unknown'
            factual = 'unknown'

        # Title analysis penalties
        title_analysis = self._analyze_title(title)
        title_penalty = title_analysis['clickbait_score']

        # Final score
        final_score = max(0, base_score - title_penalty)

        details = {
            'domain': domain,
            'domain_score': base_score,
            'bias': bias,
            'factual_reporting': factual,
            'title_penalty': title_penalty,
            'clickbait_detected': title_analysis['clickbait_score'] > 0,
            'excessive_punct': title_analysis['excessive_punct'],
            'final_score': final_score,
        }
        return final_score, details

    def is_credible(self, title: str, url: str, threshold: int = 40) -> bool:
        """Return True if article passes credibility threshold."""
        score, _ = self.score(title, url)
        return score >= threshold


# Global instance (lazy-loaded)
_scorer: Optional[CredibilityScorer] = None


def get_scorer() -> CredibilityScorer:
    """Get or create the global credibility scorer."""
    global _scorer
    if _scorer is None:
        _scorer = CredibilityScorer()
    return _scorer


def is_credible(title: str, url: str, threshold: int = 40) -> bool:
    """Convenience function to check credibility."""
    return get_scorer().is_credible(title, url, threshold)


def score_article(title: str, url: str) -> Tuple[int, Dict]:
    """Convenience function to get full score details."""
    return get_scorer().score(title, url)
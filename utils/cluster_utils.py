import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import re
from typing import List, Dict, Any

class NewsClusterer:
    def __init__(self, similarity_threshold: float = 0.3):
        self.similarity_threshold = similarity_threshold
        self._ensure_nltk_data()
        self.stop_words = set(stopwords.words('english'))

    def _ensure_nltk_data(self):
        """Ensure necessary NLTK data is downloaded."""
        try:
            nltk.data.find('tokenizers/punkt')
            nltk.data.find('corpora/stopwords')
        except LookupError:
            print("Downloading NLTK data for clustering...")
            nltk.download('punkt')
            nltk.download('stopwords')

    def _preprocess_title(self, title: str) -> set:
        """Tokenize and clean title for comparison."""
        # Lowercase and remove punctuation
        text = re.sub(r'[^\w\s]', '', title.lower())
        # Tokenize
        tokens = word_tokenize(text)
        # Remove stopwords and short words (but keep numbers like '16')
        return {word for word in tokens if word not in self.stop_words and (len(word) > 2 or word.isdigit())}

    def _calculate_jaccard_similarity(self, set1: set, set2: set) -> float:
        """Calculate Jaccard similarity between two sets of tokens."""
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return intersection / union if union > 0 else 0.0

    def cluster_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Group articles by similarity.
        Returns a list of 'parent' articles, with 'related_articles' nested inside them.
        """
        if not articles:
            return []

        # Sort by score (descending) so higher score articles tend to become parents
        # Ensure score is treated as int
        sorted_articles = sorted(
            articles, 
            key=lambda x: int(x.get('score', 0)) if str(x.get('score', 0)).isdigit() else 0, 
            reverse=True
        )

        clusters = []
        
        # Pre-compute token sets for performance
        article_tokens = [
            (article, self._preprocess_title(article.get('title', ''))) 
            for article in sorted_articles
        ]
        
        assigned_indices = set()

        for i, (parent_article, parent_tokens) in enumerate(article_tokens):
            if i in assigned_indices:
                continue

            # This article becomes a new cluster parent
            cluster_parent = parent_article.copy()
            cluster_parent['related_articles'] = []
            assigned_indices.add(i)

            # Look for related articles among the remaining unassigned ones
            for j, (candidate_article, candidate_tokens) in enumerate(article_tokens):
                if j in assigned_indices:
                    continue
                
                # Check similarity
                similarity = self._calculate_jaccard_similarity(parent_tokens, candidate_tokens)
                
                if similarity >= self.similarity_threshold:
                    candidate_copy = candidate_article.copy()
                    candidate_copy['similarity_score'] = round(similarity, 2)
                    cluster_parent['related_articles'].append(candidate_copy)
                    assigned_indices.add(j)

            clusters.append(cluster_parent)

        return clusters

"""Find past research related to a new topic: TF-IDF cosine similarity in plain Python.

TF-IDF scores a word by how often it appears in a document (term frequency) times how rare it is
across all documents (inverse document frequency), so shared rare words ("stack", "overflow")
count for much more than common ones ("impact"). Cosine similarity then compares two documents'
word-score vectors: 1.0 = same words in the same proportions, 0.0 = nothing in common.

Why not embeddings: Anthropic has no embeddings API, so embeddings would mean a second provider and
key for a corpus of a few dozen past sessions. The trade-off: matching is by words, not meaning.
`Retriever` is the seam where an embedding/pgvector implementation would plug in.
"""

import math
import re
from collections import Counter
from typing import Protocol

WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    (  # noqa: SIM905 - a word list reads better as one string
        "a an and are as at be by for from has have how in into is it its of on or that the "
        "their there these this to was were what when where which who why will with about "
        "after over under than then they them we you your our new recent recently"
    ).split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase words without stopwords. A light plural rule ("models" -> "model") helps
    'AI model' match 'AI models' without a stemming library."""
    words = []
    for word in WORD.findall(text.lower()):
        if word in STOPWORDS or len(word) < 2:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words


def _tfidf(documents: list[list[str]]) -> list[dict[str, float]]:
    n = len(documents)
    document_frequency = Counter(word for doc in documents for word in set(doc))
    vectors = []
    for doc in documents:
        counts = Counter(doc)
        total = len(doc) or 1
        vectors.append(
            {
                word: (count / total) * (math.log((1 + n) / (1 + document_frequency[word])) + 1)
                for word, count in counts.items()
            }
        )
    return vectors


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(weight * b.get(word, 0.0) for word, weight in a.items())
    norm = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(sum(w * w for w in b.values()))
    return dot / norm if norm else 0.0


class Retriever(Protocol):
    def similarities(self, query: str, documents: list[str]) -> list[float]: ...


class TfidfRetriever:
    def similarities(self, query: str, documents: list[str]) -> list[float]:
        """Similarity of `query` to each document, in document order."""
        if not documents:
            return []
        vectors = _tfidf([tokenize(d) for d in documents] + [tokenize(query)])
        query_vector = vectors[-1]
        return [_cosine(query_vector, v) for v in vectors[:-1]]

"""Shared word and character TF-IDF representation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class TextFeatures:
    char: TfidfVectorizer
    word: TfidfVectorizer
    normalize_yo: bool = False

    @classmethod
    def create(cls) -> "TextFeatures":
        return cls(
            char=TfidfVectorizer(
                analyzer="char_wb", ngram_range=(2, 5), min_df=2,
                max_features=120_000, sublinear_tf=True, dtype=np.float32,
            ),
            word=TfidfVectorizer(
                analyzer="word", ngram_range=(1, 2), token_pattern=r"(?u)\b\w+\b",
                min_df=2, max_features=60_000, sublinear_tf=True, dtype=np.float32,
            ),
        )

    @classmethod
    def baseline(cls) -> "TextFeatures":
        """Uncapped reference representation with the v3 normalization."""
        return cls(
            char=TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                                 min_df=2, sublinear_tf=True, dtype=np.float32),
            word=TfidfVectorizer(ngram_range=(1, 2), min_df=2,
                                 sublinear_tf=True, dtype=np.float32),
            normalize_yo=True,
        )

    def _prepare(self, texts: Sequence[str]) -> list[str]:
        return [s.lower().replace("ё", "е") for s in texts] if self.normalize_yo else list(texts)

    def fit_transform(self, texts: Sequence[str]) -> csr_matrix:
        texts = self._prepare(texts)
        a = self.char.fit_transform(texts)
        b = self.word.fit_transform(texts)
        return hstack((a, b), format="csr", dtype=np.float32)

    def transform(self, texts: Sequence[str]) -> csr_matrix:
        texts = self._prepare(texts)
        return hstack((self.char.transform(texts), self.word.transform(texts)),
                      format="csr", dtype=np.float32)

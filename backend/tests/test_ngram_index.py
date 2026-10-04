"""The dependency-free character n-gram index must behave exactly like scikit-learn's TfidfVectorizer(analyzer="char_wb")."""
import numpy as np
import pytest

from app.services.retriever import CharNgramIndex

TEXTS = [
    "Invoices are payable Net 30 from the invoice date. Late payments accrue interest at 1.5% per month.",
    "Section 3 is amended so that invoices are payable Net 45 from the invoice date.",
    "The outage was caused by an expired TLS certificate on the tracking API gateway.",
    "Employees receive 20 days of paid annual leave per calendar year.",
    "Passwords must be rotated every 90 days.  MFA is mandatory for remote access!",
    "a b",                                           # words shorter than the n-gram size
]
QUERIES = ["What are the payment terms?", "expired certificate outage", "annual leave days", "zzzz qqqq", "", "a"]


def test_scores_match_scikit_learn():
    sk = pytest.importorskip("sklearn.feature_extraction.text")
    vec = sk.TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1, lowercase=True)
    mat = vec.fit_transform(TEXTS)
    ours = CharNgramIndex(TEXTS)
    for q in QUERIES:
        try:
            expected = (mat @ vec.transform([q]).T).toarray().ravel()
        except Exception:
            expected = np.zeros(len(TEXTS))
        assert np.allclose(ours.scores(q), expected, atol=1e-9), q


def test_ranks_the_relevant_passage_first_and_handles_edge_cases():
    idx = CharNgramIndex(TEXTS)
    assert int(np.argmax(idx.scores("expired certificate outage"))) == 2
    assert int(np.argmax(idx.scores("payable invoices"))) in (0, 1)
    assert not idx.scores("zzzz qqqq").any() and not idx.scores("").any()          # unknown / empty queries score zero
    assert CharNgramIndex([]).scores("anything").shape == (0,)                       # empty corpus

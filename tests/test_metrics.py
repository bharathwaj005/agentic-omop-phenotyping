"""Unit tests for the concept-set metric used throughout the paper."""
import pytest

from src.metrics.evaluation import set_metrics


def test_identical_sets_score_one():
    m = set_metrics({1, 2, 3}, {1, 2, 3})
    assert (m.precision, m.recall, m.f1, m.jaccard) == (1.0, 1.0, 1.0, 1.0)


def test_partial_overlap():
    m = set_metrics({1, 2}, {2, 3})
    assert m.precision == pytest.approx(0.5)
    assert m.recall == pytest.approx(0.5)
    assert m.f1 == pytest.approx(0.5)
    assert m.jaccard == pytest.approx(1 / 3)


def test_zero_overlap_is_f1_zero_not_missing():
    """A run that predicts concepts but shares none with the reference is a real miss (F1 = 0)."""
    m = set_metrics({10, 11}, {1, 2})
    assert m.precision == 0.0 and m.recall == 0.0
    assert m.f1 == 0.0


def test_empty_prediction_is_undefined():
    """No predicted concepts: precision is undefined, so the run is unscored (counted as 0 only under All=0)."""
    m = set_metrics(set(), {1, 2})
    assert m.precision is None
    assert m.f1 is None


def test_precision_is_one_when_prediction_is_subset():
    m = set_metrics({1}, {1, 2, 3, 4})
    assert m.precision == 1.0
    assert m.recall == pytest.approx(0.25)

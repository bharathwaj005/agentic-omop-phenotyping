import pytest
import numpy as np

def test_semantic_ancestor_distance():
    ancestors = {
        (100, 200): 1,
        (200, 300): 1,
        (100, 300): 2
    }
    def match(c_pred, c_ref, max_L):
        if c_pred == c_ref: return True
        return ancestors.get((c_pred, c_ref), 999) <= max_L or ancestors.get((c_ref, c_pred), 999) <= max_L

    assert match(100, 100, 1) is True
    assert match(100, 200, 1) is True
    assert match(100, 300, 1) is False
    assert match(100, 300, 2) is True

def test_standardized_mean_difference_calculation():
    x_gen = np.array([1, 1, 0, 1, 0, 0, 1, 1])
    x_ref = np.array([1, 1, 1, 1, 1, 0, 1, 1])
    m_gen, m_ref = np.mean(x_gen), np.mean(x_ref)
    s_gen, s_ref = np.var(x_gen, ddof=1), np.var(x_ref, ddof=1)
    pooled_s = np.sqrt((s_gen + s_ref) / 2.0)
    smd = (m_gen - m_ref) / pooled_s
    assert abs(smd) > 0.0
    assert not np.isnan(smd)

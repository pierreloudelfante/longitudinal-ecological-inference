from __future__ import annotations

import numpy as np
import pytest

from code_longitudinal.ppc_v2 import (
    expected_vote_share_draws,
    posterior_predictive_metrics,
    simulate_vote_counts,
)


def test_expected_vote_share_draws_uses_group_specific_counts() -> None:
    b1 = np.array([[0.8, 0.2], [0.6, 0.4]])
    b2 = np.array([[0.1, 0.9], [0.3, 0.7]])
    n1 = np.array([75, 20])
    n2 = np.array([25, 80])

    actual = expected_vote_share_draws(b1, b2, n1, n2)

    expected = np.array([[0.625, 0.76], [0.525, 0.64]])
    np.testing.assert_allclose(actual, expected)


def test_expected_vote_share_draws_flattens_chain_and_draw_dimensions() -> None:
    b1 = np.full((2, 3, 4), 0.75)
    b2 = np.full((2, 3, 4), 0.25)
    result = expected_vote_share_draws(b1, b2, np.full(4, 60), np.full(4, 40))
    assert result.shape == (6, 4)
    np.testing.assert_allclose(result, 0.55)


def test_invalid_probabilities_and_zero_totals_are_rejected() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        expected_vote_share_draws([[1.2]], [[0.2]], [1], [1])
    with pytest.raises(ValueError, match="strictly positive"):
        expected_vote_share_draws([[0.2]], [[0.2]], [0], [0])


def test_simulated_counts_are_reproducible_and_bounded() -> None:
    theta = np.array([[0.2, 0.8], [0.4, 0.6], [0.5, 0.5]])
    first = simulate_vote_counts(theta, [10, 20], seed=42)
    second = simulate_vote_counts(theta, [10, 20], seed=42)
    np.testing.assert_array_equal(first, second)
    assert np.all(first >= 0)
    assert np.all(first <= np.array([10, 20]))


def test_ppc_metrics_recover_exact_posterior_mean_fit() -> None:
    theta = np.tile(np.array([0.2, 0.8]), (100, 1))
    totals = np.array([100, 100])
    observed = np.array([20, 80])
    replicated = simulate_vote_counts(theta, totals, seed=7)

    metrics, commune, aggregate = posterior_predictive_metrics(theta, replicated, observed, totals)

    assert metrics["mean_error"] == pytest.approx(0.0, abs=1e-12)
    assert metrics["rmse"] == pytest.approx(0.0, abs=1e-12)
    assert metrics["mae"] == pytest.approx(0.0, abs=1e-12)
    assert metrics["aggregate_observed_share"] == pytest.approx(0.5)
    assert 0 <= metrics["bayesian_p_value_pearson_upper_tail"] <= 1
    assert len(commune) == 2
    assert aggregate.shape == (100,)

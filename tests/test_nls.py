from __future__ import annotations

import numpy as np

from code_longitudinal.nls import (
    NLSData,
    aggregate_probabilities,
    fit_nls,
    objective_sse,
    probabilities,
    residuals,
    sandwich_standard_errors,
    unpack_params,
)


def synthetic_data(seed: int = 3) -> tuple[NLSData, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.dirichlet([2.0, 2.5, 3.0], size=120)
    z = np.empty((len(x), 0))
    true_params = np.array([0.8, -0.3, 0.2, 0.6, -0.4, 0.1])
    _, t = probabilities(true_params, x, z, 3)
    return NLSData(x=x, t=t, n=np.repeat(100.0, len(x)), z=z), true_params


def test_softmax_sums_to_one() -> None:
    data, params = synthetic_data()
    pi, _ = probabilities(params, data.x, data.z, 3)
    assert np.allclose(pi.sum(axis=2), 1)


def test_probabilities_are_bounded() -> None:
    data, params = synthetic_data()
    pi, fitted = probabilities(params, data.x, data.z, 3)
    assert ((pi >= 0) & (pi <= 1)).all()
    assert ((fitted >= 0) & (fitted <= 1)).all()


def test_reference_category_is_implicit_zero() -> None:
    data, _ = synthetic_data()
    zero = np.zeros(6)
    pi, _ = probabilities(zero, data.x, data.z, 3)
    assert np.allclose(pi, 1 / 3)
    assert unpack_params(zero, 3, 3, 1).shape == (3, 2, 1)


def test_fitted_margins_equal_x_times_probabilities() -> None:
    data, params = synthetic_data()
    pi, fitted = probabilities(params, data.x, data.z, 3)
    assert np.allclose(fitted, np.einsum("ir,irc->ic", data.x, pi))


def test_residuals_only_use_c_minus_one_categories() -> None:
    data, params = synthetic_data()
    assert residuals(params, data.x, data.t, data.z).size == len(data.x) * 2


def test_objective_is_exact_unweighted_sse() -> None:
    data, params = synthetic_data()
    raw = residuals(params + 0.1, data.x, data.t, data.z)
    assert np.isclose(objective_sse(params + 0.1, data.x, data.t, data.z), np.sum(raw**2))


def test_noiseless_fit_recovers_predictions() -> None:
    data, _ = synthetic_data()
    best, _ = fit_nls(data, n_starts=4, max_nfev=2000, random_seed=11)
    _, fitted = probabilities(best.x, data.x, data.z, 3)
    assert np.max(np.abs(fitted - data.t)) < 1e-6


def test_multiple_starts_agree_on_identified_predictions() -> None:
    data, _ = synthetic_data()
    _, starts = fit_nls(data, n_starts=4, max_nfev=2000, random_seed=12)
    successful = [row for row in starts if row["success"]]
    assert successful
    assert max(float(row["max_abs_prediction_difference_from_best"]) for row in successful) < 1e-4


def test_sandwich_standard_errors_have_correct_dimensions_and_are_finite() -> None:
    data, true_params = synthetic_data()
    se, _ = sandwich_standard_errors(true_params, data)
    assert se.shape == true_params.shape
    assert np.isfinite(se).all()


def test_singular_values_rank_and_condition_are_exported() -> None:
    data, true_params = synthetic_data()
    _, meta = sandwich_standard_errors(true_params, data)
    assert "bread_singular_values_json" in meta
    assert meta["bread_rank"] == len(true_params)
    assert np.isfinite(meta["bread_condition"])


def test_aggregate_probabilities_are_group_population_weighted() -> None:
    data, params = synthetic_data()
    pi, _ = probabilities(params, data.x, data.z, 3)
    aggregate = aggregate_probabilities(data.x, data.n, pi)
    assert aggregate.shape == (3, 3)
    assert np.allclose(aggregate.sum(axis=1), 1)

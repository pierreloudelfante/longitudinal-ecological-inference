from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from code_longitudinal.postprocess_aggregates_v2 import (
    aggregate_krt_draws_v2,
    group_weighted_draws,
    summarize_krt_aggregates_v2,
)


def _synthetic_posterior() -> xr.Dataset:
    return xr.Dataset(
        {
            "b_1": (
                ("chain", "draw", "b_1_dim_0"),
                np.array([[[0.2, 0.8], [0.4, 0.6]]]),
            ),
            "b_2": (
                ("chain", "draw", "b_2_dim_0"),
                np.array([[[0.9, 0.1], [0.7, 0.3]]]),
            ),
        },
        coords={"b_1_dim_0": [10, 20], "b_2_dim_0": [10, 20]},
    )


def test_pure_group_weighting_uses_the_group_denominator_for_each_draw() -> None:
    draws = np.array([[[0.2, 0.8], [0.4, 0.6]]])

    result = group_weighted_draws(draws, [90, 10])

    assert result.shape == (1, 2)
    assert np.allclose(result, [[0.26, 0.42]])


def test_pure_group_weighting_accepts_a_nonfinal_unit_axis() -> None:
    draws = np.array([[0.2, 0.4], [0.8, 0.6]])

    result = group_weighted_draws(draws, [90, 10], unit_axis=0)

    assert np.allclose(result, [0.26, 0.42])


def test_v2_draws_keep_chain_draw_dimensions_and_expose_legacy_comparison() -> None:
    posterior = _synthetic_posterior()

    result = aggregate_krt_draws_v2(
        posterior,
        b1_weights=[90, 10],
        b2_weights=[10, 90],
        total_weights=[100, 100],
    )

    assert set(result.data_vars) == {
        "b_1_group_weighted",
        "b_2_group_weighted",
        "b_1_legacy_total_weighted",
        "b_2_legacy_total_weighted",
    }
    assert result["b_1_group_weighted"].dims == ("chain", "draw")
    assert np.allclose(result["b_1_group_weighted"], [[0.26, 0.42]])
    assert np.allclose(result["b_2_group_weighted"], [[0.18, 0.34]])
    assert np.allclose(result["b_1_legacy_total_weighted"], [[0.5, 0.5]])
    assert np.allclose(result["b_2_legacy_total_weighted"], [[0.5, 0.5]])
    assert result.attrs["postprocessing_version"] == "2"


def test_arviz_like_object_and_variable_specific_unit_dimensions_are_supported() -> None:
    trace = type("Trace", (), {"posterior": _synthetic_posterior()})()

    result = aggregate_krt_draws_v2(trace, [90, 10], [10, 90])

    assert set(result.data_vars) == {"b_1_group_weighted", "b_2_group_weighted"}


def test_coordinate_mismatch_is_rejected_instead_of_silently_reordered() -> None:
    posterior = _synthetic_posterior()
    mismatched = xr.DataArray([90, 10], dims=("unit",), coords={"unit": [20, 10]})

    with pytest.raises(ValueError, match="coordinates do not exactly match"):
        aggregate_krt_draws_v2(posterior, mismatched, [10, 90])


@pytest.mark.parametrize("weights", ([0, 0], [1, -1], [1, np.nan], [1]))
def test_invalid_group_denominators_are_rejected(weights: list[float]) -> None:
    with pytest.raises(ValueError):
        group_weighted_draws(np.array([[0.2, 0.8]]), weights)


def test_summary_reports_quantiles_and_the_difference_from_legacy_mean() -> None:
    draws = aggregate_krt_draws_v2(
        _synthetic_posterior(),
        b1_weights=[90, 10],
        b2_weights=[10, 90],
        total_weights=[100, 100],
    )

    summary = summarize_krt_aggregates_v2(draws)

    assert len(summary) == 4
    corrected_b1 = summary.loc[
        summary["beta_parameter"].eq("b_1")
        & summary["aggregation_method"].eq("group_specific_population_v2")
    ].iloc[0]
    assert corrected_b1["weight_basis"] == "N1"
    assert corrected_b1["n_posterior_draws"] == 2
    assert np.isclose(corrected_b1["mean"], 0.34)
    assert np.isclose(corrected_b1["legacy_mean"], 0.5)
    assert np.isclose(corrected_b1["mean_difference_from_legacy"], -0.16)
    assert np.isclose(corrected_b1["q50"], 0.34)
    assert corrected_b1["q025"] < corrected_b1["q975"]


def test_optional_contrast_is_computed_draw_by_draw_from_group_specific_aggregates() -> None:
    draws = aggregate_krt_draws_v2(
        _synthetic_posterior(),
        b1_weights=[90, 10],
        b2_weights=[10, 90],
        total_weights=[100, 100],
        include_contrast=True,
    )

    assert np.allclose(draws["b_1_minus_b_2_group_weighted"], [[0.08, 0.08]])
    summary = summarize_krt_aggregates_v2(draws)
    contrast = summary.loc[
        summary["beta_parameter"].eq("b_1_minus_b_2")
        & summary["aggregation_method"].eq("group_specific_population_v2")
    ].iloc[0]
    assert contrast["weight_basis"] == "group_specific_population_v2"
    assert np.isclose(contrast["mean"], 0.08)

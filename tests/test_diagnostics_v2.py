from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from code_longitudinal.diagnostics_v2 import audit_trace, summary_row


def _trace(*, separated_hyperparameter: bool = False, saturated_depth: bool = False) -> SimpleNamespace:
    rng = np.random.default_rng(20260804)
    chains, draws, units = 4, 1000, 5
    b_1 = rng.normal(size=(chains, draws, units))
    b_2 = rng.normal(size=(chains, draws, units))
    c_1 = rng.normal(size=(chains, draws))
    if separated_hyperparameter:
        c_1 = c_1 + np.arange(chains)[:, None] * 4.0
    posterior = xr.Dataset(
        {
            "b_1": (("chain", "draw", "unit"), b_1),
            "b_2": (("chain", "draw", "unit"), b_2),
            "c_1": (("chain", "draw"), c_1),
            "d_1": (("chain", "draw"), rng.normal(size=(chains, draws))),
            "c_2": (("chain", "draw"), rng.normal(size=(chains, draws))),
            "d_2": (("chain", "draw"), rng.normal(size=(chains, draws))),
        }
    )
    tree_depth = np.full((chains, draws), 8)
    if saturated_depth:
        tree_depth[:] = 14
    sample_stats = xr.Dataset(
        {
            "diverging": (("chain", "draw"), np.zeros((chains, draws), dtype=bool)),
            "energy": (("chain", "draw"), rng.normal(size=(chains, draws))),
            "tree_depth": (("chain", "draw"), tree_depth),
            "acceptance_rate": (("chain", "draw"), np.full((chains, draws), 0.99)),
        }
    )
    return SimpleNamespace(posterior=posterior, sample_stats=sample_stats)


def test_audit_passes_once_and_covers_every_posterior_variable() -> None:
    audit = audit_trace(
        _trace(),
        expected_chains=4,
        expected_draws_per_chain=1000,
        max_treedepth=14,
        identification_status="pass",
    )

    assert audit["fit_status"] == "success"
    assert audit["mcmc_status"] == "pass"
    assert audit["identification_status"] == "pass"
    assert audit["selected_for_interpretation"] is True
    assert set(audit["posterior_variables"]) == {"b_1", "b_2", "c_1", "d_1", "c_2", "d_2"}
    assert audit["divergences"] == 0
    assert len(audit["bfmi_by_chain"]) == 4
    assert audit["max_treedepth_hits"] == 0


def test_hyperparameter_failure_controls_the_single_official_verdict() -> None:
    audit = audit_trace(
        _trace(separated_hyperparameter=True),
        max_treedepth=14,
        identification_status="pass",
    )

    assert audit["mcmc_status"] == "fail"
    c1 = next(row for row in audit["variable_metrics"] if row["variable"] == "c_1")
    latent = next(row for row in audit["block_metrics"] if row["block"] == "latent_preferences")
    hyper = next(row for row in audit["block_metrics"] if row["block"] == "hyperparameters")
    assert c1["max_rhat"] > 1.05
    assert hyper["max_rhat"] > latent["max_rhat"]
    assert all("status" not in row for row in audit["block_metrics"])
    assert audit["selected_for_interpretation"] is False


def test_missing_optional_sampler_metrics_yields_caveat_not_second_verdict() -> None:
    trace = _trace()
    trace.sample_stats = trace.sample_stats.drop_vars(["energy", "tree_depth"])
    audit = audit_trace(trace, identification_status="pass")

    assert audit["mcmc_status"] == "caveat"
    assert "min_bfmi_unavailable" in audit["mcmc_reasons"]
    assert "max_treedepth_saturation_unavailable" in audit["mcmc_reasons"]
    assert audit["selected_for_interpretation"] is False


def test_treedepth_saturation_and_saved_shape_can_fail_the_trace() -> None:
    audit = audit_trace(
        _trace(saturated_depth=True),
        expected_chains=4,
        expected_draws_per_chain=999,
        max_treedepth=14,
        identification_status="pass",
    )

    assert audit["mcmc_status"] == "fail"
    assert audit["max_treedepth_hits"] == 4000
    assert "saved_draws_mismatch" in audit["mcmc_reasons"]
    assert "treedepth_fraction_above_fail_threshold" in audit["mcmc_reasons"]


def test_selection_cannot_override_failed_or_unassessed_evidence() -> None:
    with pytest.raises(ValueError, match="can be selected only"):
        audit_trace(
            _trace(separated_hyperparameter=True),
            max_treedepth=14,
            identification_status="pass",
            selected_for_interpretation=True,
        )

    audit = audit_trace(_trace(), max_treedepth=14)
    assert audit["mcmc_status"] == "pass"
    assert audit["identification_status"] == "not_assessed"
    assert audit["selected_for_interpretation"] is False


def test_summary_row_has_only_the_canonical_status_fields() -> None:
    audit = audit_trace(_trace(), max_treedepth=14, identification_status="not_required")
    row = summary_row(audit)

    assert row["fit_status"] == "success"
    assert row["mcmc_status"] == "pass"
    assert row["identification_status"] == "not_required"
    assert row["selected_for_interpretation"] is True
    assert "diagnostic_status" not in row
    assert "diagnostic_verdict" not in row

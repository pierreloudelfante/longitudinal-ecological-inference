"""Diagnostic MCMC V2 unique, complet et non destructif.

Ce module ne remplace pas les exports historiques. Il fournit une lecture
canonique d'une trace ArviZ existante avec :

* R-hat et ESS sur toutes les variables postérieures ;
* divergences, BFMI et saturation de ``max_treedepth`` ;
* un seul verdict officiel ``mcmc_status`` par trace ;
* des métriques descriptives par variable et par bloc, sans second verdict.

Les quatre notions qui étaient auparavant susceptibles d'être confondues sont
séparées : ``fit_status``, ``mcmc_status``, ``identification_status`` et
``selected_for_interpretation``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np


SCHEMA_VERSION = "mcmc_diagnostics_v2.0"
_SEVERITY = {"pass": 0, "caveat": 1, "fail": 2}
_IDENTIFICATION_STATUSES = {"pass", "caveat", "fail", "not_assessed", "not_required"}


@dataclass(frozen=True)
class DiagnosticThresholds:
    """Seuils du verdict officiel.

    Les seuils ``pass`` reprennent les exigences de production du projet.
    Les seuils ``fail`` distinguent un avertissement limité d'un problème
    diagnostique substantiel. Toute valeur située entre les deux est classée
    ``caveat``.
    """

    rhat_pass: float = 1.01
    rhat_fail: float = 1.05
    ess_bulk_pass: float = 400.0
    ess_bulk_fail: float = 100.0
    ess_tail_pass: float = 400.0
    ess_tail_fail: float = 100.0
    bfmi_pass: float = 0.30
    bfmi_fail: float = 0.20
    divergence_fraction_fail: float = 0.001
    treedepth_fraction_fail: float = 0.01

    def __post_init__(self) -> None:
        if not 1.0 < self.rhat_pass <= self.rhat_fail:
            raise ValueError("rhat thresholds must satisfy 1 < pass <= fail")
        if not 0 <= self.ess_bulk_fail <= self.ess_bulk_pass:
            raise ValueError("ESS bulk thresholds must satisfy 0 <= fail <= pass")
        if not 0 <= self.ess_tail_fail <= self.ess_tail_pass:
            raise ValueError("ESS tail thresholds must satisfy 0 <= fail <= pass")
        if not 0 <= self.bfmi_fail <= self.bfmi_pass:
            raise ValueError("BFMI thresholds must satisfy 0 <= fail <= pass")
        if not 0 <= self.divergence_fraction_fail <= 1:
            raise ValueError("divergence_fraction_fail must lie in [0, 1]")
        if not 0 <= self.treedepth_fraction_fail <= 1:
            raise ValueError("treedepth_fraction_fail must lie in [0, 1]")


def _finite_values(value: Any) -> np.ndarray:
    try:
        array = np.asarray(getattr(value, "values", value), dtype=float).ravel()
    except (TypeError, ValueError):
        return np.array([], dtype=float)
    return array[np.isfinite(array)]


def _posterior_block(variable_name: str) -> str:
    """Return a stable semantic block for the KRT/King posterior names."""

    normalized = variable_name.lower().replace("-", "_")
    if normalized in {"b_1", "b_2", "b1", "b2"}:
        return "latent_preferences"
    if normalized in {"c_1", "d_1", "c_2", "d_2", "c1", "d1", "c2", "d2"}:
        return "hyperparameters"
    return "other_posterior"


def _group(trace: Any, name: str) -> Any | None:
    """Read an ArviZ group across InferenceData and DataTree versions."""

    group = getattr(trace, name, None)
    if group is not None:
        return group
    try:
        return trace[name]
    except (KeyError, TypeError):
        return None


def _sample_stat(stats: Any | None, *names: str) -> Any | None:
    if stats is None:
        return None
    for name in names:
        try:
            if name in stats:
                return stats[name]
        except TypeError:
            pass
        try:
            return getattr(stats, name)
        except AttributeError:
            continue
    return None


def _inferred_max_treedepth(trace: Any, stats: Any | None) -> int | None:
    for source in (stats, trace):
        attrs = getattr(source, "attrs", {}) if source is not None else {}
        for name in ("max_treedepth", "max_tree_depth"):
            try:
                value = int(attrs[name])
            except (KeyError, TypeError, ValueError):
                continue
            if value > 0:
                return value
    return None


def _variable_metrics(posterior: Any) -> list[dict[str, Any]]:
    import arviz as az

    rows: list[dict[str, Any]] = []
    for name in sorted(str(item) for item in posterior.data_vars):
        variable = posterior[name]
        rhat = _finite_values(az.rhat(variable, method="rank"))
        ess_bulk = _finite_values(az.ess(variable, method="bulk"))
        ess_tail = _finite_values(az.ess(variable, method="tail"))
        parameter_dims = [dim for dim in variable.dims if dim not in {"chain", "draw"}]
        n_parameters = int(np.prod([int(variable.sizes[dim]) for dim in parameter_dims])) if parameter_dims else 1
        rows.append(
            {
                "variable": name,
                "block": _posterior_block(name),
                "n_parameters": n_parameters,
                "n_rhat_finite": int(rhat.size),
                "max_rhat": float(rhat.max()) if rhat.size else None,
                "n_ess_bulk_finite": int(ess_bulk.size),
                "min_ess_bulk": float(ess_bulk.min()) if ess_bulk.size else None,
                "n_ess_tail_finite": int(ess_tail.size),
                "min_ess_tail": float(ess_tail.min()) if ess_tail.size else None,
            }
        )
    return rows


def _minimum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None and np.isfinite(row[key])]
    return min(values) if values else None


def _maximum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None and np.isfinite(row[key])]
    return max(values) if values else None


def _block_metrics(variable_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blocks = sorted({str(row["block"]) for row in variable_rows})
    for block in blocks:
        members = [row for row in variable_rows if row["block"] == block]
        rows.append(
            {
                "block": block,
                "variables": [str(row["variable"]) for row in members],
                "n_variables": len(members),
                "n_parameters": sum(int(row["n_parameters"]) for row in members),
                "max_rhat": _maximum(members, "max_rhat"),
                "min_ess_bulk": _minimum(members, "min_ess_bulk"),
                "min_ess_tail": _minimum(members, "min_ess_tail"),
            }
        )
    return rows


def _criterion(name: str, status: str, reason: str, **metrics: Any) -> dict[str, Any]:
    if status not in _SEVERITY:
        raise ValueError(f"unknown criterion status: {status}")
    return {"criterion": name, "status": status, "reason": reason, **metrics}


def _upper_is_bad(
    name: str,
    value: float | None,
    *,
    pass_at: float,
    fail_above: float,
    missing_status: str = "fail",
) -> dict[str, Any]:
    if value is None or not np.isfinite(value):
        return _criterion(name, missing_status, f"{name}_unavailable", value=value)
    if value <= pass_at:
        return _criterion(name, "pass", "", value=value)
    if value > fail_above:
        return _criterion(name, "fail", f"{name}_above_fail_threshold", value=value)
    return _criterion(name, "caveat", f"{name}_above_pass_threshold", value=value)


def _lower_is_bad(
    name: str,
    value: float | None,
    *,
    pass_at: float,
    fail_below: float,
    missing_status: str = "fail",
) -> dict[str, Any]:
    if value is None or not np.isfinite(value):
        return _criterion(name, missing_status, f"{name}_unavailable", value=value)
    if value >= pass_at:
        return _criterion(name, "pass", "", value=value)
    if value < fail_below:
        return _criterion(name, "fail", f"{name}_below_fail_threshold", value=value)
    return _criterion(name, "caveat", f"{name}_below_pass_threshold", value=value)


def _load_trace(trace_or_path: Any) -> tuple[Any, str | None]:
    if isinstance(trace_or_path, (str, Path)):
        import arviz as az

        path = Path(trace_or_path)
        return az.from_netcdf(path), str(path)
    return trace_or_path, None


def audit_trace(
    trace_or_path: Any,
    *,
    fit_status: str = "success",
    identification_status: str = "not_assessed",
    expected_chains: int | None = None,
    expected_draws_per_chain: int | None = None,
    max_treedepth: int | None = None,
    thresholds: DiagnosticThresholds | None = None,
    selected_for_interpretation: bool | None = None,
) -> dict[str, Any]:
    """Audit one trace and return its single official MCMC verdict.

    ``variable_metrics`` and ``block_metrics`` are descriptive only. They do
    not carry an alternative verdict. ``identification_status`` is supplied by
    a separate identification analysis and is never inferred from convergence.
    """

    if identification_status not in _IDENTIFICATION_STATUSES:
        raise ValueError(
            "identification_status must be one of "
            + ", ".join(sorted(_IDENTIFICATION_STATUSES))
        )
    if expected_chains is not None and expected_chains < 1:
        raise ValueError("expected_chains must be positive")
    if expected_draws_per_chain is not None and expected_draws_per_chain < 1:
        raise ValueError("expected_draws_per_chain must be positive")
    if max_treedepth is not None and max_treedepth < 1:
        raise ValueError("max_treedepth must be positive")

    limits = thresholds or DiagnosticThresholds()
    trace, trace_path = _load_trace(trace_or_path)
    posterior = _group(trace, "posterior")
    if posterior is None or not list(getattr(posterior, "data_vars", [])):
        variable_rows: list[dict[str, Any]] = []
        chains = 0
        draws = 0
    else:
        chains = int(posterior.sizes.get("chain", 0))
        draws = int(posterior.sizes.get("draw", 0))
        variable_rows = _variable_metrics(posterior) if chains >= 2 and draws >= 4 else []

    block_rows = _block_metrics(variable_rows)
    max_rhat = _maximum(variable_rows, "max_rhat")
    min_ess_bulk = _minimum(variable_rows, "min_ess_bulk")
    min_ess_tail = _minimum(variable_rows, "min_ess_tail")
    all_rhat_available = bool(variable_rows) and all(
        int(row["n_rhat_finite"]) == int(row["n_parameters"]) for row in variable_rows
    )
    all_bulk_available = bool(variable_rows) and all(
        int(row["n_ess_bulk_finite"]) == int(row["n_parameters"]) for row in variable_rows
    )
    all_tail_available = bool(variable_rows) and all(
        int(row["n_ess_tail_finite"]) == int(row["n_parameters"]) for row in variable_rows
    )

    stats = _group(trace, "sample_stats")
    diverging = _finite_values(_sample_stat(stats, "diverging"))
    total_draws = max(chains * draws, 1)
    divergences = int(diverging.sum()) if diverging.size else None
    divergence_fraction = divergences / total_draws if divergences is not None else None

    energy = _sample_stat(stats, "energy")
    if energy is not None:
        import arviz as az

        bfmi_by_chain = _finite_values(az.bfmi(energy))
    else:
        bfmi_by_chain = np.array([], dtype=float)
    min_bfmi = float(bfmi_by_chain.min()) if bfmi_by_chain.size else None

    configured_max_treedepth = max_treedepth or _inferred_max_treedepth(trace, stats)
    reached_max = _sample_stat(stats, "reached_max_treedepth")
    tree_depth = _finite_values(_sample_stat(stats, "tree_depth", "depth"))
    if reached_max is not None:
        reached = _finite_values(reached_max)
        treedepth_hits = int(reached.sum()) if reached.size else None
    elif configured_max_treedepth is not None and tree_depth.size:
        treedepth_hits = int(np.sum(tree_depth >= configured_max_treedepth))
    else:
        treedepth_hits = None
    treedepth_fraction = treedepth_hits / total_draws if treedepth_hits is not None else None
    observed_max_treedepth = float(tree_depth.max()) if tree_depth.size else None

    acceptance = _finite_values(_sample_stat(stats, "acceptance_rate", "mean_tree_accept"))
    mean_acceptance_rate = float(acceptance.mean()) if acceptance.size else None

    criteria: list[dict[str, Any]] = []
    normalized_fit = fit_status.strip().lower()
    fit_ok = normalized_fit in {"success", "succeeded", "ok", "skipped_existing_success"}
    criteria.append(
        _criterion("fit", "pass" if fit_ok else "fail", "" if fit_ok else "fit_not_successful")
    )
    if posterior is None or not list(getattr(posterior, "data_vars", [])):
        criteria.append(_criterion("posterior", "fail", "posterior_unavailable"))
    elif chains < 2 or draws < 4:
        criteria.append(
            _criterion(
                "posterior",
                "fail",
                "insufficient_chain_or_draw_dimensions",
                chains=chains,
                draws_per_chain=draws,
            )
        )
    else:
        criteria.append(_criterion("posterior", "pass", ""))

    if expected_chains is not None:
        criteria.append(
            _criterion(
                "expected_chains",
                "pass" if chains == expected_chains else "fail",
                "" if chains == expected_chains else "saved_chains_mismatch",
                saved=chains,
                expected=expected_chains,
            )
        )
    if expected_draws_per_chain is not None:
        criteria.append(
            _criterion(
                "expected_draws_per_chain",
                "pass" if draws == expected_draws_per_chain else "fail",
                "" if draws == expected_draws_per_chain else "saved_draws_mismatch",
                saved=draws,
                expected=expected_draws_per_chain,
            )
        )

    rhat_criterion = _upper_is_bad(
        "max_rhat",
        max_rhat if all_rhat_available else None,
        pass_at=limits.rhat_pass,
        fail_above=limits.rhat_fail,
    )
    bulk_criterion = _lower_is_bad(
        "min_ess_bulk",
        min_ess_bulk if all_bulk_available else None,
        pass_at=limits.ess_bulk_pass,
        fail_below=limits.ess_bulk_fail,
    )
    tail_criterion = _lower_is_bad(
        "min_ess_tail",
        min_ess_tail if all_tail_available else None,
        pass_at=limits.ess_tail_pass,
        fail_below=limits.ess_tail_fail,
    )
    criteria.extend((rhat_criterion, bulk_criterion, tail_criterion))

    if divergence_fraction is None:
        criteria.append(_criterion("divergences", "caveat", "divergences_unavailable"))
    elif divergences == 0:
        criteria.append(_criterion("divergences", "pass", "", count=0, fraction=0.0))
    elif divergence_fraction > limits.divergence_fraction_fail:
        criteria.append(
            _criterion(
                "divergences",
                "fail",
                "divergence_fraction_above_fail_threshold",
                count=divergences,
                fraction=divergence_fraction,
            )
        )
    else:
        criteria.append(
            _criterion(
                "divergences",
                "caveat",
                "nonzero_divergences",
                count=divergences,
                fraction=divergence_fraction,
            )
        )

    criteria.append(
        _lower_is_bad(
            "min_bfmi",
            min_bfmi,
            pass_at=limits.bfmi_pass,
            fail_below=limits.bfmi_fail,
            missing_status="caveat",
        )
    )
    if treedepth_fraction is None:
        criteria.append(
            _criterion(
                "max_treedepth_saturation",
                "caveat",
                "max_treedepth_saturation_unavailable",
            )
        )
    elif treedepth_hits == 0:
        criteria.append(
            _criterion("max_treedepth_saturation", "pass", "", count=0, fraction=0.0)
        )
    elif treedepth_fraction > limits.treedepth_fraction_fail:
        criteria.append(
            _criterion(
                "max_treedepth_saturation",
                "fail",
                "treedepth_fraction_above_fail_threshold",
                count=treedepth_hits,
                fraction=treedepth_fraction,
            )
        )
    else:
        criteria.append(
            _criterion(
                "max_treedepth_saturation",
                "caveat",
                "nonzero_treedepth_saturation",
                count=treedepth_hits,
                fraction=treedepth_fraction,
            )
        )

    mcmc_status = max(criteria, key=lambda row: _SEVERITY[str(row["status"])])["status"]
    reasons = [str(row["reason"]) for row in criteria if row["status"] != "pass" and row["reason"]]
    eligible = (
        fit_ok
        and mcmc_status == "pass"
        and identification_status in {"pass", "not_required"}
    )
    if selected_for_interpretation is None:
        selected = eligible
    else:
        selected = bool(selected_for_interpretation)
        if selected and not eligible:
            raise ValueError(
                "a trace can be selected only when fit_status and mcmc_status pass "
                "and identification_status is pass or not_required"
            )

    return {
        "diagnostic_schema_version": SCHEMA_VERSION,
        "trace_path": trace_path,
        "fit_status": fit_status,
        "mcmc_status": mcmc_status,
        "mcmc_reasons": reasons,
        "identification_status": identification_status,
        "selected_for_interpretation": selected,
        "saved_chains": chains,
        "saved_draws_per_chain": draws,
        "posterior_variables": [str(row["variable"]) for row in variable_rows],
        "max_rhat": max_rhat,
        "min_ess_bulk": min_ess_bulk,
        "min_ess_tail": min_ess_tail,
        "divergences": divergences,
        "divergence_fraction": divergence_fraction,
        "bfmi_by_chain": bfmi_by_chain.tolist(),
        "min_bfmi": min_bfmi,
        "configured_max_treedepth": configured_max_treedepth,
        "observed_max_treedepth": observed_max_treedepth,
        "max_treedepth_hits": treedepth_hits,
        "max_treedepth_hit_fraction": treedepth_fraction,
        "mean_acceptance_rate": mean_acceptance_rate,
        "thresholds": asdict(limits),
        "criteria": criteria,
        "variable_metrics": variable_rows,
        "block_metrics": block_rows,
    }


def summary_row(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten the canonical fields for a CSV index without duplicate verdicts."""

    fields = (
        "diagnostic_schema_version",
        "trace_path",
        "fit_status",
        "mcmc_status",
        "identification_status",
        "selected_for_interpretation",
        "saved_chains",
        "saved_draws_per_chain",
        "max_rhat",
        "min_ess_bulk",
        "min_ess_tail",
        "divergences",
        "divergence_fraction",
        "min_bfmi",
        "configured_max_treedepth",
        "observed_max_treedepth",
        "max_treedepth_hits",
        "max_treedepth_hit_fraction",
        "mean_acceptance_rate",
    )
    row = {field: audit.get(field) for field in fields}
    row["mcmc_reasons"] = ";".join(str(value) for value in audit.get("mcmc_reasons", []))
    return row


__all__ = [
    "DiagnosticThresholds",
    "SCHEMA_VERSION",
    "audit_trace",
    "summary_row",
]

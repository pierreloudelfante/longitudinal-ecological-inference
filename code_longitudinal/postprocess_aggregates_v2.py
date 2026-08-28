"""Versioned, non-destructive KRT aggregate post-processing.

The historical PyEI export weights both precinct-level posterior probabilities
by the precinct total population.  For a group-conditional probability, the
estimand instead requires the population of that group as its denominator.
This module recomputes the aggregate at every posterior draw:

    group 1: sum_i(N1_i * b1_i) / sum_i(N1_i)
    group 2: sum_i(N2_i * b2_i) / sum_i(N2_i)

Nothing in this module writes to, or mutates, the historical run directories.
Callers can therefore build explicitly versioned V2 outputs alongside them.
"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_QUANTILES = (0.025, 0.50, 0.975)
SAMPLE_DIMS = ("chain", "draw")


def _validated_weights(weights: Any, expected_size: int) -> np.ndarray:
    values = np.asarray(weights, dtype=float)
    if values.ndim != 1:
        raise ValueError("group weights must be one-dimensional")
    if values.size != expected_size:
        raise ValueError(f"group weights contain {values.size} units; expected {expected_size}")
    if not np.isfinite(values).all():
        raise ValueError("group weights must all be finite")
    if np.any(values < 0):
        raise ValueError("group weights must be non-negative")
    if float(values.sum()) <= 0:
        raise ValueError("group weights must have a strictly positive sum")
    return values


def group_weighted_draws(
    beta_draws: Any,
    group_weights: Any,
    *,
    unit_axis: int = -1,
) -> np.ndarray:
    """Return group-population-weighted values for every posterior draw.

    This is the pure NumPy calculation used by the xarray/ArviZ adapter.  The
    unit axis may appear anywhere; all other axes are retained in their
    original order.
    """

    values = np.asarray(beta_draws, dtype=float)
    if values.ndim == 0:
        raise ValueError("beta_draws must include a unit axis")
    try:
        axis = operator.index(unit_axis)
    except TypeError as exc:
        raise ValueError(f"invalid unit_axis {unit_axis!r} for {values.ndim} dimensions") from exc
    if axis < 0:
        axis += values.ndim
    if axis < 0 or axis >= values.ndim:
        raise ValueError(f"invalid unit_axis {unit_axis!r} for {values.ndim} dimensions")
    weights = _validated_weights(group_weights, values.shape[axis])
    if not np.isfinite(values).all():
        raise ValueError("beta_draws must all be finite")
    if np.any((values < 0) | (values > 1)):
        raise ValueError("KRT beta draws must lie in [0, 1]")

    values_last = np.moveaxis(values, axis, -1)
    return np.sum(values_last * weights, axis=-1) / float(weights.sum())


def _posterior_group(trace_or_posterior: Any) -> Any:
    posterior = getattr(trace_or_posterior, "posterior", trace_or_posterior)
    if posterior is None or not hasattr(posterior, "__getitem__"):
        raise TypeError("expected an ArviZ InferenceData object or posterior xarray group")
    return posterior


def _infer_unit_dim(beta: xr.DataArray, *, sample_dims: Sequence[str]) -> str:
    unit_dims = [dim for dim in beta.dims if dim not in sample_dims]
    if len(unit_dims) != 1:
        raise ValueError(
            f"{beta.name or 'beta'} must have exactly one non-sample unit dimension; "
            f"found {unit_dims} among dimensions {list(beta.dims)}"
        )
    return unit_dims[0]


def _weight_data_array(beta: xr.DataArray, weights: Any, unit_dim: str) -> xr.DataArray:
    expected_size = int(beta.sizes[unit_dim])
    if isinstance(weights, xr.DataArray):
        if weights.ndim != 1:
            raise ValueError("xarray group weights must be one-dimensional")
        weight_dim = weights.dims[0]
        if weight_dim != unit_dim:
            weights = weights.rename({weight_dim: unit_dim})
        _validated_weights(weights.values, expected_size)
        if unit_dim in beta.coords and unit_dim in weights.coords:
            try:
                _, weights = xr.align(beta, weights, join="exact", copy=False)
            except ValueError as exc:
                raise ValueError(
                    f"weight coordinates do not exactly match posterior coordinates for {unit_dim}"
                ) from exc
        elif unit_dim in beta.coords:
            weights = weights.assign_coords({unit_dim: beta.coords[unit_dim]})
        return weights.astype(float)

    values = _validated_weights(weights, expected_size)
    coords = {unit_dim: beta.coords[unit_dim]} if unit_dim in beta.coords else None
    return xr.DataArray(values, dims=(unit_dim,), coords=coords)


def _group_weighted_data_array(
    beta: xr.DataArray,
    weights: Any,
    *,
    sample_dims: Sequence[str],
) -> xr.DataArray:
    unit_dim = _infer_unit_dim(beta, sample_dims=sample_dims)
    weight_array = _weight_data_array(beta, weights, unit_dim)
    # Validate probabilities before xarray applies coordinate-aware arithmetic.
    values = np.asarray(beta.values, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{beta.name or 'beta'} contains non-finite draws")
    if np.any((values < 0) | (values > 1)):
        raise ValueError(f"{beta.name or 'beta'} contains values outside [0, 1]")
    result = (beta * weight_array).sum(dim=unit_dim) / weight_array.sum(dim=unit_dim)
    return result.astype(float)


def aggregate_krt_draws_v2(
    trace_or_posterior: Any,
    b1_weights: Any,
    b2_weights: Any,
    *,
    total_weights: Any | None = None,
    include_contrast: bool = False,
    sample_dims: Sequence[str] = SAMPLE_DIMS,
) -> xr.Dataset:
    """Compute corrected KRT aggregates, optionally beside legacy aggregates.

    ``trace_or_posterior`` may be an ArviZ ``InferenceData`` object, its
    posterior group, or an xarray ``Dataset`` containing ``b_1`` and ``b_2``.
    Variable-specific unit dimension names (for example ``b_1_dim_0`` and
    ``b_2_dim_0``) are supported and inferred independently.

    When ``total_weights`` is provided, the returned dataset also contains the
    historical total-population-weighted draw series.  Those variables exist
    only for an auditable comparison; they are not the corrected estimand.
    """

    posterior = _posterior_group(trace_or_posterior)
    missing = [name for name in ("b_1", "b_2") if name not in posterior]
    if missing:
        raise ValueError(f"posterior is missing required variables: {', '.join(missing)}")

    corrected: dict[str, xr.DataArray] = {}
    for beta_name, weights in (("b_1", b1_weights), ("b_2", b2_weights)):
        beta = posterior[beta_name]
        if not isinstance(beta, xr.DataArray):
            raise TypeError(f"posterior variable {beta_name} is not an xarray DataArray")
        corrected[f"{beta_name}_group_weighted"] = _group_weighted_data_array(
            beta, weights, sample_dims=sample_dims
        )
        if total_weights is not None:
            corrected[f"{beta_name}_legacy_total_weighted"] = _group_weighted_data_array(
                beta, total_weights, sample_dims=sample_dims
            )

    if include_contrast:
        corrected["b_1_minus_b_2_group_weighted"] = (
            corrected["b_1_group_weighted"] - corrected["b_2_group_weighted"]
        ).astype(float)
        if total_weights is not None:
            corrected["b_1_minus_b_2_legacy_total_weighted"] = (
                corrected["b_1_legacy_total_weighted"]
                - corrected["b_2_legacy_total_weighted"]
            ).astype(float)

    dataset = xr.Dataset(corrected)
    dataset.attrs.update(
        {
            "postprocessing_version": "2",
            "corrected_estimand_b_1": "sum_i(N1_i*b1_i)/sum_i(N1_i)",
            "corrected_estimand_b_2": "sum_i(N2_i*b2_i)/sum_i(N2_i)",
            "contrast_estimand": "corrected_b_1_group_aggregate - corrected_b_2_group_aggregate",
            "contrast_included": bool(include_contrast),
            "legacy_comparison_included": bool(total_weights is not None),
        }
    )
    return dataset


def _quantile_column(probability: float) -> str:
    known = {0.025: "q025", 0.50: "q50", 0.975: "q975"}
    for value, label in known.items():
        if np.isclose(probability, value):
            return label
    text = f"{probability:.6f}".rstrip("0").rstrip(".").replace(".", "_")
    return f"q_{text}"


def summarize_krt_aggregates_v2(
    aggregate_draws: xr.Dataset,
    *,
    quantiles: Iterable[float] = DEFAULT_QUANTILES,
) -> pd.DataFrame:
    """Summarize corrected and optional legacy aggregate draw series."""

    probabilities = tuple(float(value) for value in quantiles)
    if not probabilities or any(value < 0 or value > 1 for value in probabilities):
        raise ValueError("quantiles must be a non-empty collection of probabilities in [0, 1]")

    rows: list[dict[str, object]] = []
    for variable_name, data_array in aggregate_draws.data_vars.items():
        extra_dims = [dim for dim in data_array.dims if dim not in SAMPLE_DIMS]
        if extra_dims:
            raise ValueError(f"aggregate variable {variable_name} still has non-sample dimensions: {extra_dims}")
        values = np.asarray(data_array.values, dtype=float).reshape(-1)
        if values.size == 0 or not np.isfinite(values).all():
            raise ValueError(f"aggregate variable {variable_name} has no finite posterior draws")
        if variable_name.startswith("b_1_minus_b_2_"):
            beta_parameter = "b_1_minus_b_2"
        elif variable_name.startswith("b_1_"):
            beta_parameter = "b_1"
        elif variable_name.startswith("b_2_"):
            beta_parameter = "b_2"
        else:
            raise ValueError(f"unrecognized aggregate variable name: {variable_name}")
        is_legacy = variable_name.endswith("_legacy_total_weighted")
        row: dict[str, object] = {
            "beta_parameter": beta_parameter,
            "aggregation_method": "legacy_total_population" if is_legacy else "group_specific_population_v2",
            "weight_basis": (
                "N_total"
                if is_legacy
                else "N1"
                if beta_parameter == "b_1"
                else "N2"
                if beta_parameter == "b_2"
                else "group_specific_population_v2"
            ),
            "mean": float(values.mean()),
            "n_posterior_draws": int(values.size),
        }
        for probability, value in zip(probabilities, np.quantile(values, probabilities)):
            row[_quantile_column(probability)] = float(value)
        rows.append(row)

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    legacy_mean = (
        summary.loc[summary["aggregation_method"].eq("legacy_total_population")]
        .set_index("beta_parameter")["mean"]
        .to_dict()
    )
    summary["legacy_mean"] = summary["beta_parameter"].map(legacy_mean)
    summary["mean_difference_from_legacy"] = summary["mean"] - summary["legacy_mean"]
    return summary


def aggregate_krt_trace_files_v2(
    trace_path: Path | str,
    latent_summaries_path: Path | str,
    *,
    include_legacy_comparison: bool = True,
    include_contrast: bool = False,
) -> xr.Dataset:
    """Load one historical KRT trace and recompute its V2 aggregate draws.

    The latent summary rows were created in the exact precinct order used by
    PyEI.  Because historical traces expose positional precinct coordinates
    rather than commune identifiers, this adapter deliberately preserves file
    row order and rejects duplicate or non-increasing ``sample_rank`` values.
    """

    trace_path = Path(trace_path)
    latent_summaries_path = Path(latent_summaries_path)
    if latent_summaries_path.suffix.lower() == ".parquet":
        latent = pd.read_parquet(latent_summaries_path)
    elif latent_summaries_path.suffix.lower() == ".csv":
        latent = pd.read_csv(latent_summaries_path)
    else:
        raise ValueError("latent summaries must be a .parquet or .csv file")
    required = {"b1_weight", "b2_weight"}
    missing = sorted(required.difference(latent.columns))
    if missing:
        raise ValueError(f"latent summaries are missing columns: {', '.join(missing)}")
    if "unit_id" in latent and latent["unit_id"].astype(str).duplicated().any():
        raise ValueError("latent summaries contain duplicate unit_id values")
    if "sample_rank" in latent:
        ranks = pd.to_numeric(latent["sample_rank"], errors="raise")
        if ranks.duplicated().any() or not ranks.is_monotonic_increasing:
            raise ValueError("latent summary rows must have unique, increasing sample_rank values")

    try:
        import arviz as az
    except ImportError as exc:  # pragma: no cover - the production environment includes ArviZ
        raise RuntimeError("ArviZ is required to load a NetCDF trace") from exc
    trace = az.from_netcdf(trace_path)
    b1_weights = pd.to_numeric(latent["b1_weight"], errors="raise").to_numpy(dtype=float)
    b2_weights = pd.to_numeric(latent["b2_weight"], errors="raise").to_numpy(dtype=float)
    total_weights = b1_weights + b2_weights if include_legacy_comparison else None
    dataset = aggregate_krt_draws_v2(
        trace,
        b1_weights,
        b2_weights,
        total_weights=total_weights,
        include_contrast=include_contrast,
    )
    dataset.attrs.update(
        {
            "source_trace": str(trace_path),
            "source_latent_summaries": str(latent_summaries_path),
            "unit_alignment": "positional_historical_trace_order_checked_by_sample_rank",
        }
    )
    return dataset


__all__ = [
    "DEFAULT_QUANTILES",
    "aggregate_krt_draws_v2",
    "aggregate_krt_trace_files_v2",
    "group_weighted_draws",
    "summarize_krt_aggregates_v2",
]

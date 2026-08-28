from __future__ import annotations

"""Non-destructive posterior predictive checks for KRT 2x2 fits.

The KRT model fitted by :mod:`code_longitudinal.run_2x2_batch` uses, for
commune ``i`` and posterior draw ``s``,

``theta[s, i] = (N1[i] * b1[s, i] + N2[i] * b2[s, i]) / N[i]``

and the observed first-category count follows ``Binomial(N[i], theta[s, i])``.
The mapping from a saved trace to the model-ready rows is verified using all
available provenance: the input path and SHA256 in ``manifest.json``, the
ordered commune identifiers in ``commune_latent_summaries.csv``, the saved
latent posterior means, and ``observed_data/votes_count`` in ``trace.nc``.

This module only writes to explicitly supplied V2 directories. It never edits
historical run directories, tables, figures, or manifests.
"""

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .prepare_inputs import n_columns, y_columns
from .spec_registry import SCENARIO_BY_ID
from .utils import file_sha256


DEFAULT_MAX_DRAWS = 4_000
DEFAULT_SEED = 20260804


@dataclass(frozen=True)
class KrtPpcInputs:
    run_id: str
    election_id: str
    scenario_id: str
    unit_ids: np.ndarray
    group1_counts: np.ndarray
    group2_counts: np.ndarray
    observed_counts: np.ndarray
    input_observed_counts: np.ndarray
    trace_input_count_mismatch_count: int
    trace_input_count_max_abs_difference: int
    trace_input_count_total_difference: int
    b1_draws: np.ndarray
    b2_draws: np.ndarray
    posterior_draws_available: int
    input_path: Path
    trace_path: Path


def _as_draw_matrix(values: Any, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim < 2:
        raise ValueError(f"{name} must have at least draw and commune dimensions")
    matrix = array.reshape((-1, array.shape[-1]))
    if not np.isfinite(matrix).all():
        raise ValueError(f"{name} contains non-finite values")
    if ((matrix < 0) | (matrix > 1)).any():
        raise ValueError(f"{name} must lie in [0, 1]")
    return matrix


def _as_count_vector(values: Any, *, name: str, length: int | None = None) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if length is not None and len(array) != length:
        raise ValueError(f"{name} has {len(array)} communes, expected {length}")
    if not np.isfinite(array).all() or (array < 0).any():
        raise ValueError(f"{name} must contain finite non-negative counts")
    if not np.allclose(array, np.rint(array), atol=1e-8, rtol=0):
        raise ValueError(f"{name} must contain integer counts")
    return np.rint(array).astype(np.int64)


def expected_vote_share_draws(
    b1_draws: Any,
    b2_draws: Any,
    group1_counts: Any,
    group2_counts: Any,
) -> np.ndarray:
    """Return draw-wise expected first-category vote shares by commune.

    The first two dimensions of PyMC output (chain and draw) are flattened.
    Commune order is always the final dimension.
    """

    b1 = _as_draw_matrix(b1_draws, name="b1_draws")
    b2 = _as_draw_matrix(b2_draws, name="b2_draws")
    if b1.shape != b2.shape:
        raise ValueError(f"b1_draws and b2_draws have different shapes: {b1.shape} vs {b2.shape}")
    n_communes = b1.shape[1]
    n1 = _as_count_vector(group1_counts, name="group1_counts", length=n_communes)
    n2 = _as_count_vector(group2_counts, name="group2_counts", length=n_communes)
    total = n1 + n2
    if (total <= 0).any():
        raise ValueError("every commune must have a strictly positive total count")
    return (b1 * n1[None, :] + b2 * n2[None, :]) / total[None, :]


def simulate_vote_counts(
    expected_shares: Any,
    total_counts: Any,
    *,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """Generate one Binomial posterior-predictive replicate per posterior draw."""

    theta = _as_draw_matrix(expected_shares, name="expected_shares")
    totals = _as_count_vector(total_counts, name="total_counts", length=theta.shape[1])
    if (totals <= 0).any():
        raise ValueError("every commune must have a strictly positive total count")
    rng = np.random.default_rng(seed)
    return rng.binomial(totals[None, :], theta).astype(np.int64)


def posterior_predictive_metrics(
    expected_shares: Any,
    replicated_counts: Any,
    observed_counts: Any,
    total_counts: Any,
    *,
    interval: float = 0.95,
) -> tuple[dict[str, float | int | bool], pd.DataFrame, np.ndarray]:
    """Calculate PPC metrics, commune summaries, and aggregate replicated shares.

    ``mean_error``, ``rmse`` and ``mae`` compare the observed share with the
    posterior mean of ``theta``. ``precinct_coverage`` is the fraction of
    observed commune shares inside the posterior-predictive interval. The
    Bayesian p-value uses the upper tail of a Pearson discrepancy,
    ``P(T(y_rep, theta) >= T(y_obs, theta) | y)``.
    """

    if not 0 < interval < 1:
        raise ValueError("interval must lie strictly between 0 and 1")
    theta = _as_draw_matrix(expected_shares, name="expected_shares")
    y_rep = np.asarray(replicated_counts)
    if y_rep.shape != theta.shape:
        raise ValueError(f"replicated_counts has shape {y_rep.shape}, expected {theta.shape}")
    if not np.isfinite(y_rep).all() or (y_rep < 0).any():
        raise ValueError("replicated_counts must contain finite non-negative counts")
    totals = _as_count_vector(total_counts, name="total_counts", length=theta.shape[1])
    observed = _as_count_vector(observed_counts, name="observed_counts", length=theta.shape[1])
    if (totals <= 0).any():
        raise ValueError("every commune must have a strictly positive total count")
    if (observed > totals).any() or (y_rep > totals[None, :]).any():
        raise ValueError("observed and replicated counts cannot exceed total counts")

    alpha = (1 - interval) / 2
    observed_share = observed / totals
    predicted_mean = theta.mean(axis=0)
    replicated_share = y_rep / totals[None, :]
    ppc_lower, ppc_median, ppc_upper = np.quantile(
        replicated_share, [alpha, 0.5, 1 - alpha], axis=0
    )
    theta_lower, theta_median, theta_upper = np.quantile(
        theta, [alpha, 0.5, 1 - alpha], axis=0
    )
    error = predicted_mean - observed_share
    covered = (observed_share >= ppc_lower) & (observed_share <= ppc_upper)

    total_population = int(totals.sum())
    aggregate_replicated = y_rep.sum(axis=1) / total_population
    aggregate_observed = float(observed.sum() / total_population)
    aggregate_expected = (theta * totals[None, :]).sum(axis=1) / total_population
    agg_lower, agg_median, agg_upper = np.quantile(
        aggregate_replicated, [alpha, 0.5, 1 - alpha]
    )

    # Pearson discrepancy conditional on each posterior theta draw. Clipping
    # protects only the variance denominator at the exact 0/1 boundaries.
    probability = np.clip(theta, 1e-12, 1 - 1e-12)
    expected_count = totals[None, :] * probability
    variance = np.maximum(totals[None, :] * probability * (1 - probability), 1e-12)
    observed_discrepancy = np.sum((observed[None, :] - expected_count) ** 2 / variance, axis=1)
    replicated_discrepancy = np.sum((y_rep - expected_count) ** 2 / variance, axis=1)
    bayesian_p = float(np.mean(replicated_discrepancy >= observed_discrepancy))

    metrics: dict[str, float | int | bool] = {
        "posterior_draws_used": int(theta.shape[0]),
        "n_communes": int(theta.shape[1]),
        "total_count": total_population,
        "mean_error": float(error.mean()),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mae": float(np.mean(np.abs(error))),
        "weighted_mean_error": float(aggregate_expected.mean() - aggregate_observed),
        "precinct_coverage": float(covered.mean()),
        "aggregate_observed_share": aggregate_observed,
        "aggregate_predicted_mean": float(aggregate_expected.mean()),
        "aggregate_ppc_lower": float(agg_lower),
        "aggregate_ppc_median": float(agg_median),
        "aggregate_ppc_upper": float(agg_upper),
        "aggregate_covered": bool(agg_lower <= aggregate_observed <= agg_upper),
        "bayesian_p_value_pearson_upper_tail": bayesian_p,
        "interval_probability": float(interval),
    }
    commune = pd.DataFrame(
        {
            "observed_share": observed_share,
            "predicted_mean": predicted_mean,
            "theta_lower": theta_lower,
            "theta_median": theta_median,
            "theta_upper": theta_upper,
            "ppc_lower": ppc_lower,
            "ppc_median": ppc_median,
            "ppc_upper": ppc_upper,
            "error": error,
            "covered": covered,
            "total_count": totals,
            "observed_count": observed,
        }
    )
    return metrics, commune, aggregate_replicated


def _dataset(trace: Any, group: str) -> Any:
    node = getattr(trace, group, None)
    if node is None:
        raise ValueError(f"trace group {group!r} is missing")
    return getattr(node, "dataset", node)


def _resolve_model_input(root: Path, manifest: dict[str, Any]) -> tuple[Path, str]:
    input_hashes = manifest.get("input_sha256", {})
    if not isinstance(input_hashes, dict):
        raise ValueError("manifest input_sha256 is missing or invalid")
    candidates = [(Path(raw), str(digest)) for raw, digest in input_hashes.items() if str(raw).endswith(".parquet")]
    if len(candidates) != 1:
        raise ValueError(f"expected one model-ready parquet in manifest input_sha256, found {len(candidates)}")
    path, expected_hash = candidates[0]
    if not path.exists():
        fallback = root / "outputs" / "model_ready" / path.name
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(f"model-ready input not found: {path}")
    actual_hash = file_sha256(path)
    if actual_hash != expected_hash:
        raise ValueError(f"model-ready input SHA256 mismatch for {path}")
    return path, actual_hash


def _select_draws(b1: np.ndarray, b2: np.ndarray, max_draws: int | None) -> tuple[np.ndarray, np.ndarray]:
    available = b1.shape[0]
    if max_draws is None or max_draws >= available:
        return b1, b2
    if max_draws <= 0:
        raise ValueError("max_draws must be positive or None")
    indices = np.linspace(0, available - 1, num=max_draws, dtype=int)
    return b1[indices], b2[indices]


def load_krt_ppc_inputs(
    root: Path,
    run_id: str,
    *,
    max_draws: int | None = DEFAULT_MAX_DRAWS,
) -> KrtPpcInputs:
    """Load and provenance-check one existing successful KRT run."""

    root = Path(root).resolve()
    run_dir = root / "outputs" / "runs" / run_id
    manifest_path = run_dir / "manifest.json"
    trace_path = run_dir / "trace.nc"
    if not manifest_path.exists() or not trace_path.exists():
        raise FileNotFoundError(f"run {run_id} lacks manifest.json or trace.nc")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parameters = manifest.get("parameters", {})
    if manifest.get("status") != "success":
        raise ValueError(f"run {run_id} is not successful")
    if parameters.get("model_key") != "krt_beta_binomial":
        raise ValueError(f"run {run_id} is not a krt_beta_binomial fit")
    election_id = str(parameters.get("election_id", manifest.get("election_id", "")))
    scenario_id = str(parameters.get("scenario_id", manifest.get("scenario_id", "")))
    scenario = SCENARIO_BY_ID.get(scenario_id)
    if scenario is None or scenario.model_family != "2x2":
        raise ValueError(f"unknown or non-2x2 scenario: {scenario_id}")

    input_path, _ = _resolve_model_input(root, manifest)
    frame = pd.read_parquet(input_path)
    required_columns = ["unit_id", "N_g", *n_columns(scenario), y_columns(scenario)[0]]
    missing = [column for column in required_columns if column not in frame]
    if missing:
        raise ValueError(f"model-ready input is missing columns: {missing}")

    import arviz as az

    trace = az.from_netcdf(trace_path)
    posterior = _dataset(trace, "posterior")
    if "b_1" not in posterior or "b_2" not in posterior:
        raise ValueError("trace posterior lacks b_1 or b_2")
    b1_all = _as_draw_matrix(posterior["b_1"].values, name="b_1")
    b2_all = _as_draw_matrix(posterior["b_2"].values, name="b_2")
    if b1_all.shape != b2_all.shape:
        raise ValueError("trace b_1 and b_2 shapes differ")
    if len(frame) != b1_all.shape[1]:
        raise ValueError(f"trace has {b1_all.shape[1]} communes but input has {len(frame)}")

    # The latent export is written from the same in-memory fit_frame used for
    # sampling. It therefore provides the authoritative trace-to-unit order.
    latent_path = run_dir / "commune_latent_summaries.csv"
    if not latent_path.exists():
        raise FileNotFoundError(
            f"ordered latent export is required to verify trace-to-commune mapping: {latent_path}"
        )
    latent = pd.read_csv(latent_path, dtype={"unit_id": "string"})
    if len(latent) != b1_all.shape[1] or latent["unit_id"].duplicated().any():
        raise ValueError("latent export cannot identify a unique unit for each trace position")
    frame = frame.copy()
    frame["unit_id"] = frame["unit_id"].astype("string")
    if frame["unit_id"].duplicated().any():
        raise ValueError("model-ready input has duplicate unit_id values")
    by_unit = frame.set_index("unit_id", drop=False)
    ordered_ids = latent["unit_id"].astype("string").tolist()
    missing_ids = [unit_id for unit_id in ordered_ids if unit_id not in by_unit.index]
    if missing_ids:
        raise ValueError(f"latent export contains units absent from model input: {missing_ids[:5]}")
    frame = by_unit.loc[ordered_ids].reset_index(drop=True)
    if not np.allclose(b1_all.mean(axis=0), latent["b1_mean"].to_numpy(float), atol=1e-10, rtol=1e-8):
        raise ValueError("b_1 posterior means do not match the ordered latent export")
    if not np.allclose(b2_all.mean(axis=0), latent["b2_mean"].to_numpy(float), atol=1e-10, rtol=1e-8):
        raise ValueError("b_2 posterior means do not match the ordered latent export")

    n1 = _as_count_vector(frame[n_columns(scenario)[0]], name="group1_counts")
    n2 = _as_count_vector(frame[n_columns(scenario)[1]], name="group2_counts", length=len(frame))
    totals = _as_count_vector(frame["N_g"], name="total_counts", length=len(frame))
    if not np.array_equal(n1 + n2, totals):
        raise ValueError("social group counts do not sum to N_g")
    input_observed = _as_count_vector(frame[y_columns(scenario)[0]], name="observed_counts", length=len(frame))
    observed_data = _dataset(trace, "observed_data")
    if "votes_count" not in observed_data:
        raise ValueError("trace observed_data lacks votes_count")
    trace_observed = _as_count_vector(observed_data["votes_count"].values, name="trace votes_count")
    count_difference = trace_observed - input_observed
    # PyEI reconstructs the count as (integer / N) * N. A binary floating
    # round trip can land just below the integer and the observed Binomial
    # variable then stores one vote less. Existing traces cannot be changed;
    # accept only that precisely bounded legacy discrepancy and expose it in
    # every V2 output. Larger differences remain a hard mapping failure.
    if np.max(np.abs(count_difference), initial=0) > 1:
        raise ValueError("trace observed counts differ materially from the ordered model-ready input")

    b1, b2 = _select_draws(b1_all, b2_all, max_draws)
    return KrtPpcInputs(
        run_id=run_id,
        election_id=election_id,
        scenario_id=scenario_id,
        unit_ids=frame["unit_id"].astype(str).to_numpy(),
        group1_counts=n1,
        group2_counts=n2,
        observed_counts=trace_observed,
        input_observed_counts=input_observed,
        trace_input_count_mismatch_count=int(np.count_nonzero(count_difference)),
        trace_input_count_max_abs_difference=int(np.max(np.abs(count_difference), initial=0)),
        trace_input_count_total_difference=int(count_difference.sum()),
        b1_draws=b1,
        b2_draws=b2,
        posterior_draws_available=int(b1_all.shape[0]),
        input_path=input_path,
        trace_path=trace_path,
    )


def build_ppc_figure(
    commune: pd.DataFrame,
    aggregate_replicated: np.ndarray,
    metrics: dict[str, Any],
    *,
    title: str,
    subtitle: str,
    output_stem: Path,
) -> None:
    """Render a compact four-panel PPC diagnostic figure as PNG and SVG."""

    import matplotlib.pyplot as plt

    blue = "#2F6B9A"
    gold = "#D5A43B"
    ink = "#1F2933"
    quiet = "#D9E0E6"
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.5))
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.08, top=0.84, hspace=0.34, wspace=0.24)

    observed = commune["observed_share"].to_numpy(float)
    predicted = commune["predicted_mean"].to_numpy(float)
    limits = (0.0, 1.0)
    axes[0, 0].scatter(observed, predicted, s=18, facecolors="none", edgecolors=blue, alpha=0.55, linewidths=0.8)
    axes[0, 0].plot(limits, limits, color=ink, linewidth=1.1, linestyle="--")
    axes[0, 0].set(xlim=limits, ylim=limits, xlabel="Part observée", ylabel="Part prédite moyenne", title="Observé et prédit")

    calibration = commune.assign(bin=pd.qcut(predicted, q=min(10, len(commune)), duplicates="drop"))
    calibration = calibration.groupby("bin", observed=False).agg(
        predicted_mean=("predicted_mean", "mean"), observed_mean=("observed_share", "mean"), n=("observed_share", "size")
    )
    axes[0, 1].plot(limits, limits, color=ink, linewidth=1.1, linestyle="--")
    axes[0, 1].scatter(
        calibration["predicted_mean"], calibration["observed_mean"],
        s=22 + 2 * calibration["n"], facecolors=gold, edgecolors=ink, linewidths=0.7, alpha=0.85,
    )
    axes[0, 1].set(xlim=limits, ylim=limits, xlabel="Part prédite moyenne", ylabel="Part observée moyenne", title="Calibration par décile")

    axes[1, 0].scatter(predicted, commune["error"], s=18, facecolors="none", edgecolors=blue, alpha=0.55, linewidths=0.8)
    axes[1, 0].axhline(0, color=ink, linewidth=1.1, linestyle="--")
    axes[1, 0].set(xlabel="Part prédite moyenne", ylabel="Prédit − observé", title="Résidus communaux")

    axes[1, 1].hist(aggregate_replicated, bins=30, color=gold, edgecolor=ink, linewidth=0.5, alpha=0.8)
    axes[1, 1].axvline(metrics["aggregate_observed_share"], color=ink, linewidth=1.5, linestyle="--", label="Observé")
    axes[1, 1].set(xlabel="Part agrégée répliquée", ylabel="Nombre de tirages", title="Distribution prédictive agrégée")
    axes[1, 1].legend(frameon=False, loc="upper left")

    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="both", color=quiet, linewidth=0.6, alpha=0.65)
        ax.set_axisbelow(True)
    fig.suptitle(title, y=0.975, fontsize=15, color=ink, fontweight="semibold")
    fig.text(0.5, 0.925, subtitle, ha="center", va="top", fontsize=9.5, color="#52606D")
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=180, facecolor="white")
    fig.savefig(output_stem.with_suffix(".svg"), facecolor="white")
    plt.close(fig)


def run_ppc_for_run(
    root: Path,
    run_id: str,
    *,
    output_dir: Path,
    figure_dir: Path,
    max_draws: int | None = DEFAULT_MAX_DRAWS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Validate, compute, and export PPC V2 outputs for one existing run."""

    inputs = load_krt_ppc_inputs(root, run_id, max_draws=max_draws)
    theta = expected_vote_share_draws(
        inputs.b1_draws, inputs.b2_draws, inputs.group1_counts, inputs.group2_counts
    )
    run_seed = seed ^ int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16)
    totals = inputs.group1_counts + inputs.group2_counts
    replicated = simulate_vote_counts(theta, totals, seed=run_seed)
    metrics, commune, aggregate_replicated = posterior_predictive_metrics(
        theta, replicated, inputs.observed_counts, totals
    )
    metadata: dict[str, Any] = {
        "run_id": run_id,
        "election_id": inputs.election_id,
        "scenario_id": inputs.scenario_id,
        "model_key": "krt_beta_binomial",
        "posterior_draws_available": inputs.posterior_draws_available,
        "ppc_seed": run_seed,
        "model_input_path": str(inputs.input_path),
        "trace_path": str(inputs.trace_path),
        "observed_count_basis": "trace observed_data/votes_count (actual fitted counts)",
        "trace_input_count_mismatch_count": inputs.trace_input_count_mismatch_count,
        "trace_input_count_max_abs_difference": inputs.trace_input_count_max_abs_difference,
        "trace_input_count_total_difference": inputs.trace_input_count_total_difference,
        "metric_definition": "posterior predictive Binomial(N_g, theta), theta=(N1*b1+N2*b2)/N_g",
        "bayesian_p_value_definition": "P(Pearson_T(y_rep,theta) >= Pearson_T(y_obs,theta) | y)",
        **metrics,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    commune.insert(0, "unit_id", inputs.unit_ids)
    commune.insert(commune.columns.get_loc("observed_count") + 1, "input_observed_count", inputs.input_observed_counts)
    commune.insert(commune.columns.get_loc("observed_share") + 1, "input_observed_share", inputs.input_observed_counts / totals)
    commune.insert(0, "scenario_id", inputs.scenario_id)
    commune.insert(0, "election_id", inputs.election_id)
    commune.insert(0, "run_id", run_id)
    commune.to_csv(output_dir / f"{run_id}__communes.csv", index=False, encoding="utf-8-sig")
    (output_dir / f"{run_id}__metrics.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    build_ppc_figure(
        commune,
        aggregate_replicated,
        metadata,
        title="Contrôle prédictif postérieur KRT",
        subtitle=(
            f"{inputs.election_id} · {inputs.scenario_id} · n={len(inputs.unit_ids)} communes · "
            f"{theta.shape[0]} tirages postérieurs"
        ),
        output_stem=figure_dir / f"{run_id}__ppc_krt_v2",
    )
    return metadata


def _priority_run_ids(root: Path, index_path: Path) -> list[str]:
    path = index_path if index_path.is_absolute() else root / index_path
    table = pd.read_csv(path)
    required = {"run_id", "model_key", "fit_status"}
    if not required.issubset(table.columns):
        raise ValueError(f"priority index lacks columns: {sorted(required - set(table.columns))}")
    selected = table.loc[
        table["model_key"].eq("krt_beta_binomial") & table["fit_status"].eq("success"), "run_id"
    ].astype(str)
    return list(dict.fromkeys(selected))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Non-destructive KRT posterior predictive checks (V2).")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-id", action="append", default=[], help="Existing successful KRT run id; repeatable.")
    parser.add_argument("--priority-all", action="store_true", help="Use successful KRT runs in priority_best_runs.csv.")
    parser.add_argument("--priority-index", type=Path, default=Path("outputs/priority_best_runs.csv"))
    parser.add_argument("--max-draws", type=int, default=DEFAULT_MAX_DRAWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/v2/ppc_krt"))
    parser.add_argument("--figure-dir", type=Path, default=Path("figures/v2/ppc_krt"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()
    run_ids = list(args.run_id)
    if args.priority_all:
        run_ids.extend(_priority_run_ids(root, args.priority_index))
    run_ids = list(dict.fromkeys(run_ids))
    if not run_ids:
        parser.error("provide at least one --run-id or use --priority-all")
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    figure_dir = args.figure_dir if args.figure_dir.is_absolute() else root / args.figure_dir
    rows = [
        run_ppc_for_run(
            root,
            run_id,
            output_dir=output_dir,
            figure_dir=figure_dir,
            max_draws=args.max_draws,
            seed=args.seed,
        )
        for run_id in run_ids
    ]
    pd.DataFrame(rows).to_csv(output_dir / "ppc_metrics.csv", index=False, encoding="utf-8-sig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

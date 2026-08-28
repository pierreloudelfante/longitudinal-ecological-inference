from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import arviz as az
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .build_panel import load_settings
from .nls import NLSData, aggregate_probabilities, fit_nls, probabilities
from .paths import CONFIG_DIR, OUTPUT_DIR, PANEL_DIR, ROOT, RUNS_DIR
from .postprocess_aggregates_v2 import aggregate_krt_trace_files_v2
from .prepare_inputs import n_columns, prepare_model_ready, x_columns, y_columns
from .run_2x2_batch import run_2x2
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import file_sha256, write_json


RELEASE_ROOT = ROOT / "work" / "longitudinal_2000_v1.0.1_H0A_H1_candidate"
AUDIT_DIR = RELEASE_ROOT / "03_panel_et_audit"
SYNTHESIS_DIR = RELEASE_ROOT / "02_syntheses"
FIGURE_DIR = RELEASE_ROOT / "04_figures_essentielles"
AUX_DIR = RELEASE_ROOT / "07_auxiliary_runs" / "h1_panel_sensitivity"
PANEL_RUNTIME_DIR = AUX_DIR / "runtime_panels"

ELECTION_IDS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
SCENARIO = SCENARIO_BY_ID["H1"]
MODEL_KEY = "krt_beta_binomial"

LEGACY_RUNS = {
    "leg_1962_r1": "20260804T150252Z__2df1cacde040",
    "leg_1986_r1": "20260804T161211Z__6719825c1e9a",
    "leg_2022_r1": "20260804T163742Z__1cc94b3f41d5",
}
PRIMARY_RUNS = {
    "leg_1962_r1": "20260811T201058Z__3cb4b61aed7b",
    "leg_1986_r1": "20260811T203720Z__a2b0b18f9a93",
    "leg_2022_r1": "20260811T205629Z__0f28ce7fbb0a",
}

CELL_LABELS = {
    "cell_1_legacy_v2_3000_old_pipeline": "V2 3 000 × ancien pipeline",
    "cell_2_legacy_v2_3000_current_pipeline": "V2 3 000 × pipeline actuel",
    "cell_3_current_master_3000_current_pipeline": "Maître actuel 3 000 × pipeline actuel",
    "cell_4_current_primary_2000_current_pipeline": "Panel actuel 2 000 × pipeline actuel",
}


def _ensure_dirs() -> None:
    for path in (AUDIT_DIR, SYNTHESIS_DIR, FIGURE_DIR, AUX_DIR, PANEL_RUNTIME_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _write_panel_copies() -> dict[str, Path]:
    legacy_source = PANEL_DIR / "panel_3000_common_1962_1986_2022_v2.csv"
    current_source = PANEL_DIR / "longitudinal_2000_v1.parquet"
    if file_sha256(legacy_source) != "d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f":
        raise AssertionError("legacy V2 panel hash changed")
    if file_sha256(current_source) != "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a":
        raise AssertionError("current panel hash changed")

    legacy = pd.read_csv(legacy_source, dtype={"unit_id": "string"})
    legacy_id = "v101_sensitivity_legacy_v2_3000_current_preparation"
    legacy["panel_id"] = legacy_id
    legacy["sample_id"] = legacy_id
    legacy["master_draw_order"] = legacy["sample_rank"]
    legacy_path = PANEL_RUNTIME_DIR / "legacy_v2_3000_current_preparation.parquet"
    if legacy_path.exists():
        existing = pd.read_parquet(legacy_path).sort_values("master_draw_order")
        expected_units = legacy.sort_values("master_draw_order")["unit_id"].astype("string").tolist()
        if existing["unit_id"].astype("string").tolist() != expected_units or not existing["panel_id"].astype("string").eq(legacy_id).all():
            raise AssertionError("existing legacy sensitivity runtime panel is incompatible")
    else:
        legacy.to_parquet(legacy_path, index=False)

    current = pd.read_parquet(current_source)
    current_id = "v101_sensitivity_current_master_3000_current_preparation"
    current["panel_id"] = current_id
    current["sample_id"] = current_id
    current_path = PANEL_RUNTIME_DIR / "current_master_3000_current_preparation.parquet"
    if current_path.exists():
        existing = pd.read_parquet(current_path).sort_values("master_draw_order")
        expected_units = current.sort_values("master_draw_order")["unit_id"].astype("string").tolist()
        if existing["unit_id"].astype("string").tolist() != expected_units or not existing["panel_id"].astype("string").eq(current_id).all():
            raise AssertionError("existing current-master sensitivity runtime panel is incompatible")
    else:
        current.to_parquet(current_path, index=False)
    return {"cell_2": legacy_path, "cell_3": current_path}


def _manifest_model_ready(run_id: str) -> Path:
    manifest = json.loads((RUNS_DIR / run_id / "manifest.json").read_text(encoding="utf-8"))
    matches = [Path(path) for path in manifest.get("input_sha256", {}) if "model_ready" in path and path.endswith(".parquet")]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one model-ready input for {run_id}, got {matches}")
    path = matches[0]
    expected = manifest["input_sha256"][str(path)]
    if not path.exists() or file_sha256(path) != expected:
        raise AssertionError(f"historical model-ready input missing or changed for {run_id}")
    return path


def _array_hash(values: np.ndarray) -> str:
    array = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(list(array.shape)).encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _component_hashes(frame: pd.DataFrame) -> dict[str, str]:
    x = frame.loc[:, list(x_columns(SCENARIO))].to_numpy(dtype="float64")
    y = frame.loc[:, list(y_columns(SCENARIO))].to_numpy(dtype="int64")
    n = frame["N_g"].to_numpy(dtype="int64")
    if not np.array_equal(y.sum(axis=1), n):
        raise AssertionError("H1 political margins do not close exactly")
    return {"x_sha256": _array_hash(x), "y_sha256": _array_hash(y), "n_sha256": _array_hash(n)}


def _fit_auxiliary_nls(frame: pd.DataFrame) -> dict[str, Any]:
    settings = load_settings(CONFIG_DIR / "run_settings.json")["nls"]
    x = frame.loc[:, list(x_columns(SCENARIO))].to_numpy(dtype=float)
    n = frame["N_g"].to_numpy(dtype=float)
    y = frame.loc[:, list(y_columns(SCENARIO))].to_numpy(dtype=float)
    data = NLSData(x=x, t=y / n[:, None], n=n, z=np.empty((len(frame), 0), dtype=float))
    best, starts = fit_nls(
        data,
        n_starts=int(settings["n_starts"]),
        start_scale=float(settings["start_scale"]),
        n_start_strata=int(settings["n_start_strata"]),
        max_nfev=int(settings["max_nfev"]),
        tolerance=float(settings["tolerance"]),
        random_seed=int(settings["random_seed"]),
    )
    pi, _ = probabilities(best.x, x, data.z, y.shape[1])
    aggregate = aggregate_probabilities(x, n, pi)
    objectives = pd.to_numeric(pd.DataFrame(starts).get("cost", pd.Series(dtype=float)), errors="coerce")
    return {
        "nls_b1": float(aggregate[0, 0]),
        "nls_b2": float(aggregate[1, 0]),
        "nls_contrast": float(aggregate[0, 0] - aggregate[1, 0]),
        "nls_success": bool(best.success),
        "nls_objective": float(best.cost),
        "nls_nfev": int(best.nfev),
        "nls_start_objective_sd": float(objectives.std(ddof=0)) if len(objectives) else np.nan,
    }


def _composition(frame: pd.DataFrame) -> dict[str, Any]:
    n = frame["N_g"].to_numpy(dtype=float)
    x = frame[x_columns(SCENARIO)[0]].to_numpy(dtype=float)
    y = frame[y_columns(SCENARIO)[0]].to_numpy(dtype=float)
    region = frame["region13"].astype("string")
    vbbm = pd.to_numeric(frame["vbbm"], errors="coerce")
    dep = frame["unit_id"].astype("string").str[:2]
    return {
        "n_communes": int(len(frame)),
        "electoral_weight_total": int(n.sum()),
        "target_group_share_unweighted": float(x.mean()),
        "target_group_share_electoral_weighted": float(np.average(x, weights=n)),
        "left_vote_share": float(y.sum() / n.sum()),
        "electoral_weight_mean": float(n.mean()),
        "electoral_weight_q50": float(np.quantile(n, 0.5)),
        "electoral_weight_q95": float(np.quantile(n, 0.95)),
        "vbbm_mean": float(vbbm.mean()),
        "n_regions": int(region.nunique(dropna=True)),
        "n_departments": int(dep.nunique(dropna=True)),
        "region_distribution_json": json.dumps(region.value_counts(normalize=True, dropna=False).sort_index().round(8).to_dict(), ensure_ascii=False, sort_keys=True),
        "department_distribution_json": json.dumps(dep.value_counts(normalize=True, dropna=False).sort_index().round(8).to_dict(), ensure_ascii=False, sort_keys=True),
    }


def prepare_diagnostics() -> pd.DataFrame:
    _ensure_dirs()
    panel_paths = _write_panel_copies()
    rows: list[dict[str, Any]] = []
    matrix_index: dict[str, dict[str, str]] = {}
    for election_id in ELECTION_IDS:
        election = ELECTION_BY_ID[election_id]
        old_path = _manifest_model_ready(LEGACY_RUNS[election_id])
        primary_path = _manifest_model_ready(PRIMARY_RUNS[election_id])
        prepared_2, _, _ = prepare_model_ready(
            election,
            SCENARIO,
            sample_size=3000,
            panel_path=panel_paths["cell_2"],
            diagnostic_only_allow_transversal_order_violations=True,
        )
        prepared_3, _, _ = prepare_model_ready(election, SCENARIO, sample_size=3000, panel_path=panel_paths["cell_3"])
        frames = {
            "cell_1_legacy_v2_3000_old_pipeline": (pd.read_parquet(old_path), old_path),
            "cell_2_legacy_v2_3000_current_pipeline": (prepared_2, _prepared_path(prepared_2, election_id)),
            "cell_3_current_master_3000_current_pipeline": (prepared_3, _prepared_path(prepared_3, election_id)),
            "cell_4_current_primary_2000_current_pipeline": (pd.read_parquet(primary_path), primary_path),
        }
        for cell, (frame, path) in frames.items():
            hashes = _component_hashes(frame)
            matrix_index[f"{election_id}|{cell}"] = hashes
            rows.append(
                {
                    "election_id": election_id,
                    "year": election.year,
                    "cell": cell,
                    "cell_label": CELL_LABELS[cell],
                    "model_ready_path": str(path.relative_to(ROOT)).replace("\\", "/") if path.is_relative_to(ROOT) else str(path),
                    "model_ready_sha256": file_sha256(path),
                    **hashes,
                    **_composition(frame),
                    **_fit_auxiliary_nls(frame),
                    "run_role": "diagnostic_only",
                }
            )
    diagnostics = pd.DataFrame(rows)
    diagnostics.to_csv(SYNTHESIS_DIR / "h1_panel_sensitivity_nls_diagnostics.csv", index=False, encoding="utf-8-sig")
    write_json(AUX_DIR / "model_ready_component_hashes.json", matrix_index)
    return diagnostics


def _prepared_path(frame: pd.DataFrame, election_id: str) -> Path:
    sample_id = str(frame["sample_id"].iloc[0])
    return OUTPUT_DIR / "model_ready" / f"{election_id}__H1__{sample_id}__n3000.parquet"


def _find_completed_run(election_id: str, panel_sha256: str) -> str:
    matches: list[tuple[str, str]] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        params = manifest.get("parameters", {})
        if (
            manifest.get("status") == "success"
            and params.get("election_id") == election_id
            and params.get("scenario_id") == "H1"
            and params.get("model_key") == MODEL_KEY
            and int(params.get("sample_size", 0)) == 3000
            and int(params.get("draws", 0)) == 1000
            and int(params.get("tune", 0)) == 1000
            and int(params.get("chains", 0)) == 4
            and int(params.get("random_seed", 0)) == 20260802
            and params.get("panel_sha256") == panel_sha256
        ):
            matches.append((str(manifest.get("finished_at_utc", "")), manifest_path.parent.name))
    if not matches:
        raise RuntimeError(f"no completed sensitivity run found for {election_id}/{panel_sha256}")
    return sorted(matches)[-1][1]


def run_krt_sensitivity() -> pd.DataFrame:
    _ensure_dirs()
    panel_paths = _write_panel_copies()
    registry_path = AUX_DIR / "auxiliary_run_registry.csv"
    registry = pd.read_csv(registry_path, dtype="string") if registry_path.exists() else pd.DataFrame()
    for cell_short, panel_path in panel_paths.items():
        panel_hash = file_sha256(panel_path)
        for election_id in ELECTION_IDS:
            result = run_2x2(
                ELECTION_BY_ID[election_id],
                SCENARIO,
                MODEL_KEY,
                sample_size=3000,
                draws=1000,
                tune=1000,
                chains=4,
                cores=1,
                target_accept=0.99,
                max_treedepth=14,
                random_seed=20260802,
                force=False,
                progressbar=False,
                panel_path=panel_path,
                skip_preflight=True,
                preflight_override_reason="v1.0.1 H1 panel sensitivity requested by release protocol",
                diagnostic_only_allow_transversal_order_violations=(cell_short == "cell_2"),
            )
            run_id = str(result.get("run_id") or _find_completed_run(election_id, panel_hash))
            row = pd.DataFrame(
                [{
                    "election_id": election_id,
                    "cell": "cell_2_legacy_v2_3000_current_pipeline" if cell_short == "cell_2" else "cell_3_current_master_3000_current_pipeline",
                    "run_id": run_id,
                    "run_role": "panel_sensitivity",
                    "panel_path": str(panel_path.relative_to(ROOT)).replace("\\", "/"),
                    "panel_sha256": panel_hash,
                    "status": "success",
                }]
            )
            if not registry.empty:
                keep = ~(
                    registry["election_id"].eq(election_id)
                    & registry["cell"].eq(str(row.iloc[0]["cell"]))
                )
                registry = registry.loc[keep]
            registry = pd.concat([registry, row], ignore_index=True)
            registry = registry.sort_values(["election_id", "cell"])
            registry.to_csv(registry_path, index=False, encoding="utf-8-sig")
    return registry


def _aggregate_draws(run_id: str) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    run_dir = RUNS_DIR / run_id
    dataset = aggregate_krt_trace_files_v2(
        run_dir / "trace.nc", run_dir / "commune_latent_summaries.parquet", include_legacy_comparison=False
    )
    arrays = {
        "beta1": np.asarray(dataset["b_1_group_weighted"].values, dtype=float),
        "beta2": np.asarray(dataset["b_2_group_weighted"].values, dtype=float),
    }
    arrays["contrast"] = arrays["beta1"] - arrays["beta2"]
    stats: dict[str, float] = {}
    for estimand, values in arrays.items():
        flat = values.reshape(-1)
        data = values if values.ndim == 2 else flat[None, :]
        stats[f"{estimand}_mean"] = float(flat.mean())
        stats[f"{estimand}_q025"] = float(np.quantile(flat, 0.025))
        stats[f"{estimand}_q50"] = float(np.quantile(flat, 0.5))
        stats[f"{estimand}_q975"] = float(np.quantile(flat, 0.975))
        stats[f"{estimand}_mcse"] = float(np.asarray(az.mcse(data)).reshape(-1)[0])
    return arrays, stats


def _interval_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> tuple[bool, float]:
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    union = max(a_high, b_high) - min(a_low, b_low)
    return overlap > 0, overlap / union if union > 0 else 1.0


def finalize_sensitivity() -> pd.DataFrame:
    diagnostics_path = SYNTHESIS_DIR / "h1_panel_sensitivity_nls_diagnostics.csv"
    if not diagnostics_path.exists():
        prepare_diagnostics()
    diagnostics = pd.read_csv(diagnostics_path)
    registry_path = AUX_DIR / "auxiliary_run_registry.csv"
    if not registry_path.exists():
        raise FileNotFoundError("run the six KRT sensitivity fits before finalization")
    auxiliary = pd.read_csv(registry_path)
    run_map: dict[tuple[str, str], str] = {}
    for election_id in ELECTION_IDS:
        run_map[(election_id, "cell_1_legacy_v2_3000_old_pipeline")] = LEGACY_RUNS[election_id]
        run_map[(election_id, "cell_4_current_primary_2000_current_pipeline")] = PRIMARY_RUNS[election_id]
    for row in auxiliary.itertuples(index=False):
        run_map[(row.election_id, row.cell)] = row.run_id

    draw_cache: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    nls_columns = {"beta1": "nls_b1", "beta2": "nls_b2", "contrast": "nls_contrast"}
    result_rows: list[dict[str, Any]] = []
    for election_id in ELECTION_IDS:
        for cell in CELL_LABELS:
            run_id = run_map[(election_id, cell)]
            arrays, stats = _aggregate_draws(run_id)
            draw_cache[(election_id, cell)] = arrays
            diag = diagnostics.loc[(diagnostics.election_id == election_id) & (diagnostics.cell == cell)].iloc[0]
            manifest = json.loads((RUNS_DIR / run_id / "manifest.json").read_text(encoding="utf-8"))
            for estimand in ("beta1", "beta2", "contrast"):
                result_rows.append(
                    {
                        "row_type": "estimate",
                        "election_id": election_id,
                        "year": int(diag.year),
                        "estimand": estimand,
                        "cell": cell,
                        "cell_label": CELL_LABELS[cell],
                        "run_id": run_id,
                        "run_role": (
                            "canonical"
                            if cell == "cell_4_current_primary_2000_current_pipeline"
                            else "diagnostic_only"
                            if cell == "cell_1_legacy_v2_3000_old_pipeline"
                            else "panel_sensitivity"
                        ),
                        "mean": stats[f"{estimand}_mean"],
                        "q025": stats[f"{estimand}_q025"],
                        "q50": stats[f"{estimand}_q50"],
                        "q975": stats[f"{estimand}_q975"],
                        "mcse_mean": stats[f"{estimand}_mcse"],
                        "nls_point": float(diag[nls_columns[estimand]]),
                        "model_ready_sha256": diag.model_ready_sha256,
                        "x_sha256": diag.x_sha256,
                        "y_sha256": diag.y_sha256,
                        "n_sha256": diag.n_sha256,
                        "mcmc_status": manifest.get("diagnostic_status", manifest.get("canonical_mcmc_diagnostic", {}).get("mcmc_status", "unknown")),
                        "comparison_label": "",
                        "difference_mean": np.nan,
                        "difference_q025_descriptive": np.nan,
                        "difference_q975_descriptive": np.nan,
                        "intervals_overlap": np.nan,
                        "overlap_ratio": np.nan,
                        "interpretation_scope": "separate_model_estimate",
                    }
                )

        comparisons = (
            ("cell_1_legacy_v2_3000_old_pipeline", "cell_2_legacy_v2_3000_current_pipeline", "changement_preparation_pipeline"),
            ("cell_2_legacy_v2_3000_current_pipeline", "cell_3_current_master_3000_current_pipeline", "changement_panel_V2_vers_maitre_actuel_3000"),
            ("cell_3_current_master_3000_current_pipeline", "cell_4_current_primary_2000_current_pipeline", "sensibilite_sous_panel_emboite_3000_vers_2000"),
        )
        for source, target, label in comparisons:
            source_diag = diagnostics.loc[(diagnostics.election_id == election_id) & (diagnostics.cell == source)].iloc[0]
            target_diag = diagnostics.loc[(diagnostics.election_id == election_id) & (diagnostics.cell == target)].iloc[0]
            if label == "changement_preparation_pipeline" and all(
                source_diag[key] == target_diag[key] for key in ("x_sha256", "y_sha256", "n_sha256")
            ):
                label = "pipeline_only"
            for estimand in ("beta1", "beta2", "contrast"):
                a = draw_cache[(election_id, source)][estimand].reshape(-1)
                b = draw_cache[(election_id, target)][estimand].reshape(-1)
                m = min(len(a), len(b))
                difference = b[:m] - a[:m]
                a_interval = np.quantile(a, [0.025, 0.975])
                b_interval = np.quantile(b, [0.025, 0.975])
                overlaps, ratio = _interval_overlap(*a_interval, *b_interval)
                result_rows.append(
                    {
                        "row_type": "descriptive_difference",
                        "election_id": election_id,
                        "year": int(source_diag.year),
                        "estimand": estimand,
                        "cell": f"{target}_minus_{source}",
                        "cell_label": f"{CELL_LABELS[target]} − {CELL_LABELS[source]}",
                        "run_id": f"{run_map[(election_id, target)]}|{run_map[(election_id, source)]}",
                        "run_role": "panel_sensitivity",
                        "mean": np.nan,
                        "q025": np.nan,
                        "q50": np.nan,
                        "q975": np.nan,
                        "mcse_mean": np.nan,
                        "nls_point": float(
                            target_diag[nls_columns[estimand]] - source_diag[nls_columns[estimand]]
                        ),
                        "model_ready_sha256": f"{target_diag.model_ready_sha256}|{source_diag.model_ready_sha256}",
                        "x_sha256": f"{target_diag.x_sha256}|{source_diag.x_sha256}",
                        "y_sha256": f"{target_diag.y_sha256}|{source_diag.y_sha256}",
                        "n_sha256": f"{target_diag.n_sha256}|{source_diag.n_sha256}",
                        "mcmc_status": "not_applicable_separate_models",
                        "comparison_label": label,
                        "difference_mean": float(difference.mean()),
                        "difference_q025_descriptive": float(np.quantile(difference, 0.025)),
                        "difference_q975_descriptive": float(np.quantile(difference, 0.975)),
                        "intervals_overlap": bool(overlaps),
                        "overlap_ratio": float(ratio),
                        "interpretation_scope": "distribution_descriptive_difference_independent_fits_not_causal",
                    }
                )
    result = pd.DataFrame(result_rows)
    result.to_csv(SYNTHESIS_DIR / "h1_panel_sensitivity.csv", index=False, encoding="utf-8-sig")
    _plot_sensitivity(result)
    return result


def _plot_sensitivity(result: pd.DataFrame) -> None:
    estimates = result.loc[(result.row_type == "estimate") & (result.estimand == "contrast")].copy()
    differences = result.loc[(result.row_type == "descriptive_difference") & (result.estimand == "contrast")].copy()
    colors = ["#7f8c8d", "#4c78a8", "#f58518", "#54a24b"]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5), constrained_layout=True)
    for col, election_id in enumerate(ELECTION_IDS):
        top = estimates.loc[estimates.election_id == election_id]
        for idx, cell in enumerate(CELL_LABELS):
            row = top.loc[top.cell == cell].iloc[0]
            axes[0, col].errorbar(
                idx,
                row["mean"],
                yerr=[[row["mean"] - row.q025], [row.q975 - row["mean"]]],
                fmt="o",
                color=colors[idx],
                capsize=3,
            )
        axes[0, col].axhline(0, color="#999999", lw=0.8)
        axes[0, col].set_title(election_id.replace("leg_", "Législatives ").replace("_r1", ""))
        axes[0, col].set_xticks(range(4), ["V2 ancien", "V2 actuel", "Maître 3k", "Panel 2k"], rotation=25, ha="right")
        axes[0, col].set_ylabel("Contraste β₁ − β₂" if col == 0 else "")

        bottom = differences.loc[differences.election_id == election_id]
        labels = [
            "Préparation/\npipeline",
            "V2 → maître\nactuel 3k",
            "Sous-panel\n3k → 2k",
        ]
        for idx, comparison in enumerate(bottom.comparison_label.tolist()):
            row = bottom.iloc[idx]
            axes[1, col].errorbar(
                idx,
                row.difference_mean,
                yerr=[[row.difference_mean - row.difference_q025_descriptive], [row.difference_q975_descriptive - row.difference_mean]],
                fmt="o",
                color=["#4c78a8", "#f58518", "#54a24b"][idx],
                capsize=3,
            )
        axes[1, col].axhline(0, color="#555555", lw=0.8)
        axes[1, col].set_xticks(range(3), labels, rotation=15, ha="right")
        axes[1, col].set_ylabel("Différence descriptive" if col == 0 else "")
    fig.suptitle("Sensibilité H1 au pipeline et aux panels — intervalles descriptifs, modèles estimés séparément", fontsize=14)
    fig.savefig(FIGURE_DIR / "h1_panel_sensitivity.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the v1.0.1 H1 panel sensitivity protocol.")
    parser.add_argument("stage", choices=("prepare", "relabel-diagnostics", "run-krt", "finalize", "all"))
    return parser.parse_args()


def relabel_diagnostics() -> pd.DataFrame:
    path = SYNTHESIS_DIR / "h1_panel_sensitivity_nls_diagnostics.csv"
    frame = pd.read_csv(path)
    if "vbbm_share" in frame.columns:
        frame = frame.rename(columns={"vbbm_share": "vbbm_mean"})
    if "vbbm_mean" not in frame.columns:
        raise AssertionError("VBBM diagnostic column is missing")
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return frame


def main() -> None:
    args = parse_args()
    if args.stage in {"prepare", "all"}:
        print(prepare_diagnostics().to_json(orient="records"))
    if args.stage in {"relabel-diagnostics", "all"}:
        print(json.dumps({"diagnostic_rows": len(relabel_diagnostics()), "vbbm_field": "vbbm_mean"}))
    if args.stage in {"run-krt", "all"}:
        print(run_krt_sensitivity().to_json(orient="records"))
    if args.stage in {"finalize", "all"}:
        print(finalize_sensitivity().to_json(orient="records"))


if __name__ == "__main__":
    main()

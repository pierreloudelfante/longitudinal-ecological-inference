from __future__ import annotations

from pathlib import Path
import json
import shutil

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from .paths import FIGURE_DIR, OUTPUT_DIR, RUNS_DIR, ensure_runtime_dirs
from .run_registry import selected_successful_run_dirs
from .spec_registry import SCENARIO_BY_ID
from .utils import canonical_hash


MODEL_ORDER = ("king_truncated_normal", "krt_beta_binomial")
MODEL_LABEL = {
    "king_truncated_normal": "King — normale tronquée",
    "krt_beta_binomial": "KRT — King99",
}
CSP_LABEL = {
    "agri": "agriculteurs",
    "indp": "indépendants",
    "cadr": "cadres",
    "pint": "professions intermédiaires",
    "empl": "employés",
    "ouvr": "ouvriers",
}


def _social_group_label(key: str, components: tuple[str, ...]) -> str:
    if key == "complement_group":
        return "autres CSP"
    if key == "salaries":
        return "salariés"
    return " + ".join(CSP_LABEL.get(component, component) for component in components)


def _density(values: np.ndarray, grid: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    mask = np.isfinite(values)
    values = values[mask]
    if weights is not None:
        weights = np.asarray(weights, dtype=float)[mask]
        weights = np.maximum(weights, 0)
        weights = weights / weights.sum() if weights.sum() > 0 else None
    if values.size < 2 or np.allclose(values, values[0]):
        hist, edges = np.histogram(values, bins=50, range=(0, 1), density=True, weights=weights)
        centers = (edges[:-1] + edges[1:]) / 2
        return np.interp(grid, centers, hist, left=0, right=0)
    try:
        return gaussian_kde(values, weights=weights)(grid)
    except np.linalg.LinAlgError:
        hist, edges = np.histogram(values, bins=50, range=(0, 1), density=True, weights=weights)
        return np.interp(grid, (edges[:-1] + edges[1:]) / 2, hist, left=0, right=0)


def load_latent_runs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for run_dir in selected_successful_run_dirs():
        path = run_dir / "commune_latent_summaries.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _comparison_metadata() -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for run_dir in selected_successful_run_dirs():
        path = run_dir / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict) or parameters.get("model_key") not in MODEL_ORDER:
            continue
        comparison_parameters = {key: value for key, value in parameters.items() if key != "model_key"}
        metadata[str(manifest.get("run_id", path.parent.name))] = {
            "comparison_key": canonical_hash(comparison_parameters)[:12],
            "n_communes_requested": parameters.get("sample_size", np.nan),
            "draws": parameters.get("draws", np.nan),
            "tune": parameters.get("tune", np.nan),
            "chains": parameters.get("chains", np.nan),
        }
    return metadata


def _with_scopes(latent: pd.DataFrame) -> pd.DataFrame:
    if latent.empty:
        return latent
    enriched = latent.copy()
    metadata = _comparison_metadata()
    if "run_id" in enriched:
        for column in ("comparison_key", "n_communes_requested", "draws", "tune", "chains"):
            enriched[column] = enriched["run_id"].astype(str).map(
                {run_id: values[column] for run_id, values in metadata.items()}
            )
    else:
        enriched["comparison_key"] = "unregistered"
        enriched["n_communes_requested"] = len(enriched)
        enriched["draws"] = np.nan
        enriched["tune"] = np.nan
        enriched["chains"] = np.nan
    enriched["comparison_key"] = enriched["comparison_key"].fillna("unregistered")
    native = enriched.copy()
    native["comparison_scope"] = "native"
    common_parts: list[pd.DataFrame] = []
    keys = ["sample_id", "election_id", "scenario_id", "comparison_key"]
    for _, group in enriched.groupby(keys, sort=True):
        models = {model: set(part["unit_id"].astype(str)) for model, part in group.groupby("model_key")}
        if not all(model in models for model in MODEL_ORDER):
            continue
        common_ids = models[MODEL_ORDER[0]] & models[MODEL_ORDER[1]]
        part = group.loc[group["unit_id"].astype(str).isin(common_ids)].copy()
        part["comparison_scope"] = "common_intersection"
        common_parts.append(part)
    return pd.concat([native, *common_parts], ignore_index=True) if common_parts else native


def build_density_data(latent: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    ensure_runtime_dirs()
    scoped = _with_scopes(load_latent_runs() if latent is None else latent)
    if scoped.empty:
        marginal = pd.DataFrame()
        joint = pd.DataFrame()
        marginal.to_parquet(OUTPUT_DIR / "density_marginal_data.parquet", index=False)
        joint.to_parquet(OUTPUT_DIR / "density_joint_data.parquet", index=False)
        return marginal, joint
    grid = np.linspace(0, 1, 201)
    density_rows: list[dict[str, object]] = []
    group_keys = [
        "run_id",
        "run_key",
        "sample_id",
        "election_id",
        "scenario_id",
        "model_key",
        "comparison_key",
        "n_communes_requested",
        "draws",
        "tune",
        "chains",
        "comparison_scope",
    ]
    for key, group in scoped.groupby(group_keys, sort=True):
        base = dict(zip(group_keys, key))
        for parameter, label, weight_column in (
            ("b1_mean", "b1", "b1_weight"),
            ("b2_mean", "b2", "b2_weight"),
        ):
            for weight_mode, weights in (
                ("equal_commune", None),
                ("social_population_weighted", group[weight_column].to_numpy(dtype=float)),
            ):
                density = _density(group[parameter].to_numpy(dtype=float), grid, weights)
                for grid_value, density_value in zip(grid, density):
                    density_rows.append(
                        {
                            **base,
                            "latent_parameter": label,
                            "weight_mode": weight_mode,
                            "grid_value": float(grid_value),
                            "density": float(density_value),
                            "n_communes": int(len(group)),
                        }
                    )
    marginal = pd.DataFrame(density_rows)
    joint = scoped[
        [
            "run_id",
            "run_key",
            "sample_id",
            "election_id",
            "scenario_id",
            "model_key",
            "comparison_key",
            "n_communes_requested",
            "draws",
            "tune",
            "chains",
            "comparison_scope",
            "unit_id",
            "sample_rank",
            "b1_mean",
            "b2_mean",
            "b1_weight",
            "b2_weight",
        ]
    ].copy()
    marginal.to_parquet(OUTPUT_DIR / "density_marginal_data.parquet", index=False)
    marginal.to_csv(OUTPUT_DIR / "density_marginal_data.csv", index=False, encoding="utf-8-sig")
    joint.to_parquet(OUTPUT_DIR / "density_joint_data.parquet", index=False)
    joint.to_csv(OUTPUT_DIR / "density_joint_data.csv", index=False, encoding="utf-8-sig")
    return marginal, joint


def _diagnostic_lookup() -> dict[str, str]:
    path = OUTPUT_DIR / "run_registry.csv"
    if not path.exists():
        return {}
    registry = pd.read_csv(path, dtype="string")
    return dict(zip(registry.get("run_id", []), registry.get("diagnostic_status", [])))


def _save(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(base.with_suffix(".png"), dpi=170)
    fig.savefig(base.with_suffix(".svg"))
    plt.close(fig)


def _select_largest_plot_views(
    marginal: pd.DataFrame, joint: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Select one honest density comparison per election/scenario.

    A common King/KRT rung has priority. The largest requested rung is chosen;
    ties prefer the greatest saved MCMC work. If no common view exists, keep
    only the largest native rung of each available model.
    """
    metadata_columns = [
        "run_id",
        "sample_id",
        "election_id",
        "scenario_id",
        "model_key",
        "comparison_key",
        "n_communes_requested",
        "draws",
        "tune",
        "chains",
        "comparison_scope",
    ]
    metadata = joint[metadata_columns].drop_duplicates().copy()
    for column in ("n_communes_requested", "draws", "tune", "chains"):
        metadata[column] = pd.to_numeric(metadata[column], errors="coerce")
    metadata["mcmc_work"] = (
        (metadata["draws"].fillna(0) + metadata["tune"].fillna(0))
        * metadata["chains"].fillna(0)
    )
    selected_masks: list[pd.Series] = []
    selection_rows: list[dict[str, object]] = []
    status_by_run = _diagnostic_lookup()
    for (election_id, scenario_id), study in metadata.groupby(
        ["election_id", "scenario_id"], sort=True
    ):
        common = study.loc[study["comparison_scope"].eq("common_intersection")]
        candidates: list[tuple[float, float, str]] = []
        for comparison_key, candidate in common.groupby("comparison_key"):
            if set(candidate["model_key"]) >= set(MODEL_ORDER):
                candidates.append(
                    (
                        float(candidate["n_communes_requested"].max()),
                        float(candidate["mcmc_work"].max()),
                        str(comparison_key),
                    )
                )
        if candidates:
            n_requested, _, comparison_key = max(candidates)
            mask = (
                joint["election_id"].eq(election_id)
                & joint["scenario_id"].eq(scenario_id)
                & joint["comparison_key"].astype(str).eq(comparison_key)
                & joint["comparison_scope"].eq("common_intersection")
            )
            selected_masks.append(mask)
            chosen = joint.loc[mask]
            for model_key, part in chosen.groupby("model_key"):
                selection_rows.append(
                    {
                        "election_id": election_id,
                        "scenario_id": scenario_id,
                        "selection_scope": "largest_common_intersection",
                        "model_key": model_key,
                        "run_id": str(part["run_id"].iloc[0]),
                        "comparison_key": comparison_key,
                        "n_communes_requested": int(n_requested),
                        "n_communes_selected": int(part["unit_id"].astype(str).nunique()),
                        "draws": int(pd.to_numeric(part["draws"], errors="coerce").max()),
                        "tune": int(pd.to_numeric(part["tune"], errors="coerce").max()),
                        "chains": int(pd.to_numeric(part["chains"], errors="coerce").max()),
                        "diagnostic_status": status_by_run.get(str(part["run_id"].iloc[0]), ""),
                    }
                )
            continue

        native = study.loc[study["comparison_scope"].eq("native")]
        for model_key, model_rows in native.groupby("model_key"):
            chosen_row = model_rows.sort_values(
                ["n_communes_requested", "mcmc_work", "run_id"]
            ).iloc[-1]
            run_id = str(chosen_row["run_id"])
            mask = joint["run_id"].astype(str).eq(run_id) & joint[
                "comparison_scope"
            ].eq("native")
            selected_masks.append(mask)
            part = joint.loc[mask]
            selection_rows.append(
                {
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "selection_scope": "largest_native_only",
                    "model_key": model_key,
                    "run_id": run_id,
                    "comparison_key": str(chosen_row["comparison_key"]),
                    "n_communes_requested": int(chosen_row["n_communes_requested"]),
                    "n_communes_selected": int(part["unit_id"].astype(str).nunique()),
                    "draws": int(chosen_row["draws"]),
                    "tune": int(chosen_row["tune"]),
                    "chains": int(chosen_row["chains"]),
                    "diagnostic_status": status_by_run.get(run_id, ""),
                }
            )

    if not selected_masks:
        empty = joint.iloc[0:0].copy()
        return marginal.iloc[0:0].copy(), empty, pd.DataFrame(selection_rows)
    joint_mask = np.logical_or.reduce([mask.to_numpy() for mask in selected_masks])
    selected_joint = joint.loc[joint_mask].copy()
    selected_keys = set(
        zip(
            selected_joint["run_id"].astype(str),
            selected_joint["comparison_scope"].astype(str),
        )
    )
    marginal_mask = [
        (str(run_id), str(scope)) in selected_keys
        for run_id, scope in zip(marginal["run_id"], marginal["comparison_scope"])
    ]
    selected_marginal = marginal.loc[marginal_mask].copy()
    selection = pd.DataFrame(selection_rows).sort_values(
        ["election_id", "scenario_id", "model_key"]
    )
    return selected_marginal, selected_joint, selection


def _plot_curated_overlays(
    marginal: pd.DataFrame, selection: pd.DataFrame, output_root: Path
) -> None:
    curated = output_root / "curated"
    if curated.exists():
        shutil.rmtree(curated)
    curated.mkdir(parents=True, exist_ok=True)
    equal = marginal.loc[marginal["weight_mode"].eq("equal_commune")]
    for (election_id, scenario_id), group in equal.groupby(
        ["election_id", "scenario_id"], sort=True
    ):
        fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.6), sharey=False)
        scenario = SCENARIO_BY_ID.get(str(scenario_id))
        social_groups = (
            [
                _social_group_label(str(key), tuple(value))
                for key, value in scenario.social_groups.items()
            ]
            if scenario is not None
            else ["groupe 1", "groupe 2"]
        )
        for ax, parameter, social_group in zip(
            axes, ("b1", "b2"), social_groups[:2]
        ):
            parameter_rows = group.loc[group["latent_parameter"].eq(parameter)]
            for model_key in MODEL_ORDER:
                curve = parameter_rows.loc[parameter_rows["model_key"].eq(model_key)]
                if curve.empty:
                    continue
                ax.plot(
                    curve["grid_value"],
                    curve["density"],
                    linewidth=2.0,
                    label=MODEL_LABEL[model_key],
                )
                ax.fill_between(
                    curve["grid_value"], curve["density"], alpha=0.10
                )
            ax.set_xlim(0, 1)
            beta_label = "β₁" if parameter == "b1" else "β₂"
            ax.set_xlabel(f"{beta_label} — {social_group}")
            ax.set_ylabel("Densité entre communes")
            ax.grid(alpha=0.18)
            ax.legend(frameon=False)
        selected = selection.loc[
            selection["election_id"].eq(election_id)
            & selection["scenario_id"].eq(scenario_id)
        ]
        n_requested = int(selected["n_communes_requested"].max())
        common_n = int(selected["n_communes_selected"].min())
        draws = int(selected["draws"].max())
        chains = int(selected["chains"].max())
        statuses = "/".join(
            selected.set_index("model_key")["diagnostic_status"]
            .reindex(MODEL_ORDER)
            .dropna()
            .astype(str)
        )
        scope = str(selected["selection_scope"].iloc[0])
        scope_label = (
            "intersection exacte King/KRT au plus grand palier commun"
            if scope == "largest_common_intersection"
            else "plus grand palier natif disponible (comparaison commune impossible)"
        )
        fig.suptitle(
            f"Densités communales — {election_id} — {scenario_id}\n"
            f"palier demandé={n_requested} • communes={common_n} • draws={draws} • chaînes={chains} • diagnostics={statuses}\n"
            f"{scope_label} — CALIBRATION NON SUBSTANTIELLE (une chaîne)",
            fontsize=11,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.83))
        base = curated / f"density_overlay__{election_id}__{scenario_id}__n{n_requested}"
        fig.savefig(base.with_suffix(".png"), dpi=190)
        fig.savefig(base.with_suffix(".svg"))
        plt.close(fig)


def plot_density_figures(marginal: pd.DataFrame, joint: pd.DataFrame) -> None:
    if marginal.empty or joint.empty:
        return
    density_root = FIGURE_DIR / "densities"
    density_root.mkdir(parents=True, exist_ok=True)
    for generated_subdir in ("marginal", "joint", "comparisons"):
        path = density_root / generated_subdir
        if path.exists():
            shutil.rmtree(path)
    marginal, joint, selection = _select_largest_plot_views(marginal, joint)
    selection.to_csv(
        OUTPUT_DIR / "pilot_density_selection.csv", index=False, encoding="utf-8-sig"
    )
    _plot_curated_overlays(marginal, selection, density_root)
    status_by_run = _diagnostic_lookup()
    keys = ["run_id", "election_id", "scenario_id", "model_key", "n_communes_requested", "comparison_scope"]
    for key, group in marginal.loc[marginal["weight_mode"].eq("equal_commune")].groupby(keys, sort=True):
        run_id, election_id, scenario_id, model_key, n_requested, scope = key
        fig, ax = plt.subplots(figsize=(6.4, 4.5))
        for parameter, label in (("b1", "β₁ — groupe cible"), ("b2", "β₂ — groupe complémentaire")):
            curve = group.loc[group["latent_parameter"].eq(parameter)]
            ax.plot(curve["grid_value"], curve["density"], label=label)
        n = int(group["n_communes"].max())
        status = status_by_run.get(str(run_id), "")
        ax.set(xlim=(0, 1), xlabel="Probabilité latente communale", ylabel="Densité")
        scope_label = "intersection King/KRT" if scope == "common_intersection" else "vue native"
        ax.set_title(
            f"Densité des β communaux — {election_id} — {scenario_id}\n"
            f"{MODEL_LABEL.get(model_key, model_key)} • n={n} • {scope_label} • diagnostic={status}",
            fontsize=11,
        )
        ax.legend()
        suffix = "" if scope == "native" else "__common"
        suffix += f"__n{int(n_requested)}"
        _save(fig, FIGURE_DIR / "densities" / "marginal" / f"{election_id}__{scenario_id}__{model_key}{suffix}")

        points = joint.loc[
            joint["run_id"].eq(run_id) & joint["comparison_scope"].eq(scope)
        ]
        fig, ax = plt.subplots(figsize=(5.4, 5.2))
        ax.hexbin(points["b1_mean"], points["b2_mean"], gridsize=28, extent=(0, 1, 0, 1), mincnt=1, cmap="viridis")
        ax.scatter(points["b1_mean"], points["b2_mean"], s=6, alpha=0.28, color="white", linewidths=0)
        if len(points) >= 5:
            try:
                values = np.vstack([points["b1_mean"], points["b2_mean"]])
                kde = gaussian_kde(values)
                axis = np.linspace(0, 1, 75)
                xx, yy = np.meshgrid(axis, axis)
                zz = kde(np.vstack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
                ax.contour(xx, yy, zz, levels=5, colors="black", linewidths=0.7, alpha=0.75)
            except np.linalg.LinAlgError:
                pass
        ax.plot([0, 1], [0, 1], linestyle="--", color="red", linewidth=1)
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="β₁ moyen", ylabel="β₂ moyen")
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(
            f"β communaux — {election_id} — {scenario_id}\n"
            f"{MODEL_LABEL.get(model_key, model_key)} • n={len(points)} • {scope_label} • diagnostic={status}",
            fontsize=10.5,
        )
        _save(fig, FIGURE_DIR / "densities" / "joint" / f"{election_id}__{scenario_id}__{model_key}{suffix}")

    common = joint.loc[joint["comparison_scope"].eq("common_intersection")]
    for key, group in common.groupby(["sample_id", "election_id", "scenario_id", "comparison_key", "n_communes_requested"], sort=True):
        if not all(model in set(group["model_key"]) for model in MODEL_ORDER):
            continue
        sample_id, election_id, scenario_id, comparison_key, n_requested = key
        fig, axes = plt.subplots(1, 2, figsize=(10.8, 5.0), sharex=True, sharey=True)
        for ax, model_key in zip(axes, MODEL_ORDER):
            points = group.loc[group["model_key"].eq(model_key)]
            ax.hexbin(points["b1_mean"], points["b2_mean"], gridsize=26, extent=(0, 1, 0, 1), mincnt=1, cmap="viridis")
            ax.plot([0, 1], [0, 1], "r--", linewidth=1)
            ax.set_title(f"{model_key}\nn={len(points)}")
            ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="β₁ moyen", ylabel="β₂ moyen")
            ax.set_aspect("equal", adjustable="box")
        statuses = {
            model: status_by_run.get(str(part["run_id"].iloc[0]), "")
            for model, part in group.groupby("model_key")
        }
        status_label = "/".join(statuses.get(model, "") for model in MODEL_ORDER)
        draws = int(pd.to_numeric(group["draws"], errors="coerce").max())
        chains = int(pd.to_numeric(group["chains"], errors="coerce").max())
        fig.suptitle(
            f"Comparaison commune — {election_id} — {scenario_id}\n"
            f"palier={int(n_requested)} • draws={draws} • chaînes={chains} • diagnostics King/KRT={status_label}",
            fontsize=12,
        )
        _save(
            fig,
            FIGURE_DIR
            / "densities"
            / "comparisons"
            / f"{election_id}__{scenario_id}__king_vs_krt__n{int(n_requested)}__{comparison_key}",
        )

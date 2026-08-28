from __future__ import annotations

import json

import pandas as pd

from .output_schema import BETA_ESTIMATE_COLUMNS, BETA_TRACE_INDEX_COLUMNS, empty_frame
from .paths import OUTPUT_DIR, ROOT
from .run_registry import selected_successful_run_dirs
from .spec_registry import SCENARIO_BY_ID
from .utils import canonical_hash, file_sha256


def _run_metadata() -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for run_dir in selected_successful_run_dirs():
        path = run_dir / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        comparison_parameters = {key: value for key, value in parameters.items() if key != "model_key"}
        run_id = str(manifest.get("run_id", run_dir.name))
        metadata[run_id] = {
            "run_key": manifest.get("run_key", ""),
            "sample_id": manifest.get("sample_id", ""),
            "election_id": manifest.get("election_id", parameters.get("election_id", "")),
            "scenario_id": manifest.get("scenario_id", parameters.get("scenario_id", "")),
            "model_key": manifest.get("model_key", parameters.get("model_key", "")),
            "comparison_key": canonical_hash(comparison_parameters)[:12],
            "n_communes_requested": parameters.get("sample_size", ""),
            "n_communes_used": manifest.get("n_communes_used", ""),
            "draws": parameters.get("draws", ""),
            "tune": parameters.get("tune", ""),
            "chains": parameters.get("chains", ""),
            "diagnostic_status": manifest.get("diagnostic_status", ""),
            "run_dir": run_dir,
        }
    return metadata


def build_commune_beta_estimates(latent: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Export beta estimates at the commune grain and index full posterior traces."""
    metadata = _run_metadata()
    rows: list[dict[str, object]] = []
    for run_id, group in latent.groupby("run_id", sort=True):
        meta = metadata.get(str(run_id), {})
        scenario_id = str(group["scenario_id"].iloc[0])
        scenario = SCENARIO_BY_ID.get(scenario_id)
        social_groups = list(scenario.social_groups) if scenario is not None else ["group_1", "group_2"]
        for parameter, prefix, group_index in (("b_1", "b1", 0), ("b_2", "b2", 1)):
            social_group = social_groups[group_index] if group_index < len(social_groups) else f"group_{group_index + 1}"
            part = pd.DataFrame(
                {
                    "run_id": group["run_id"],
                    "run_key": group["run_key"],
                    "sample_id": group["sample_id"],
                    "election_id": group["election_id"],
                    "scenario_id": group["scenario_id"],
                    "model_key": group["model_key"],
                    "comparison_key": meta.get("comparison_key", ""),
                    "n_communes_requested": meta.get("n_communes_requested", ""),
                    "n_communes_used": meta.get("n_communes_used", len(group)),
                    "draws": meta.get("draws", ""),
                    "tune": meta.get("tune", ""),
                    "chains": meta.get("chains", ""),
                    "diagnostic_status": meta.get("diagnostic_status", ""),
                    "unit_id": group["unit_id"],
                    "sample_rank": group["sample_rank"],
                    "beta_parameter": parameter,
                    "social_group": social_group,
                    "estimate_basis": "commune_posterior_mean",
                    "weight": group[f"{prefix}_weight"],
                    "estimate": group[f"{prefix}_mean"],
                    "posterior_sd": group[f"{prefix}_sd"],
                    "q025": group[f"{prefix}_q025"],
                    "q50": group[f"{prefix}_q50"],
                    "q975": group[f"{prefix}_q975"],
                }
            )
            rows.extend(part.to_dict("records"))
    beta = pd.DataFrame(rows, columns=BETA_ESTIMATE_COLUMNS) if rows else empty_frame(BETA_ESTIMATE_COLUMNS)
    beta.to_csv(OUTPUT_DIR / "commune_beta_estimates.csv", index=False, encoding="utf-8-sig")
    beta.to_parquet(OUTPUT_DIR / "commune_beta_estimates.parquet", index=False)

    trace_rows: list[dict[str, object]] = []
    beta_models = {"king_truncated_normal", "krt_beta_binomial"}
    for run_id, meta in metadata.items():
        if meta.get("model_key") not in beta_models:
            continue
        trace_path = meta["run_dir"] / "trace.nc"
        if not trace_path.exists():
            continue
        trace_rows.append(
            {
                **{column: meta.get(column, "") for column in BETA_TRACE_INDEX_COLUMNS if column not in {"variables", "trace_path", "trace_size_bytes", "trace_sha256"}},
                "run_id": run_id,
                "variables": "b_1,b_2",
                "trace_path": trace_path.relative_to(ROOT).as_posix(),
                "trace_size_bytes": trace_path.stat().st_size,
                "trace_sha256": file_sha256(trace_path),
            }
        )
    trace_index = pd.DataFrame(trace_rows, columns=BETA_TRACE_INDEX_COLUMNS) if trace_rows else empty_frame(BETA_TRACE_INDEX_COLUMNS)
    trace_index.to_csv(OUTPUT_DIR / "beta_trace_index.csv", index=False, encoding="utf-8-sig")
    return beta, trace_index


def build_beta_density_data(marginal: pd.DataFrame) -> pd.DataFrame:
    beta_density = marginal.rename(columns={"latent_parameter": "beta_parameter"}).copy()
    if not beta_density.empty:
        beta_density["beta_parameter"] = beta_density["beta_parameter"].replace({"b1": "b_1", "b2": "b_2"})
        beta_density["estimate_basis"] = "density_of_commune_posterior_means"
    beta_density.to_csv(OUTPUT_DIR / "beta_density_data.csv", index=False, encoding="utf-8-sig")
    beta_density.to_parquet(OUTPUT_DIR / "beta_density_data.parquet", index=False)
    return beta_density

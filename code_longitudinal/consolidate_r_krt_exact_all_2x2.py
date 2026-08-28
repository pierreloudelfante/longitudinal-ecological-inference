from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import OUTPUT_DIR, ROOT
from .run_r_krt_exact_all_2x2 import EXPECTED_ELECTIONS, R_SCRIPT, RUN_DIR
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
COMMUNE_PATH = REPLICATION_DIR / "longitudinal_krt_exact_r_commune_all_2x2.parquet"
AGGREGATE_PATH = REPLICATION_DIR / "longitudinal_krt_exact_r_aggregate_all_2x2.parquet"
DIAGNOSTICS_PATH = REPLICATION_DIR / "longitudinal_krt_exact_r_diagnostics_all_2x2.csv"
MANIFEST_PATH = REPLICATION_DIR / "longitudinal_krt_exact_r_consolidation_manifest.json"
EXPECTED_PAIRS = sum(EXPECTED_ELECTIONS.values())
ESTIMAND_MAP = {
    "beta1_aggregate": "b_1",
    "beta2_aggregate": "b_2",
    "contrast_aggregate": "b_1_minus_b_2",
}


def _rhat_ess_status(max_rhat: float, min_ess_bulk: float, min_ess_tail: float) -> tuple[str, str]:
    values = (max_rhat, min_ess_bulk, min_ess_tail)
    if not all(np.isfinite(value) for value in values):
        return "fail", "fail"
    if max_rhat > 1.05 or min_ess_bulk < 100 or min_ess_tail < 100:
        return "fail", "fail"
    if max_rhat <= 1.01 and min_ess_bulk >= 400 and min_ess_tail >= 400:
        return "pass", "pass"
    if max_rhat <= 1.03 and min_ess_bulk >= 200 and min_ess_tail >= 200:
        return "caveat", "caveat_modere"
    return "caveat", "caveat_severe"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def _valid_run(run_dir: Path) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    manifest_path = run_dir / "manifest_r.json"
    commune_path = run_dir / "commune_latent_summaries_r.csv"
    aggregate_path = run_dir / "aggregate_summaries_r.csv"
    parameter_path = run_dir / "parameter_diagnostics_r.csv"
    if not all(path.is_file() for path in (manifest_path, commune_path, aggregate_path, parameter_path)):
        return None
    manifest = _load_json(manifest_path)
    if not (
        manifest.get("status") == "success"
        and manifest.get("model") == "exact_reimplementation_of_pyei_ei_beta_binom_model"
        and int(manifest.get("n_communes", -1)) == 2000
        and int(manifest.get("chains", -1)) == 4
        and int(manifest.get("warmup", -1)) == 1000
        and int(manifest.get("draws_per_chain", -1)) == 1000
        and manifest.get("runner_script_sha256") == file_sha256(R_SCRIPT)
    ):
        return None
    input_csv = Path(str(manifest["input_csv"]))
    if not input_csv.is_file() or manifest.get("input_sha256") != file_sha256(input_csv):
        return None
    commune = pd.read_csv(commune_path, dtype={"unit_id": "string"})
    aggregate = pd.read_csv(aggregate_path)
    parameters = pd.read_csv(parameter_path)
    if len(commune) != 4000 or set(commune["parameter"].astype(str)) != {"b_1", "b_2"}:
        return None
    if commune.groupby("parameter")["unit_id"].nunique().to_dict() != {"b_1": 2000, "b_2": 2000}:
        return None
    if len(aggregate) != 3 or set(aggregate["estimand"].astype(str)) != set(ESTIMAND_MAP):
        return None
    return manifest, commune, aggregate, parameters


def consolidate() -> dict[str, object]:
    REPLICATION_DIR.mkdir(parents=True, exist_ok=True)
    commune_frames: list[pd.DataFrame] = []
    aggregate_frames: list[pd.DataFrame] = []
    diagnostic_rows: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for run_dir in sorted(path for path in RUN_DIR.glob("*__*") if path.is_dir()):
        loaded = _valid_run(run_dir)
        if loaded is None:
            continue
        manifest, commune, aggregate, parameters = loaded
        election_id = str(manifest["election_id"])
        scenario_id = str(manifest["scenario_id"])
        pair = (election_id, scenario_id)
        if pair in seen_pairs:
            raise AssertionError(f"duplicate exact R pair: {pair}")
        seen_pairs.add(pair)

        input_frame = pd.read_csv(
            str(manifest["input_csv"]),
            dtype={"unit_id": "string"},
            usecols=lambda column: column in {
                "unit_id", "panel_id", "year", "round", "sample_rank", "N_g"
            } or column.startswith("N__"),
        )
        input_ids = input_frame["unit_id"].astype("string").tolist()
        for parameter in ("b_1", "b_2"):
            parameter_ids = commune.loc[commune["parameter"].eq(parameter), "unit_id"].astype("string").tolist()
            if parameter_ids != input_ids:
                raise AssertionError(f"unit_id order mismatch for {pair} {parameter}")

        wide_parts: list[pd.DataFrame] = []
        for parameter, prefix in (("b_1", "b1"), ("b_2", "b2")):
            part = commune.loc[commune["parameter"].eq(parameter)].copy()
            part = part[["unit_id", "mean", "sd", "q025", "q50", "q975"]].rename(
                columns={name: f"{prefix}_{name}" for name in ("mean", "sd", "q025", "q50", "q975")}
            )
            wide_parts.append(part)
        wide = wide_parts[0].merge(wide_parts[1], on="unit_id", how="inner", validate="one_to_one")
        n_columns = [column for column in input_frame if column.startswith("N__")]
        if len(n_columns) != 2:
            raise AssertionError(f"expected two social count columns for {pair}")
        metadata = input_frame[["unit_id", "panel_id", "year", "round", "sample_rank", "N_g", *n_columns]].copy()
        metadata = metadata.rename(columns={n_columns[0]: "b1_weight", n_columns[1]: "b2_weight"})
        wide = metadata.merge(wide, on="unit_id", how="inner", validate="one_to_one")
        wide.insert(1, "election_id", election_id)
        wide.insert(4, "scenario_id", scenario_id)
        wide.insert(5, "model_key", "krt_beta_binomial_nimble_r_exact")
        wide.insert(6, "engine", "R_NIMBLE")
        commune_frames.append(wide)

        aggregate = aggregate.copy()
        aggregate["estimand"] = aggregate["estimand"].map(ESTIMAND_MAP)
        if aggregate["estimand"].isna().any():
            raise AssertionError(f"unknown aggregate estimand for {pair}")
        aggregate["median"] = aggregate.pop("q50")
        aggregate["engine"] = "R_NIMBLE"
        aggregate_frames.append(aggregate)

        finite_rhat = pd.to_numeric(parameters.get("rhat"), errors="coerce")
        finite_bulk = pd.to_numeric(parameters.get("ess_bulk"), errors="coerce")
        finite_tail = pd.to_numeric(parameters.get("ess_tail"), errors="coerce")
        max_rhat = float(finite_rhat.max()) if finite_rhat.notna().any() else np.nan
        min_ess_bulk = float(finite_bulk.min()) if finite_bulk.notna().any() else np.nan
        min_ess_tail = float(finite_tail.min()) if finite_tail.notna().any() else np.nan
        mcmc_status, caveat_class = _rhat_ess_status(max_rhat, min_ess_bulk, min_ess_tail)
        diagnostic_rows.append(
            {
                "panel_id": manifest["panel_id"],
                "election_id": election_id,
                "scenario_id": scenario_id,
                "engine": "R_NIMBLE",
                "model": manifest["model"],
                "sampler": manifest.get("sampler"),
                "max_rhat": max_rhat,
                "min_ess_bulk": min_ess_bulk,
                "min_ess_tail": min_ess_tail,
                "mcmc_status": mcmc_status,
                "mcmc_caveat_class": caveat_class,
                "mcmc_status_basis": "rank_normalized_rhat_and_bulk_tail_ess_non_nuts",
                "bfmi_status": "not_applicable_non_nuts_sampler",
                "divergence_status": "not_applicable_non_nuts_sampler",
                "treedepth_status": "not_applicable_non_nuts_sampler",
                "compile_seconds": float(manifest.get("compile_seconds", np.nan)),
                "sample_seconds": float(manifest.get("sample_seconds", np.nan)),
                "seed": int(manifest["seed"]),
                "chains": int(manifest["chains"]),
                "warmup": int(manifest["warmup"]),
                "draws_per_chain": int(manifest["draws_per_chain"]),
                "king_lambda": float(manifest["king_lambda"]),
                "input_sha256": manifest["input_sha256"],
                "run_dir": portable_path(run_dir, root=ROOT),
            }
        )

    commune_all = pd.concat(commune_frames, ignore_index=True) if commune_frames else pd.DataFrame()
    aggregate_all = pd.concat(aggregate_frames, ignore_index=True) if aggregate_frames else pd.DataFrame()
    diagnostics = pd.DataFrame(diagnostic_rows)
    if not commune_all.empty:
        commune_all = commune_all.sort_values(["scenario_id", "election_id", "sample_rank"])
        commune_all.to_parquet(COMMUNE_PATH, index=False)
    if not aggregate_all.empty:
        aggregate_all = aggregate_all.sort_values(["scenario_id", "election_id", "estimand"])
        aggregate_all.to_parquet(AGGREGATE_PATH, index=False)
    diagnostics = diagnostics.sort_values(["scenario_id", "election_id"]) if not diagnostics.empty else diagnostics
    diagnostics.to_csv(DIAGNOSTICS_PATH, index=False, encoding="utf-8-sig")

    scenario_counts = (
        diagnostics.groupby("scenario_id").size().astype(int).to_dict()
        if not diagnostics.empty
        else {}
    )
    expected_counts = {key: EXPECTED_ELECTIONS[key] for key in EXPECTED_ELECTIONS}
    ready = len(seen_pairs) == EXPECTED_PAIRS and scenario_counts == expected_counts
    mcmc_status_counts = (
        diagnostics["mcmc_status"].value_counts().astype(int).to_dict()
        if not diagnostics.empty
        else {}
    )
    result = {
        "schema_version": "longitudinal_r_krt_exact_consolidation_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "exact_reimplementation_of_pyei_ei_beta_binom_model",
        "engine": "R_NIMBLE",
        "expected_pairs": EXPECTED_PAIRS,
        "consolidated_pairs": len(seen_pairs),
        "commune_rows": len(commune_all),
        "aggregate_rows": len(aggregate_all),
        "scenario_counts": scenario_counts,
        "mcmc_status_counts": mcmc_status_counts,
        "ready": ready,
        "commune_path": portable_path(COMMUNE_PATH, root=ROOT) if COMMUNE_PATH.exists() else None,
        "aggregate_path": portable_path(AGGREGATE_PATH, root=ROOT) if AGGREGATE_PATH.exists() else None,
        "diagnostics_path": portable_path(DIAGNOSTICS_PATH, root=ROOT),
        "hashes": {
            portable_path(path, root=ROOT): file_sha256(path)
            for path in (COMMUNE_PATH, AGGREGATE_PATH, DIAGNOSTICS_PATH)
            if path.exists()
        },
    }
    write_json(MANIFEST_PATH, result)
    return result


def main() -> None:
    print(json.dumps(consolidate(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

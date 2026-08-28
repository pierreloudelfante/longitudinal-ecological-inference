from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, ROOT
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


R_SCRIPT = ROOT / "r_replication" / "run_king_ei_replication.R"
R_LIBRARY = ROOT / ".cache" / "R" / "library"
REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
RUN_DIR = REPLICATION_DIR / "king_ei_runs"
PROGRESS_PATH = REPLICATION_DIR / "king_ei_progress.parquet"
R_COMMUNE_PATH = REPLICATION_DIR / "longitudinal_king_ei_r_commune.parquet"
R_AGGREGATE_PATH = REPLICATION_DIR / "longitudinal_king_ei_r_aggregate.parquet"
AGGREGATE_COMPARISON_PATH = REPLICATION_DIR / "king_python_r_aggregate_comparison.parquet"
COMMUNE_COMPARISON_PATH = REPLICATION_DIR / "king_python_r_commune_comparison.parquet"
COMMUNE_SUMMARY_PATH = REPLICATION_DIR / "king_python_r_commune_comparison_summary.parquet"
MANIFEST_PATH = REPLICATION_DIR / "king_python_r_comparison_manifest.json"


def _rscript_path() -> Path:
    configured = os.environ.get("LONGITUDINAL_RSCRIPT")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"LONGITUDINAL_RSCRIPT does not point to a file: {path}")
    discovered = shutil.which("Rscript")
    if discovered:
        return Path(discovered).resolve()
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        r_root = Path(program_files) / "R"
        for candidate in sorted(r_root.glob("R-*/bin/Rscript.exe"), reverse=True):
            if candidate.is_file():
                return candidate.resolve()
    raise FileNotFoundError(
        "Rscript was not found; add it to PATH or set LONGITUDINAL_RSCRIPT"
    )


def _model_ready_inputs(panel_id: str) -> list[Path]:
    pattern = f"*__H0A__{panel_id}__n2000.csv"
    paths = sorted((OUTPUT_DIR / "model_ready").glob(pattern))
    if len(paths) != 26:
        raise AssertionError(f"expected 26 H0A model-ready CSV files; found {len(paths)}")
    return paths


def _manifest_is_reusable(path: Path, input_csv: Path) -> bool:
    if not path.exists():
        return False
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        manifest.get("status") == "success"
        and int(manifest.get("n_communes", -1)) == 2000
        and manifest.get("scenario_id") == "H0A"
        and manifest.get("input_sha256") == file_sha256(input_csv)
        and manifest.get("mathematical_identity_with_python_model") is False
    )


def _python_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    final_dir = OUTPUT_DIR / SPEC_VERSION / "final"
    aggregate = pd.read_parquet(final_dir / "longitudinal_krt_aggregate.parquet")
    commune = pd.read_parquet(final_dir / "longitudinal_krt_commune.parquet")
    aggregate = aggregate.loc[aggregate["scenario_id"].eq("H0A")].copy()
    commune = commune.loc[commune["scenario_id"].eq("H0A")].copy()
    if aggregate["election_id"].nunique() != 26 or commune["election_id"].nunique() != 26:
        raise AssertionError("Python KRT H0A final tables do not contain 26 elections")
    return aggregate, commune


def _aggregate_comparison(r_aggregate: pd.DataFrame, python: pd.DataFrame) -> pd.DataFrame:
    estimand_map = {
        "beta1_aggregate": "b_1",
        "beta2_aggregate": "b_2",
        "contrast_aggregate": "b_1_minus_b_2",
    }
    left = r_aggregate.copy()
    left["python_estimand"] = left["estimand"].map(estimand_map)
    right = python.rename(
        columns={
            "estimand": "python_estimand",
            "mean": "mean_python_krt",
            "median": "q50_python_krt",
            "q025": "q025_python_krt",
            "q975": "q975_python_krt",
            "run_id": "python_run_id",
            "mcmc_status": "python_mcmc_status",
            "identification_status": "python_identification_status",
        }
    )[
        [
            "panel_id",
            "election_id",
            "scenario_id",
            "python_estimand",
            "python_run_id",
            "mean_python_krt",
            "q025_python_krt",
            "q50_python_krt",
            "q975_python_krt",
            "python_mcmc_status",
            "python_identification_status",
        ]
    ]
    left = left.rename(
        columns={
            "mean": "mean_r_ei",
            "sd": "sd_r_ei",
            "q025": "q025_r_ei",
            "q50": "q50_r_ei",
            "q975": "q975_r_ei",
            "n_posterior_draws": "n_importance_draws_r_ei",
        }
    )
    compared = left.merge(
        right,
        on=["panel_id", "election_id", "scenario_id", "python_estimand"],
        how="inner",
        validate="one_to_one",
    )
    if len(compared) != 78:
        raise AssertionError(f"expected 78 aggregate comparisons; found {len(compared)}")
    compared["difference_r_minus_python"] = compared["mean_r_ei"] - compared["mean_python_krt"]
    compared["absolute_difference"] = compared["difference_r_minus_python"].abs()
    compared["credible_intervals_overlap"] = np.maximum(
        compared["q025_r_ei"], compared["q025_python_krt"]
    ) <= np.minimum(compared["q975_r_ei"], compared["q975_python_krt"])
    return compared


def _commune_comparison(r_commune: pd.DataFrame, python: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    python_long = pd.concat(
        [
            python.assign(parameter="b_1").rename(
                columns={
                    "b1_mean": "mean_python_krt",
                    "b1_sd": "sd_python_krt",
                    "b1_q025": "q025_python_krt",
                    "b1_q50": "q50_python_krt",
                    "b1_q975": "q975_python_krt",
                }
            ),
            python.assign(parameter="b_2").rename(
                columns={
                    "b2_mean": "mean_python_krt",
                    "b2_sd": "sd_python_krt",
                    "b2_q025": "q025_python_krt",
                    "b2_q50": "q50_python_krt",
                    "b2_q975": "q975_python_krt",
                }
            ),
        ],
        ignore_index=True,
    )[
        [
            "panel_id",
            "election_id",
            "scenario_id",
            "unit_id",
            "parameter",
            "mean_python_krt",
            "sd_python_krt",
            "q025_python_krt",
            "q50_python_krt",
            "q975_python_krt",
        ]
    ]
    left = r_commune.rename(
        columns={
            "mean": "mean_r_ei",
            "sd": "sd_r_ei",
            "q025": "q025_r_ei",
            "q50": "q50_r_ei",
            "q975": "q975_r_ei",
        }
    )
    compared = left.merge(
        python_long,
        on=["panel_id", "election_id", "scenario_id", "unit_id", "parameter"],
        how="inner",
        validate="one_to_one",
    )
    if len(compared) != 104_000:
        raise AssertionError(f"expected 104,000 commune comparisons; found {len(compared)}")
    compared["difference_r_minus_python"] = compared["mean_r_ei"] - compared["mean_python_krt"]
    compared["absolute_difference"] = compared["difference_r_minus_python"].abs()
    compared["credible_intervals_overlap"] = np.maximum(
        compared["q025_r_ei"], compared["q025_python_krt"]
    ) <= np.minimum(compared["q975_r_ei"], compared["q975_python_krt"])

    def summarize(group: pd.DataFrame) -> pd.Series:
        valid = group.dropna(subset=["mean_r_ei", "mean_python_krt"])
        correlation = valid["mean_r_ei"].corr(valid["mean_python_krt"]) if len(valid) > 1 else np.nan
        return pd.Series(
            {
                "n_rows": len(group),
                "n_comparable": len(valid),
                "mean_difference_r_minus_python": valid["difference_r_minus_python"].mean(),
                "mean_absolute_difference": valid["absolute_difference"].mean(),
                "median_absolute_difference": valid["absolute_difference"].median(),
                "p95_absolute_difference": valid["absolute_difference"].quantile(0.95),
                "correlation_of_commune_means": correlation,
                "credible_interval_overlap_rate": valid["credible_intervals_overlap"].mean(),
            }
        )

    summary = (
        compared.groupby(["panel_id", "election_id", "scenario_id", "parameter"], sort=True)
        .apply(summarize, include_groups=False)
        .reset_index()
    )
    return compared, summary


def run_r_king_ei_replication(*, force: bool = False) -> dict[str, object]:
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    inputs = _model_ready_inputs(panel_id)
    rscript = _rscript_path()
    R_LIBRARY.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["R_LIBS_USER"] = str(R_LIBRARY)
    progress_rows: list[dict[str, object]] = []
    for sequence, input_csv in enumerate(inputs, start=1):
        election_id = input_csv.name.split("__H0A__", maxsplit=1)[0]
        output_dir = RUN_DIR / f"{election_id}__H0A"
        manifest_path = output_dir / "manifest_r.json"
        status = "skipped_existing_success"
        error = ""
        if force or not _manifest_is_reusable(manifest_path, input_csv):
            completed = subprocess.run(
                [
                    str(rscript),
                    str(R_SCRIPT),
                    str(input_csv),
                    str(output_dir),
                    str(20260802 + sequence - 1),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                status = "success"
            else:
                status = "failed"
                error = (completed.stderr or completed.stdout).strip()
        progress_rows.append(
            {
                "sequence": sequence,
                "panel_id": panel_id,
                "election_id": election_id,
                "scenario_id": "H0A",
                "status": status,
                "error": error,
                "input_csv": portable_path(input_csv, root=ROOT),
                "output_dir": portable_path(output_dir, root=ROOT),
            }
        )
        pd.DataFrame(progress_rows).to_parquet(PROGRESS_PATH, index=False)

    progress = pd.DataFrame(progress_rows)
    if progress["status"].eq("failed").any():
        failures = progress.loc[progress["status"].eq("failed"), ["election_id", "error"]]
        raise RuntimeError(f"R King EI failures:\n{failures.to_string(index=False)}")

    r_commune = pd.concat(
        [pd.read_csv(path / "commune_latent_summaries_r.csv", dtype={"unit_id": "string"}) for path in sorted(RUN_DIR.glob("*__H0A"))],
        ignore_index=True,
    )
    r_aggregate = pd.concat(
        [pd.read_csv(path / "aggregate_summaries_r.csv") for path in sorted(RUN_DIR.glob("*__H0A"))],
        ignore_index=True,
    )
    if len(r_commune) != 104_000 or len(r_aggregate) != 78:
        raise AssertionError(f"unexpected R EI consolidated sizes: {len(r_commune)=}, {len(r_aggregate)=}")
    r_commune.to_parquet(R_COMMUNE_PATH, index=False)
    r_aggregate.to_parquet(R_AGGREGATE_PATH, index=False)

    python_aggregate, python_commune = _python_tables()
    aggregate_comparison = _aggregate_comparison(r_aggregate, python_aggregate)
    commune_comparison, commune_summary = _commune_comparison(r_commune, python_commune)
    aggregate_comparison.to_parquet(AGGREGATE_COMPARISON_PATH, index=False)
    commune_comparison.to_parquet(COMMUNE_COMPARISON_PATH, index=False)
    commune_summary.to_parquet(COMMUNE_SUMMARY_PATH, index=False)

    result = {
        "schema_version": "longitudinal_king_python_r_comparison_v1",
        "status": "success",
        "panel_id": panel_id,
        "scenario_id": "H0A",
        "elections": int(r_aggregate["election_id"].nunique()),
        "n_communes_per_election": 2000,
        "r_model": "King_1997_truncated_bivariate_normal_EI",
        "python_model": "King_Rosen_Tanner_1999_beta_binomial",
        "mathematical_identity": False,
        "same_input_margins_and_unit_ids": True,
        "r_native_importance_draws_per_election": 99,
        "aggregate_rows": len(aggregate_comparison),
        "aggregate_interval_overlap_rate": float(aggregate_comparison["credible_intervals_overlap"].mean()),
        "aggregate_max_absolute_difference": float(aggregate_comparison["absolute_difference"].max()),
        "aggregate_median_absolute_difference": float(aggregate_comparison["absolute_difference"].median()),
        "commune_rows": len(commune_comparison),
        "commune_comparable_rows": int(commune_comparison["mean_r_ei"].notna().sum()),
        "r_script": portable_path(R_SCRIPT, root=ROOT),
        "r_script_sha256": file_sha256(R_SCRIPT),
        "r_commune_output": portable_path(R_COMMUNE_PATH, root=ROOT),
        "r_aggregate_output": portable_path(R_AGGREGATE_PATH, root=ROOT),
        "aggregate_comparison_output": portable_path(AGGREGATE_COMPARISON_PATH, root=ROOT),
        "commune_comparison_output": portable_path(COMMUNE_COMPARISON_PATH, root=ROOT),
        "commune_summary_output": portable_path(COMMUNE_SUMMARY_PATH, root=ROOT),
    }
    write_json(MANIFEST_PATH, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the longitudinal R King EI replication.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_r_king_ei_replication(force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["run_r_king_ei_replication"]

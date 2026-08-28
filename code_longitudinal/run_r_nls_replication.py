from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, ROOT
from .scoped_finalizer import _selected_nls_runs
from .spec_registry import HARMONIZATION_VERSION, SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


R_REPLICATION_DIR = OUTPUT_DIR / SPEC_VERSION / "r_replication"
R_NLS_RUN_DIR = R_REPLICATION_DIR / "nls_runs"
R_NLS_PATH = R_REPLICATION_DIR / "longitudinal_nls_r.parquet"
R_NLS_COMPARISON_PATH = R_REPLICATION_DIR / "nls_python_r_comparison.parquet"
R_NLS_PROGRESS_PATH = R_REPLICATION_DIR / "nls_r_progress.parquet"
R_NLS_MANIFEST_PATH = R_REPLICATION_DIR / "nls_r_manifest.json"
R_SCRIPT_PATH = ROOT / "r_replication" / "run_nls_replication.R"


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
        for path in sorted(r_root.glob("R-*/bin/Rscript.exe"), reverse=True):
            if path.is_file():
                return path.resolve()
    raise FileNotFoundError(
        "Rscript was not found; add it to PATH or set LONGITUDINAL_RSCRIPT"
    )


def _prepared_csv(manifest: dict[str, Any]) -> Path:
    preparation = manifest.get("preparation_manifest", {})
    if not isinstance(preparation, dict) or not preparation.get("output"):
        raise ValueError("missing preparation manifest output")
    parquet = Path(str(preparation["output"]))
    if not parquet.is_absolute():
        parquet = ROOT / parquet
    csv_path = parquet.with_suffix(".csv")
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    return csv_path


def run_r_nls_replication(*, force: bool = False) -> dict[str, object]:
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    runs = [
        (run_dir, manifest)
        for run_dir, manifest in _selected_nls_runs(panel_id)
        if str(manifest.get("model_key", manifest.get("parameters", {}).get("model_key", ""))).startswith("rosen_nls")
    ]
    if len(runs) != 270:
        raise AssertionError(f"R NLS replication requires 270 successful Python NLS runs; found {len(runs)}")
    R_NLS_RUN_DIR.mkdir(parents=True, exist_ok=True)
    rscript = _rscript_path()
    progress_rows: list[dict[str, object]] = []
    r_frames: list[pd.DataFrame] = []
    comparison_frames: list[pd.DataFrame] = []
    for index, (run_dir, manifest) in enumerate(runs, start=1):
        run_id = str(manifest.get("run_id", run_dir.name))
        election_id = str(manifest.get("election_id", manifest["parameters"]["election_id"]))
        scenario_id = str(manifest.get("scenario_id", manifest["parameters"]["scenario_id"]))
        model_csv = _prepared_csv(manifest)
        starts_csv = run_dir / "nls_start_diagnostics.csv"
        python_csv = run_dir / "longitudinal_estimates.csv"
        output_csv = R_NLS_RUN_DIR / f"{run_id}.csv"
        diagnostics_json = R_NLS_RUN_DIR / f"{run_id}.json"
        status = "skipped_existing_success"
        error = ""
        if force or not output_csv.exists() or not diagnostics_json.exists():
            command = [
                str(rscript),
                str(R_SCRIPT_PATH),
                str(model_csv),
                str(starts_csv),
                str(output_csv),
                str(diagnostics_json),
            ]
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            if completed.returncode != 0:
                status = "failed"
                error = (completed.stderr or completed.stdout).strip()
            else:
                status = "success"
        if status != "failed":
            r_frame = pd.read_csv(output_csv)
            r_frame.insert(0, "python_run_id", run_id)
            r_frame.insert(1, "panel_id", panel_id)
            r_frame["spec_version"] = SPEC_VERSION
            r_frame["harmonization_version"] = HARMONIZATION_VERSION
            r_frames.append(r_frame)
            python_frame = pd.read_csv(python_csv)[
                ["election_id", "scenario_id", "social_group", "vote_category", "estimate"]
            ]
            compared = python_frame.merge(
                r_frame[
                    [
                        "python_run_id",
                        "panel_id",
                        "election_id",
                        "scenario_id",
                        "social_group",
                        "vote_category",
                        "estimate_r",
                        "objective_sse_unweighted_r",
                        "optimizer",
                        "convergence",
                    ]
                ],
                on=["election_id", "scenario_id", "social_group", "vote_category"],
                how="inner",
                validate="one_to_one",
            )
            compared = compared.rename(columns={"estimate": "estimate_python"})
            compared["difference_r_minus_python"] = compared["estimate_r"] - compared["estimate_python"]
            comparison_frames.append(compared)
        progress_rows.append(
            {
                "sequence": index,
                "python_run_id": run_id,
                "panel_id": panel_id,
                "election_id": election_id,
                "scenario_id": scenario_id,
                "status": status,
                "error": error,
                "model_ready_csv": portable_path(model_csv, root=ROOT),
                "r_output_csv": portable_path(output_csv, root=ROOT),
            }
        )
        pd.DataFrame(progress_rows).to_parquet(R_NLS_PROGRESS_PATH, index=False)

    progress = pd.DataFrame(progress_rows)
    if progress["status"].eq("failed").any():
        failed = progress.loc[progress["status"].eq("failed"), ["election_id", "scenario_id", "error"]]
        raise RuntimeError(f"R NLS replication failures:\n{failed.to_string(index=False)}")
    r_output = pd.concat(r_frames, ignore_index=True)
    comparison = pd.concat(comparison_frames, ignore_index=True)
    r_output.to_parquet(R_NLS_PATH, index=False)
    comparison.to_parquet(R_NLS_COMPARISON_PATH, index=False)
    max_abs_difference = float(comparison["difference_r_minus_python"].abs().max())
    result = {
        "schema_version": "longitudinal_r_nls_replication_v1",
        "panel_id": panel_id,
        "python_nls_pairs": 270,
        "r_nls_pairs": int(r_output[["election_id", "scenario_id"]].drop_duplicates().shape[0]),
        "comparison_rows": int(len(comparison)),
        "max_abs_difference_r_python": max_abs_difference,
        "tolerance": 1e-6,
        "within_tolerance": bool(max_abs_difference <= 1e-6),
        "r_version": "R 4.6.0",
        "r_optimizer": "stats::optim_BFGS",
        "shared_python_start_vectors": 20,
        "r_script": portable_path(R_SCRIPT_PATH, root=ROOT),
        "r_script_sha256": file_sha256(R_SCRIPT_PATH),
        "r_output": portable_path(R_NLS_PATH, root=ROOT),
        "comparison_output": portable_path(R_NLS_COMPARISON_PATH, root=ROOT),
    }
    write_json(R_NLS_MANIFEST_PATH, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the longitudinal R NLS replication.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_r_nls_replication(force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["R_NLS_COMPARISON_PATH", "R_NLS_PATH", "run_r_nls_replication"]

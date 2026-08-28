from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .paths import ROOT, RUNS_DIR
from .run_r_nls_replication import R_SCRIPT_PATH, _prepared_csv, _rscript_path
from .run_rxc_panel_extension_v11 import DEFAULT_OUTPUT_DIR, EXPECTED_PANEL_SHA256
from .spec_registry import HARMONIZATION_VERSION, SPEC_VERSION
from .utils import file_sha256, write_json


R_OUTPUT_DIR = DEFAULT_OUTPUT_DIR / "r_replication"


def run_replication(*, force: bool = False) -> dict[str, object]:
    progress_path = DEFAULT_OUTPUT_DIR / "rxc_nls_panel_extension_progress.csv"
    progress = pd.read_csv(progress_path, dtype="string")
    if len(progress) != 22 or progress[["election_id", "scenario_id"]].duplicated().any():
        raise ValueError("Python RxC extension must contain exactly 22 unique pairs")
    if not progress["execution_status"].eq("success").all():
        raise ValueError("all Python extension runs must succeed before R replication")
    if not progress["panel_sha256"].eq(EXPECTED_PANEL_SHA256).all():
        raise ValueError("Python extension contains an unexpected panel hash")

    R_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_output_dir = R_OUTPUT_DIR / "runs"
    run_output_dir.mkdir(parents=True, exist_ok=True)
    rscript = _rscript_path()
    progress_rows: list[dict[str, object]] = []
    r_frames: list[pd.DataFrame] = []
    comparison_frames: list[pd.DataFrame] = []

    for index, row in enumerate(progress.itertuples(index=False), start=1):
        run_id = str(row.run_id)
        run_dir = RUNS_DIR / run_id
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        model_csv = _prepared_csv(manifest)
        starts_csv = run_dir / "nls_start_diagnostics.csv"
        python_csv = run_dir / "longitudinal_estimates.csv"
        output_csv = run_output_dir / f"{run_id}.csv"
        diagnostics_json = run_output_dir / f"{run_id}.json"
        status = "skipped_existing_success"
        error = ""
        if force or not output_csv.exists() or not diagnostics_json.exists():
            completed = subprocess.run(
                [
                    str(rscript),
                    str(R_SCRIPT_PATH),
                    str(model_csv),
                    str(starts_csv),
                    str(output_csv),
                    str(diagnostics_json),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                status = "failed"
                error = (completed.stderr or completed.stdout).strip()
            else:
                status = "success"

        if status != "failed":
            r_frame = pd.read_csv(output_csv)
            r_frame.insert(0, "python_run_id", run_id)
            r_frame.insert(1, "panel_sha256", EXPECTED_PANEL_SHA256)
            r_frames.append(r_frame)
            python = pd.read_csv(python_csv)[
                ["election_id", "scenario_id", "social_group", "vote_category", "estimate"]
            ]
            compared = python.merge(
                r_frame[
                    [
                        "python_run_id",
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
            ).rename(columns={"estimate": "estimate_python"})
            compared["difference_r_minus_python"] = compared["estimate_r"] - compared["estimate_python"]
            comparison_frames.append(compared)
        progress_rows.append(
            {
                "sequence": index,
                "python_run_id": run_id,
                "election_id": row.election_id,
                "scenario_id": row.scenario_id,
                "status": status,
                "error": error,
                "model_ready_csv": model_csv.relative_to(ROOT).as_posix(),
                "r_output_csv": output_csv.relative_to(ROOT).as_posix(),
            }
        )
        pd.DataFrame(progress_rows).to_csv(
            R_OUTPUT_DIR / "r_replication_progress.csv", index=False, encoding="utf-8-sig"
        )

    replication_progress = pd.DataFrame(progress_rows)
    if replication_progress["status"].eq("failed").any():
        result = {
            "status": "complete_with_execution_failures",
            "n_pairs_attempted": 22,
            "n_pairs_failed": int(replication_progress["status"].eq("failed").sum()),
            "ready": False,
        }
        write_json(R_OUTPUT_DIR / "r_extension_manifest.json", result)
        return result

    r_output = pd.concat(r_frames, ignore_index=True)
    comparison = pd.concat(comparison_frames, ignore_index=True)
    if r_output[["election_id", "scenario_id"]].drop_duplicates().shape[0] != 22 or len(comparison) != 495:
        raise AssertionError("R replication does not cover the expected 22 pairs / 495 cells")
    pair_summary = (
        comparison.assign(abs_difference=lambda frame: frame["difference_r_minus_python"].abs())
        .groupby(["election_id", "scenario_id"], as_index=False)
        .agg(
            comparison_rows=("abs_difference", "size"),
            max_abs_difference_r_python=("abs_difference", "max"),
            objective_sse_unweighted_r=("objective_sse_unweighted_r", "first"),
            r_convergence=("convergence", "max"),
        )
    )
    python_diagnostics = pd.concat(
        [pd.read_csv(RUNS_DIR / str(row.run_id) / "model_diagnostics.csv") for row in progress.itertuples(index=False)],
        ignore_index=True,
    )[
        ["election_id", "scenario_id", "objective_sse_unweighted", "diagnostic_status", "bread_rank", "bread_condition"]
    ]
    pair_summary = pair_summary.merge(
        python_diagnostics, on=["election_id", "scenario_id"], how="left", validate="one_to_one"
    )
    pair_summary["objective_difference_r_minus_python"] = (
        pair_summary["objective_sse_unweighted_r"] - pair_summary["objective_sse_unweighted"]
    )
    pair_summary["within_1e_6"] = pair_summary["max_abs_difference_r_python"].le(1e-6)
    pair_summary["replication_assessment"] = pair_summary.apply(
        lambda item: (
            "pass"
            if bool(item["within_1e_6"]) and int(item["r_convergence"]) == 0
            else "divergent_or_optimizer_caveat"
        ),
        axis=1,
    )

    r_path = R_OUTPUT_DIR / "longitudinal_nls_r_extension_22.parquet"
    comparison_path = R_OUTPUT_DIR / "nls_python_r_extension_comparison.parquet"
    summary_path = R_OUTPUT_DIR / "nls_python_r_extension_pair_summary.csv"
    r_output.to_parquet(r_path, index=False)
    comparison.to_parquet(comparison_path, index=False)
    pair_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    pair_summary.to_parquet(summary_path.with_suffix(".parquet"), index=False)

    base_r_path = ROOT / "outputs" / SPEC_VERSION / "r_replication" / "longitudinal_nls_r.parquet"
    base_comparison_path = ROOT / "outputs" / SPEC_VERSION / "r_replication" / "nls_python_r_comparison.parquet"
    base_r = pd.read_parquet(base_r_path)
    base_comparison = pd.read_parquet(base_comparison_path)
    panel_ids = base_r["panel_id"].dropna().astype(str).unique().tolist()
    if len(panel_ids) != 1:
        raise AssertionError("base R replication does not contain exactly one panel_id")
    extension_pairs = r_output[["election_id", "scenario_id"]].drop_duplicates()
    base_pairs = base_r[["election_id", "scenario_id"]].drop_duplicates()
    if not extension_pairs.merge(base_pairs, on=["election_id", "scenario_id"]).empty:
        raise AssertionError("R extension overlaps the 270-pair base replication")
    r_extension_normalized = r_output.copy()
    r_extension_normalized["panel_id"] = panel_ids[0]
    r_extension_normalized["spec_version"] = SPEC_VERSION
    r_extension_normalized["harmonization_version"] = HARMONIZATION_VERSION
    r_combined = pd.concat(
        [base_r, r_extension_normalized.reindex(columns=base_r.columns)], ignore_index=True
    )
    comparison_extension_normalized = comparison.copy()
    comparison_extension_normalized["panel_id"] = panel_ids[0]
    comparison_combined = pd.concat(
        [base_comparison, comparison_extension_normalized.reindex(columns=base_comparison.columns)],
        ignore_index=True,
    )
    if r_combined[["election_id", "scenario_id"]].drop_duplicates().shape[0] != 292:
        raise AssertionError("combined R output does not contain 292 pairs")
    if len(r_combined) != 2130 or len(comparison_combined) != 2130:
        raise AssertionError("combined R/Python cell comparison must contain 2,130 rows")
    combined_r_path = R_OUTPUT_DIR / "longitudinal_nls_r_292_candidate.parquet"
    combined_comparison_path = R_OUTPUT_DIR / "nls_python_r_292_comparison_candidate.parquet"
    r_combined.to_parquet(combined_r_path, index=False)
    comparison_combined.to_parquet(combined_comparison_path, index=False)

    maximum = float(pair_summary["max_abs_difference_r_python"].max())
    failed_tolerance = int((~pair_summary["within_1e_6"]).sum())
    result = {
        "status": "complete",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "panel_sha256": EXPECTED_PANEL_SHA256,
        "python_pairs": 22,
        "r_pairs": 22,
        "comparison_rows": 495,
        "max_abs_difference_r_python": maximum,
        "tolerance": 1e-6,
        "pairs_within_tolerance": int(pair_summary["within_1e_6"].sum()),
        "pairs_outside_tolerance": failed_tolerance,
        "within_tolerance_all": failed_tolerance == 0,
        "r_version": "R 4.6.0",
        "r_optimizer": "stats::optim_BFGS",
        "shared_python_start_vectors": 20,
        "ready_for_public_release": bool(failed_tolerance == 0 and pair_summary["diagnostic_status"].eq("pass").all()),
        "outputs": {
            "r_extension": {"path": r_path.relative_to(ROOT).as_posix(), "sha256": file_sha256(r_path)},
            "comparison": {
                "path": comparison_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(comparison_path),
            },
            "pair_summary": {
                "path": summary_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(summary_path),
            },
            "r_292_candidate": {
                "path": combined_r_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(combined_r_path),
            },
            "comparison_292_candidate": {
                "path": combined_comparison_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(combined_comparison_path),
            },
        },
    }
    write_json(R_OUTPUT_DIR / "r_extension_manifest.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Replicate the 22 deferred RxC NLS pairs in R.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_replication(force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

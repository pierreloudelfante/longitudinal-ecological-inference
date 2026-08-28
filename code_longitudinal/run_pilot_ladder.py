from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .paths import CONFIG_DIR, OUTPUT_DIR, ensure_runtime_dirs
from .utils import write_json


PILOT_SCENARIOS = {
    "leg_1962_r1": ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5"),
    "leg_1986_r1": ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"),
    "leg_2022_r1": ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"),
}
EXTENSION_SCENARIOS = {
    "leg_1962_r1": ("H0B", "H0C", "H2", "H3", "H4"),
    "leg_1986_r1": ("H0B", "H0C", "H2", "H3", "H4"),
    "leg_2022_r1": ("H0B", "H0C", "H2", "H3", "H4"),
}
MODELS = ("king_truncated_normal", "krt_beta_binomial")
RESOURCE_LIMITED_KRT_PAIRS = (
    ("leg_1986_r1", "H6", "krt_beta_binomial"),
    ("leg_1986_r1", "H7", "krt_beta_binomial"),
    ("leg_2022_r1", "H5", "krt_beta_binomial"),
)
CALIBRATION = {
    "draws": 20,
    "tune": 20,
    "chains": 1,
    "cores": 1,
    "target_accept": 0.99,
    "random_seed": 20260802,
    "progressbar": False,
}


def _run_isolated_fit(
    election_id: str,
    scenario_id: str,
    model_key: str,
    rung: int,
    *,
    force: bool,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "code_longitudinal.run_pipeline",
        "--stage",
        "2x2",
        "--election-id",
        election_id,
        "--scenario-id",
        scenario_id,
        "--model",
        model_key,
        "--sample-size",
        str(rung),
        "--draws",
        str(CALIBRATION["draws"]),
        "--tune",
        str(CALIBRATION["tune"]),
        "--chains",
        str(CALIBRATION["chains"]),
        "--cores",
        str(CALIBRATION["cores"]),
        "--target-accept",
        str(CALIBRATION["target_accept"]),
        "--random-seed",
        str(CALIBRATION["random_seed"]),
    ]
    if force:
        command.append("--force")
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=12 * 60 * 60,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
        result = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(result, dict):
            raise TypeError(f"unexpected pipeline result: {type(result).__name__}")
    except Exception as exc:
        result = {
            "status": "failed",
            "error": f"isolated_fit_output_error: {exc}",
            "stdout_tail": completed.stdout[-1000:],
        }
    result.setdefault("election_id", election_id)
    result.setdefault("scenario_id", scenario_id)
    result.setdefault("model_key", model_key)
    result.setdefault("sample_size", rung)
    result["isolated_process_exit_code"] = completed.returncode
    if completed.returncode != 0:
        result["stderr_tail"] = completed.stderr[-2000:]
        result["status"] = "failed"
    return result


def _run_ladder_map(
    scenario_map: dict[str, tuple[str, ...]],
    *,
    report_path: Path,
    purpose: str,
    max_rung: int,
    force: bool,
    refresh_initial: bool,
) -> dict[str, object]:
    settings = json.loads((CONFIG_DIR / "run_settings.json").read_text(encoding="utf-8"))
    rungs = [int(value) for value in settings["mcmc"]["ladder"] if int(value) <= max_rung]
    if not rungs or max_rung not in rungs:
        raise ValueError(f"max_rung must be one of {settings['mcmc']['ladder']}")

    results: list[dict[str, object]] = []
    blocked_pairs: set[tuple[str, str, str]] = set()
    for election_id, scenario_ids in scenario_map.items():
        for scenario_id in scenario_ids:
            for model_key in MODELS:
                pair = (election_id, scenario_id, model_key)
                for rung in rungs:
                    if pair in blocked_pairs:
                        break
                    result = _run_isolated_fit(
                        election_id,
                        scenario_id,
                        model_key,
                        rung,
                        force=force or (refresh_initial and rung == rungs[0]),
                    )
                    if str(result.get("status")) == "failed":
                        blocked_pairs.add(pair)
                    results.append(result)
                    write_json(
                        report_path,
                        {
                            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                            "purpose": purpose,
                            "calibration": CALIBRATION,
                            "memory_measurement_scope": "one_isolated_python_process_per_fit",
                            "refresh_initial": refresh_initial,
                            "max_rung": max_rung,
                            "results": results,
                            "blocked_pairs": [list(value) for value in sorted(blocked_pairs)],
                        },
                    )
    successful_or_resumed = sum(
        str(row.get("status")) in {"success", "skipped_existing_success"}
        for row in results
    )
    return {
        "report_path": str(report_path),
        "attempts": len(results),
        "successful_or_resumed": successful_or_resumed,
        "failed": len(results) - successful_or_resumed,
        "blocked_pairs": [list(value) for value in sorted(blocked_pairs)],
        "max_rung": max_rung,
    }


def run_pilot_ladder(
    *,
    max_rung: int = 3000,
    force: bool = False,
    refresh_initial: bool = False,
) -> dict[str, object]:
    """Run the common King/KRT calibration ladder for the focused pilot.

    Runs are deliberately non-substantive (20 draws, one chain). Their purpose
    is to validate the complete n=3000 data/trace/density path and calibrate the
    resource gates before any 4x1000 production fit.
    """
    ensure_runtime_dirs()
    return _run_ladder_map(
        PILOT_SCENARIOS,
        report_path=OUTPUT_DIR / "pilot_1962_1986_2022_ladder_execution.json",
        purpose="non_substantive_full_ladder_pipeline_calibration",
        max_rung=max_rung,
        force=force,
        refresh_initial=refresh_initial,
    )


def run_missing_hypotheses_ladder(*, max_rung: int = 3000) -> dict[str, object]:
    """Run only H0B/H0C/H2/H3/H4, which were absent from the first pilot."""
    ensure_runtime_dirs()
    return _run_ladder_map(
        EXTENSION_SCENARIOS,
        report_path=OUTPUT_DIR / "pilot_extension_missing_hypotheses_execution.json",
        purpose="non_substantive_extension_to_all_admissible_2x2_hypotheses",
        max_rung=max_rung,
        force=False,
        refresh_initial=False,
    )


def retry_extension_resource_limited(*, max_rung: int = 3000) -> dict[str, object]:
    """Retry extension pairs stopped by the first, fixed-overhead-biased gate.

    The normal preflight remains binding. Its memory prediction can now use
    the conservative empirical upper envelope of comparable successful runs.
    """
    ensure_runtime_dirs()
    source_path = OUTPUT_DIR / "pilot_extension_missing_hypotheses_execution.json"
    if not source_path.exists():
        raise FileNotFoundError(f"missing first-pass report: {source_path}")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    blocked_pairs = [tuple(value) for value in source.get("blocked_pairs", [])]
    settings = json.loads((CONFIG_DIR / "run_settings.json").read_text(encoding="utf-8"))
    rungs = [int(value) for value in settings["mcmc"]["ladder"] if int(value) <= max_rung]
    report_path = OUTPUT_DIR / "pilot_extension_empirical_retries.json"
    if report_path.exists():
        previous_report = json.loads(report_path.read_text(encoding="utf-8"))
        results = list(previous_report.get("results", []))
    else:
        results: list[dict[str, object]] = []

    successful_first_pass: dict[tuple[str, str, str], int] = {}
    for row in list(source.get("results", [])) + results:
        if str(row.get("status")) not in {"success", "skipped_existing_success"}:
            continue
        pair = (
            str(row.get("election_id")),
            str(row.get("scenario_id")),
            str(row.get("model_key")),
        )
        successful_first_pass[pair] = max(
            successful_first_pass.get(pair, 0),
            int(row.get("n_communes_requested", row.get("sample_size", 0)) or 0),
        )

    for election_id, scenario_id, model_key in blocked_pairs:
        pair = (str(election_id), str(scenario_id), str(model_key))
        completed_n = successful_first_pass.get(pair, 0)
        for rung in (value for value in rungs if value > completed_n):
            result = _run_isolated_fit(*pair, rung, force=False)
            results.append(result)
            write_json(
                report_path,
                {
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "purpose": "empirical_memory_gate_retry_for_extension_pairs",
                    "calibration": CALIBRATION,
                    "resource_gates_bypassed": False,
                    "memory_estimator": "same_model_upper_envelope_plus_10pct",
                    "max_rung": max_rung,
                    "results": results,
                },
            )
            if str(result.get("status")) == "failed":
                break
    return {
        "report_path": str(report_path),
        "attempts": len(results),
        "successful_or_resumed": sum(
            str(row.get("status")) in {"success", "skipped_existing_success"}
            for row in results
        ),
        "failed": sum(str(row.get("status")) == "failed" for row in results),
        "max_rung": max_rung,
    }


def retry_resource_limited_krt(*, max_rung: int = 3000) -> dict[str, object]:
    """Retry only the three known KRT gaps, preserving every resource gate."""
    ensure_runtime_dirs()
    settings = json.loads((CONFIG_DIR / "run_settings.json").read_text(encoding="utf-8"))
    rungs = [
        int(value)
        for value in settings["mcmc"]["ladder"]
        if 25 < int(value) <= max_rung
    ]
    results: list[dict[str, object]] = []
    for election_id, scenario_id, model_key in RESOURCE_LIMITED_KRT_PAIRS:
        for rung in rungs:
            result = _run_isolated_fit(
                election_id,
                scenario_id,
                model_key,
                rung,
                force=False,
            )
            results.append(result)
            if str(result.get("status")) == "failed":
                break
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "retry_only_previously_memory_limited_krt_pairs",
        "calibration": CALIBRATION,
        "resource_gates_bypassed": False,
        "max_rung": max_rung,
        "results": results,
    }
    write_json(OUTPUT_DIR / "pilot_targeted_krt_retries.json", report)
    return {
        "attempts": len(results),
        "successful_or_resumed": sum(
            str(row.get("status")) in {"success", "skipped_existing_success"}
            for row in results
        ),
        "failed": sum(str(row.get("status")) == "failed" for row in results),
        "max_rung": max_rung,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused 1962-1986-2022 King/KRT calibration ladder")
    parser.add_argument("--max-rung", type=int, default=3000)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--refresh-initial", action="store_true")
    parser.add_argument("--retry-resource-limited", action="store_true")
    parser.add_argument("--missing-hypotheses", action="store_true")
    parser.add_argument("--retry-extension-resource-limited", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    if arguments.retry_extension_resource_limited:
        result = retry_extension_resource_limited(max_rung=arguments.max_rung)
    elif arguments.retry_resource_limited:
        result = retry_resource_limited_krt(max_rung=arguments.max_rung)
    elif arguments.missing_hypotheses:
        result = run_missing_hypotheses_ladder(max_rung=arguments.max_rung)
    else:
        result = run_pilot_ladder(
            max_rung=arguments.max_rung,
            force=arguments.force,
            refresh_initial=arguments.refresh_initial,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))

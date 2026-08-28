from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .prepare_inputs import validate_model_ready
from .run_pilot_ladder import MODELS, PILOT_SCENARIOS
from .spec_registry import ELECTION_BY_ID, ELECTIONS, SCENARIOS, SCENARIO_BY_ID, scenario_is_allowed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_partition_integrity() -> pd.DataFrame:
    """Export one validation row for every admissible 26-election partition."""
    manifests: dict[tuple[str, str], Path] = {}
    for path in (OUTPUT_DIR / "model_ready").glob("*__n3000__manifest.json"):
        manifest = _load_json(path)
        key = (str(manifest.get("election_id", "")), str(manifest.get("scenario_id", "")))
        manifests[key] = path

    rows: list[dict[str, object]] = []
    for election in ELECTIONS:
        for scenario in SCENARIOS:
            if not scenario_is_allowed(scenario, election):
                continue
            key = (election.election_id, scenario.scenario_id)
            manifest_path = manifests.get(key)
            manifest = _load_json(manifest_path) if manifest_path else {}
            checks = manifest.get("checks", {})
            checks = checks if isinstance(checks, dict) else {}
            output_value = str(manifest.get("output", ""))
            output_path = Path(output_value) if output_value else None
            validation_error = ""
            valid = False
            no_duplicate_units = False
            no_negative_values = False
            if output_path is not None and output_path.exists():
                try:
                    frame = pd.read_parquet(output_path)
                    validate_model_ready(frame, scenario)
                    no_duplicate_units = not frame["unit_id"].astype(str).duplicated().any()
                    count_columns = [column for column in frame if column.startswith(("N__", "Y__"))]
                    no_negative_values = bool(frame[count_columns].ge(0).all().all())
                    valid = bool(no_duplicate_units and no_negative_values)
                except Exception as exc:
                    validation_error = str(exc)
            elif manifest_path is None:
                validation_error = "missing_manifest"
            else:
                validation_error = "missing_model_ready_parquet"
            rows.append(
                {
                    "election_id": election.election_id,
                    "election_type": election.election_type,
                    "year": election.year,
                    "scenario_id": scenario.scenario_id,
                    "model_family": scenario.model_family,
                    "n_communes_requested": manifest.get("n_communes_requested", 3000),
                    "n_communes_used": manifest.get("n_communes_used", 0),
                    "n_communes_excluded": manifest.get("n_communes_excluded", 3000),
                    "rows": checks.get("rows", 0),
                    "N_total": checks.get("N_total", 0),
                    "maximum_social_share_gap": checks.get("max_abs_x_sum_minus_one", float("nan")),
                    "maximum_social_count_gap": checks.get("max_abs_social_sum_minus_N", float("nan")),
                    "maximum_vote_count_gap": checks.get("max_abs_vote_sum_minus_N", float("nan")),
                    "no_duplicate_units": no_duplicate_units,
                    "no_negative_values": no_negative_values,
                    "valid": valid,
                    "validation_error": validation_error,
                    "manifest_path": str(manifest_path.relative_to(ROOT)) if manifest_path else "",
                }
            )
    result = pd.DataFrame(rows).sort_values(["election_type", "year", "scenario_id"])
    result.to_csv(
        OUTPUT_DIR / "all_elections_partition_integrity.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


def _successful_calibration_manifests() -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for path in RUNS_DIR.glob("*/manifest.json"):
        manifest = _load_json(path)
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if manifest.get("status") != "success":
            continue
        if parameters.get("model_key") not in MODELS:
            continue
        if not (
            int(parameters.get("draws", 0)) == 20
            and int(parameters.get("tune", 0)) == 20
            and int(parameters.get("chains", 0)) == 1
        ):
            continue
        manifest["_manifest_path"] = str(path.relative_to(ROOT))
        values.append(manifest)
    return values


def build_pilot_model_coverage() -> pd.DataFrame:
    """Summarise the largest successful calibration rung for each pilot pair."""
    success = _successful_calibration_manifests()
    attempt_rows: list[dict[str, Any]] = []
    for filename in (
        "pilot_1962_1986_2022_ladder_execution.json",
        "pilot_targeted_krt_retries.json",
        "pilot_extension_missing_hypotheses_execution.json",
        "pilot_extension_empirical_retries.json",
    ):
        path = OUTPUT_DIR / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        values = payload.get("results", []) if isinstance(payload, dict) else payload
        attempt_rows.extend(row for row in values if isinstance(row, dict))
    failure_text: dict[tuple[str, str, str], str] = {}
    for row in attempt_rows:
        if row.get("status") != "failed":
            continue
        pair = (
            str(row.get("election_id", "")),
            str(row.get("scenario_id", "")),
            str(row.get("model_key", "")),
        )
        failure_text[pair] = str(row.get("error", ""))
    rows: list[dict[str, object]] = []
    for election_id, scenario_ids in PILOT_SCENARIOS.items():
        for scenario_id in scenario_ids:
            for model_key in MODELS:
                candidates = [
                    manifest
                    for manifest in success
                    if manifest.get("parameters", {}).get("election_id") == election_id
                    and manifest.get("parameters", {}).get("scenario_id") == scenario_id
                    and manifest.get("parameters", {}).get("model_key") == model_key
                ]
                candidates.sort(
                    key=lambda manifest: (
                        int(manifest.get("parameters", {}).get("sample_size", 0)),
                        str(manifest.get("finished_at_utc", "")),
                    )
                )
                chosen = candidates[-1] if candidates else {}
                parameters = chosen.get("parameters", {}) if chosen else {}
                largest = int(parameters.get("sample_size", 0)) if parameters else 0
                pair = (election_id, scenario_id, model_key)
                if largest >= 3000:
                    coverage_status = "reached_n3000"
                    limitation = "calibration_non_substantive"
                elif "no rows left after model-specific filtering" in failure_text.get(pair, "") or pair == ("leg_1962_r1", "H5", "king_truncated_normal"):
                    coverage_status = "structurally_inapplicable"
                    limitation = "truncated_normal_filter_leaves_no_interior_rows"
                elif any(
                    marker in failure_text.get(pair, "").lower()
                    for marker in ("memory", "estimated_time", "12-hour", "ladder gate blocked")
                ):
                    coverage_status = "partial_resource_block"
                    limitation = failure_text.get(pair, "resource_gate_blocked")
                elif largest:
                    coverage_status = "partial"
                    limitation = "ladder_not_completed"
                else:
                    coverage_status = "not_run"
                    limitation = "no_successful_calibration"
                election = ELECTION_BY_ID[election_id]
                rows.append(
                    {
                        "election_id": election_id,
                        "year": election.year,
                        "scenario_id": scenario_id,
                        "model_key": model_key,
                        "target_n": 3000,
                        "largest_successful_n_requested": largest,
                        "n_communes_used": chosen.get("n_communes_used", 0) if chosen else 0,
                        "draws": parameters.get("draws", 0) if parameters else 0,
                        "tune": parameters.get("tune", 0) if parameters else 0,
                        "chains": parameters.get("chains", 0) if parameters else 0,
                        "diagnostic_status": chosen.get("diagnostic_status", "") if chosen else "",
                        "coverage_status": coverage_status,
                        "limitation": limitation,
                        "run_id": chosen.get("run_id", "") if chosen else "",
                        "manifest_path": chosen.get("_manifest_path", "") if chosen else "",
                    }
                )
    result = pd.DataFrame(rows).sort_values(["year", "scenario_id", "model_key"])
    result.to_csv(
        OUTPUT_DIR / "pilot_model_coverage.csv", index=False, encoding="utf-8-sig"
    )
    return result


def build_pilot_audit_tables() -> dict[str, int]:
    partitions = build_partition_integrity()
    coverage = build_pilot_model_coverage()
    return {
        "all_elections_partition_integrity": len(partitions),
        "pilot_model_coverage": len(coverage),
    }

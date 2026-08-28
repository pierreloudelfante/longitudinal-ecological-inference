from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .run_rxc_panel_extension_v11 import EXPECTED_PANEL_SHA256
from .spec_registry import ELECTIONS, SCENARIOS, scenario_is_allowed
from .utils import file_sha256, write_json


PRODUCTION_ROOT = OUTPUT_DIR / "longitudinal_2000_v1" / "production"
ALL_2X2_SELECTION = PRODUCTION_ROOT / "all_2x2_candidate" / "krt_240_candidate_selection.csv"
NLS_292 = PRODUCTION_ROOT / "rxc_nls_panel_extension_v11" / "longitudinal_nls_292_candidate.parquet"
NLS_270 = (
    OUTPUT_DIR
    / "longitudinal_2000_v1"
    / "final"
    / "longitudinal_2000_v1.0.2_H0A_H1"
    / "longitudinal_nls.parquet"
)


def _krt_attempts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if parameters.get("model_key") != "krt_beta_binomial":
            continue
        if int(parameters.get("sample_size", 0)) != 2000:
            continue
        if parameters.get("panel_sha256") != EXPECTED_PANEL_SHA256:
            continue
        rows.append(
            {
                "run_id": manifest.get("run_id", path.parent.name),
                "election_id": parameters.get("election_id", manifest.get("election_id", "")),
                "scenario_id": parameters.get("scenario_id", manifest.get("scenario_id", "")),
                "execution_status": manifest.get("status", ""),
                "diagnostic_status": manifest.get("diagnostic_status", "not_yet_available"),
                "sampler_backend": parameters.get("sampler_backend", ""),
                "draws": parameters.get("draws", 0),
                "warmup": parameters.get("tune", 0),
                "run_role": parameters.get("run_role", ""),
                "release_id": parameters.get("release_id", ""),
                "started_at_utc": manifest.get("started_at_utc", ""),
                "finished_at_utc": manifest.get("finished_at_utc", ""),
            }
        )
    return pd.DataFrame(rows)


def build_coverage() -> dict[str, object]:
    nls_path = NLS_292 if NLS_292.exists() else NLS_270
    nls = pd.read_parquet(nls_path)
    nls_pair = (
        nls.sort_values(["election_id", "scenario_id"])
        .groupby(["election_id", "scenario_id"], as_index=False)
        .agg(diagnostic_status=("diagnostic_status", "first"))
    )
    krt_attempts = _krt_attempts()
    # Rebuild the explicit candidate selection so diagnostic counts follow the
    # preregistered canonical/rerun rules instead of the chronologically latest
    # successful attempt.  This matters for the immutable H0A/H1 selections.
    try:
        from .consolidate_current_krt_all_2x2 import consolidate

        consolidate()
    except Exception:
        # Coverage remains available as an operational fallback even if a
        # partially-written external artifact prevents consolidation.
        pass
    if ALL_2X2_SELECTION.exists():
        selected = pd.read_csv(ALL_2X2_SELECTION, dtype="string")
        successful = selected.rename(columns={"mcmc_status": "diagnostic_status"}).copy()
        successful["execution_status"] = "success"
        successful = successful.merge(
            krt_attempts[["run_id", "sampler_backend"]].drop_duplicates("run_id", keep="last"),
            on="run_id",
            how="left",
            validate="one_to_one",
        )
    else:
        successful = krt_attempts.loc[krt_attempts["execution_status"].eq("success")].copy()
        if not successful.empty:
            successful = successful.sort_values("finished_at_utc").drop_duplicates(
                ["election_id", "scenario_id"], keep="last"
            )
    running = krt_attempts.loc[krt_attempts["execution_status"].eq("running")].copy()

    rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        expected = sum(scenario_is_allowed(scenario, election) for election in ELECTIONS)
        nls_part = nls_pair.loc[nls_pair["scenario_id"].eq(scenario.scenario_id)]
        if scenario.model_family == "2x2":
            krt_expected = expected
            krt_part = successful.loc[successful["scenario_id"].eq(scenario.scenario_id)]
            running_part = running.loc[running["scenario_id"].eq(scenario.scenario_id)]
            krt_status = (
                "complete"
                if len(krt_part) == krt_expected
                else "partial"
                if len(krt_part) or len(running_part)
                else "not_started"
            )
        else:
            krt_expected = 0
            krt_part = successful.iloc[0:0]
            running_part = running.iloc[0:0]
            krt_status = "not_in_current_krt_scope"
        nls_counts = nls_part["diagnostic_status"].value_counts()
        krt_counts = krt_part["diagnostic_status"].value_counts()
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "model_family": scenario.model_family,
                "admissible_election_pairs": expected,
                "nls_estimated_pairs": int(len(nls_part)),
                "nls_pass_pairs": int(nls_counts.get("pass", 0)),
                "nls_warning_pairs": int(nls_counts.get("warning", 0)),
                "nls_fail_pairs": int(nls_counts.get("fail", 0)),
                "nls_coverage_status": "complete" if len(nls_part) == expected else "partial",
                "krt_expected_pairs": krt_expected,
                "krt_successful_pairs": int(len(krt_part)),
                "krt_running_manifests": int(len(running_part)),
                "krt_pass_pairs": int(krt_counts.get("pass", 0)),
                "krt_caveat_pairs": int(krt_counts.get("caveat", 0)),
                "krt_fail_pairs": int(krt_counts.get("fail", 0)),
                "krt_backends": "|".join(sorted(krt_part["sampler_backend"].dropna().astype(str).unique())),
                "krt_coverage_status": krt_status,
            }
        )
    coverage = pd.DataFrame(rows)
    output_path = PRODUCTION_ROOT / "current_estimation_coverage.csv"
    coverage.to_csv(output_path, index=False, encoding="utf-8-sig")
    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "panel_sha256": EXPECTED_PANEL_SHA256,
        "nls_source": nls_path.relative_to(ROOT).as_posix(),
        "nls_pairs": int(len(nls_pair)),
        "krt_successful_unique_pairs": int(len(successful)),
        "krt_running_manifest_pairs": int(len(running)),
        "coverage_path": output_path.relative_to(ROOT).as_posix(),
        "coverage_sha256": file_sha256(output_path),
        "ready": False,
        "ready_reason": "remaining KRT hypothesis production is still running",
    }
    write_json(PRODUCTION_ROOT / "current_estimation_coverage.json", result)
    return result


def main() -> None:
    print(json.dumps(build_coverage(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

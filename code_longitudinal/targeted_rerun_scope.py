from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .audit_longitudinal import RUN_PLAN_PATH, build_longitudinal_audit
from .paths import OUTPUT_DIR
from .release_scope import load_release_scope
from .spec_registry import SPEC_VERSION
from .targeted_rerun_remaining import rerun_pair_if_required
from .utils import write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _eligible_pairs(release_config_path: Path) -> tuple[object, pd.DataFrame]:
    scope = load_release_scope(release_config_path)
    if not RUN_PLAN_PATH.exists():
        build_longitudinal_audit()
    plan = pd.read_parquet(RUN_PLAN_PATH)
    selected = plan.loc[
        plan["scenario_id"].isin(scope.krt_scenarios)
        & plan["preparation_status"].eq("admissible")
    ].copy()
    selected = selected.sort_values(["year", "election_type", "election_id", "scenario_id"])
    if selected.duplicated(["election_id", "scenario_id"]).any():
        raise AssertionError("duplicate eligible election/scenario pairs")
    return scope, selected


def run_targeted_scope(release_config_path: Path) -> dict[str, Any]:
    """Recover missing initials and apply at most one strengthened rerun per pair."""
    scope, selected = _eligible_pairs(release_config_path)
    production_dir = OUTPUT_DIR / SPEC_VERSION / "production" / scope.release_id
    production_dir.mkdir(parents=True, exist_ok=True)
    progress_path = production_dir / "targeted_rerun_scope_progress.csv"
    status_path = production_dir / "targeted_rerun_scope_status.json"
    rows: list[dict[str, Any]] = []

    for item in selected.itertuples(index=False):
        election_id = str(item.election_id)
        scenario_id = str(item.scenario_id)
        try:
            result = rerun_pair_if_required(release_config_path, election_id, scenario_id)
            row = {
                "election_id": election_id,
                "scenario_id": scenario_id,
                "status": str(result["status"]),
                "initial_run_id": str(result.get("initial_run_id", "")),
                "selected_run_id": str(result.get("selected_run_id", "")),
                "selection_reason": str(result.get("selection_reason", "")),
                "error": "",
            }
        except Exception as exc:
            row = {
                "election_id": election_id,
                "scenario_id": scenario_id,
                "status": "unresolved",
                "initial_run_id": "",
                "selected_run_id": "",
                "selection_reason": "",
                "error": str(exc),
            }
        rows.append(row)
        frame = pd.DataFrame(rows)
        frame.to_csv(progress_path, index=False, encoding="utf-8-sig")
        write_json(
            status_path,
            {
                "status": "running",
                "release_id": scope.release_id,
                "pairs_expected": int(len(selected)),
                "pairs_checked": int(len(frame)),
                "status_counts": frame["status"].value_counts().to_dict(),
                "current_election_id": election_id,
                "current_scenario_id": scenario_id,
                "updated_at_utc": _utc_now(),
            },
        )

    frame = pd.DataFrame(rows)
    unresolved = int(frame["status"].eq("unresolved").sum()) if not frame.empty else 0
    result = {
        "status": "completed" if unresolved == 0 else "completed_with_unresolved_pairs",
        "release_id": scope.release_id,
        "pairs_expected": int(len(selected)),
        "pairs_checked": int(len(frame)),
        "status_counts": frame["status"].value_counts().to_dict() if not frame.empty else {},
        "unresolved_pairs": unresolved,
        "progress_path": progress_path.relative_to(OUTPUT_DIR.parent).as_posix(),
        "updated_at_utc": _utc_now(),
    }
    write_json(status_path, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover and target strengthened KRT reruns for one release scope.")
    parser.add_argument("--release-config", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(run_targeted_scope(args.release_config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


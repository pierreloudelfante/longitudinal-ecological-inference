from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .h23_pilot_gate import evaluate_krt_run
from .h23_supervisor import _production_dir, _select_pair, _selection_row, _utc_now
from .release_scope import load_release_scope
from .utils import write_json


def rerun_pair_if_required(
    release_config_path: Path,
    election_id: str,
    scenario_id: str,
) -> dict[str, Any]:
    """Apply the preregistered single-rerun rule to one completed initial fit."""
    scope = load_release_scope(release_config_path)
    if scenario_id not in scope.krt_scenarios:
        raise ValueError(f"scenario outside configured release scope: {scenario_id}")

    initial_before = evaluate_krt_run(scope, election_id, scenario_id, rerun=False)
    production_dir = _production_dir(scope)
    output_path = production_dir / f"targeted_rerun__{election_id}__{scenario_id}.json"
    logs_dir = production_dir / "targeted_rerun_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status_path = production_dir / "targeted_rerun_supervisor_status.json"
    state: dict[str, Any] = {
        "status": "running",
        "release_id": scope.release_id,
        "current_election_id": election_id,
        "current_scenario_id": scenario_id,
        "initial_run_id": initial_before["run_id"] if initial_before is not None else "",
        "initial_mcmc_substatus": (
            str(initial_before.get("mcmc_substatus", "fail"))
            if initial_before is not None
            else "initial_fit_missing"
        ),
        "updated_at_utc": _utc_now(),
    }
    write_json(status_path, state)
    selected, decision = _select_pair(
        scope,
        release_config_path,
        election_id,
        scenario_id,
        logs_dir=logs_dir,
        status_path=status_path,
        state=state,
    )
    initial = evaluate_krt_run(scope, election_id, scenario_id, rerun=False)
    if initial is None:
        raise RuntimeError(f"initial KRT fit remains unavailable: {election_id}/{scenario_id}")
    severity = str(initial.get("mcmc_substatus", "fail"))
    selection = _selection_row(selected, decision)
    replaced = bool(selection["replaces_run_id"])
    recovered_initial = initial_before is None
    result = {
        "status": "selected" if replaced else ("initial_recovered" if recovered_initial else "not_required"),
        "election_id": election_id,
        "scenario_id": scenario_id,
        "initial_run_id": initial["run_id"],
        "initial_mcmc_status": initial["mcmc_status"],
        "initial_mcmc_substatus": severity,
        "selected_run_id": selection["run_id"],
        "selected_mcmc_status": selection["mcmc_status"],
        "selected_mcmc_substatus": selection["mcmc_caveat_severity"],
        "selection_reason": selection["selected_reason"],
        "compatibility": decision["compatibility"],
        "updated_at_utc": _utc_now(),
    }
    write_json(output_path, result)
    state.update({"status": "completed", "result_path": output_path.as_posix(), "updated_at_utc": _utc_now()})
    write_json(status_path, state)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one preregistered strengthened KRT rerun when required.")
    parser.add_argument("--release-config", type=Path, required=True)
    parser.add_argument("--election-id", required=True)
    parser.add_argument("--scenario-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = rerun_pair_if_required(args.release_config, args.election_id, args.scenario_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

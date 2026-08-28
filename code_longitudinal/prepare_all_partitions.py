from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .paths import OUTPUT_DIR, ensure_runtime_dirs
from .prepare_inputs import prepare_model_ready
from .spec_registry import ELECTIONS, SCENARIOS, scenario_is_allowed
from .utils import write_json


def prepare_all_partitions(*, sample_size: int = 3000) -> dict[str, object]:
    """Materialise every admissible election/scenario partition independently.

    A failed election/scenario is recorded and the batch continues.  The
    underlying preparation routine validates the raw political margins before
    applying deterministic largest-remainder closure.
    """
    ensure_runtime_dirs()
    results: list[dict[str, object]] = []
    for election in ELECTIONS:
        for scenario in SCENARIOS:
            if not scenario_is_allowed(scenario, election):
                continue
            try:
                _, _, manifest = prepare_model_ready(
                    election,
                    scenario,
                    sample_size=sample_size,
                )
                results.append(
                    {
                        "election_id": election.election_id,
                        "scenario_id": scenario.scenario_id,
                        "status": "success",
                        "n_communes_requested": sample_size,
                        "n_communes_used": int(manifest["n_communes_used"]),
                        "n_communes_excluded": int(manifest["n_communes_excluded"]),
                        "output": str(manifest["output"]),
                        "error": "",
                    }
                )
            except Exception as exc:  # keep the complete longitudinal audit running
                results.append(
                    {
                        "election_id": election.election_id,
                        "scenario_id": scenario.scenario_id,
                        "status": "failed",
                        "n_communes_requested": sample_size,
                        "n_communes_used": 0,
                        "n_communes_excluded": sample_size,
                        "output": "",
                        "error": str(exc),
                    }
                )
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_size": sample_size,
        "expected_admissible_partitions": len(results),
        "successful_partitions": sum(row["status"] == "success" for row in results),
        "failed_partitions": sum(row["status"] == "failed" for row in results),
        "results": results,
    }
    write_json(OUTPUT_DIR / "all_elections_partition_preparation.json", report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare and validate all admissible 1962-2022 partitions"
    )
    parser.add_argument("--sample-size", type=int, default=3000)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = _parse_args()
    print(
        json.dumps(
            prepare_all_partitions(sample_size=arguments.sample_size),
            ensure_ascii=False,
            indent=2,
        )
    )

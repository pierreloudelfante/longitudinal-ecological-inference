from __future__ import annotations

from typing import Iterable

from .run_nls_batch import run_nls
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID


ROBUSTNESS_MATRIX = (
    ("leg_2022_r1", "RXC1", "vbbm"),
    ("leg_2022_r1", "H5", "revenue"),
    ("leg_2022_r1", "H5", "capital"),
    ("leg_2022_r1", "H6", "immigrant_share"),
    ("leg_2022_r1", "H7", "immigrant_share"),
    ("leg_2022_r1", "RXC1", "ne_vs_se"),
)


def run_robustness_batch(
    *,
    sample_size: int = 3000,
    selected: Iterable[tuple[str, str, str]] = ROBUSTNESS_MATRIX,
    force: bool = False,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for election_id, scenario_id, covariate in selected:
        try:
            result = run_nls(
                ELECTION_BY_ID[election_id],
                SCENARIO_BY_ID[scenario_id],
                sample_size=sample_size,
                covariate_name=covariate,
                force=force,
            )
        except Exception as exc:
            result = {
                "status": "failed",
                "election_id": election_id,
                "scenario_id": scenario_id,
                "covariate_name": covariate,
                "error": str(exc),
            }
        results.append(result)
    return results

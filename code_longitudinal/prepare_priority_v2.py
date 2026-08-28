from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .build_common_panel_v2 import COMMON_ELECTION_IDS, DEFAULT_OUTPUT as DEFAULT_PANEL
from .paths import OUTPUT_DIR, ensure_runtime_dirs
from .prepare_inputs import prepare_model_ready
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import write_json


PRIORITY_SCENARIOS = ("H0A", "H1", "H2", "H4")
DEFAULT_AUDIT = OUTPUT_DIR / "v2" / "priority_model_ready_3000_audit.csv"
DEFAULT_MANIFEST = OUTPUT_DIR / "v2" / "priority_model_ready_3000_manifest.json"


def prepare_priority_v2(panel_path: Path = DEFAULT_PANEL) -> pd.DataFrame:
    ensure_runtime_dirs()
    rows: list[dict[str, object]] = []
    for scenario_id in PRIORITY_SCENARIOS:
        for election_id in COMMON_ELECTION_IDS:
            frame, exclusions, manifest = prepare_model_ready(
                ELECTION_BY_ID[election_id],
                SCENARIO_BY_ID[scenario_id],
                sample_size=3000,
                panel_path=panel_path,
            )
            rows.append(
                {
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "sample_id": frame["sample_id"].iloc[0],
                    "n_requested": 3000,
                    "n_used": len(frame),
                    "n_excluded": len(exclusions),
                    "unit_ids_unique": not frame["unit_id"].astype(str).duplicated().any(),
                    "N_total": int(frame["N_g"].sum()),
                    "max_abs_x_sum_minus_one": manifest["checks"]["max_abs_x_sum_minus_one"],
                    "max_abs_social_sum_minus_N": manifest["checks"]["max_abs_social_sum_minus_N"],
                    "max_abs_vote_sum_minus_N": manifest["checks"]["max_abs_vote_sum_minus_N"],
                    "output": manifest["output"],
                }
            )
    audit = pd.DataFrame(rows)
    if not (
        audit["n_used"].eq(3000).all()
        and audit["n_excluded"].eq(0).all()
        and audit["unit_ids_unique"].all()
        and audit["max_abs_social_sum_minus_N"].eq(0).all()
        and audit["max_abs_vote_sum_minus_N"].eq(0).all()
    ):
        raise AssertionError("The exact common 3,000-unit preparation failed validation.")
    DEFAULT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(DEFAULT_AUDIT, index=False, encoding="utf-8-sig")
    write_json(
        DEFAULT_MANIFEST,
        {
            "schema_version": "priority_model_ready_v2.0",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "panel_path": str(panel_path),
            "elections": list(COMMON_ELECTION_IDS),
            "scenarios": list(PRIORITY_SCENARIOS),
            "fits_planned": len(audit),
            "all_exactly_3000": True,
            "audit": str(DEFAULT_AUDIT),
        },
    )
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare exact n=3000 V2 inputs for all priority fits.")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = prepare_priority_v2(args.panel)
    print(json.dumps(audit.to_dict(orient="records"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

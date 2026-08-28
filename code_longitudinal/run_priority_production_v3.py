"""Run H0A/H1 production fits on the quality-repaired 3,000-unit panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import run_priority_production_v2 as runner
from .paths import OUTPUT_DIR, PANEL_DIR, ensure_runtime_dirs


PANEL_PATH = PANEL_DIR / "panel_3000_common_1962_1986_2022_v3.csv"
OUTPUT_V3_DIR = OUTPUT_DIR / "v3"
PROGRESS_PATH = OUTPUT_V3_DIR / "priority_production_progress_v3.json"


def configure_runner() -> None:
    """Give the tested resumable runner an isolated V3 state namespace."""

    runner.RUNNER_SCHEMA_VERSION = "priority_production_v3.0"
    runner.PROGRESS_SCHEMA_VERSION = "priority_production_progress_v3.0"
    runner.PANEL_PATH = PANEL_PATH
    runner.OUTPUT_V2_DIR = OUTPUT_V3_DIR
    runner.PROGRESS_LATEST_PATH = PROGRESS_PATH
    runner.PROGRESS_HISTORY_DIR = OUTPUT_V3_DIR / "progress_history"
    runner.AUDIT_DIR = OUTPUT_V3_DIR / "diagnostic_audits"
    runner.AUDIT_INDEX_PATH = OUTPUT_V3_DIR / "priority_production_diagnostics_v3.csv"
    # Two chains run concurrently; this halves wall time while keeping memory bounded.
    runner.CORES = 2
    runner.SKIP_PREFLIGHT_REASON = (
        "quality_repaired_exact_common_panel_3000_v3_2026-08-04; "
        "four_chains_two_concurrent_cores; resumable_progress_v3_enabled"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Production H0A/H1 on the V3 quality-repaired common panel."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    return parser.parse_args()


def main() -> None:
    ensure_runtime_dirs()
    args = parse_args()
    configure_runner()
    panel_metadata = runner.validate_exact_panel(PANEL_PATH)
    plan = runner.build_plan(panel_metadata)
    progress = runner._load_or_create_progress(plan, panel_metadata)
    selected_ids = runner.select_item_ids(plan, scenarios=("H0A", "H1"))
    summary = runner.progress_summary(
        progress,
        plan,
        retry_failed=args.retry_failed,
        initial_seconds_per_fit=1800.0,
        selected_item_ids=selected_ids,
    )
    print(
        json.dumps(
            {
                "panel": panel_metadata,
                "selected_item_ids": selected_ids,
                "cores": runner.CORES,
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    if args.dry_run:
        return
    runner.execute_plan(
        plan,
        progress,
        retry_failed=args.retry_failed,
        initial_seconds_per_fit=1800.0,
        selected_item_ids=selected_ids,
    )


if __name__ == "__main__":
    main()

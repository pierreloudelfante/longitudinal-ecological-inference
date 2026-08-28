from __future__ import annotations

import argparse
import json
from pathlib import Path

from .paths import ensure_runtime_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configuration-driven longitudinal production pipeline.")
    parser.add_argument(
        "stage",
        choices=("krt", "h23-audit", "h23-gate", "finalize", "migrate-v102", "report-v102", "package-v102"),
    )
    parser.add_argument("--release-config", type=Path, required=True)
    parser.add_argument("--election-id")
    parser.add_argument("--scenario-id")
    parser.add_argument("--canonical-selection", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--draws", type=int)
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--chains", type=int)
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--base-seed", type=int)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--progressbar", action="store_true")
    return parser.parse_args()


def main() -> None:
    ensure_runtime_dirs()
    args = parse_args()
    if args.stage == "krt":
        from .run_longitudinal_production import run_krt_longitudinal

        result = run_krt_longitudinal(
            release_config_path=args.release_config,
            election_id=args.election_id,
            scenario_ids=(args.scenario_id,) if args.scenario_id else None,
            draws=args.draws,
            tune=args.warmup,
            chains=args.chains,
            cores=args.cores,
            base_seed=args.base_seed,
            rerun=args.rerun,
            force=args.force,
            progressbar=args.progressbar,
        )
    elif args.stage == "h23-audit":
        from .h23_pilot_gate import audit_pilot_inputs

        result = audit_pilot_inputs(args.release_config)
    elif args.stage == "h23-gate":
        from .h23_pilot_gate import evaluate_pilot_gate

        result = evaluate_pilot_gate(args.release_config)
    elif args.stage == "finalize":
        if not args.canonical_selection:
            raise ValueError("--canonical-selection is required for finalize")
        from .scoped_finalizer import finalize_scoped_release

        result = finalize_scoped_release(
            release_config_path=args.release_config,
            canonical_selection_path=args.canonical_selection,
        )
    elif args.stage == "migrate-v102":
        if not args.source_root or not args.release_root:
            raise ValueError("--source-root and --release-root are required for migrate-v102")
        from .release_artifacts import build_scoped_artifacts
        from .release_scope import load_release_scope

        result = build_scoped_artifacts(
            args.source_root,
            args.release_root,
            load_release_scope(args.release_config),
        )
    elif args.stage == "report-v102":
        if not args.release_root or not args.output:
            raise ValueError("--release-root and --output are required for report-v102")
        from .render_scoped_report_pdf import render_report

        render_report(args.release_root, args.release_config, args.output)
        result = {"report": str(args.output)}
    else:
        if not args.release_root:
            raise ValueError("--release-root is required for package-v102")
        from .package_scoped_release import package_v102

        result = package_v102(args.release_root, args.release_config)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .paths import CONFIG_DIR, PANEL_DIR, ensure_runtime_dirs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline longitudinal d'inférence écologique 1962-2022")
    parser.add_argument(
        "--stage",
        required=True,
        choices=(
            "panel",
            "schema-pilot",
            "abstention",
            "2x2",
            "rxc-nls",
            "rxc-rosen-benchmark",
            "robustness",
            "consolidate",
            "freeze-benchmark",
            "audit",
            "panel-longitudinal",
            "validate-panel-longitudinal",
            "nls-longitudinal",
            "r-nls-longitudinal",
            "krt-longitudinal",
            "finalize-longitudinal",
            "release-longitudinal",
        ),
    )
    parser.add_argument("--election-id")
    parser.add_argument("--scenario-id")
    parser.add_argument("--model", choices=("king_truncated_normal", "krt_beta_binomial"))
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--draws", type=int)
    parser.add_argument("--tune", type=int)
    parser.add_argument("--chains", type=int)
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument("--target-accept", type=float)
    parser.add_argument("--max-treedepth", type=int)
    parser.add_argument("--random-seed", type=int)
    parser.add_argument("--release-config", type=Path)
    parser.add_argument("--canonical-selection", type=Path)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--covariate")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--progressbar", action="store_true")
    return parser.parse_args()


def _mcmc_args(args: argparse.Namespace, settings: dict[str, object]) -> dict[str, object]:
    mcmc = settings["mcmc"]
    if args.production:
        defaults = (int(mcmc["production_draws"]), int(mcmc["production_tune"]), int(mcmc["production_chains"]), 2000)
    else:
        defaults = (20, 20, 1, 25)
    return {
        "draws": args.draws or defaults[0],
        "tune": args.tune or defaults[1],
        "chains": args.chains or defaults[2],
        "sample_size": args.sample_size or defaults[3],
        "cores": args.cores,
        "target_accept": args.target_accept or float(mcmc["target_accept"]),
        "max_treedepth": args.max_treedepth or 10,
        "random_seed": args.random_seed or 20260802,
        "force": args.force,
        "progressbar": args.progressbar,
    }


def main() -> None:
    ensure_runtime_dirs()
    args = parse_args()
    settings_path = CONFIG_DIR / "run_settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID

    if args.stage == "freeze-benchmark":
        from .freeze_benchmark import freeze_benchmark

        result = freeze_benchmark()
    elif args.stage == "audit":
        from .audit_longitudinal import build_longitudinal_audit

        result = build_longitudinal_audit(settings_path)
    elif args.stage == "panel-longitudinal":
        from .build_longitudinal_panel import build_longitudinal_panel

        result = build_longitudinal_panel(settings_path)
    elif args.stage == "validate-panel-longitudinal":
        from .validate_longitudinal_panel import validate_longitudinal_panel

        result = validate_longitudinal_panel()
    elif args.stage == "nls-longitudinal":
        from .run_longitudinal_production import run_nls_longitudinal

        result = run_nls_longitudinal(
            election_id=args.election_id,
            scenario_id=args.scenario_id,
            force=args.force,
        )
    elif args.stage == "r-nls-longitudinal":
        from .run_r_nls_replication import run_r_nls_replication

        result = run_r_nls_replication(force=args.force)
    elif args.stage == "krt-longitudinal":
        from .run_longitudinal_production import run_krt_longitudinal

        result = run_krt_longitudinal(
            release_config_path=args.release_config,
            election_id=args.election_id,
            scenario_ids=(args.scenario_id,) if args.scenario_id else None,
            draws=args.draws,
            tune=args.tune,
            chains=args.chains,
            cores=args.cores,
            target_accept=args.target_accept,
            max_treedepth=args.max_treedepth,
            base_seed=args.random_seed,
            rerun=args.rerun,
            force=args.force,
            progressbar=args.progressbar,
        )
    elif args.stage == "finalize-longitudinal":
        if args.release_config:
            if not args.canonical_selection:
                raise ValueError("--canonical-selection is required with --release-config")
            from .scoped_finalizer import finalize_scoped_release

            result = finalize_scoped_release(
                release_config_path=args.release_config,
                canonical_selection_path=args.canonical_selection,
            )
        else:
            from .finalize_longitudinal import finalize_longitudinal

            result = finalize_longitudinal()
    elif args.stage == "release-longitudinal":
        from .finalize_longitudinal import build_longitudinal_release

        result = build_longitudinal_release()
    elif args.stage == "panel":
        from .build_panel import build_panel
        from .prepare_inputs import build_presence_ledger

        result = build_panel(settings_path)
        presence = build_presence_ledger(3000)
        result["presence_rows"] = len(presence)
    elif args.stage == "schema-pilot":
        from .build_manifest import build_file_manifest
        from .build_outputs import consolidate_outputs
        from .build_professor_global_recap import build_professor_global_recap
        from .output_schema import initialize_output_schema
        from .prepare_inputs import build_presence_ledger, prepare_model_ready
        from .review_package import build_review_package
        from .run_nls_batch import run_nls
        from .validate_outputs import validate_outputs

        if not (PANEL_DIR / "panel_3000.csv").exists():
            from .build_panel import build_panel

            build_panel(settings_path)
        initialize_output_schema()
        build_presence_ledger(3000)
        for election_id in settings["pilot"]["h0_elections"]:
            prepare_model_ready(ELECTION_BY_ID[election_id], SCENARIO_BY_ID["H0A"], sample_size=3000)
        recent = settings["pilot"]["recent_hypothesis"]
        prepare_model_ready(ELECTION_BY_ID[recent["election_id"]], SCENARIO_BY_ID[recent["scenario_id"]], sample_size=3000)
        nls_spec = settings["pilot"]["nls"]
        nls_result = run_nls(
            ELECTION_BY_ID[nls_spec["election_id"]],
            SCENARIO_BY_ID[nls_spec["scenario_id"]],
            sample_size=args.sample_size or 3000,
            force=args.force,
        )
        consolidation = consolidate_outputs()
        review = build_review_package()
        validation = validate_outputs()
        professor_recap = build_professor_global_recap()
        consolidation.update(
            {f"professor_recap_{key}": value for key, value in professor_recap.items()}
        )
        review = build_review_package()
        manifest = build_file_manifest()
        result = {"nls": nls_result, "consolidation": consolidation, "validation": validation, "review": review, "manifest": manifest}
    elif args.stage in {"abstention", "2x2"}:
        from .run_2x2_batch import run_2x2

        defaults = _mcmc_args(args, settings)
        scenario_id = args.scenario_id or ("H0A" if args.stage == "abstention" else settings["pilot"]["recent_hypothesis"]["scenario_id"])
        election_ids = [args.election_id] if args.election_id else (
            settings["pilot"]["h0_elections"] if args.stage == "abstention" else [settings["pilot"]["recent_hypothesis"]["election_id"]]
        )
        models = [args.model] if args.model else ["king_truncated_normal", "krt_beta_binomial"]
        result = []
        for election_id in election_ids:
            for model in models:
                try:
                    result.append(run_2x2(ELECTION_BY_ID[election_id], SCENARIO_BY_ID[scenario_id], model, **defaults))
                except Exception as exc:
                    result.append({"status": "failed", "election_id": election_id, "scenario_id": scenario_id, "model_key": model, "error": str(exc)})
    elif args.stage == "rxc-nls":
        from .run_nls_batch import run_nls

        election_id = args.election_id or settings["pilot"]["nls"]["election_id"]
        scenario_id = args.scenario_id or settings["pilot"]["nls"]["scenario_id"]
        result = run_nls(
            ELECTION_BY_ID[election_id],
            SCENARIO_BY_ID[scenario_id],
            sample_size=args.sample_size or 3000,
            covariate_name=args.covariate,
            force=args.force,
        )
    elif args.stage == "rxc-rosen-benchmark":
        from .run_rosen_benchmark import run_rosen_benchmark

        defaults = _mcmc_args(args, settings)
        election_ids = [args.election_id] if args.election_id else settings["pilot"]["rosen_elections"]
        result = []
        for election_id in election_ids:
            try:
                result.append(run_rosen_benchmark(ELECTION_BY_ID[election_id], SCENARIO_BY_ID[args.scenario_id or "RXC1"], **defaults))
            except Exception as exc:
                result.append({"status": "failed", "election_id": election_id, "scenario_id": args.scenario_id or "RXC1", "error": str(exc)})
    elif args.stage == "robustness":
        from .run_robustness import run_robustness_batch

        result = run_robustness_batch(sample_size=args.sample_size or 3000, force=args.force)
    else:
        from .build_manifest import build_file_manifest
        from .build_outputs import consolidate_outputs
        from .build_professor_global_recap import build_professor_global_recap
        from .review_package import build_review_package
        from .validate_outputs import validate_outputs

        consolidation = consolidate_outputs()
        review = build_review_package()
        validation = validate_outputs()
        professor_recap = build_professor_global_recap()
        consolidation.update(
            {f"professor_recap_{key}": value for key, value in professor_recap.items()}
        )
        review = build_review_package()
        manifest = build_file_manifest()
        result = {"consolidation": consolidation, "validation": validation, "review": review, "manifest": manifest}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

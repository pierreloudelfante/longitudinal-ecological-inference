from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .build_longitudinal_panel import load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, RUNS_DIR
from .release_scope import load_release_scope


EXPECTED_PANEL_SHA256 = str(load_longitudinal_panel_manifest()["panel_sha256"])


DEFAULT_CONFIG = Path("config/releases/v1.5_retained6.json")
SOURCE_SELECTION = (
    OUTPUT_DIR
    / "longitudinal_2000_v1"
    / "production"
    / "all_2x2_candidate"
    / "krt_240_candidate_selection.csv"
)


def build_selection(*, release_config: Path, output: Path) -> pd.DataFrame:
    scope = load_release_scope(release_config)
    source = pd.read_csv(SOURCE_SELECTION, dtype="string")
    selected = source.loc[source["scenario_id"].isin(scope.krt_scenarios)].copy()
    selected = selected.sort_values(["scenario_id", "election_id"]).reset_index(drop=True)
    if len(selected) != scope.expected_krt_pairs:
        counts = selected.groupby("scenario_id")["election_id"].nunique().to_dict()
        raise RuntimeError(
            f"retained Python scope is incomplete: {len(selected)}/{scope.expected_krt_pairs}; "
            f"counts={counts}"
        )
    if selected[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("duplicate retained election/scenario pair")

    audit_rows: list[dict[str, object]] = []
    for row in selected.itertuples(index=False):
        manifest_path = RUNS_DIR / str(row.run_id) / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = manifest.get("parameters", {})
        checks = {
            "fit_completed": manifest.get("status") == "success",
            "election_matches": parameters.get("election_id") == row.election_id,
            "scenario_matches": parameters.get("scenario_id") == row.scenario_id,
            "panel_size_2000": int(parameters.get("sample_size", 0)) == 2000,
            "panel_hash_matches": parameters.get("panel_sha256") == EXPECTED_PANEL_SHA256,
            "model_is_krt": parameters.get("model_key") == "krt_beta_binomial",
            "commune_output_exists": (manifest_path.parent / "commune_latent_summaries.parquet").is_file(),
            "aggregate_output_exists": (manifest_path.parent / "aggregate_comparison_v2.csv").is_file(),
        }
        if not all(checks.values()):
            raise AssertionError(f"invalid retained run {row.run_id}: {checks}")
        audit_rows.append(
            {
                "election_id": str(row.election_id),
                "scenario_id": str(row.scenario_id),
                "run_id": str(row.run_id),
                "run_role": "canonical",
                "selection_status": str(row.selection_status),
                "mcmc_status": str(row.mcmc_status),
                "identification_status": str(row.identification_status),
                "selection_note": (
                    "canonical completed attempt for the retained reporting scope; "
                    "release readiness remains governed by diagnostics"
                ),
            }
        )
    result = pd.DataFrame(audit_rows).sort_values(["scenario_id", "election_id"])
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the explicit six-scenario KRT selection.")
    parser.add_argument("--release-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_selection(release_config=args.release_config, output=args.output)
    print(
        json.dumps(
            {
                "status": "complete",
                "rows": len(result),
                "scenarios": sorted(result["scenario_id"].unique().tolist()),
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

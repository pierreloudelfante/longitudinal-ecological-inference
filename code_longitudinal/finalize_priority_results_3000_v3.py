"""Finalize the six quality-repaired V3 production fits without rebuilding old ZIPs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .density_figures_v2 import generate_density_figures
from .finalize_priority_results_3000 import (
    SCENARIOS,
    compute_artifacts,
    load_completed_required_fits,
    plot_release_figures,
    validate_artifacts,
    write_artifacts,
)
from .paths import FIGURE_DIR, OUTPUT_DIR, ROOT, ensure_runtime_dirs
from .utils import file_sha256, write_json


PROGRESS_PATH = OUTPUT_DIR / "v3" / "priority_production_progress_v3.json"
OUTPUT_PATH = OUTPUT_DIR / "v3" / "priority_3000_intermediate"
FIGURE_PATH = FIGURE_DIR / "v3" / "priority_3000_intermediate"
PANEL_STEM = "panel_3000_common_1962_1986_2022_v3"
PANEL_PATH = ROOT / "panel" / f"{PANEL_STEM}.csv"


def finalize_v3() -> dict[str, object]:
    ensure_runtime_dirs()
    fits = load_completed_required_fits(progress_path=PROGRESS_PATH)
    artifacts = compute_artifacts(fits)
    validate_artifacts(artifacts)
    paths = write_artifacts(artifacts, output_path=OUTPUT_PATH)
    plot_release_figures(artifacts, figure_path=FIGURE_PATH)
    density_paths, _ = generate_density_figures(
        paths["joint_latent"],
        FIGURE_PATH / "densities",
        metadata_path=OUTPUT_PATH / "density_bandwidths_3000_v1.csv",
        scenarios=SCENARIOS,
    )
    if len(density_paths) != 6:
        raise AssertionError(f"six density figures expected, observed={len(density_paths)}")

    copied: dict[str, str] = {}
    for suffix in (".csv", "_balance.csv", "_attempts.csv", "_denominator_audit.csv", "_manifest.json"):
        source = ROOT / "panel" / f"{PANEL_STEM}{suffix}"
        target = OUTPUT_PATH / source.name
        target.write_bytes(source.read_bytes())
        copied[target.name] = file_sha256(target)

    manifest_path = OUTPUT_PATH / "release_manifest_3000_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "schema_version": "priority_results_3000_intermediate_v3.0",
            "release_status": "intermediate",
            "panel_revision": "v3_quality_repair",
            "panel_path": f"panel/{PANEL_PATH.name}",
            "panel_sha256": file_sha256(PANEL_PATH),
            "model_hyperparameters": {"king_lambda": 0.5},
            "panel_artifact_sha256": copied,
            "source_data_rule": "0 <= exprimes <= votants <= inscrits",
            "source_anomaly_policy": (
                "invalid source rows excluded from the common sampling frame; "
                "no unverifiable numerical correction was imputed"
            ),
        }
    )
    write_json(manifest_path, manifest)
    return {
        "fits": len(fits),
        "output_path": str(OUTPUT_PATH),
        "figure_path": str(FIGURE_PATH),
        "run_ids": [fit.run_id for fit in fits],
        "rows": {name: len(pd.read_csv(path)) for name, path in paths.items()},
    }


if __name__ == "__main__":
    print(json.dumps(finalize_v3(), ensure_ascii=False, indent=2))

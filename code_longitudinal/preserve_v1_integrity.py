from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .paths import ROOT, RUNS_DIR
from .utils import file_sha256, write_json


DEFAULT_MANIFEST = ROOT / "outputs" / "v2" / "preservation_manifest_v1.json"


def protected_v1_files() -> list[Path]:
    paths = [
        ROOT / "deliverables" / "longitudinal_priority_results_clear.zip",
        ROOT / "deliverables" / "longitudinal_priority_results_clear.zip.sha256",
        ROOT / "deliverables" / "longitudinal_2022_release_01.zip",
        ROOT / "deliverables" / "longitudinal_2022_release_01.sha256",
        ROOT / "docs" / "PRIORITY_RESULTS_FOR_PROFESSOR.md",
        ROOT / "docs" / "PRIORITY_CHART_MAP.md",
        ROOT / "outputs" / "priority_best_runs.csv",
        ROOT / "outputs" / "priority_best_estimates.csv",
        ROOT / "outputs" / "priority_joint_beta_data.csv",
        ROOT / "outputs" / "priority_production_diagnostics.csv",
        ROOT / "panel" / "panel_3000.csv",
        ROOT / "panel" / "panel_2000.csv",
        ROOT / "panel" / "panel_manifest.json",
    ]
    paths.extend(sorted((ROOT / "figures" / "priority_production").glob("*")))
    best_path = ROOT / "outputs" / "priority_best_runs.csv"
    if best_path.exists():
        best = pd.read_csv(best_path)
        for run_id in best["run_id"].astype(str):
            run_dir = RUNS_DIR / run_id
            paths.extend(sorted(path for path in run_dir.glob("*") if path.is_file()))
    return sorted({path.resolve() for path in paths if path.exists() and path.is_file()})


def create_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    files = protected_v1_files()
    manifest = {
        "schema_version": "v1_preservation_manifest.1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": (
            "Published V1 deliverables, priority reports/tables/figures, original panel files, "
            "and every file in the 12 V1 selected run directories."
        ),
        "root": str(ROOT),
        "file_count": len(files),
        "files": [
            {
                "path": item.relative_to(ROOT).as_posix(),
                "size_bytes": item.stat().st_size,
                "sha256": file_sha256(item),
            }
            for item in files
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, manifest)
    return manifest


def verify_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    missing: list[str] = []
    changed: list[str] = []
    for row in manifest["files"]:
        item = ROOT / row["path"]
        if not item.exists():
            missing.append(row["path"])
        elif item.stat().st_size != int(row["size_bytes"]) or file_sha256(item) != row["sha256"]:
            changed.append(row["path"])
    return {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": str(path),
        "file_count": int(manifest["file_count"]),
        "missing": missing,
        "changed": changed,
        "integrity_ok": not missing and not changed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or verify the V1 preservation manifest.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = verify_manifest(args.manifest) if args.verify else create_manifest(args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

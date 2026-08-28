from __future__ import annotations

import shutil
from pathlib import Path

from .paths import OUTPUT_DIR, PANEL_DIR, ROOT
from .utils import file_sha256, portable_path, write_json


BENCHMARK_ID = "benchmark_3000_1962_1986_2022_v2"
BENCHMARK_DIR = OUTPUT_DIR / "benchmarks" / BENCHMARK_ID


def freeze_benchmark() -> dict[str, object]:
    """Create an immutable-by-convention snapshot without posterior traces."""
    source_results = OUTPUT_DIR / "v2" / "priority_3000_final"
    if not source_results.exists():
        raise FileNotFoundError(source_results)
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in sorted(source_results.iterdir()):
        if not source.is_file() or source.suffix.lower() == ".nc":
            continue
        target = BENCHMARK_DIR / source.name
        shutil.copy2(source, target)
        copied.append(target)
    for name in (
        "panel_3000_common_1962_1986_2022_v2.csv",
        "panel_3000_common_1962_1986_2022_v2_manifest.json",
        "panel_3000_common_1962_1986_2022_v3.csv",
        "panel_3000_common_1962_1986_2022_v3_manifest.json",
        "panel_3000_common_1962_1986_2022_v3_denominator_audit.csv",
    ):
        source = PANEL_DIR / name
        if source.exists():
            target = BENCHMARK_DIR / name
            shutil.copy2(source, target)
            copied.append(target)
    finalizer = ROOT / "code_longitudinal" / "finalize_priority_results_3000.py"
    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "status": "frozen_historical_benchmark",
        "panel_used_for_estimation": "v2",
        "v3_status": "corrected_future_panel_not_reestimated_in_this_benchmark",
        "known_source_anomalies": 9,
        "known_anomalies_in_v2_panel": ["59473", "14606", "02643", "06149"],
        "historical_finalizer": {
            "path": portable_path(finalizer, root=ROOT),
            "sha256": file_sha256(finalizer),
        },
        "contains_posterior_traces": False,
        "files": [
            {
                "path": path.relative_to(BENCHMARK_DIR).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            for path in copied
        ],
    }
    write_json(BENCHMARK_DIR / "benchmark_manifest.json", manifest)
    return manifest


__all__ = ["BENCHMARK_DIR", "BENCHMARK_ID", "freeze_benchmark"]

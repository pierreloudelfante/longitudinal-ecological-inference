from __future__ import annotations

from pathlib import Path

import pandas as pd

from .paths import OUTPUT_DIR, ROOT, ensure_runtime_dirs
from .utils import file_sha256


EXCLUDED_PARTS = {".cache", "__pycache__", ".pytest_cache", "deliverables"}


def _role(path: Path) -> str:
    first = path.relative_to(ROOT).parts[0]
    return {
        "code_longitudinal": "source_code",
        "config": "configuration",
        "docs": "documentation",
        "tests": "tests",
        "panel": "fixed_panel",
        "outputs": "analytical_output",
        "figures": "figure",
        "review_for_professor_01": "review_package",
    }.get(first, "project_file")


def build_file_manifest() -> dict[str, object]:
    """Create an exact, deterministic inventory of deliverable files.

    The inventory excludes transient caches, generated release replicas and
    itself, because a file cannot truthfully contain its own final digest.
    """
    ensure_runtime_dirs()
    destination = OUTPUT_DIR / "file_manifest.csv"
    rows: list[dict[str, object]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path == destination or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        rows.append(
            {
                "relative_path": relative.as_posix(),
                "role": _role(path),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    frame = pd.DataFrame(rows).sort_values("relative_path")
    frame.to_csv(destination, index=False, encoding="utf-8-sig")
    return {"path": str(destination), "files_inventoried": int(len(frame)), "self_excluded": True}

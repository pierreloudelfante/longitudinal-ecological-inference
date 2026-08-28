from __future__ import annotations

import os
from pathlib import Path


_DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("LONGITUDINAL_PROJECT_ROOT", _DEFAULT_ROOT)).expanduser().resolve()
PART2_ROOT = ROOT.parent
RAW_ARCHIVES = PART2_ROOT / "pour_moi_avec_data" / "data" / "raw" / "archives"
CONFIG_DIR = ROOT / "config"
PANEL_DIR = ROOT / "panel"
OUTPUT_DIR = ROOT / "outputs"
RUNS_DIR = OUTPUT_DIR / "runs"
FIGURE_DIR = ROOT / "figures"
DOCS_DIR = ROOT / "docs"
REVIEW_DIR = ROOT / "review_for_professor_01"
CACHE_DIR = ROOT / ".cache"


def ensure_runtime_dirs() -> None:
    for path in (
        PANEL_DIR,
        OUTPUT_DIR,
        RUNS_DIR,
        FIGURE_DIR,
        DOCS_DIR,
        REVIEW_DIR,
        CACHE_DIR / "matplotlib",
        CACHE_DIR / "numba",
        CACHE_DIR / "pytensor",
    ):
        path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(CACHE_DIR / "matplotlib"))
    os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE_DIR / "numba"))
    flags = os.environ.get("PYTENSOR_FLAGS", "")
    if "base_compiledir" not in flags:
        prefix = f"{flags}," if flags else ""
        os.environ["PYTENSOR_FLAGS"] = f"{prefix}base_compiledir={(CACHE_DIR / 'pytensor').as_posix()}"

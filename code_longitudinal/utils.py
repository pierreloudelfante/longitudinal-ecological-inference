from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


VALID_COMMUNE_RE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$")
PLM_WHOLE = {"75056", "69123", "13055"}
PLM_ARM_TO_WHOLE = {
    **{f"751{i:02d}": "75056" for i in range(1, 21)},
    **{f"6938{i}": "69123" for i in range(1, 10)},
    **{f"132{i:02d}": "13055" for i in range(1, 17)},
}


def normalize_unit_id(value: object) -> str:
    """Normalize a Cagé-Piketty commune code without losing Corsican letters."""
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(5) if text.isdigit() and len(text) < 5 else text


def is_valid_unit_id(value: object) -> bool:
    return bool(VALID_COMMUNE_RE.fullmatch(normalize_unit_id(value)))


def plm_parent(value: object) -> str:
    unit_id = normalize_unit_id(value)
    return PLM_ARM_TO_WHOLE.get(unit_id, unit_id)


def apply_plm_whole(df: pd.DataFrame, *, unit_col: str = "unit_id") -> pd.DataFrame:
    """Use whole Paris/Lyon/Marseille when present; otherwise aggregate arms."""
    out = df.copy()
    out[unit_col] = out[unit_col].map(normalize_unit_id)
    parents = out[unit_col].map(plm_parent)
    whole_present = set(out.loc[out[unit_col].isin(PLM_WHOLE), unit_col])
    drop_arm = out[unit_col].isin(PLM_ARM_TO_WHOLE) & parents.isin(whole_present)
    out = out.loc[~drop_arm].copy()
    out[unit_col] = out[unit_col].map(plm_parent)
    if not out[unit_col].duplicated().any():
        return out
    numeric = [c for c in out.columns if c != unit_col and pd.api.types.is_numeric_dtype(out[c])]
    other = [c for c in out.columns if c not in numeric and c != unit_col]
    agg = {c: "sum" for c in numeric}
    agg.update({c: "first" for c in other})
    return out.groupby(unit_col, as_index=False).agg(agg)


def largest_remainder_round(values: Iterable[float], target: int) -> np.ndarray:
    """Round non-negative cells to integers summing exactly to ``target``."""
    arr = np.asarray(list(values), dtype=float)
    if target < 0 or np.any(~np.isfinite(arr)) or np.any(arr < -1e-9):
        raise ValueError("largest-remainder inputs must be finite and non-negative")
    arr = np.maximum(arr, 0.0)
    if arr.size == 0:
        if target:
            raise ValueError("cannot allocate a positive target to no cells")
        return np.array([], dtype=int)
    if arr.sum() <= 0:
        if target:
            raise ValueError("cannot allocate a positive target from a zero partition")
        return np.zeros(arr.size, dtype=int)
    scaled = arr * (target / arr.sum())
    floors = np.floor(scaled + 1e-12).astype(int)
    diff = int(target - floors.sum())
    if diff > 0:
        order = np.argsort(-(scaled - floors), kind="mergesort")
        floors[order[:diff]] += 1
    elif diff < 0:
        candidates = np.where(floors > 0)[0]
        order = candidates[np.argsort((scaled - floors)[candidates], kind="mergesort")]
        floors[order[: -diff]] -= 1
    if int(floors.sum()) != int(target):
        raise AssertionError(f"largest remainder failed: {floors.sum()} != {target}")
    return floors


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(path: Path, *, root: Path) -> str:
    """Return a POSIX relative path when ``path`` belongs to ``root``."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def canonical_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def new_run_id(run_key: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}__{run_key[:12]}"


def package_versions(names: Iterable[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        if name.lower() == "python":
            versions[name] = platform.python_version()
            continue
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

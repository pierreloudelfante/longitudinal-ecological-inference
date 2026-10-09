from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import ROOT
from .run_r_ei_all_2x2 import _r_library_search_path


R_SCRIPT = ROOT / "r_replication" / "generate_king_ei_density_figures.R"
DEFAULT_OUTPUT = (
    ROOT
    / "outputs"
    / "longitudinal_2000_v1"
    / "r_replication"
    / "density_cross_validation_r"
)
DEFAULT_SCENARIOS = ("H0A", "H1", "H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7")


def _rscript_path() -> Path:
    candidates = [
        Path(r"C:\Program Files\R\R-4.6.0\bin\Rscript.exe"),
        Path(r"C:\Program Files\R\R-4.5.1\bin\Rscript.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Rscript was not found")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _run_r(output_dir: Path, scenarios: tuple[str, ...]) -> None:
    environment = os.environ.copy()
    environment["R_LIBS_USER"] = _r_library_search_path()
    environment["R_LIBS"] = ""
    environment["R_LIBS_SITE"] = ""
    command = [
        str(_rscript_path()),
        "--vanilla",
        str(R_SCRIPT),
        str(ROOT),
        str(output_dir),
        ",".join(scenarios),
    ]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def _validate_grid(grid: pd.DataFrame) -> pd.DataFrame:
    required = {
        "method",
        "scenario_id",
        "election_id",
        "year",
        "density_type",
        "variant",
        "x",
        "y",
        "density",
    }
    missing = sorted(required - set(grid.columns))
    if missing:
        raise AssertionError(f"density grid is missing columns: {missing}")
    if grid.empty:
        raise AssertionError("density grid is empty")
    if not grid["method"].eq("r_eipack").all():
        raise AssertionError("density grid contains an unexpected method")
    if not np.isfinite(grid["x"].to_numpy(float)).all():
        raise AssertionError("density grid x coordinates are not finite")
    density = grid["density"].to_numpy(float)
    if not np.isfinite(density).all() or np.any(density < 0):
        raise AssertionError("density grid contains invalid density values")

    rows: list[dict[str, object]] = []
    keys = ["scenario_id", "election_id", "year", "density_type", "variant"]
    for key, group in grid.groupby(keys, sort=True, dropna=False):
        scenario_id, election_id, year, density_type, variant = key
        x_values = group["x"].drop_duplicates().to_numpy(float)
        expected_rows = len(x_values)
        if density_type == "joint_2d":
            expected_rows *= int(group["y"].nunique(dropna=True))
        if len(group) != expected_rows:
            raise AssertionError(
                f"{key} has {len(group)} grid rows; expected {expected_rows}"
            )
        axis = np.sort(group["x"].unique().astype(float))
        if len(axis) < 2:
            raise AssertionError(f"{key} has an invalid grid axis")
        step = float(axis[1] - axis[0])
        integral = float(group["density"].sum() * step)
        if density_type == "joint_2d":
            if group["y"].isna().any():
                raise AssertionError(f"{key} is missing joint y coordinates")
            integral *= step
        elif not group["y"].isna().all():
            raise AssertionError(f"{key} should have null marginal y coordinates")
        if not 0.10 <= integral <= 1.10:
            raise AssertionError(f"{key} has an implausible [0,1] grid integral: {integral}")
        rows.append(
            {
                "scenario_id": scenario_id,
                "election_id": election_id,
                "year": int(year),
                "density_type": density_type,
                "variant": variant,
                "grid_rows": len(group),
                "grid_step": step,
                "density_min": float(group["density"].min()),
                "density_max": float(group["density"].max()),
                "integral_on_unit_domain": integral,
                "finite_nonnegative": True,
            }
        )
    return pd.DataFrame(rows)


def build(*, output_dir: Path, scenarios: tuple[str, ...], skip_r: bool) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not skip_r:
        _run_r(output_dir, scenarios)

    r_manifest_path = output_dir / "density_cross_validation_r_manifest.json"
    r_manifest = json.loads(r_manifest_path.read_text(encoding="utf-8"))
    completed_raw = r_manifest.get("scenarios_completed", [])
    if isinstance(completed_raw, str):
        completed = (completed_raw,)
    else:
        completed = tuple(str(value) for value in completed_raw)
    if not completed:
        raise AssertionError("R did not complete any density scenario")

    inputs = pd.read_csv(output_dir / "density_inputs_r.csv", dtype={"unit_id": "string"})
    grid = pd.read_csv(output_dir / "density_grid_r.csv")
    bandwidths = pd.read_csv(output_dir / "density_bandwidths_r.csv")
    validation = _validate_grid(grid)

    if set(inputs["scenario_id"].astype(str)) != set(completed):
        raise AssertionError("density input scenarios differ from the R manifest")
    if set(grid["scenario_id"].astype(str)) != set(completed):
        raise AssertionError("density grid scenarios differ from the R manifest")
    if set(bandwidths["scenario_id"].astype(str)) != set(completed):
        raise AssertionError("bandwidth scenarios differ from the R manifest")
    bandwidth_counts = bandwidths.groupby("scenario_id").size()
    if (bandwidth_counts < 4).any():
        raise AssertionError("each completed scenario must have at least four bandwidth rows")

    figure_rows: list[dict[str, object]] = []
    for scenario_id in completed:
        scenario_dir = output_dir / scenario_id
        figures = sorted(
            path for path in scenario_dir.iterdir() if path.suffix.lower() in {".png", ".svg"}
        )
        if len(figures) < 6 or len(figures) % 2:
            raise AssertionError(
                f"{scenario_id} has {len(figures)} figures; expected PNG/SVG pairs"
            )
        for path in figures:
            figure_rows.append(
                {
                    "scenario_id": scenario_id,
                    "figure_name": path.stem,
                    "format": path.suffix.lower().lstrip("."),
                    "path": _portable(path),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    figure_map = pd.DataFrame(figure_rows)
    format_counts = figure_map.groupby(["scenario_id", "figure_name"])["format"].nunique()
    if not format_counts.eq(2).all():
        raise AssertionError("every R density figure must have both PNG and SVG formats")

    parquet_outputs = {
        "density_inputs_r.parquet": inputs,
        "density_grid_r.parquet": grid,
        "density_bandwidths_r.parquet": bandwidths,
        "density_grid_validation_r.parquet": validation,
        "density_figure_map_r.parquet": figure_map,
    }
    for name, frame in parquet_outputs.items():
        frame.to_parquet(output_dir / name, index=False)

    generated_files = sorted(
        [output_dir / name for name in parquet_outputs]
        + [path for path in output_dir.rglob("*.png")]
        + [path for path in output_dir.rglob("*.svg")]
    )
    manifest = {
        "schema_version": "longitudinal_r_density_cross_validation_postprocess_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if set(completed) == set(scenarios) else "partial",
        "scenarios_requested": list(scenarios),
        "scenarios_completed": list(completed),
        "scenarios_skipped_missing_anchor_runs": r_manifest.get(
            "scenarios_skipped_missing_anchor_runs", {}
        ),
        "mathematical_identity_with_python_krt": False,
        "cross_validation_interpretation": (
            "descriptive method comparison; R ei/eiPack and Python KRT are not identical models"
        ),
        "row_counts": {
            "density_inputs": len(inputs),
            "density_grid": len(grid),
            "density_bandwidths": len(bandwidths),
            "density_grid_validation": len(validation),
            "density_figure_map": len(figure_map),
        },
        "files": [
            {
                "path": _portable(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in generated_files
        ],
    }
    manifest_path = output_dir / "density_cross_validation_postprocess_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and validate R-native King EI density figures and Parquet outputs."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scenarios", nargs="+", default=list(DEFAULT_SCENARIOS))
    parser.add_argument(
        "--skip-r",
        action="store_true",
        help="Only validate and convert CSV files already generated by the R script.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build(
        output_dir=args.output_dir.resolve(),
        scenarios=tuple(args.scenarios),
        skip_r=bool(args.skip_r),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import OUTPUT_DIR, ROOT
from .run_rxc_panel_extension_v11 import EXPECTED_PANEL_SHA256
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, portable_path, write_json


PANEL_PATH = ROOT / "panel" / "longitudinal_2000_v1.parquet"
OUTPUT_ROOT = OUTPUT_DIR / SPEC_VERSION / "production" / "all_2x2_candidate"
AUDIT_PATH = OUTPUT_ROOT / "model_ready_240_audit.csv"
MANIFEST_PATH = OUTPUT_ROOT / "model_ready_240_audit.json"
PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
EXPECTED_BY_SCENARIO = {
    "H0A": 26, "H0B": 26, "H0C": 26, "H1": 26,
    "H2": 26, "H3": 26, "H4": 26, "H5": 26,
    "H6": 16, "H7": 16,
}


def audit() -> dict[str, object]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    if file_sha256(PANEL_PATH) != EXPECTED_PANEL_SHA256:
        raise AssertionError("panel SHA-256 mismatch")
    panel = pd.read_parquet(
        PANEL_PATH,
        columns=["unit_id", "included_primary_2000", "master_draw_order"],
    )
    panel = panel.loc[panel["included_primary_2000"]].sort_values("master_draw_order")
    panel_ids = panel["unit_id"].astype("string").tolist()
    if len(panel_ids) != 2000 or len(set(panel_ids)) != 2000:
        raise AssertionError("panel does not contain exactly 2,000 unique unit_id")

    rows: list[dict[str, object]] = []
    for scenario_id, expected in EXPECTED_BY_SCENARIO.items():
        paths = sorted(
            (OUTPUT_DIR / "model_ready").glob(
                f"*__{scenario_id}__{PANEL_ID}__n2000.parquet"
            )
        )
        if len(paths) != expected:
            raise AssertionError(f"{scenario_id}: expected {expected} files, found {len(paths)}")
        for path in paths:
            frame = pd.read_parquet(path)
            csv_path = path.with_suffix(".csv")
            y_columns = [column for column in frame if column.startswith("Y__")]
            n_columns = [column for column in frame if column.startswith("N__")]
            x_columns = [column for column in frame if column.startswith("X__")]
            n_suffixes = [column.removeprefix("N__") for column in n_columns]
            x_suffixes = [column.removeprefix("X__") for column in x_columns]
            partition_columns_valid = bool(
                len(y_columns) == 2
                and len(n_columns) == 2
                and len(x_columns) == 2
                and n_suffixes == x_suffixes
            )
            required = ["unit_id", "N_g", *n_columns, *x_columns, *y_columns]
            missing = sorted(set(required) - set(frame.columns))
            unit_ids = frame["unit_id"].astype("string").tolist() if "unit_id" in frame else []
            count_columns = ["N_g", *n_columns, *y_columns]
            finite_counts = bool(
                partition_columns_valid
                and not missing
                and np.isfinite(frame[count_columns].to_numpy(float)).all()
            )
            nonnegative = bool(
                finite_counts and (frame[count_columns].to_numpy(float) >= 0).all()
            )
            social_gap = (
                float((frame[n_columns].sum(axis=1) - frame["N_g"]).abs().max())
                if partition_columns_valid and not missing else np.nan
            )
            political_gap = (
                float((frame[y_columns].sum(axis=1) - frame["N_g"]).abs().max())
                if partition_columns_valid and not missing else np.nan
            )
            x_gap = (
                float((frame[x_columns].sum(axis=1) - 1.0).abs().max())
                if partition_columns_valid and not missing else np.nan
            )
            x_count_gap = (
                float(
                    np.max(
                        np.abs(
                            frame[x_columns].to_numpy(float)
                            - frame[n_columns].to_numpy(float)
                            / frame["N_g"].to_numpy(float)[:, None]
                        )
                    )
                )
                if partition_columns_valid
                and not missing
                and (frame["N_g"] > 0).all()
                else np.nan
            )
            csv_scientific_equivalent = False
            csv_max_abs_numeric_gap = np.nan
            if csv_path.is_file() and partition_columns_valid and not missing:
                csv_frame = pd.read_csv(csv_path, dtype={"unit_id": "string"})
                scientific_columns = ["unit_id", "N_g", *n_columns, *x_columns, *y_columns]
                if set(scientific_columns).issubset(csv_frame.columns) and len(csv_frame) == len(frame):
                    csv_ids = csv_frame["unit_id"].astype("string").tolist()
                    numeric_columns = ["N_g", *n_columns, *x_columns, *y_columns]
                    parquet_numeric = frame[numeric_columns].to_numpy(float)
                    csv_numeric = csv_frame[numeric_columns].to_numpy(float)
                    csv_max_abs_numeric_gap = float(np.max(np.abs(parquet_numeric - csv_numeric)))
                    csv_scientific_equivalent = bool(
                        csv_ids == unit_ids
                        and np.isfinite(csv_numeric).all()
                        and csv_max_abs_numeric_gap <= 1e-12
                    )
            valid = bool(
                len(frame) == 2000
                and unit_ids == panel_ids
                and len(set(unit_ids)) == 2000
                and partition_columns_valid
                and not missing
                and finite_counts
                and nonnegative
                and social_gap == 0
                and political_gap == 0
                and x_gap <= 1e-12
                and x_count_gap <= 1e-12
                and csv_scientific_equivalent
            )
            rows.append(
                {
                    "election_id": str(frame["election_id"].iloc[0]),
                    "scenario_id": scenario_id,
                    "rows": len(frame),
                    "unique_unit_ids": len(set(unit_ids)),
                    "exact_panel_order": unit_ids == panel_ids,
                    "y_column_count": len(y_columns),
                    "x_columns": "|".join(x_columns),
                    "n_columns": "|".join(n_columns),
                    "y_columns": "|".join(y_columns),
                    "partition_columns_valid": partition_columns_valid,
                    "missing_columns": "|".join(missing),
                    "finite_counts": finite_counts,
                    "nonnegative_counts": nonnegative,
                    "max_abs_social_closure_gap": social_gap,
                    "max_abs_political_closure_gap": political_gap,
                    "max_abs_x_sum_gap": x_gap,
                    "max_abs_x_count_roundtrip_gap": x_count_gap,
                    "csv_scientific_equivalent": csv_scientific_equivalent,
                    "csv_max_abs_numeric_gap": csv_max_abs_numeric_gap,
                    "valid": valid,
                    "model_ready_path": portable_path(path, root=ROOT),
                    "model_ready_sha256": file_sha256(path),
                    "model_ready_csv_path": portable_path(csv_path, root=ROOT),
                    "model_ready_csv_sha256": file_sha256(csv_path) if csv_path.is_file() else None,
                }
            )
    audit_frame = pd.DataFrame(rows).sort_values(["scenario_id", "election_id"])
    audit_frame.to_csv(AUDIT_PATH, index=False, encoding="utf-8-sig")
    invalid = audit_frame.loc[~audit_frame["valid"]]
    result = {
        "schema_version": "longitudinal_model_ready_2x2_audit_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "panel_path": portable_path(PANEL_PATH, root=ROOT),
        "panel_sha256": EXPECTED_PANEL_SHA256,
        "expected_pairs": sum(EXPECTED_BY_SCENARIO.values()),
        "audited_pairs": len(audit_frame),
        "valid_pairs": int(audit_frame["valid"].sum()),
        "invalid_pairs": len(invalid),
        "scenario_counts": audit_frame.groupby("scenario_id").size().to_dict(),
        "maximum_social_closure_gap": float(audit_frame["max_abs_social_closure_gap"].max()),
        "maximum_political_closure_gap": float(audit_frame["max_abs_political_closure_gap"].max()),
        "maximum_parquet_csv_numeric_gap": float(audit_frame["csv_max_abs_numeric_gap"].max()),
        "parquet_csv_scientific_equivalence_all_pairs": bool(
            audit_frame["csv_scientific_equivalent"].all()
        ),
        "exact_panel_order_all_pairs": bool(audit_frame["exact_panel_order"].all()),
        "ready_for_estimation": bool(invalid.empty),
        "audit_path": portable_path(AUDIT_PATH, root=ROOT),
        "audit_sha256": file_sha256(AUDIT_PATH),
    }
    write_json(MANIFEST_PATH, result)
    if not invalid.empty:
        raise AssertionError(f"{len(invalid)} model-ready pairs failed the 2x2 audit")
    return result


def main() -> None:
    print(json.dumps(audit(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

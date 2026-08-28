from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODEL_READY_DIR = ROOT / "outputs" / "model_ready"
RUNS_DIR = ROOT / "outputs" / "runs"
HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "shared_inputs"
RESULT_DIR = HERE / "results"

SAMPLE_ID = "panel_3000_seed_20260802"
ELECTIONS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
SCENARIOS = {
    "H0A": {
        "event": "abstention",
        "group_1": "target_group",
        "group_2": "complement_group",
        "label": "Abstention — ouvriers et employés vs autres CSP",
    },
    "H1": {
        "event": "gauche",
        "group_1": "target_group",
        "group_2": "complement_group",
        "label": "Vote à gauche — ouvriers et employés vs autres CSP",
    },
}

# These are the six existing PyEI truncated-normal runs on the same nominal
# 3,000-unit panel.  They are intentionally pinned rather than selected by
# "latest", so the comparison remains reproducible.
PYTHON_RUNS = {
    ("leg_1962_r1", "H0A"): "20260803T124845Z__faf7b595820c",
    ("leg_1962_r1", "H1"): "20260803T125654Z__3cf18c478208",
    ("leg_1986_r1", "H0A"): "20260803T130726Z__9a9495902439",
    ("leg_1986_r1", "H1"): "20260803T131358Z__ccb76ff99324",
    ("leg_2022_r1", "H0A"): "20260803T134739Z__5611ce5a46b0",
    ("leg_2022_r1", "H1"): "20260803T135343Z__254948175c29",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_model_ready(election_id: str, scenario_id: str) -> Path:
    pattern = f"{election_id}__{scenario_id}__{SAMPLE_ID}__n3000.csv"
    path = MODEL_READY_DIR / pattern
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def truncated_normal_filter(frame: pd.DataFrame, scenario_id: str) -> pd.Series:
    event = SCENARIOS[scenario_id]["event"]
    x = frame["X__target_group"].astype(float)
    y = frame[f"Y__{event}"].astype(float) / frame["N_g"].astype(float)
    tolerance = 1e-9
    valid = x.gt(tolerance) & x.lt(1 - tolerance) & y.gt(tolerance) & y.lt(1 - tolerance)
    interior = valid.copy()
    if valid.any():
        xv = x.loc[valid].to_numpy()
        yv = y.loc[valid].to_numpy()
        b1_lower = np.maximum(0.0, (yv - 1.0 + xv) / xv)
        b1_upper = np.minimum(1.0, yv / xv)
        b2_lower = np.maximum(0.0, (yv - xv) / (1.0 - xv))
        b2_upper = np.minimum(1.0, yv / (1.0 - xv))
        width = np.maximum(b1_upper - b1_lower, b2_upper - b2_lower)
        interior.loc[valid] = width > tolerance
    return interior


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []

    for election_id in ELECTIONS:
        year = int(election_id.split("_")[1])
        for scenario_id, scenario in SCENARIOS.items():
            source_path = find_model_ready(election_id, scenario_id)
            source = pd.read_csv(source_path, dtype={"unit_id": "string", "sample_id": "string"})
            if len(source) > 3000 or source["unit_id"].duplicated().any():
                raise AssertionError(f"Unexpected prepared input shape in {source_path}")
            keep = truncated_normal_filter(source, scenario_id)
            fit = source.loc[keep].copy()
            event = str(scenario["event"])
            fit["x"] = fit["X__target_group"].astype(float)
            fit["t"] = fit[f"Y__{event}"].astype(float) / fit["N_g"].astype(float)
            fit["N1"] = fit["N__target_group"].astype(int)
            fit["N2"] = fit["N__complement_group"].astype(int)
            fit["Y1"] = fit[f"Y__{event}"].astype(int)
            complement_col = next(col for col in fit.columns if col.startswith("Y__") and col != f"Y__{event}")
            fit["Y2"] = fit[complement_col].astype(int)
            columns = [
                "unit_id",
                "sample_id",
                "sample_rank",
                "election_id",
                "year",
                "scenario_id",
                "N_g",
                "N1",
                "N2",
                "Y1",
                "Y2",
                "x",
                "t",
            ]
            shared = fit.loc[:, columns].copy()
            output_path = INPUT_DIR / f"{election_id}__{scenario_id}__king_common_input.csv"
            shared.to_csv(output_path, index=False, encoding="utf-8")

            run_id = PYTHON_RUNS[(election_id, scenario_id)]
            run_dir = RUNS_DIR / run_id
            latent_path = run_dir / "commune_latent_summaries.csv"
            diagnostic_path = run_dir / "model_diagnostics.csv"
            estimate_path = run_dir / "longitudinal_estimates.csv"
            for required in (latent_path, diagnostic_path, estimate_path, run_dir / "manifest.json"):
                if not required.exists():
                    raise FileNotFoundError(required)
            latent = pd.read_csv(latent_path, dtype={"unit_id": "string"})
            order_match = latent["unit_id"].astype(str).tolist() == shared["unit_id"].astype(str).tolist()
            if not order_match:
                raise AssertionError(f"Unit order differs from pinned Python run {run_id}")

            accounting_error = np.max(np.abs(shared["x"] * shared["N_g"] - shared["N1"]))
            vote_error = np.max(np.abs(shared["t"] * shared["N_g"] - shared["Y1"]))
            key = f"{election_id}__{scenario_id}"
            manifest_rows.append(
                {
                    "comparison_key": key,
                    "election_id": election_id,
                    "year": year,
                    "scenario_id": scenario_id,
                    "scenario_label": scenario["label"],
                    "event": event,
                    "group_1": scenario["group_1"],
                    "group_2": scenario["group_2"],
                    "nominal_panel_n": 3000,
                    "effective_n": len(shared),
                    "python_run_id": run_id,
                    "shared_input": str(output_path.relative_to(HERE)).replace("\\", "/"),
                    "shared_input_sha256": sha256(output_path),
                    "source_input": str(source_path.relative_to(ROOT)).replace("\\", "/"),
                    "source_input_sha256": sha256(source_path),
                }
            )
            audit_rows.append(
                {
                    "comparison_key": key,
                    "nominal_rows": 3000,
                    "prepared_rows": len(source),
                    "excluded_during_preparation": 3000 - len(source),
                    "effective_rows": len(shared),
                    "excluded_degenerate_rows": int((~keep).sum()),
                    "duplicate_unit_ids": int(shared["unit_id"].duplicated().sum()),
                    "python_unit_order_match": order_match,
                    "N_total": int(shared["N_g"].sum()),
                    "x_min": float(shared["x"].min()),
                    "x_max": float(shared["x"].max()),
                    "t_min": float(shared["t"].min()),
                    "t_max": float(shared["t"].max()),
                    "max_group_count_roundtrip_error": float(accounting_error),
                    "max_vote_count_roundtrip_error": float(vote_error),
                    "shared_input_sha256": sha256(output_path),
                }
            )

    manifest = pd.DataFrame(manifest_rows).sort_values(["scenario_id", "year"])
    audit = pd.DataFrame(audit_rows).sort_values("comparison_key")
    manifest.to_csv(RESULT_DIR / "comparison_manifest.csv", index=False, encoding="utf-8-sig")
    audit.to_csv(RESULT_DIR / "input_audit.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "analysis": "King 2x2 EI comparison: PyEI truncated_normal vs R ei",
        "nominal_panel": SAMPLE_ID,
        "hypotheses": list(SCENARIOS),
        "elections": list(ELECTIONS),
        "input_policy": "R receives the exact post-filter rows and row order used by the pinned Python fit.",
        "important_model_note": (
            "Both implementations target King's truncated-normal 2x2 EI family, but they do not share "
            "the same sampler or identical prior parameterization. This is an implementation comparison, "
            "not a bit-for-bit posterior replication and not a comparison to PyEI king99 beta-binomial."
        ),
    }
    (RESULT_DIR / "analysis_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(manifest.to_string(index=False))
    print("\nInput audit")
    print(audit.to_string(index=False))


if __name__ == "__main__":
    main()

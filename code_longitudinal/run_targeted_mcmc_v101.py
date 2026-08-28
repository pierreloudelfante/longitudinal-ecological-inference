from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .paths import PANEL_DIR, ROOT, RUNS_DIR
from .run_2x2_batch import run_2x2
from .run_h1_panel_sensitivity_v101 import _aggregate_draws, _interval_overlap
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import file_sha256


RELEASE_ROOT = ROOT / "work" / "longitudinal_2000_v1.0.1_H0A_H1_candidate"
SYNTHESIS_DIR = RELEASE_ROOT / "02_syntheses"
AUX_DIR = RELEASE_ROOT / "07_auxiliary_runs" / "targeted_mcmc_reruns"
PANEL_RUNTIME_DIR = AUX_DIR / "runtime_panel"
CANONICAL_PATH = SYNTHESIS_DIR / "canonical_run_selection.csv"

TARGETS = (
    ("pre_2007_r1", "H0A"),
    ("leg_2007_r1", "H0A"),
    ("leg_2002_r1", "H0A"),
    ("pre_2012_r1", "H1"),
    ("leg_2022_r1", "H1"),
    # Longest observed canonical fit: kept last so the five shorter robustness
    # runs are safely checkpointed first if the workstation is interrupted.
    ("leg_2017_r1", "H1"),
)


def _ensure_dirs() -> None:
    for path in (SYNTHESIS_DIR, AUX_DIR, PANEL_RUNTIME_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _runtime_panel() -> Path:
    source = PANEL_DIR / "longitudinal_2000_v1.parquet"
    if file_sha256(source) != "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a":
        raise AssertionError("primary/master panel hash changed")
    panel = pd.read_parquet(source).sort_values("master_draw_order").copy()
    original_units = panel.head(2000)["unit_id"].astype("string").tolist()
    panel_id = "v101_targeted_rerun_current_primary_2000"
    panel["panel_id"] = panel_id
    panel["sample_id"] = panel_id
    path = PANEL_RUNTIME_DIR / "current_primary_2000_targeted_rerun.parquet"
    if path.exists():
        existing = pd.read_parquet(path).sort_values("master_draw_order")
        existing_units = existing.head(2000)["unit_id"].astype("string").tolist()
        if existing_units != original_units or not existing["panel_id"].astype("string").eq(panel_id).all():
            raise AssertionError("existing targeted-rerun runtime panel is incompatible")
    else:
        panel.to_parquet(path, index=False)
    written = pd.read_parquet(path).sort_values("master_draw_order").head(2000)
    if written["unit_id"].astype("string").tolist() != original_units:
        raise AssertionError("targeted-rerun panel does not preserve the primary 2,000 unit order")
    return path


def _find_completed_run(election_id: str, scenario_id: str, panel_sha256: str) -> str:
    matches: list[tuple[str, str]] = []
    for path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        params = manifest.get("parameters", {})
        if (
            manifest.get("status") == "success"
            and params.get("election_id") == election_id
            and params.get("scenario_id") == scenario_id
            and params.get("model_key") == "krt_beta_binomial"
            and int(params.get("sample_size", 0)) == 2000
            and int(params.get("draws", 0)) == 2000
            and int(params.get("tune", 0)) == 2000
            and int(params.get("chains", 0)) == 4
            and int(params.get("random_seed", 0)) == 20260817
            and params.get("panel_sha256") == panel_sha256
        ):
            matches.append((str(manifest.get("finished_at_utc", "")), path.parent.name))
    if not matches:
        raise RuntimeError(f"no successful targeted rerun found for {election_id}/{scenario_id}")
    return sorted(matches)[-1][1]


def run_targeted() -> pd.DataFrame:
    _ensure_dirs()
    panel_path = _runtime_panel()
    panel_sha = file_sha256(panel_path)
    canonical = pd.read_csv(CANONICAL_PATH, dtype="string")
    registry_path = AUX_DIR / "auxiliary_run_registry.csv"
    if registry_path.exists():
        registry = pd.read_csv(registry_path, dtype="string")
    else:
        registry = pd.DataFrame()
    for election_id, scenario_id in TARGETS:
        initial = canonical.loc[
            canonical["election_id"].eq(election_id) & canonical["scenario_id"].eq(scenario_id)
        ]
        if len(initial) != 1:
            raise AssertionError(f"expected one initial canonical run for {election_id}/{scenario_id}")
        result = run_2x2(
            ELECTION_BY_ID[election_id],
            SCENARIO_BY_ID[scenario_id],
            "krt_beta_binomial",
            sample_size=2000,
            draws=2000,
            tune=2000,
            chains=4,
            cores=1,
            target_accept=0.99,
            max_treedepth=14,
            random_seed=20260817,
            force=False,
            progressbar=False,
            panel_path=panel_path,
            skip_preflight=True,
            preflight_override_reason="v1.0.1 targeted robustness rerun requested by release protocol",
        )
        run_id = str(result.get("run_id") or _find_completed_run(election_id, scenario_id, panel_sha))
        row = pd.DataFrame(
            [
                {
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "old_run_id": str(initial.iloc[0]["run_id"]),
                    "new_run_id": run_id,
                    "run_role": "targeted_rerun",
                    "panel_sha256": panel_sha,
                    "status": "success",
                }
            ]
        )
        if not registry.empty:
            keep = ~(
                registry["election_id"].eq(election_id)
                & registry["scenario_id"].eq(scenario_id)
            )
            registry = registry.loc[keep]
        registry = pd.concat([registry, row], ignore_index=True)
        registry = registry.sort_values(["scenario_id", "election_id"])
        registry.to_csv(registry_path, index=False, encoding="utf-8-sig")
    return registry


def _diagnostics(run_id: str) -> dict[str, Any]:
    run_dir = RUNS_DIR / run_id
    mcmc = json.loads((run_dir / "mcmc_diagnostics_v2.json").read_text(encoding="utf-8"))
    identification = json.loads((run_dir / "identification_diagnostics.json").read_text(encoding="utf-8"))
    return {
        "mcmc_status": str(mcmc.get("mcmc_status", "unknown")),
        "identification_status": str(identification.get("identification_status", "unknown")),
        "max_rhat": float(mcmc.get("max_rhat", np.nan)),
        "min_ess_bulk": float(mcmc.get("min_ess_bulk", np.nan)),
        "min_ess_tail": float(mcmc.get("min_ess_tail", np.nan)),
        "min_bfmi": float(mcmc.get("min_bfmi", np.nan)),
        "divergences": int(mcmc.get("divergences", 0)),
        "treedepth_hits": int(mcmc.get("max_treedepth_hits", 0)),
        "treedepth_hit_fraction": float(mcmc.get("max_treedepth_hit_fraction", np.nan)),
    }


def _sign_supported(low: float, high: float) -> int:
    if low > 0:
        return 1
    if high < 0:
        return -1
    return 0


def finalize_targeted() -> pd.DataFrame:
    registry_path = AUX_DIR / "auxiliary_run_registry.csv"
    if not registry_path.exists():
        raise FileNotFoundError("run the six targeted fits before finalization")
    registry = pd.read_csv(registry_path, dtype="string")
    canonical = pd.read_csv(CANONICAL_PATH, dtype="string")
    rows: list[dict[str, Any]] = []
    ready_blocker = False
    for item in registry.itertuples(index=False):
        old_arrays, old_stats = _aggregate_draws(item.old_run_id)
        new_arrays, new_stats = _aggregate_draws(item.new_run_id)
        old_diag = _diagnostics(item.old_run_id)
        new_diag = _diagnostics(item.new_run_id)
        old_low, old_high = old_stats["contrast_q025"], old_stats["contrast_q975"]
        new_low, new_high = new_stats["contrast_q025"], new_stats["contrast_q975"]
        overlap, overlap_ratio = _interval_overlap(old_low, old_high, new_low, new_high)
        sign_inversion = _sign_supported(old_low, old_high) * _sign_supported(new_low, new_high) == -1
        compatible = bool(overlap and not sign_inversion)
        stability = "pass" if compatible else "fail"
        old_status = old_diag["mcmc_status"]
        new_status = new_diag["mcmc_status"]
        if old_status == "pass":
            selected_run = item.old_run_id
            selected_reason = "initial_pass_remains_canonical"
        elif new_status == "pass" and compatible:
            selected_run = item.new_run_id
            selected_reason = "initial_caveat_new_pass_compatible"
        elif old_status == "caveat" and new_status == "caveat" and compatible:
            selected_run = item.new_run_id
            selected_reason = "both_caveat_compatible_long_run_selected"
        else:
            selected_run = item.old_run_id
            selected_reason = "no_automatic_replacement_incompatible_or_failed"
            ready_blocker = True
        selected_diag = new_diag if selected_run == item.new_run_id else old_diag
        mask = canonical["election_id"].eq(item.election_id) & canonical["scenario_id"].eq(item.scenario_id)
        if int(mask.sum()) != 1:
            raise AssertionError(f"canonical selection mismatch for {item.election_id}/{item.scenario_id}")
        canonical.loc[mask, "run_id"] = selected_run
        canonical.loc[mask, "mcmc_status"] = selected_diag["mcmc_status"]
        canonical.loc[mask, "identification_status"] = selected_diag["identification_status"]
        canonical.loc[mask, "run_role"] = "canonical"
        canonical.loc[mask, "selected_reason"] = selected_reason
        canonical.loc[mask, "replaces_run_id"] = item.old_run_id if selected_run == item.new_run_id else ""
        rows.append(
            {
                "election_id": item.election_id,
                "scenario_id": item.scenario_id,
                "old_run_id": item.old_run_id,
                "new_run_id": item.new_run_id,
                "old_contrast_mean": old_stats["contrast_mean"],
                "old_contrast_q025": old_low,
                "old_contrast_q975": old_high,
                "old_contrast_mcse": old_stats["contrast_mcse"],
                "new_contrast_mean": new_stats["contrast_mean"],
                "new_contrast_q025": new_low,
                "new_contrast_q975": new_high,
                "new_contrast_mcse": new_stats["contrast_mcse"],
                "intervals_overlap": overlap,
                "overlap_ratio": overlap_ratio,
                "supported_sign_inversion": sign_inversion,
                "old_mcmc_status": old_status,
                "new_mcmc_status": new_status,
                "mcmc_status": selected_diag["mcmc_status"],
                "identification_status": selected_diag["identification_status"],
                "estimate_stability_status": stability,
                "old_max_rhat": old_diag["max_rhat"],
                "new_max_rhat": new_diag["max_rhat"],
                "old_min_ess_bulk": old_diag["min_ess_bulk"],
                "new_min_ess_bulk": new_diag["min_ess_bulk"],
                "old_min_ess_tail": old_diag["min_ess_tail"],
                "new_min_ess_tail": new_diag["min_ess_tail"],
                "old_min_bfmi": old_diag["min_bfmi"],
                "new_min_bfmi": new_diag["min_bfmi"],
                "old_divergences": old_diag["divergences"],
                "new_divergences": new_diag["divergences"],
                "old_treedepth_hits": old_diag["treedepth_hits"],
                "new_treedepth_hits": new_diag["treedepth_hits"],
                "old_treedepth_hit_fraction": old_diag["treedepth_hit_fraction"],
                "new_treedepth_hit_fraction": new_diag["treedepth_hit_fraction"],
                "selected_run_id": selected_run,
                "selected_reason": selected_reason,
                "ready_blocker": selected_reason == "no_automatic_replacement_incompatible_or_failed",
            }
        )
    if len(canonical) != 52 or canonical[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("canonical selection must retain exactly 52 unique KRT pairs")
    canonical.to_csv(CANONICAL_PATH, index=False, encoding="utf-8-sig")
    result = pd.DataFrame(rows)
    result.to_csv(SYNTHESIS_DIR / "targeted_mcmc_reruns.csv", index=False, encoding="utf-8-sig")
    (AUX_DIR / "ready_blocker.txt").write_text(str(ready_blocker).lower() + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run v1.0.1 targeted KRT robustness fits.")
    parser.add_argument("stage", choices=("run", "finalize", "all"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.stage in {"run", "all"}:
        print(run_targeted().to_json(orient="records"))
    if args.stage in {"finalize", "all"}:
        print(finalize_targeted().to_json(orient="records"))


if __name__ == "__main__":
    main()

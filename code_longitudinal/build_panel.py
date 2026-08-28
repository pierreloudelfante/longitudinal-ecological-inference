from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .balance_checks import CATEGORICAL_BALANCE, CONTINUOUS_BALANCE, balance_summary, compute_balance_checks
from .data_io import load_reference_universe
from .paths import CONFIG_DIR, FIGURE_DIR, PANEL_DIR, RAW_ARCHIVES, ensure_runtime_dirs
from .spec_registry import ELECTION_BY_ID
from .utils import file_sha256, write_json


def load_settings(path: Path | None = None) -> dict[str, object]:
    settings_path = path or CONFIG_DIR / "run_settings.json"
    return json.loads(settings_path.read_text(encoding="utf-8"))


def _save_balance_figures(universe: pd.DataFrame, sample: pd.DataFrame) -> None:
    output = FIGURE_DIR / "panel_balance"
    output.mkdir(parents=True, exist_ok=True)
    for column in CONTINUOUS_BALANCE:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ax.hist(universe[column], bins=35, density=True, alpha=0.45, label=f"univers (n={len(universe)})")
        ax.hist(sample[column], bins=35, density=True, alpha=0.55, label=f"panel (n={len(sample)})")
        ax.set_title(f"Équilibre du panel — {column}")
        ax.set_xlabel(column)
        ax.set_ylabel("Densité")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output / f"continuous__{column}.png", dpi=160)
        fig.savefig(output / f"continuous__{column}.svg")
        plt.close(fig)
    for column in CATEGORICAL_BALANCE:
        levels = sorted(universe[column].dropna().astype(str).unique())
        up = [universe[column].astype(str).eq(level).mean() for level in levels]
        sp = [sample[column].astype(str).eq(level).mean() for level in levels]
        x = np.arange(len(levels))
        fig, ax = plt.subplots(figsize=(max(7, len(levels) * 0.55), 4.5))
        ax.bar(x - 0.2, up, width=0.4, label="univers")
        ax.bar(x + 0.2, sp, width=0.4, label="panel")
        ax.set_xticks(x, levels, rotation=45, ha="right")
        ax.set_ylabel("Proportion")
        ax.set_title(f"Équilibre du panel — {column}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output / f"categorical__{column}.png", dpi=160)
        fig.savefig(output / f"categorical__{column}.svg")
        plt.close(fig)


def build_panel(settings_path: Path | None = None) -> dict[str, object]:
    ensure_runtime_dirs()
    settings = load_settings(settings_path)
    panel_settings = settings["panel"]
    universe = load_reference_universe(ELECTION_BY_ID["leg_2022_r1"])
    panel_size = int(panel_settings["master_panel_size"])
    pilot_size = int(panel_settings["primary_panel_size"])
    if len(universe) < panel_size:
        raise ValueError(f"reference universe has {len(universe)} units, fewer than {panel_size}")

    attempts: list[dict[str, object]] = []
    accepted: pd.DataFrame | None = None
    accepted_checks: pd.DataFrame | None = None
    accepted_pilot_checks: pd.DataFrame | None = None
    accepted_seed: int | None = None
    for attempt in range(int(panel_settings["max_attempts"])):
        seed = int(panel_settings["panel_seed"]) + attempt
        order = np.random.default_rng(seed).permutation(len(universe))
        candidate = universe.iloc[order[:panel_size]].copy()
        candidate["sample_rank"] = np.arange(1, panel_size + 1)
        checks = compute_balance_checks(universe, candidate)
        panel_summary = balance_summary(
            checks,
            max_smd=float(panel_settings["max_abs_smd"]),
            max_category_gap=float(panel_settings["max_abs_category_gap"]),
        )
        pilot_candidate = candidate.iloc[:pilot_size]
        pilot_checks = compute_balance_checks(universe, pilot_candidate)
        pilot_summary = balance_summary(
            pilot_checks,
            max_smd=float(panel_settings["max_abs_smd"]),
            max_category_gap=float(panel_settings["max_abs_category_gap"]),
        )
        both_accepted = bool(panel_summary["accepted"] and pilot_summary["accepted"])
        attempts.append(
            {
                "attempt": attempt + 1,
                "seed": seed,
                "accepted": both_accepted,
                **{f"panel_3000_{key}": value for key, value in panel_summary.items()},
                **{f"panel_2000_{key}": value for key, value in pilot_summary.items()},
            }
        )
        if both_accepted:
            accepted = candidate
            accepted_checks = checks
            accepted_pilot_checks = pilot_checks
            accepted_seed = seed
            break
    if accepted is None or accepted_checks is None or accepted_pilot_checks is None or accepted_seed is None:
        raise RuntimeError("no balanced panel found within max_attempts")

    sample_id = f"panel_3000_seed_{accepted_seed}"
    accepted.insert(1, "sample_id", sample_id)
    accepted.insert(2, "sample_seed", accepted_seed)
    accepted["included_panel_3000"] = True
    pilot = accepted.iloc[:pilot_size].copy()
    pilot["sample_id"] = f"panel_2000_nested_seed_{accepted_seed}"
    pilot["included_panel_2000"] = True
    pilot_checks = accepted_pilot_checks
    accepted_checks.insert(0, "sample_id", sample_id)
    pilot_checks.insert(0, "sample_id", f"panel_2000_nested_seed_{accepted_seed}")
    checks_all = pd.concat([accepted_checks, pilot_checks], ignore_index=True)

    accepted.to_csv(PANEL_DIR / "panel_3000.csv", index=False, encoding="utf-8-sig")
    pilot.to_csv(PANEL_DIR / "panel_2000.csv", index=False, encoding="utf-8-sig")
    checks_all.to_csv(PANEL_DIR / "panel_balance_checks.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(attempts).to_csv(PANEL_DIR / "panel_balance_attempts.csv", index=False, encoding="utf-8-sig")
    _save_balance_figures(universe, accepted)

    panel_3000_summary = balance_summary(
        accepted_checks,
        max_smd=float(panel_settings["max_abs_smd"]),
        max_category_gap=float(panel_settings["max_abs_category_gap"]),
    )
    panel_2000_summary = balance_summary(
        pilot_checks,
        max_smd=float(panel_settings["max_abs_smd"]),
        max_category_gap=float(panel_settings["max_abs_category_gap"]),
    )
    manifest = {
        "status": "accepted",
        "reference_year": 2022,
        "reference_universe_definition": "valid stable id; 2022 registered > 0; complete non-negative six-CSP base; positive CSP total; VBBM and metropolitan region present",
        "universe_size": int(len(universe)),
        "sample_id": sample_id,
        "sample_seed": accepted_seed,
        "attempts": len(attempts),
        "panel_3000": panel_3000_summary,
        "panel_2000_nested": panel_2000_summary,
        "source_sha256": {
            name: file_sha256(RAW_ARCHIVES / name)
            for name in ("political_leg_2022_csv.zip", "socio_csp_csv.zip", "socio_agl_csv.zip")
        },
        "selection_is_outcome_blind": True,
    }
    write_json(PANEL_DIR / "panel_manifest.json", manifest)
    return manifest

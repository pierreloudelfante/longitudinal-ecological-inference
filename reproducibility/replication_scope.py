"""Selection only: complete and bounded runs share the same production workers.

No sampler settings, diagnostic thresholds, or result values belong here.
The frozen historical contracts remain authoritative for both scopes.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "reproducibility" / "contract_v2"
ENVIRONMENT_KEY = "LONGITUDINAL_REPLICATION_SCOPE"
SCENARIO_IDS = ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7")
# One election per hypothesis, two longitudinal H0A/H1 contrasts, and one
# legislative/reinforced-sampling case. This covers all five historical
# backend/parameterization/draw-count combinations without shortening a fit.
COURT_PAIRS = frozenset(
    [("pre_2022_r1", scenario) for scenario in SCENARIO_IDS]
    + [("pre_2017_r1", "H0A"), ("pre_2017_r1", "H1"), ("leg_2022_r1", "H1")]
)


@dataclass(frozen=True)
class ReplicationScope:
    name: str
    pairs: frozenset[tuple[str, str]]
    nls_pairs: frozenset[tuple[str, str]]
    extension_nls_pairs: frozenset[tuple[str, str]]

    @property
    def is_full(self) -> bool:
        return self.name == "full"

    @property
    def base_nls_pairs(self):
        return self.nls_pairs - self.extension_nls_pairs

    @property
    def canonical_pairs(self):
        return frozenset((e, s) for e, s in self.pairs if s in {"H0A", "H1"})

    @property
    def election_ids(self):
        return tuple(sorted({e for e, _ in self.pairs}))

    @property
    def scenario_ids(self):
        return tuple(s for s in SCENARIO_IDS if any(t == s for _, t in self.pairs))

    @property
    def pair_count(self) -> int:
        return len(self.pairs)

    @property
    def density_count(self) -> int:
        return 2 * self.pair_count

    def filter_frame(self, frame):
        """Project by available scientific identifiers, without changing values."""
        if self.is_full:
            return frame.copy()
        if {"election_id", "scenario_id"}.issubset(frame.columns):
            mask = [(str(e), str(s)) in self.nls_pairs
                    for e, s in zip(frame["election_id"], frame["scenario_id"])]
            return frame.loc[mask].copy()
        if "election_id" in frame.columns:
            return frame.loc[frame["election_id"].astype(str).isin(self.election_ids)].copy()
        if "scenario_id" in frame.columns:
            scenarios = {s for _, s in self.nls_pairs}
            return frame.loc[frame["scenario_id"].astype(str).isin(scenarios)].copy()
        return frame.copy()

    def nls_rows(self, pairs=None) -> int:
        from code_longitudinal.spec_registry import SCENARIO_BY_ID
        total = 0
        for _, scenario in self.nls_pairs if pairs is None else pairs:
            spec = SCENARIO_BY_ID[scenario]
            # 2x2: four cell probabilities + one group contrast.
            total += 5 if spec.model_family == "2x2" else len(spec.social_groups) * len(spec.vote_categories)
        return total

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "pairs": [list(pair) for pair in sorted(self.pairs)],
            "nls_pairs": [list(pair) for pair in sorted(self.nls_pairs)],
            "base_nls_pairs": [list(pair) for pair in sorted(self.base_nls_pairs)],
            "extension_nls_pairs": [list(pair) for pair in sorted(self.extension_nls_pairs)],
            "pair_count": self.pair_count,
            "density_count": self.density_count,
            "complete_raw_panel": True,
            "sampling_contract_unchanged": True,
            "complete_campaign": self.is_full,
        }


def get_scope(name: str | None = None) -> ReplicationScope:
    name = name or os.environ.get(ENVIRONMENT_KEY, "full")
    if name not in {"full", "court"}:
        raise ValueError("Unknown replication scope: " + name)
    entries = json.loads((CONTRACT / "krt_replay_240.json").read_text(encoding="utf-8"))["entries"]
    all_pairs = frozenset((r["election_id"], r["scenario_id"]) for r in entries)
    if len(all_pairs) != len(entries) or len(all_pairs) != 240:
        raise ValueError("Invalid historical KRT pair contract")
    pairs = all_pairs if name == "full" else COURT_PAIRS
    if not pairs <= all_pairs:
        raise ValueError("Scoped pair missing from historical contract")
    elections = {e for e, _ in pairs}
    nls_pairs = pairs | frozenset((e, s) for e in elections for s in ("RXC1", "RXC2"))
    with (ROOT / "reproducibility/reference/rxc_ineligible_audit.csv").open(encoding="utf-8-sig", newline="") as stream:
        deferred = frozenset((r["election_id"], r["scenario_id"]) for r in csv.DictReader(stream))
    if len(deferred) != 22:
        raise ValueError("Invalid historical RxC extension contract")
    return ReplicationScope(name, pairs, nls_pairs, nls_pairs & deferred)

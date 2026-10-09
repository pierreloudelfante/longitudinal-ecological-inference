"""Deterministic inventory projection, independent of scientific dependencies.

The source contract is always the complete, frozen reference inventory. Its
hashes identify historical reference files, not projected candidate contents.
No candidate files or numerical reference outputs are read to plan a scope.
"""
from __future__ import annotations

from copy import deepcopy
import re


def project_result_contract(contract: dict, scope) -> dict:
    """Keep the full output architecture, reducing only pair-dependent volume.

Global plots, reports, diagnostics, panel and documentation retain their
required paths and formats. Only individual densities and their family atlases
have pair-dependent paths. The eight final table schemas are unchanged.
"""
    projected = deepcopy(contract)
    if scope.is_full:
        return projected
    pairs = frozenset(scope.pairs)
    family_scenarios = {
        ("legislative" if election.startswith("leg_") else "presidential", scenario)
        for election, scenario in pairs
    }
    rows = {
        "longitudinal_contrasts_krt_r_nls.parquet": 3 * scope.pair_count,
        "longitudinal_krt_aggregate.parquet": 3 * scope.pair_count,
        "longitudinal_krt_commune.parquet": 2000 * scope.pair_count,
        "longitudinal_nls.parquet": scope.nls_rows(),
        "longitudinal_nls_covariate_coefficients.parquet": 28 * scope.pair_count,
        "longitudinal_nls_covariates.parquet": 12 * scope.pair_count,
        "longitudinal_r_ei_aggregate.parquet": 3 * scope.pair_count,
        "longitudinal_r_ei_commune.parquet": 2000 * scope.pair_count,
    }
    selected = []
    for entry in projected["files"]:
        path = entry["path"]
        density = re.fullmatch(r"03_FIGURES/densites_completes/[^/]+/([^/]+)/([^/]+)\.png", path)
        atlas = re.fullmatch(r"03_FIGURES/atlas_densites_resumes/[^/]+/([^/]+)/([^/]+)\.png", path)
        if density and (density[2], density[1]) not in pairs:
            continue
        if atlas and (atlas[2], atlas[1]) not in family_scenarios:
            continue
        if "parquet" in entry:
            name = path.rsplit("/", 1)[-1]
            if name not in rows:
                raise ValueError("No explicit scope row contract for " + path)
            entry["parquet"]["rows"] = rows[name]
        selected.append(entry)
    projected["files"] = selected
    projected["scope_projection"] = {
        "scope": scope.as_dict(),
        "full_reference_file_count": len(contract["files"]),
        "expected_file_count": len(selected),
        "omitted_paths": sorted({r["path"] for r in contract["files"]} - {r["path"] for r in selected}),
        "historical_hashes_are_not_projected_candidate_hashes": True,
        "global_artifact_comparison_remains_required": True,
    }
    return projected

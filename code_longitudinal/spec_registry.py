from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


CSP_GROUPS = ("agri", "indp", "cadr", "pint", "empl", "ouvr")
VOTE_BLOCKS = ("voteG", "voteCG", "voteC", "voteCD", "voteD")
MODEL_2X2_KEYS = (
    "king_truncated_normal",
    "krt_beta_binomial",
    "rosen_nls_2x2_unadjusted",
)
SPEC_VERSION = "longitudinal_2000_v1"
HARMONIZATION_VERSION = "stable_unit_geography_v1"


@dataclass(frozen=True)
class ElectionSpec:
    election_id: str
    election_type: str
    year: int
    round: int
    archive_name: str
    member_name: str
    rn_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    model_family: str
    social_groups: Mapping[str, tuple[str, ...]]
    vote_categories: tuple[str, ...]
    vote_definition: str
    denominator: str
    min_year: int
    models: tuple[str, ...]


LEGISLATIVE_YEARS = (1962, 1967, 1968, 1973, 1978, 1981, 1986, 1988, 1993, 1997, 2002, 2007, 2012, 2017, 2022)
PRESIDENTIAL_YEARS = (1965, 1969, 1974, 1981, 1988, 1995, 2002, 2007, 2012, 2017, 2022)

RN_LEGISLATIVE = {**{year: ("voixFN",) for year in LEGISLATIVE_YEARS if 1986 <= year <= 2017}, 2022: ("voixRN",)}
RN_PRESIDENTIAL = {
    1988: ("voixLEPEN",),
    1995: ("voixLEPEN",),
    2002: ("voixLEPEN",),
    2007: ("voixLEPEN",),
    2012: ("voixMLEPEN",),
    2017: ("voixMLEPEN",),
    2022: ("voixMLEPEN",),
}


def _elections() -> tuple[ElectionSpec, ...]:
    rows: list[ElectionSpec] = []
    for year in LEGISLATIVE_YEARS:
        rows.append(
            ElectionSpec(
                election_id=f"leg_{year}_r1",
                election_type="legislative",
                year=year,
                round=1,
                archive_name=f"political_leg_{year}_csv.zip",
                member_name=f"leg{year}comm.csv",
                rn_columns=RN_LEGISLATIVE.get(year, ()),
            )
        )
    for year in PRESIDENTIAL_YEARS:
        rows.append(
            ElectionSpec(
                election_id=f"pre_{year}_r1",
                election_type="presidential",
                year=year,
                round=1,
                archive_name=f"political_pre_{year}_csv.zip",
                member_name=f"pres{year}comm.csv",
                rn_columns=RN_PRESIDENTIAL.get(year, ()),
            )
        )
    return tuple(rows)


ELECTIONS = _elections()
ELECTION_BY_ID = {item.election_id: item for item in ELECTIONS}


def _binary_groups(target: tuple[str, ...]) -> Mapping[str, tuple[str, ...]]:
    complement = tuple(group for group in CSP_GROUPS if group not in target)
    return {"target_group": target, "complement_group": complement}


SCENARIOS = (
    ScenarioSpec("H0A", "2x2", _binary_groups(("ouvr", "empl")), ("abstention", "participation"), "abstention", "registered", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H0B", "2x2", _binary_groups(("ouvr",)), ("abstention", "participation"), "abstention", "registered", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H0C", "2x2", _binary_groups(("empl",)), ("abstention", "participation"), "abstention", "registered", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H1", "2x2", _binary_groups(("ouvr", "empl")), ("gauche", "non_gauche"), "left", "expressed", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H2", "2x2", _binary_groups(("ouvr",)), ("gauche", "non_gauche"), "left", "expressed", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H3", "2x2", _binary_groups(("empl",)), ("gauche", "non_gauche"), "left", "expressed", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H4", "2x2", {"agri_indp": ("agri", "indp"), "salaries": ("cadr", "pint", "empl", "ouvr")}, ("droite", "reste"), "right", "expressed", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H5", "2x2", _binary_groups(("cadr",)), ("centre", "non_centre"), "centre", "expressed", 1962, MODEL_2X2_KEYS),
    ScenarioSpec("H6", "2x2", _binary_groups(("ouvr",)), ("fn_rn", "non_fn_rn"), "rn", "expressed", 1986, MODEL_2X2_KEYS),
    ScenarioSpec("H7", "2x2", _binary_groups(("empl",)), ("fn_rn", "non_fn_rn"), "rn", "expressed", 1986, MODEL_2X2_KEYS),
    ScenarioSpec("RXC1", "rxc", {"ouvriers": ("ouvr",), "employes": ("empl",), "autres": ("agri", "indp", "cadr", "pint")}, ("gauche", "centre_gauche", "centre", "centre_droit", "droite"), "five_blocks", "expressed", 1962, ("rosen_nls", "rosen_multinomial_dirichlet")),
    ScenarioSpec("RXC2", "rxc", {group: (group,) for group in CSP_GROUPS}, ("gauche", "centre_gauche", "centre", "centre_droit", "droite"), "five_blocks", "expressed", 1962, ("rosen_nls", "rosen_multinomial_dirichlet")),
)
SCENARIO_BY_ID = {item.scenario_id: item for item in SCENARIOS}


def scenario_is_allowed(scenario: ScenarioSpec, election: ElectionSpec) -> bool:
    if election.year < scenario.min_year:
        return False
    if scenario.vote_definition == "rn" and not election.rn_columns:
        return False
    return True


def planned_run_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for election in ELECTIONS:
        for scenario in SCENARIOS:
            if not scenario_is_allowed(scenario, election):
                continue
            for model in scenario.models:
                rows.append(
                    {
                        "election_id": election.election_id,
                        "election_type": election.election_type,
                        "year": election.year,
                        "round": election.round,
                        "scenario_id": scenario.scenario_id,
                        "model_key": model,
                        "model_family": scenario.model_family,
                        "status": "planned",
                    }
                )
    return rows

from __future__ import annotations

from pathlib import Path

import pandas as pd

from code_longitudinal.build_density_report_atlas import (
    build_full_size_reader,
    build_overview_html,
    write_density_readme,
)


def _catalog() -> pd.DataFrame:
    rows = []
    for method in ("krt_python", "r_eipack"):
        for election_type, election_id, year in (
            ("legislative", "leg_1962_r1", 1962),
            ("legislative", "leg_2022_r1", 2022),
            ("presidential", "pre_1965_r1", 1965),
            ("presidential", "pre_2022_r1", 2022),
        ):
            rows.append(
                {
                    "method": method,
                    "scenario_id": "H0A",
                    "election_type": election_type,
                    "election_id": election_id,
                    "year": year,
                    "round": 1,
                    "finite_both": 2_000,
                    "total_rows": 2_000,
                    "warning": "",
                    "report_png": f"03_FIGURES/densites_completes/{method}/H0A/{election_id}.png",
                }
            )
    return pd.DataFrame(rows)


def test_full_size_reader_exposes_all_years_and_both_methods(tmp_path: Path) -> None:
    build_full_size_reader(_catalog(), tmp_path)

    reader = (tmp_path / "01_RAPPORT" / "ANNEXE_ATLAS_DENSITES.html").read_text(
        encoding="utf-8"
    )
    assert "lecteur plein format, toutes les années" in reader
    assert "leg_1962_r1" in reader
    assert "leg_2022_r1" in reader
    assert "pre_1965_r1" in reader
    assert "pre_2022_r1" in reader
    assert "KRT Python" in reader
    assert "King EI — R/eiPack" in reader
    assert "Ouvrir le PNG seul (2100 × 760)" in reader
    assert "ANNEXE_ATLAS_DENSITES_GRILLE.html" in reader


def test_overview_and_density_readme_point_back_to_full_size_reader(tmp_path: Path) -> None:
    build_overview_html(_catalog(), tmp_path)
    write_density_readme(tmp_path)

    overview = (
        tmp_path / "01_RAPPORT" / "ANNEXE_ATLAS_DENSITES_GRILLE.html"
    ).read_text(encoding="utf-8")
    readme = (
        tmp_path / "03_FIGURES" / "densites_completes" / "00_LIRE_EN_PREMIER.txt"
    ).read_text(encoding="utf-8")
    assert "Revenir au lecteur plein format" in overview
    assert "ANNEXE_ATLAS_DENSITES.html" in overview
    assert "TOUTES LES ANNEES" in readme
    assert "1962 à 2022" in readme
    assert "présidentielles : 1965 à 2022" in readme

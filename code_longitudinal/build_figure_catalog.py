from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .paths import DOCS_DIR, FIGURE_DIR


FAMILY_INFO = {
    "panel_balance": (
        "Balance du panel",
        "`panel/panel_balance_checks.csv`",
        "Diagnostic descriptif de représentativité du tirage fixe 2022.",
    ),
    "densities/curated": (
        "Densités principales King/KRT",
        "`outputs/pilot_density_selection.csv`, `outputs/beta_density_data.parquet`",
        "Calibration non substantielle : une commune = un poids, plus grand palier commun ou vue native explicitée.",
    ),
    "densities/marginal": (
        "Densités marginales des bêtas",
        "`outputs/density_marginal_data.parquet`",
        "Calibration non substantielle ; moyenne postérieure communale de b_1 ou b_2.",
    ),
    "densities/joint": (
        "Relations jointes b_1/b_2",
        "`outputs/density_joint_data.parquet`",
        "Calibration non substantielle ; vue native ou intersection exacte selon le nom.",
    ),
    "densities/comparisons": (
        "Comparaisons King/KRT",
        "`outputs/density_joint_data.parquet`",
        "Calibration non substantielle sur l’intersection exacte des communes utilisées.",
    ),
    "longitudinal": (
        "Figures longitudinales",
        "`outputs/longitudinal_estimates.parquet`",
        "Séparer législatives et présidentielles ; vérifier le modèle et son statut diagnostique avant interprétation.",
    ),
    "election_2022": (
        "Diagnostic mono-élection 2022",
        "`outputs/election_2022_input_integrity.csv`, `outputs/election_2022_fit_quality.csv`",
        "Figures d’intégrité et d’ajustement ; les NLS sans intervalle ne portent pas d’incertitude validée.",
    ),
    "illustrated_report": (
        "Comparaisons du rapport illustré",
        "`outputs/illustrated_report_estimates.csv`",
        "Comparaisons descriptives ; les PyEI 20/20/1 restent non substantiels.",
    ),
    "professor_recap": (
        "Comparaisons canoniques du récapitulatif professeur",
        "`outputs/professor_canonical_comparisons.csv`",
        "Trois coupes discrètes ; moyenne communale et P25–P75 entre communes, sans interprétation causale.",
    ),
}


def _scope_from_name(path: Path) -> str:
    stem = path.stem
    tokens = stem.split("__")
    labelled: list[str] = []
    start = 0 if tokens[0].startswith(("leg_", "pres_")) else 1
    for token in tokens[start:]:
        if token.startswith(("leg_", "pres_")):
            labelled.append(f"scrutin `{token}`")
        elif token.startswith(("H", "RXC")):
            labelled.append(f"scénario `{token}`")
        elif token.startswith("n") and token[1:].isdigit():
            labelled.append(f"palier demandé `{token[1:]}`")
        elif token in {"king_truncated_normal", "krt_beta_binomial", "rosen_nls"}:
            labelled.append(f"modèle `{token}`")
        elif token and not re.fullmatch(r"[0-9a-f]{12}", token):
            labelled.append(f"vue `{token}`")
    return "; ".join(labelled) if labelled else stem.replace("_", " ")


def build_figure_catalog() -> dict[str, int | str]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(FIGURE_DIR.rglob("*.svg")):
        family = path.relative_to(FIGURE_DIR).parent.as_posix()
        grouped[family].append(path)

    total = sum(len(paths) for paths in grouped.values())
    lines = [
        "# Catalogue exhaustif des figures",
        "",
        f"Ce catalogue est généré par `code_longitudinal/build_figure_catalog.py`. Il indexe les **{total} figures SVG** présentes dans `figures/`.",
        "Les PNG du dépôt de travail sont des aperçus ; le ZIP minimal conserve les SVG vectoriels.",
        "",
        "## Règles de lecture",
        "",
        "- `n` dans un nom est le palier demandé ; le titre donne l’effectif effectivement utilisé.",
        "- Toute figure PyEI issue de 20 draws, 20 tune et une chaîne est une calibration non substantielle, même à n=3 000.",
        "- Les densités principales donnent le même poids à chaque commune et portent sur les moyennes postérieures communales de b_1/b_2.",
        "- Les valeurs numériques reproductibles sont dans les tables sources indiquées sous chaque famille.",
        "",
        "## Synthèse par famille",
        "",
        "| Famille | SVG | Source principale |",
        "|---|---:|---|",
    ]
    for family, paths in grouped.items():
        title, source, _ = FAMILY_INFO.get(family, (family, "voir le README du dossier", ""))
        lines.append(f"| `{family}/` — {title} | {len(paths)} | {source} |")

    for family, paths in grouped.items():
        title, source, interpretation = FAMILY_INFO.get(
            family, (family, "voir le README du dossier", "Consulter le titre et le diagnostic associé.")
        )
        lines.extend(
            [
                "",
                f"## {title} — `{family}/` ({len(paths)})",
                "",
                f"Source : {source}",
                "",
                f"Interprétation : {interpretation}",
                "",
                "| Figure | Portée identifiée par le nom |",
                "|---|---|",
            ]
        )
        for path in paths:
            relative = path.relative_to(FIGURE_DIR).as_posix()
            lines.append(f"| [`{path.name}`](../figures/{relative}) | {_scope_from_name(path)} |")

    output = DOCS_DIR / "FIGURE_CATALOG.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(output), "svg_figures": total, "families": len(grouped)}


if __name__ == "__main__":
    print(build_figure_catalog())

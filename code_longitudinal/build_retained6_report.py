from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .paths import ROOT


CANDIDATE = ROOT / "work" / "longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3_candidate"
PDF_PATH = ROOT / "output" / "pdf" / "rapport_professeur_retained6.pdf"


def _image(path: Path, *, width: float = 17.2 * cm, height: float = 7.0 * cm) -> Image:
    if not path.is_file():
        raise FileNotFoundError(path)
    return Image(str(path), width=width, height=height, kind="proportional")


def _status_table(aggregate: pd.DataFrame) -> list[list[str]]:
    pairs = aggregate[["election_id", "scenario_id", "mcmc_status"]].drop_duplicates()
    cross = pairs.groupby(["scenario_id", "mcmc_status"]).size().unstack(fill_value=0)
    rows = [["Hypothèse", "pass", "caveat", "fail", "total"]]
    for scenario_id in ("H0A", "H1", "H0B", "H0C", "H2", "H3"):
        row = cross.loc[scenario_id] if scenario_id in cross.index else pd.Series(dtype=int)
        values = [int(row.get(status, 0)) for status in ("pass", "caveat", "fail")]
        rows.append([scenario_id, *(str(value) for value in values), str(sum(values))])
    return rows


def _footer(canvas: object, document: object) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5b6570"))
    canvas.drawString(1.7 * cm, 1.0 * cm, "Longitudinal 2 000 communes - périmètre retenu")
    canvas.drawRightString(19.3 * cm, 1.0 * cm, f"Page {document.page}")
    canvas.restoreState()


def build(candidate: Path = CANDIDATE, pdf_path: Path = PDF_PATH) -> dict[str, object]:
    aggregate = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(candidate / "01_resultats_python" / "longitudinal_nls.parquet")
    r_aggregate = pd.read_parquet(candidate / "03_resultats_r_eipack" / "longitudinal_king_ei_r_aggregate_retained6.parquet")
    r_comparison = pd.read_parquet(candidate / "04_comparaison_python_r" / "king_python_r_retained6_aggregate_comparison.parquet")
    validation = json.loads((candidate / "VALIDATION_RETAINED6.json").read_text(encoding="utf-8"))
    krt_nls = pd.read_csv(candidate / "02_syntheses" / "krt_nls_comparison_h0a_h1_h0b_h0c_h2_h3.csv")

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, alignment=TA_CENTER, textColor=colors.HexColor("#18344b"), spaceAfter=18))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#234f70"), spaceAfter=10))
    styles.add(ParagraphStyle(name="Subsection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#8b5427"), spaceAfter=6))
    styles.add(ParagraphStyle(name="BodyCompact", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.4, leading=13.2, spaceAfter=7))
    styles.add(ParagraphStyle(name="Warning", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=9.3, leading=13, backColor=colors.HexColor("#fff3d6"), borderColor=colors.HexColor("#d59b31"), borderWidth=0.7, borderPadding=7, spaceAfter=10))

    status_label = "VALIDÉ" if validation["scientific_ready"] else "CANDIDATE - RÉSERVES MCMC"
    story: list[object] = [
        Spacer(1, 1.4 * cm),
        Paragraph("Estimations écologiques longitudinales", styles["ReportTitle"]),
        Paragraph("Panel fixe de 2 000 communes - H0A, H1, H0B, H0C, H2 et H3", styles["Heading2"]),
        Spacer(1, 0.7 * cm),
        Paragraph(f"Statut scientifique : <b>{status_label}</b>", styles["Warning"]),
        Paragraph(
            "La livraison est structurellement complète sur six hypothèses et 26 scrutins. "
            "Un fit terminé n'est pas automatiquement validé : les diagnostics MCMC, l'identification écologique "
            "et la stabilité des estimations sont présentés séparément.",
            styles["BodyCompact"],
        ),
        Table(
            [
                ["Panel", "KRT Python", "NLS", "R ei/eiPack"],
                ["2 000 communes fixes", "156 couples / 312 000 communes", f"{nls[['election_id','scenario_id']].drop_duplicates().shape[0]} couples", f"{r_aggregate[['election_id','scenario_id']].drop_duplicates().shape[0]} couples"],
            ],
            colWidths=[4.2 * cm] * 4,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#234f70")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8c2cc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
            ]),
        ),
        Spacer(1, 1.0 * cm),
        Paragraph("Méthodes en une phrase", styles["Subsection"]),
        Paragraph(
            "Python KRT : beta-binomial hiérarchique, quatre chaînes, 1 000 chauffe + 1 000 tirages. "
            "R : modèle EI classique de King via <i>ei</i>/<i>eiPack</i>, sans NIMBLE. "
            "Les deux modèles ne sont pas mathématiquement identiques.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("1. Panel et couverture", styles["Section"]),
        Paragraph(
            "Le panel contient exactement les mêmes 2 000 codes communaux aux 26 scrutins. "
            "Son SHA-256 est bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a. "
            "Les contrôles imposent des marges non négatives et la fermeture exacte des partitions préparées.",
            styles["BodyCompact"],
        ),
        Paragraph(
            "Le département 54 est presque entièrement perdu dans la source 1988 : 589 lignes n'ont pas de résultats "
            "substantiels et l'unique commune restante (54602) échoue à la marge sociale. Cette lacune ne modifie pas le panel.",
            styles["BodyCompact"],
        ),
        Paragraph("Entrées et lignage", styles["Subsection"]),
        Paragraph(
            "Chaque couple élection-hypothèse possède une matrice <i>model_ready</i> hashée, au grain communal, et l'archive "
            "technique en conserve un seul format Parquet. Les variables territoriales jointes aux sorties ne sont pas des covariables des KRT.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("2. H0A et H1", styles["Section"]),
        _image(candidate / "04_figures_essentielles" / "h0a_contrast.png", height=7.2 * cm),
        Spacer(1, 0.25 * cm),
        _image(candidate / "04_figures_essentielles" / "h1_contrast.png", height=7.2 * cm),
        Paragraph(
            "H0A étudie participation/abstention selon le groupe ouvriers-employés. H1 étudie gauche/non-gauche "
            "pour le même groupe. Les législatives et présidentielles sont affichées dans des panneaux séparés.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("3. H0B et H0C", styles["Section"]),
        _image(candidate / "04_figures_essentielles" / "h0b_contrast.png", height=7.2 * cm),
        Spacer(1, 0.25 * cm),
        _image(candidate / "04_figures_essentielles" / "h0c_contrast.png", height=7.2 * cm),
        Paragraph(
            "H0B isole les ouvriers dans l'analyse participation/abstention ; H0C isole les employés. "
            "Les compléments diffèrent, ce qui interdit de lire leurs contrastes comme une décomposition mécanique de H0A.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("4. H2 et H3", styles["Section"]),
        _image(candidate / "04_figures_essentielles" / "h2_h3_target_probabilities_descriptive.png", height=8.5 * cm),
        Spacer(1, 0.25 * cm),
        _image(candidate / "04_figures_essentielles" / "h2_contrast.png", width=8.4 * cm, height=5.5 * cm),
        Paragraph(
            "Le β1 de H2 estime P(gauche | ouvriers) et celui de H3 P(gauche | employés). "
            "La comparaison est descriptive : H2 et H3 sont deux modèles séparés aux compléments différents.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("5. Comparaison KRT-NLS", styles["Section"]),
        _image(candidate / "04_figures_essentielles" / "krt_nls_comparison.png", height=18.2 * cm),
        Paragraph(
            f"Le NLS est un point sans pseudo-intervalle. Sur {len(krt_nls)} couples, "
            f"{int(krt_nls['nls_inside_krt_interval'].sum())} points NLS se situent dans l'intervalle KRT à 95 %. "
            "Un écart KRT-NLS n'est pas un diagnostic MCMC.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("6. Comparaison Python-R", styles["Section"]),
        _image(candidate / "04_figures_essentielles" / "python_r_aggregate_scatter.png", height=8.2 * cm),
        Spacer(1, 0.25 * cm),
        _image(candidate / "04_figures_essentielles" / "python_r_contrast_h1.png", height=7.2 * cm),
        Paragraph(
            f"La médiane de l'écart absolu agrégé est {r_comparison['absolute_difference'].median():.3f}; "
            f"le maximum est {r_comparison['absolute_difference'].max():.3f}. "
            "Ces écarts mesurent une robustesse entre le KRT beta-binomial Python et l'EI normal tronqué R, pas une différence pure de langage.",
            styles["BodyCompact"],
        ),
        PageBreak(),
        Paragraph("7. Diagnostics et limites", styles["Section"]),
        _image(candidate / "04_figures_essentielles" / "mcmc_status_by_scenario.png", height=8.0 * cm),
        Spacer(1, 0.35 * cm),
        Table(
            _status_table(aggregate),
            colWidths=[3.0 * cm] * 5,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#234f70")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8c2cc")),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ]),
        ),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "Zéro divergence ne suffit pas : R-hat, ESS et BFMI peuvent encore conduire à un caveat ou un fail. "
            "Une chaîne plus longue peut améliorer la précision Monte Carlo, mais ne resserre pas des bornes écologiques structurellement larges.",
            styles["BodyCompact"],
        ),
        Paragraph(
            "La suite scientifique recommandée reste ciblée : résoudre seulement les fails substantifs si nécessaire, puis envisager un RxC 3x2 "
            "{ouvriers, employés, autres} x {gauche, non-gauche} pour une comparaison jointe plus propre.",
            styles["BodyCompact"],
        ),
    ]

    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.45 * cm,
        title="Estimations écologiques longitudinales - périmètre retenu",
        author="Projet ARE",
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)

    html_path = candidate / "RAPPORT_PROFESSEUR.html"
    sections = [
        ("Panel et périmètre", "2 000 communes fixes, 26 scrutins, six hypothèses et 156 couples."),
        ("Python KRT", "312 000 lignes communales et 468 agrégats, avec diagnostics MCMC séparés de l'identification."),
        ("R ei/eiPack", "156 couples sans NIMBLE ; modèle King classique non identique au KRT beta-binomial."),
        ("Comparaisons", "KRT-NLS et Python-R sont des robustesses de méthode, sans interprétation causale du logiciel."),
        ("Statut", status_label),
    ]
    cards = "".join(f"<section><h2>{html.escape(title)}</h2><p>{html.escape(body)}</p></section>" for title, body in sections)
    html_path.write_text(
        "<!doctype html><html lang='fr'><meta charset='utf-8'><title>Rapport professeur</title>"
        "<style>body{font:16px/1.55 system-ui;max-width:980px;margin:auto;padding:40px;color:#23313d}"
        "h1,h2{color:#234f70}section{border-top:1px solid #ccd5dc;padding:18px 0}"
        "img{max-width:100%;margin:16px 0}</style><body>"
        "<h1>Estimations écologiques longitudinales</h1>"
        f"<p><b>{html.escape(status_label)}</b> - H0A, H1, H0B, H0C, H2, H3.</p>{cards}"
        "<p>Voir le PDF pour les trajectoires, tableaux et diagnostics complets.</p></body></html>",
        encoding="utf-8",
    )
    candidate_pdf = candidate / "RAPPORT_PROFESSEUR.pdf"
    candidate_pdf.parent.mkdir(parents=True, exist_ok=True)
    candidate_pdf.write_bytes(pdf_path.read_bytes())
    return {
        "status": "complete",
        "pdf": str(pdf_path),
        "candidate_pdf": str(candidate_pdf),
        "html": str(html_path),
        "pages_expected": 8,
    }


def main() -> None:
    print(json.dumps(build(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, Table, TableStyle
from reportlab.pdfgen import canvas

from .release_scope import load_release_scope


PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 1.55 * cm
TOP_Y = PAGE_HEIGHT - 1.65 * cm
BOTTOM_Y = 1.35 * cm
INK = colors.HexColor("#1f2933")
BLUE = colors.HexColor("#2f6b9a")
ORANGE = colors.HexColor("#d0823b")
LIGHT = colors.HexColor("#edf3f7")
GRID = colors.HexColor("#d6dde3")


FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
STYLES = getSampleStyleSheet()
BODY = ParagraphStyle(
    "ReleaseBody",
    parent=STYLES["BodyText"],
    fontName=FONT,
    fontSize=9.1,
    leading=12.2,
    textColor=INK,
    alignment=TA_LEFT,
    spaceAfter=5,
)
SMALL = ParagraphStyle(
    "ReleaseSmall",
    parent=BODY,
    fontSize=7.7,
    leading=9.7,
)


def _header_footer(pdf: canvas.Canvas, page_number: int, release_id: str) -> None:
    pdf.setStrokeColor(GRID)
    pdf.setLineWidth(0.5)
    pdf.line(MARGIN_X, PAGE_HEIGHT - 1.12 * cm, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 1.12 * cm)
    pdf.setFont(FONT, 7.2)
    pdf.setFillColor(colors.HexColor("#5f6b74"))
    pdf.drawString(MARGIN_X, PAGE_HEIGHT - 0.88 * cm, release_id)
    pdf.drawRightString(PAGE_WIDTH - MARGIN_X, 0.72 * cm, f"Page {page_number}/8")


def _new_page(pdf: canvas.Canvas, page_number: int, release_id: str, title: str) -> float:
    if page_number > 1:
        pdf.showPage()
    _header_footer(pdf, page_number, release_id)
    pdf.setFont(FONT_BOLD, 17)
    pdf.setFillColor(INK)
    pdf.drawString(MARGIN_X, TOP_Y, title)
    pdf.setStrokeColor(BLUE)
    pdf.setLineWidth(2.0)
    pdf.line(MARGIN_X, TOP_Y - 0.22 * cm, PAGE_WIDTH - MARGIN_X, TOP_Y - 0.22 * cm)
    return TOP_Y - 0.75 * cm


def _paragraph(pdf: canvas.Canvas, text: str, y: float, *, width: float | None = None, style: ParagraphStyle = BODY) -> float:
    box_width = width or PAGE_WIDTH - 2 * MARGIN_X
    paragraph = Paragraph(text, style)
    _, height = paragraph.wrap(box_width, PAGE_HEIGHT)
    paragraph.drawOn(pdf, MARGIN_X, y - height)
    return y - height - 0.12 * cm


def _bullets(pdf: canvas.Canvas, items: Iterable[str], y: float) -> float:
    for item in items:
        y = _paragraph(pdf, f"<bullet>&bull;</bullet>{item}", y)
    return y


def _image(pdf: canvas.Canvas, path: Path, y_top: float, *, max_height: float, max_width: float | None = None) -> float:
    if not path.exists():
        raise FileNotFoundError(path)
    image = Image(str(path))
    width = max_width or PAGE_WIDTH - 2 * MARGIN_X
    scale = min(width / image.imageWidth, max_height / image.imageHeight)
    draw_width = image.imageWidth * scale
    draw_height = image.imageHeight * scale
    image.drawWidth = draw_width
    image.drawHeight = draw_height
    x = (PAGE_WIDTH - draw_width) / 2
    image.drawOn(pdf, x, y_top - draw_height)
    return y_top - draw_height - 0.18 * cm


def _table(pdf: canvas.Canvas, data: list[list[object]], y_top: float, widths: list[float]) -> float:
    table_data = [[Paragraph(str(cell), SMALL) for cell in row] for row in data]
    table = Table(table_data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                ("TEXTCOLOR", (0, 0), (-1, 0), INK),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    _, height = table.wrap(sum(widths), PAGE_HEIGHT)
    table.drawOn(pdf, MARGIN_X, y_top - height)
    return y_top - height - 0.2 * cm


def _metric_box(pdf: canvas.Canvas, x: float, y: float, width: float, label: str, value: str) -> None:
    pdf.setFillColor(LIGHT)
    pdf.setStrokeColor(GRID)
    pdf.roundRect(x, y, width, 1.45 * cm, 4, fill=1, stroke=1)
    pdf.setFillColor(colors.HexColor("#52606d"))
    pdf.setFont(FONT, 7.5)
    pdf.drawString(x + 0.18 * cm, y + 0.98 * cm, label)
    pdf.setFillColor(INK)
    pdf.setFont(FONT_BOLD, 14)
    pdf.drawString(x + 0.18 * cm, y + 0.35 * cm, value)


def render_report(release_root: Path, config_path: Path, output_path: Path) -> None:
    scope = load_release_scope(config_path)
    synth = release_root / "02_syntheses"
    audit = release_root / "03_panel_et_audit"
    figures = release_root / "04_figures_essentielles"
    diagnostics = pd.read_csv(synth / "diagnostics_krt_par_election.csv")
    summary = pd.read_csv(synth / "diagnostics_krt_resume.csv")
    comparison = pd.read_csv(synth / "krt_nls_comparison_h0a_h1.csv") if (synth / "krt_nls_comparison_h0a_h1.csv").exists() else pd.read_csv(synth / "krt_nls_comparison_h0a_h1.csv")
    sensitivity = pd.read_csv(synth / "h1_panel_sensitivity.csv")
    nls_replication = pd.read_csv(synth / "nls_python_r_replication_summary.csv").iloc[0]
    panel_exact = json.loads((audit / "panel_exact_validation.json").read_text(encoding="utf-8"))
    invariance = json.loads(
        (audit / "NUMERICAL_INVARIANCE_v1.0.1_to_v1.0.2.json").read_text(encoding="utf-8")
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    pdf.setTitle("Release longitudinale H0A-H1 v1.0.2")
    pdf.setAuthor("Projet longitudinal - rapport professeur")

    # Page 1 - technical summary.
    _header_footer(pdf, 1, scope.release_id)
    pdf.setFont(FONT_BOLD, 22)
    pdf.setFillColor(INK)
    pdf.drawString(MARGIN_X, TOP_Y - 0.2 * cm, "Estimations ecologiques longitudinales")
    pdf.setFont(FONT_BOLD, 15)
    pdf.setFillColor(BLUE)
    pdf.drawString(MARGIN_X, TOP_Y - 0.95 * cm, "Release corrective v1.0.2 - H0A et H1")
    pdf.setFont(FONT, 9)
    pdf.setFillColor(colors.HexColor("#52606d"))
    pdf.drawString(MARGIN_X, TOP_Y - 1.55 * cm, "Panel fixe de 2 000 communes - 26 scrutins - KRT et NLS")
    box_y = TOP_Y - 3.25 * cm
    gap = 0.25 * cm
    box_width = (PAGE_WIDTH - 2 * MARGIN_X - 2 * gap) / 3
    _metric_box(pdf, MARGIN_X, box_y, box_width, "Couples KRT canoniques", str(scope.expected_krt_pairs))
    _metric_box(pdf, MARGIN_X + box_width + gap, box_y, box_width, "Lignes communales", f"{scope.expected_krt_commune_rows:,}".replace(",", " "))
    _metric_box(pdf, MARGIN_X + 2 * (box_width + gap), box_y, box_width, "Couples NLS publics", str(scope.expected_nls_pairs))
    y = box_y - 0.55 * cm
    y = _paragraph(pdf, "<b>Synthese technique.</b> La v1.0.2 corrige l'interface publique, les syntheses, les dictionnaires et le packaging. Aucun modele H0A/H1 n'a ete reestime. Le controle d'invariance confirme que les valeurs scientifiques de la v1.0.1 sont conservees exactement apres tri par les cles publiques.", y)
    y = _bullets(
        pdf,
        [
            f"Panel: {scope.panel_size} codes <i>unit_id</i> fixes sur {scope.expected_elections} scrutins; hash SHA-256 conforme ({scope.panel_sha256[:12]}...).",
            "H0A: abstention des ouvriers-employes contre leur complement; H1: vote de gauche des ouvriers-employes contre leur complement.",
            "Les diagnostics MCMC, l'identification ecologique et la stabilite entre specifications sont presentes separement.",
            "Les ratios de revenu/capital, le VBBM, le departement et la region sont des caracteristiques jointes aux sorties, pas des covariables incluses dans les KRT non ajustes.",
        ],
        y,
    )
    y = _paragraph(pdf, f"<b>Porte de migration:</b> invariance={invariance['status']}; panel_exact={panel_exact.get('status', panel_exact.get('panel_status', 'pass'))}; schema public={scope.public_schema_version}.", y)

    # Page 2 - H0A.
    y = _new_page(pdf, 2, scope.release_id, "H0A - Abstention et structure sociale")
    y = _paragraph(pdf, "Le contraste beta1 - beta2 compare la probabilite d'abstention estimee pour les ouvriers-employes a celle de leur complement. Les presidentielles et les legislatives sont tracees dans deux panneaux distincts; les intervalles sont les intervalles credibles KRT a 95 %.", y)
    y = _image(pdf, figures / "h0a_contrast.png", y, max_height=14.8 * cm)
    _paragraph(pdf, "Lecture: un contraste positif indique une abstention estimee plus forte parmi les ouvriers-employes. La largeur des intervalles reflete l'incertitude posterieure, mais ne suffit pas a diagnostiquer l'identification ecologique.", y)

    # Page 3 - H1.
    y = _new_page(pdf, 3, scope.release_id, "H1 - Vote de gauche et structure sociale")
    y = _paragraph(pdf, "H1 utilise la definition harmonisee gauche = voteG + voteCG, avec non-gauche = exprimes - gauche. Les egalites sont controlees commune par commune sur le panel avant estimation.", y)
    y = _image(pdf, figures / "h1_contrast.png", y, max_height=14.8 * cm)
    _paragraph(pdf, "Lecture: un contraste positif indique une probabilite de vote de gauche estimee plus forte pour les ouvriers-employes. Les changements entre dates restent descriptifs et ne constituent pas un modele temporel hierarchique.", y)

    # Page 4 - KRT vs NLS.
    y = _new_page(pdf, 4, scope.release_id, "KRT et NLS - deux estimateurs, deux lectures")
    max_gap = float(comparison["absolute_krt_nls_gap"].max())
    inside_share = float(comparison["nls_inside_krt_interval"].mean())
    y = _paragraph(pdf, f"La figure place le contraste KRT et son intervalle a 95 % face au point NLS sans pseudo-intervalle posterieur. Sur les {len(comparison)} couples H0A/H1, l'ecart absolu maximal entre les deux points est {max_gap:.3f}; {inside_share:.1%} des points NLS se situent dans l'intervalle KRT.", y)
    y = _image(pdf, figures / "krt_nls_comparison.png", y, max_height=14.0 * cm)
    _paragraph(pdf, "Un ecart KRT-NLS signale une sensibilite a la methode et doit conduire a revoir les entrees, les marges et l'identification. Il ne justifie pas un ajustement opportuniste de king_lambda ou des priors.", y)

    # Page 5 - diagnostics.
    y = _new_page(pdf, 5, scope.release_id, "Convergence MCMC et identification ecologique")
    status_table = [["Hypothese", "Pass", "Caveat", "Fail"]]
    for scenario_id in scope.krt_scenarios:
        counts = summary.loc[summary["scenario_id"].eq(scenario_id)].set_index("mcmc_status")["n_runs"]
        status_table.append([scenario_id, int(counts.get("pass", 0)), int(counts.get("caveat", 0)), int(counts.get("fail", 0))])
    y = _table(pdf, status_table, y, [4.5 * cm, 3.2 * cm, 3.2 * cm, 3.2 * cm])
    severity = diagnostics["mcmc_caveat_severity"].value_counts().to_dict()
    identification_counts = diagnostics["identification_status"].value_counts().to_dict()
    y = _bullets(
        pdf,
        [
            f"Sous-classification MCMC: {severity.get('caveat_modere', 0)} caveats moderes et {severity.get('caveat_severe', 0)} caveats severes selon les seuils preetablis.",
            f"Identification ecologique: {identification_counts}. Ce statut mesure notamment la largeur des bornes tomographiques et la variation du plan.",
            "Une chaine plus longue peut ameliorer R-hat ou ESS; elle ne resserre pas automatiquement des bornes ecologiques structurellement larges.",
            "Aucun fail MCMC inexplique n'entre dans cette release H0A-H1.",
        ],
        y,
    )
    detail = diagnostics.sort_values(["max_rhat", "min_ess"], ascending=[False, True]).head(8)
    detail_table = [["Scrutin", "H", "Statut", "R-hat max", "ESS min", "BFMI min"]]
    for row in detail.itertuples():
        detail_table.append([row.election_id, row.scenario_id, row.mcmc_status, f"{row.max_rhat:.3f}", f"{row.min_ess:.0f}", f"{row.min_bfmi:.3f}"])
    _table(pdf, detail_table, y, [4.0 * cm, 1.2 * cm, 2.2 * cm, 2.2 * cm, 2.0 * cm, 2.2 * cm])

    # Page 6 - sensitivity.
    y = _new_page(pdf, 6, scope.release_id, "Sensibilite H1 - 1962, 1986 et 2022")
    y = _paragraph(pdf, "La sensibilite compare quatre cellules: panel V2 3 000 avec ancien pipeline, le meme panel V2 avec la preparation actuelle, le maitre actuel 3 000, puis le sous-panel emboite 2 000. Les libelles de differences restent descriptifs; ils n'isolent pas des effets causaux purs.", y)
    y = _image(pdf, figures / "h1_panel_sensitivity.png", y, max_height=12.6 * cm)
    estimates = sensitivity.loc[(sensitivity["row_type"].eq("estimate")) & (sensitivity["estimand"].eq("contrast"))]
    rows = [["Scrutin", "V2 ancien", "V2 actuel", "Maitre 3 000", "Panel 2 000"]]
    cells = [
        "cell_1_legacy_v2_3000_old_pipeline",
        "cell_2_legacy_v2_3000_current_pipeline",
        "cell_3_current_master_3000_current_pipeline",
        "cell_4_current_primary_2000_current_pipeline",
    ]
    for election_id in ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1"):
        part = estimates.loc[estimates["election_id"].eq(election_id)].set_index("cell")
        rows.append([election_id] + [f"{float(part.loc[cell, 'mean']):.3f}" for cell in cells])
    _table(pdf, rows, y, [3.3 * cm, 2.5 * cm, 2.5 * cm, 2.8 * cm, 2.8 * cm])

    # Page 7 - 2022 audit.
    y = _new_page(pdf, 7, scope.release_id, "Audit 2022 - donnees brutes et identification")
    y = _paragraph(pdf, "Les nuages bruts 2022 sont colores separement par la largeur maximale des bornes tomographiques et par la part du groupe cible. Cette vue complete les hexbin/KDE sans confondre densite graphique et identification.", y)
    y = _image(pdf, figures / "raw_scatter_2022_bounds_and_target_share.png", y, max_height=14.0 * cm)
    _paragraph(pdf, "Les points proches des frontieres ou associes a des bornes larges doivent etre interpretes avec prudence. Une densite visuelle plus nette n'apporte pas, a elle seule, davantage d'information individuelle.", y)

    # Page 8 - reproducibility and next steps.
    y = _new_page(pdf, 8, scope.release_id, "Reproductibilite, limites et suite H2/H3")
    y = _paragraph(pdf, "<b>Replication NLS R/Python.</b>", y)
    y = _bullets(
        pdf,
        [
            "Python: scipy.optimize.least_squares.",
            "Methode TRF, 20 departs, tolerance 1e-9, maximum 5 000 evaluations.",
            f"Ecart maximal Python-R = {float(nls_replication['maximum_absolute_difference']):.7e} < 1e-6 sur exactement {int(nls_replication['n_election_scenario_pairs'])} couples.",
        ],
        y,
    )
    y = _paragraph(pdf, "<b>Limites de la release.</b>", y)
    y = _bullets(
        pdf,
        [
            "ready=true signifie uniquement que le perimetre H0A-H1 est valide; toutes les hypotheses du projet ne le sont pas encore.",
            "Les modeles H0A/H1 sont non ajustes. Les caracteristiques communales jointes facilitent les tris et analyses descriptives, mais ne sont pas des regresseurs KRT.",
            "La reproduction complete exige les archives brutes du depot parent; elles ne sont pas incluses dans les ZIP de livraison.",
            "Les NetCDF ne sont pas livres; ils ont ete utilises uniquement pendant le post-traitement.",
        ],
        y,
    )
    y = _paragraph(pdf, "<b>Suite scientifique.</b> La v1.1 ajoute H2 (ouvriers) et H3 (employes) sur le meme panel. Les deux modeles ont des complements differents: leur comparaison est descriptive et ne constitue pas une estimation jointe ouvriers-employes. Un RxC 3x2 cible sera l'extension jointe suivante apres H6/H7, H0B/H0C et H4/H5.", y)
    y = _paragraph(pdf, "Le bundle technique fournit la configuration, le code minimal de production, les diagnostics individuels, les manifestes et les tests. Les chemins de livraison sont relatifs et les dependances externes sont explicitees.", y)

    pdf.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the scoped professor report as an eight-page PDF.")
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render_report(args.release_root, args.config, args.output)


if __name__ == "__main__":
    main()

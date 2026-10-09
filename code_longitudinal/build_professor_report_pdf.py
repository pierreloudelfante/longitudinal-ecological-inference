from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VENV_SITE_PACKAGES = (
    Path(__file__).resolve().parents[2]
    / "pour_moi_avec_data"
    / ".venv-ei"
    / "Lib"
    / "site-packages"
)
if VENV_SITE_PACKAGES.is_dir():
    sys.path.append(str(VENV_SITE_PACKAGES))

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
LIGHT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate"
REPORT_BUILD = ROOT / "work" / "professor_report_build"
OUTPUT = LIGHT / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.pdf"
FIGURES = LIGHT / "03_FIGURES"
KRT_AGG = LIGHT / "02_TABLES_PRINCIPALES" / "longitudinal_krt_aggregate.parquet"
NLS = LIGHT / "02_TABLES_PRINCIPALES" / "longitudinal_nls.parquet"

BLUE = colors.HexColor("#2457A7")
ORANGE = colors.HexColor("#D97706")
GOLD = colors.HexColor("#B78B20")
INK = colors.HexColor("#20242A")
MUTED = colors.HexColor("#5B6472")
GRID = colors.HexColor("#D8DDE5")
PALE = colors.HexColor("#F4F6F9")


def register_fonts() -> None:
    font_root = Path(os.environ.get("WINDIR", "Windows")) / "Fonts"
    regular = font_root / "arial.ttf"
    bold = font_root / "arialbd.ttf"
    italic = font_root / "ariali.ttf"
    if regular.is_file() and bold.is_file():
        pdfmetrics.registerFont(TTFont("ProfessorSans", str(regular)))
        pdfmetrics.registerFont(TTFont("ProfessorSans-Bold", str(bold)))
        if italic.is_file():
            pdfmetrics.registerFont(TTFont("ProfessorSans-Italic", str(italic)))
        pdfmetrics.registerFontFamily(
            "ProfessorSans",
            normal="ProfessorSans",
            bold="ProfessorSans-Bold",
            italic="ProfessorSans-Italic" if italic.is_file() else "ProfessorSans",
            boldItalic="ProfessorSans-Bold",
        )


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleProfessor",
            parent=base["Title"],
            fontName="ProfessorSans-Bold",
            fontSize=25,
            leading=30,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleProfessor",
            parent=base["Normal"],
            fontName="ProfessorSans",
            fontSize=11,
            leading=15,
            textColor=MUTED,
            spaceAfter=8 * mm,
        ),
        "h1": ParagraphStyle(
            "H1Professor",
            parent=base["Heading1"],
            fontName="ProfessorSans-Bold",
            fontSize=17,
            leading=21,
            textColor=INK,
            spaceBefore=3 * mm,
            spaceAfter=4 * mm,
        ),
        "h2": ParagraphStyle(
            "H2Professor",
            parent=base["Heading2"],
            fontName="ProfessorSans-Bold",
            fontSize=13,
            leading=17,
            textColor=BLUE,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "BodyProfessor",
            parent=base["BodyText"],
            fontName="ProfessorSans",
            fontSize=10.2,
            leading=14.2,
            textColor=INK,
            spaceAfter=3 * mm,
        ),
        "small": ParagraphStyle(
            "SmallProfessor",
            parent=base["BodyText"],
            fontName="ProfessorSans",
            fontSize=8.2,
            leading=11,
            textColor=MUTED,
            spaceAfter=2 * mm,
        ),
        "metric": ParagraphStyle(
            "MetricProfessor",
            parent=base["Normal"],
            fontName="ProfessorSans-Bold",
            fontSize=18,
            leading=21,
            textColor=BLUE,
            alignment=TA_CENTER,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabelProfessor",
            parent=base["Normal"],
            fontName="ProfessorSans",
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }


def page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("ProfessorSans", 8)
    canvas.drawString(doc.leftMargin, 8.5 * mm, "Résultats longitudinaux — panel de 2 000 communes")
    canvas.drawRightString(A4[0] - doc.rightMargin, 8.5 * mm, f"{doc.page}")
    canvas.restoreState()


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def metric_strip(style: dict[str, ParagraphStyle], values: list[tuple[str, str]]) -> Table:
    cells = []
    for value, label in values:
        cells.append([p(value, style["metric"]), p(label, style["metric_label"])])
    table = Table(cells, colWidths=[(A4[0] - 40 * mm) / len(cells)] * len(cells))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def figure(path: Path, max_width: float = 170 * mm, max_height: float = 205 * mm) -> Image:
    if not path.is_file():
        raise FileNotFoundError(path)
    image = Image(str(path))
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return image


def data_table(data: list[list[object]], widths: list[float], repeat_rows: int = 1) -> Table:
    table = Table(data, colWidths=widths, repeatRows=repeat_rows)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "ProfessorSans-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "ProfessorSans"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build() -> None:
    register_fonts()
    s = styles()
    stats = json.loads((REPORT_BUILD / "REPORT_STATISTICS.json").read_text(encoding="utf-8"))
    krt = pd.read_parquet(KRT_AGG)
    nls = pd.read_parquet(NLS)

    current = krt.loc[
        krt["year"].eq(2022)
        & krt["scenario_id"].isin(["H0A", "H1"])
        & krt["estimand"].eq("b_1_minus_b_2")
    ].sort_values(["scenario_id", "election_id"])

    story = []
    story.append(p("Résultats longitudinaux d'inférence écologique", s["title"]))
    story.append(p("Panel fixe de 2 000 communes · 26 scrutins · 1962–2022 · KRT Python, réplication R EI et NLS", s["subtitle"]))
    story.append(p("Résumé des résultats", s["h1"]))
    story.append(
        p(
            "La couverture de calcul est complète pour les <b>240 couples KRT canoniques</b> et les "
            "<b>240 réplications R EI</b>. Les trajectoires H0A et H1 mettent en évidence deux déplacements de long terme : "
            "le contraste d'abstention populaire passe d'un signe négatif à un signe positif, tandis que le contraste de vote populaire à gauche, "
            "positif pendant une grande partie de la période, devient négatif dans les scrutins récents. Ces résultats sont écologiques et non causaux.",
            s["body"],
        )
    )
    story.append(
        metric_strip(
            s,
            [
                ("240/240", "KRT Python canoniques"),
                ("240/240", "R EI valides"),
                (f"{stats['nls_diagnostics'].get('pass', 0)}/292", "NLS au diagnostic pass"),
                (f"{stats['krt_mcmc'].get('pass', 0)}/240", "KRT au statut MCMC pass"),
            ],
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        p(
            f"La sensibilité KRT–R EI est la plus forte en médiane pour <b>{max(stats['model_gap'], key=stats['model_gap'].get)}</b> "
            f"et la plus faible pour <b>{min(stats['model_gap'], key=stats['model_gap'].get)}</b>. "
            "Une couverture de calcul complète ne vaut donc pas validation générale : les diagnostics MCMC et d'identification restent attachés à chaque estimation.",
            s["body"],
        )
    )
    current_rows = [["Scrutin", "Hyp.", "Contraste", "IC 95 %", "MCMC", "Identification"]]
    for row in current.itertuples(index=False):
        current_rows.append(
            [
                row.election_id,
                row.scenario_id,
                f"{100 * row.mean:+.1f} pts",
                f"[{100 * row.q025:+.1f} ; {100 * row.q975:+.1f}]",
                row.mcmc_status,
                row.identification_status,
            ]
        )
    story.append(p("Repères 2022 — KRT", s["h2"]))
    story.append(data_table(current_rows, [34 * mm, 14 * mm, 24 * mm, 31 * mm, 24 * mm, 29 * mm]))
    story.append(Spacer(1, 3 * mm))
    story.append(p("Source : 02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet.", s["small"]))
    story.append(PageBreak())

    story.append(p("Question scientifique et lien avec Cagé–Piketty", s["h1"]))
    story.append(
        p(
            "Le projet mesure comment les associations entre structure sociale communale et choix électoraux se déplacent entre 1962 et 2022. "
            "Le lien avec le programme Cagé–Piketty tient à la transformation de la composition sociale des électorats. Les estimations communales offrent une lecture locale et longitudinale complémentaire aux agrégats nationaux.",
            s["body"],
        )
    )
    story.append(p("Données et limites de l'inférence écologique", s["h1"]))
    story.append(
        p(
            "Les marges électorales et sociales sont observées au niveau communal. Les β sont latents et estimés sous contraintes comptables. "
            "Ils ne prouvent ni transfert individuel ni causalité. L'erreur écologique reste possible; les résultats décrivent des associations entre marges à un niveau territorial.",
            s["body"],
        )
    )
    story.append(p("Construction du panel de 2 000 communes", s["h1"]))
    story.append(
        p(
            "Le panel correspond aux 2 000 premiers rangs d'un échantillon emboîté défini indépendamment des résultats électoraux. "
            "Les identifiants, départements, régions, VBBM et variables communales jointes sont livrés avec leur provenance. Une commune historique absente n'est jamais remplacée silencieusement.",
            s["body"],
        )
    )
    story.append(p("Méthodes NLS, KRT et réplication R", s["h1"]))
    story.append(
        p(
            "KRT estime des β communaux par modèle bêta-binomial NumPyro et fournit une distribution postérieure. NLS résout un objectif déterministe multi-départs, sans intervalle validé. "
            "La réplication R utilise le modèle classique de King à normale tronquée via ei/eiPack. Elle constitue un contrôle de robustesse, pas une traduction mathématique bit-à-bit de KRT.",
            s["body"],
        )
    )
    story.append(p("Principe de lecture", s["h2"]))
    story.append(
        p(
            "β<sub>1</sub> désigne le taux latent du groupe cible, β<sub>2</sub> celui du groupe complémentaire et β<sub>1</sub>−β<sub>2</sub> leur contraste agrégé. "
            "Les figures séparent systématiquement législatives et présidentielles; les bandes représentent les intervalles à 95 % lorsque le modèle en fournit.",
            s["body"],
        )
    )
    story.append(PageBreak())

    story.append(p("Trajectoire H0A : abstention populaire", s["h1"]))
    story.append(
        p(
            "H0A oppose les ouvriers et employés aux autres groupes sur l'abstention. Le contraste est négatif au début de la série, franchit zéro autour des années 1980 et reste positif dans la période récente. "
            "La réplication R reproduit la forme générale, avec de petits écarts de niveau.",
            s["body"],
        )
    )
    story.append(figure(FIGURES / "trajectoire_H0A" / "H0A_legislative.png", max_height=105 * mm))
    story.append(p("Législatives — contraste β<sub>1</sub>−β<sub>2</sub>, modèles KRT et R EI.", s["small"]))
    story.append(PageBreak())
    story.append(p("H0A — présidentielles", s["h1"]))
    story.append(figure(FIGURES / "trajectoire_H0A" / "H0A_presidential.png", max_height=118 * mm))
    story.append(
        p(
            "La bascule est également visible aux présidentielles, avec un contraste récent positif mais inférieur au pic observé dans les législatives du début des années 2000. "
            "Ces écarts de calendrier justifient la séparation des deux familles de scrutin.",
            s["body"],
        )
    )
    story.append(PageBreak())

    story.append(p("Trajectoire H1 : vote populaire à gauche", s["h1"]))
    story.append(
        p(
            "H1 oppose ouvriers et employés aux autres groupes sur le vote à gauche. Le contraste est positif pendant une grande partie de la période, puis diminue et devient négatif dans les scrutins récents. "
            "Le retournement de signe apparaît dans les deux moteurs.",
            s["body"],
        )
    )
    story.append(figure(FIGURES / "trajectoire_H1" / "H1_legislative.png", max_height=105 * mm))
    story.append(p("Législatives — contraste β<sub>1</sub>−β<sub>2</sub>, modèles KRT et R EI.", s["small"]))
    story.append(PageBreak())
    story.append(p("H1 — présidentielles", s["h1"]))
    story.append(figure(FIGURES / "trajectoire_H1" / "H1_presidential.png", max_height=118 * mm))
    story.append(
        p(
            "La série présidentielle atteint un maximum à la fin des années 1980, puis converge vers zéro avant de devenir négative en 2022. "
            "La concordance de signe KRT–R en 2022 renforce la robustesse descriptive, sans lever les réserves d'identification écologique.",
            s["body"],
        )
    )
    story.append(PageBreak())

    story.append(p("H2/H3 : ouvriers et employés séparés", s["h1"]))
    story.append(
        p(
            "H2 isole les ouvriers et H3 les employés dans le contraste de vote à gauche. Cette séparation évite d'imposer une trajectoire commune à deux groupes dont les associations électorales évoluent différemment. "
            "Les trajectoires NLS ci-dessous servent de repère ponctuel; elles doivent être lues avec le statut numérique de chaque couple.",
            s["body"],
        )
    )
    story.append(p("H4 et H6/H7", s["h1"]))
    story.append(
        p(
            "H4 oppose agriculteurs et indépendants aux salariés sur le vote à droite. H6/H7 étudient respectivement ouvriers et employés face au vote FN/RN. "
            "H6/H7 ne sont admissibles qu'à partir de 1986; la fenêtre graphique et les tables respectent cette contrainte.",
            s["body"],
        )
    )
    story.append(figure(FIGURES / "trajectoires_NLS_autres_hypotheses" / "trajectoires_nls.png", max_height=175 * mm))
    story.append(p("Source : 02_TABLES_PRINCIPALES/longitudinal_nls.parquet.", s["small"]))
    story.append(PageBreak())

    story.append(p("Comparaison KRT–NLS", s["h1"]))
    story.append(
        p(
            "La comparaison se fait au même grain élection × hypothèse. Les points proches de la diagonale signalent un accord de niveau; les écarts reflètent des objectifs différents : "
            "KRT représente l'hétérogénéité communale et l'incertitude postérieure, tandis que NLS fournit une solution ponctuelle globale. L'accord de signe est informatif, l'identité numérique n'est pas attendue.",
            s["body"],
        )
    )
    story.append(figure(FIGURES / "comparaison_KRT_NLS" / "comparaison_krt_nls.png", max_height=120 * mm))
    story.append(p("Or : diagnostic NLS à revoir. Diagonale : égalité des contrastes.", s["small"]))
    story.append(PageBreak())

    story.append(p("Distributions communales et audit 2022", s["h1"]))
    story.append(
        p(
            "Chaque hexagone regroupe des communes selon leurs moyennes postérieures β<sub>1</sub> et β<sub>2</sub>. Chaque commune compte une fois; la diagonale repère l'égalité. "
            "Les quatre panneaux séparent H0A/H1 et législatives/présidentielles. Les Parquet communaux permettent de revenir à chaque point avec son département, sa région, son VBBM, ses poids et ses quantiles.",
            s["body"],
        )
    )
    story.append(figure(FIGURES / "distributions_2D_2022" / "distributions_2d_2022.png", max_height=190 * mm))
    story.append(PageBreak())

    story.append(p("Convergence, identification et cellules fragiles", s["h1"]))
    story.append(
        p(
            f"Sur 240 couples KRT, <b>{stats['krt_mcmc'].get('pass', 0)}</b> ont un statut MCMC pass, "
            f"<b>{stats['krt_mcmc'].get('caveat', 0)}</b> caveat et <b>{stats['krt_mcmc'].get('fail', 0)}</b> fail. "
            f"L'identification est pass pour <b>{stats['krt_identification'].get('pass', 0)}</b>, caveat pour <b>{stats['krt_identification'].get('caveat', 0)}</b> et fail pour <b>{stats['krt_identification'].get('fail', 0)}</b> couple. "
            f"NLS passe sur <b>{stats['nls_diagnostics'].get('pass', 0)}/292</b> couples admissibles.",
            s["body"],
        )
    )
    diag_rows = [["Moteur", "Statut", "Couples", "Règle de lecture"]]
    for status in ["pass", "caveat", "fail"]:
        diag_rows.append(["KRT / MCMC", status, stats["krt_mcmc"].get(status, 0), "Conserver le statut près de l'estimation"])
    for status in ["pass", "caveat", "fail"]:
        diag_rows.append(["KRT / identification", status, stats["krt_identification"].get(status, 0), "Ne pas surinterpréter les cellules fragiles"])
    for status in ["pass", "fail"]:
        diag_rows.append(["NLS", status, stats["nls_diagnostics"].get(status, 0), "Solution ponctuelle; conditionnement à vérifier"])
    story.append(data_table(diag_rows, [43 * mm, 27 * mm, 21 * mm, 69 * mm]))
    story.append(Spacer(1, 4 * mm))
    story.append(
        p(
            "La livraison conserve tous les résultats canoniques initiaux, sans sélectionner de relance diagnostique ciblée. Les statuts caveat/fail ne sont pas supprimés : ils font partie de l'information substantielle et de la transparence du projet.",
            s["body"],
        )
    )
    story.append(PageBreak())

    story.append(p("Prochaines extensions : modèle 3×2 et covariables", s["h1"]))
    story.append(
        p(
            "La prochaine extension prioritaire est un modèle 3×2 permettant de séparer davantage les groupes sociaux, puis l'introduction de covariables communales. "
            "Ces extensions exigent une nouvelle stratégie d'identification, des diagnostics adaptés et une validation hors échantillon. Elles devront conserver le panel fixe, la fermeture des marges, les graines et la traçabilité des sélections.",
            s["body"],
        )
    )
    story.append(p("Fichiers à utiliser", s["h1"]))
    files = [
        ["Fichier", "Usage principal"],
        ["longitudinal_krt_commune.parquet", "Quantiles, poids, géographie et variables jointes au niveau communal"],
        ["longitudinal_krt_aggregate.parquet", "β1, β2, contraste, intervalles et diagnostics KRT"],
        ["longitudinal_nls.parquet", "Estimations ponctuelles, objectif, conditionnement et stabilité"],
        ["longitudinal_r_ei_commune.parquet", "Réplication R communale enrichie, graines et versions"],
        ["longitudinal_r_ei_aggregate.parquet", "Réplication R agrégée et intervalles"],
    ]
    story.append(data_table(files, [57 * mm, 103 * mm]))
    story.append(Spacer(1, 5 * mm))
    story.append(
        p(
            "Le ZIP professeur contient les tables, figures, diagnostics et documentation nécessaires à la lecture. L'archive technique séparée contient le code, les configurations, les manifestes, les erreurs conservées pour audit, les contrôles QA et les commandes de reproduction.",
            s["body"],
        )
    )
    story.append(p("Conclusion", s["h1"]))
    story.append(
        p(
            "Le projet livre une série longitudinale complète au niveau des 240 couples 2×2, doublée d'une réplication R et d'un socle NLS. "
            "Les trajectoires H0A et H1 fournissent les résultats centraux; H2/H3/H4/H6/H7 élargissent l'analyse. La robustesse descriptive est réelle, mais les diagnostics de convergence et d'identification imposent une lecture différenciée plutôt qu'un verdict uniforme.",
            s["body"],
        )
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="Résultats longitudinaux d'inférence écologique — panel de 2 000 communes",
        author="Projet longitudinal 2000",
    )
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(json.dumps({"status": "created", "pdf": str(OUTPUT), "bytes": OUTPUT.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    build()

from __future__ import annotations

import os
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
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
RENDERS = ROOT / "work" / "presentation_correction_audit" / "final-render"
OUTPUT = ROOT / "deliverables" / "CORRECTION_AUDIT_20260908" / "GUIDE_EXPLICATION_SLIDES_LONGITUDINAL_CORRIGE.pdf"

BLUE = colors.HexColor("#2457A7")
ORANGE = colors.HexColor("#D97706")
INK = colors.HexColor("#20242A")
MUTED = colors.HexColor("#5B6472")
WASH = colors.HexColor("#F3F6FA")
GOLD = colors.HexColor("#B78B20")

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
windows_root = os.environ.get("WINDIR")
if windows_root:
    font_dir = Path(windows_root) / "Fonts"
    regular_path = font_dir / "arial.ttf"
    bold_path = font_dir / "arialbd.ttf"
    if regular_path.is_file() and bold_path.is_file():
        pdfmetrics.registerFont(TTFont("ArialPDF", str(regular_path)))
        pdfmetrics.registerFont(TTFont("ArialPDF-Bold", str(bold_path)))
        FONT_REGULAR = "ArialPDF"
        FONT_BOLD = "ArialPDF-Bold"


def page_number(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D8DDE5"))
    canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont(FONT_REGULAR, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9 * mm, "Guide d'explication — résultats longitudinaux")
    canvas.drawRightString(192 * mm, 9 * mm, str(doc.page))
    canvas.restoreState()


def bullet(text: str, style: ParagraphStyle) -> Paragraph:
    # ReportLab's fallback font mapping does not reliably render Unicode
    # subscript digits. Ordinary digits stay unambiguous and portable.
    portable = text.replace("₁", "1").replace("₂", "2").replace("`", "")
    return Paragraph(f"• {portable}", style)


def slide_page(story: list, styles: dict, slide: int, title: str, sections: list[tuple[str, list[str]]]) -> None:
    story.append(Paragraph(f"Slide {slide:02d} — {title}", styles["slide_title"]))
    image = RENDERS / f"slide-{slide:02d}.png"
    if image.is_file():
        story.append(Image(str(image), width=174 * mm, height=97.9 * mm))
        story.append(Spacer(1, 4 * mm))
    for heading, lines in sections:
        block = [Paragraph(heading, styles["section"])]
        block.extend(bullet(line, styles["bullet"]) for line in lines)
        story.append(KeepTogether(block))
        story.append(Spacer(1, 2.2 * mm))
    story.append(PageBreak())


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles0 = getSampleStyleSheet()
    styles = {
        "cover": ParagraphStyle("cover", parent=styles0["Title"], fontName=FONT_BOLD, fontSize=27, leading=31, textColor=INK, alignment=TA_LEFT, spaceAfter=8 * mm),
        "subtitle": ParagraphStyle("subtitle", parent=styles0["BodyText"], fontName=FONT_REGULAR, fontSize=13, leading=18, textColor=MUTED, spaceAfter=5 * mm),
        "slide_title": ParagraphStyle("slide_title", parent=styles0["Heading1"], fontName=FONT_BOLD, fontSize=17, leading=21, textColor=INK, spaceAfter=4 * mm),
        "section": ParagraphStyle("section", parent=styles0["Heading2"], fontName=FONT_BOLD, fontSize=10.5, leading=13, textColor=BLUE, spaceBefore=1 * mm, spaceAfter=1 * mm),
        "bullet": ParagraphStyle("bullet", parent=styles0["BodyText"], fontName=FONT_REGULAR, fontSize=8.7, leading=11.2, textColor=INK, leftIndent=3 * mm, firstLineIndent=-3 * mm, spaceAfter=0.7 * mm),
        "body": ParagraphStyle("body", parent=styles0["BodyText"], fontName=FONT_REGULAR, fontSize=10, leading=14, textColor=INK, spaceAfter=3 * mm),
        "small": ParagraphStyle("small", parent=styles0["BodyText"], fontName=FONT_REGULAR, fontSize=8.5, leading=11, textColor=MUTED),
    }
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm, title="Guide d'explication des slides — longitudinal",
        author="Projet ARE — version corrigée de l'audit",
    )
    story: list = []
    story.append(Spacer(1, 28 * mm))
    story.append(Paragraph("Guide d'explication des slides", styles["cover"]))
    story.append(Paragraph("Résultats longitudinaux d'inférence écologique · panel fixe de 2 000 communes · 1962–2022", styles["subtitle"]))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Objet", styles["section"]))
    story.append(Paragraph("Ce guide explique les 20 diapositives, les axes, unités, symboles, diagnostics et limites d'interprétation. Il accompagne la présentation corrigée sans modifier les estimations centrales.", styles["body"]))
    status_table = Table(
        [["Dimension", "Statut"], ["Couverture", "KRT 240/240 · R EI 240/240"], ["Validation KRT", "41 pass · 88 caveat · 111 fail"], ["Périmètre central", "H0A et H1"], ["Extensions", "H0B, H0C, H2 à H7"], ["Restriction forte", "H3 non validée · H5 aucun pass"]],
        colWidths=[48 * mm, 114 * mm],
    )
    status_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD), ("FONTNAME", (0, 1), (0, -1), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("LEADING", (0, 0), (-1, -1), 12),
        ("BACKGROUND", (0, 1), (-1, -1), WASH), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD3DF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(status_table)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Règle de fond : une estimation calculée n'est pas automatiquement une estimation validée. Les β sont des associations écologiques estimées, jamais des comportements individuels observés ni des effets causaux.", styles["body"]))
    story.append(PageBreak())

    story.append(Paragraph("Comment lire tous les graphiques de trajectoire", styles["slide_title"]))
    for heading, lines in [
        ("Axe horizontal (abscisse)", ["Année du scrutin. Les législatives et les présidentielles sont affichées séparément; on ne les moyenne pas.", "H6 et H7 commencent en 1986 parce que les colonnes FN/RN ne sont admissibles qu'à partir de cette date."]),
        ("Axe vertical (ordonnée)", ["Contraste β₁−β₂ en proportion. Une valeur de +0,09 équivaut à +9 points de pourcentage.", "β₁ est le taux estimé du choix cible dans le groupe social cible; β₂ est le même taux dans le groupe complémentaire.", "Zéro signifie absence de contraste estimé; positif signifie β₁ supérieur à β₂; négatif signifie β₁ inférieur à β₂."]),
        ("Méthodes et incertitude", ["Bleu : KRT Python, backend PyMC ou NumPyro selon le run. Orange : King EI sous R. Or en tirets : NLS non ajusté.", "Les bandes à 95 % représentent l'incertitude fournie par KRT/R; NLS est ponctuel et ne dispose pas ici d'un intervalle validé.", "La proximité des méthodes est une information de sensibilité, pas une preuve d'identité ou de validation croisée."]),
        ("Statuts visuels", ["Point plein : `pass`.", "Point ouvert : `caveat` ou `warning`; la valeur peut être regardée avec prudence.", "Croix grise : `fail`; la ligne est interrompue à cet endroit pour éviter de présenter une continuité non validée."]),
    ]:
        story.append(Paragraph(heading, styles["section"]))
        story.extend(bullet(line, styles["body"]) for line in lines)
        story.append(Spacer(1, 2 * mm))
    story.append(PageBreak())

    slides: list[tuple[int, str, list[tuple[str, list[str]]]]] = [
        (1, "Couverture", [("Message", ["Présentation des résultats longitudinaux sur le panel fixe de 2 000 communes.", "240/240 signifie une couverture de calcul KRT et R; ce nombre n'est pas un score de validité."]), ("Visuel", ["Le graphique de couverture illustre H0A aux législatives. Il sert d'entrée en matière, pas de preuve synthétique pour les dix hypothèses."])]),
        (2, "Deux trajectoires centrales", [("Message", ["H0A (abstention populaire) et H1 (vote populaire à gauche) structurent l'argument principal.", "Les cartes 240/240 mesurent la couverture; 270/292 le diagnostic NLS pass; 41/240 le diagnostic MCMC KRT pass."]), ("Prudence", ["Le signe ≠ rappelle que couverture et validation substantielle sont différentes."])]),
        (3, "Question, données et méthodes", [("Panel", ["2 000 communes fixes, géographie harmonisée et provenance jointe."]), ("KRT", ["Modèle bêta-binomial Python; backend PyMC ou NumPyro consigné par run; β communaux et intervalles postérieurs."]), ("R et NLS", ["R EI est une réplication de sensibilité avec le modèle de King; NLS est une solution déterministe ponctuelle multi-départs."]), ("Limite", ["Toutes les méthodes utilisent des marges communales; aucune ne révèle directement le vote individuel."])]),
        (4, "H0A — législatives", [("Axes", ["x : années législatives 1962–2022; y : contraste d'abstention β populaire−β complémentaire, en proportion."]), ("Repères KRT", ["1962 : −12,0 points [−15,0; −8,9]. 1986 : +3,6 [1,4; 5,9]. 2022 : +9,0 [6,8; 11,2]."]), ("Conclusion autorisée", ["Changement de signe et transformation temporelle. Ne pas parler d'une rupture exacte ou uniforme entre toutes les méthodes."])]),
        (5, "H0A — présidentielles", [("Axes", ["x : années présidentielles; y : même contraste H0A en proportion."]), ("Repère KRT", ["2022 : +7,0 points [5,3; 8,5]."]), ("Conclusion autorisée", ["Transformation vers un contraste positif selon un calendrier propre aux présidentielles; ne pas fusionner cette série avec les législatives."])]),
        (6, "H1 — législatives", [("Axes", ["x : élections législatives; y : contraste de vote à gauche β populaire−β complémentaire."]), ("Repères KRT", ["1962 : +4,5 points [−2,9; 11,5] : l'intervalle inclut zéro.", "1986 : +13,8 [8,4; 18,8]. 2022 : −5,5 [−8,8; −2,0]."]), ("Conclusion autorisée", ["Transformation de long terme vers un contraste négatif récent; ne pas décrire 1962 comme un point positif certain."])]),
        (7, "H1 — présidentielles", [("Axes", ["x : élections présidentielles; y : même contraste H1 en proportion."]), ("Repère KRT", ["2022 : −4,1 points [−6,4; −1,8]."]), ("Prudence", ["Les points 2012 et 2017 demandent une lecture diagnostique prudente. La baisse ne constitue pas une preuve de transfert individuel."])]),
        (8, "H0B — abstention des ouvriers", [("Définition", ["β₁ : abstention estimée des ouvriers; β₂ : abstention estimée des autres groupes."]), ("Statut", ["0 pass, 23 caveat, 3 fail. Extension descriptive; pas de conclusion générale."]), ("Axes", ["Deux panneaux : législatives à gauche, présidentielles à droite; ordonnée en proportion."])]),
        (9, "H0C — abstention des employés", [("Définition", ["β₁ : abstention estimée des employés; β₂ : abstention des autres groupes."]), ("Statut", ["0 pass, 7 caveat, 19 fail. La forme graphique ne suffit pas à valider une trajectoire."]), ("Lecture", ["Les croix grises et les ruptures de ligne indiquent les segments à ne pas interpréter substantiellement."])]),
        (10, "H2 — vote à gauche des ouvriers", [("Définition", ["β₁ : vote à gauche estimé des ouvriers; β₂ : vote à gauche estimé des autres groupes."]), ("Statut", ["3 pass, 13 caveat, 10 fail. Résultat très conditionnel."]), ("Lecture", ["Comparer les calendriers électoraux, sans conclure à une trajectoire individuelle."])]),
        (11, "H3 — vote à gauche des employés", [("Définition", ["β₁ : vote à gauche estimé des employés; β₂ : celui des autres groupes."]), ("Statut critique", ["0 pass, 2 caveat, 24 fail : H3 n'est pas une série validée."]), ("Interdit", ["Ne pas dire que H3 confirme une dynamique; la figure documente un diagnostic et la sensibilité des méthodes."])]),
        (12, "H4 — vote à droite", [("Définition", ["β₁ : vote à droite estimé des agriculteurs et indépendants; β₂ : vote à droite estimé des salariés."]), ("Statut", ["5 pass, 6 caveat, 15 fail. Interprétation limitée aux cellules bien diagnostiquées."]), ("Harmonisation", ["Le vote à droite est construit comme voteCD + voteD; le complément est le reste des suffrages exprimés."])]),
        (13, "H5 — vote au centre des cadres", [("Définition", ["β₁ : vote au centre estimé des cadres; β₂ : celui des autres groupes."]), ("Statut critique", ["0 pass, 0 caveat, 26 fail. Aucun couple KRT validé."]), ("Interdit", ["H5 ne soutient aucune conclusion substantielle, même si les valeurs R/NLS sont visibles à des fins d'audit."])]),
        (14, "H6 — vote FN/RN des ouvriers", [("Définition", ["β₁ : vote FN/RN estimé des ouvriers; β₂ : celui des autres groupes."]), ("Période", ["Abscisse limitée à 1986–2022; les colonnes de vote changent selon le scrutin et sont documentées dans l'harmonisation."]), ("Statut", ["0 pass, 13 caveat, 3 fail. Extension, pas résultat central."])]),
        (15, "H7 — vote FN/RN des employés", [("Définition", ["β₁ : vote FN/RN estimé des employés; β₂ : celui des autres groupes."]), ("Période", ["Même fenêtre 1986–2022 que H6."]), ("Statut", ["0 pass, 5 caveat, 11 fail. Lecture essentiellement diagnostique."])]),
        (16, "Comparaison KRT–NLS", [("Abscisse", ["Contraste NLS en proportion."]), ("Ordonnée", ["Contraste KRT en proportion, au même couple élection × hypothèse."]), ("Diagonale", ["La droite y=x signifie égalité numérique. La distance à la diagonale mesure un désaccord entre deux objectifs statistiques."]), ("Symboles", ["Plein : pass combiné; ouvert : caveat/warning; croix grise : au moins un fail. Une proximité à la diagonale n'est pas une validation croisée."])]),
        (17, "Sensibilité KRT–R", [("Abscisse", ["Médiane de |contraste R−contraste KRT|, en proportion; 0,01 correspond à 1 point de pourcentage."]), ("Ordonnée", ["Hypothèses, triées de l'écart médian le plus grand au plus petit."]), ("Lecture", ["Une barre longue indique une plus grande sensibilité au choix du modèle. H3/H5 restent non concluantes en raison de leurs diagnostics."])]),
        (18, "Distributions communales 2022", [("Axes", ["x : moyenne postérieure communale β₁; y : moyenne postérieure communale β₂; les deux vont de 0 à 1."]), ("Couleur", ["La barre bleue compte les communes dans chaque hexagone; elle ne mesure pas une probabilité individuelle."]), ("Diagonale", ["Sous y=x : β₁ estimé supérieur à β₂; au-dessus : β₂ supérieur à β₁."]), ("Nature", ["Distribution de moyennes communales estimées, ni observations individuelles ni distribution postérieure nationale."])]),
        (19, "Diagnostics et sélection", [("KRT MCMC", ["41 pass, 88 caveat, 111 fail; total 240 couples calculés."]), ("Identification et NLS", ["Identification KRT : 17 pass, 222 caveat, 1 fail. NLS non ajusté : 270 pass, 22 fail sur 292 couples admissibles."]), ("Sélection", ["52 runs `canonical_v1.0.2` et 188 `initial_fit_user_selected`; 145 PyMC et 95 NumPyro.", "Six runs H0A/H1 sont renforcés à 2 000 tirages et 2 000 réglages."])]),
        (20, "Conclusion et livraison", [("Résultat central", ["H0A et H1 décrivent des transformations temporelles écologiques; les diagnostics restent attachés aux points."]), ("Hiérarchie", ["Central : KRT commune, KRT agrégée, NLS et H0A/H1. Extensions : R, covariables et coefficients. Vue pratique : contrastes. Atlas : annexe optionnelle."]), ("Contrat des ZIP", ["Ils permettent la lecture, l'audit et la réutilisation. La reproduction intégrale dépend du dépôt parent, des entrées et des dépendances documentées."]), ("Quatre statuts", ["Toujours distinguer couverture des calculs, intégrité de la livraison, validation numérique et périmètre scientifique retenu."])]),
    ]
    for slide, title, sections in slides:
        slide_page(story, styles, slide, title, sections)

    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return OUTPUT


if __name__ == "__main__":
    print(build())

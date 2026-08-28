from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _fonts() -> tuple[str, str]:
    windows = Path("C:/Windows/Fonts")
    regular = windows / "arial.ttf"
    bold = windows / "arialbd.ttf"
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("ReleaseSans", regular))
        pdfmetrics.registerFont(TTFont("ReleaseSans-Bold", bold))
        return "ReleaseSans", "ReleaseSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _table(records: list[dict[str, Any]], columns: list[tuple[str, str]], widths: list[float], font: str) -> Table:
    header = [Paragraph(label, ParagraphStyle("th", fontName=font, fontSize=7, leading=8, textColor=colors.white)) for _, label in columns]
    data = [header]
    cell_style = ParagraphStyle("td", fontName=font, fontSize=6.5, leading=8)
    for record in records:
        data.append([Paragraph(_fmt(record.get(key, "")), cell_style) for key, _ in columns])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#245c8a")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ccd8e2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _scaled_image(path: Path, max_width: float, max_height: float) -> Image:
    image = Image(str(path))
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def render(payload_path: Path, release_root: Path, output: Path) -> None:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    font, bold = _fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("ReleaseTitle", parent=styles["Title"], fontName=bold, fontSize=23, leading=27, textColor=colors.HexColor("#172033"), spaceAfter=8))
    styles.add(ParagraphStyle("ReleaseH1", parent=styles["Heading1"], fontName=bold, fontSize=15, leading=18, textColor=colors.HexColor("#245c8a"), spaceBefore=14, spaceAfter=8))
    styles.add(ParagraphStyle("ReleaseBody", parent=styles["BodyText"], fontName=font, fontSize=9.3, leading=13, spaceAfter=7))
    styles.add(ParagraphStyle("ReleaseSmall", parent=styles["BodyText"], fontName=font, fontSize=7.5, leading=10, textColor=colors.HexColor("#5e6b78")))
    styles.add(ParagraphStyle("ReleaseStatus", parent=styles["BodyText"], fontName=bold, fontSize=10, leading=14, backColor=colors.HexColor("#eef4f8"), borderColor=colors.HexColor("#245c8a"), borderWidth=1, borderPadding=8, spaceAfter=12))

    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=1.55 * cm,
        leftMargin=1.55 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.55 * cm,
        title="Rapport technique longitudinal 2000 v1.0.1 H0A-H1",
        author="Projet longitudinal — release auditée",
    )

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#5e6b78"))
        canvas.drawString(1.55 * cm, 0.75 * cm, payload["release_id"])
        canvas.drawRightString(A4[0] - 1.55 * cm, 0.75 * cm, f"Page {document.page}")
        canvas.restoreState()

    story: list[Any] = []
    story.append(Paragraph("Release longitudinale v1.0.1 — H0A/H1", styles["ReleaseTitle"]))
    story.append(Paragraph(payload["release_id"], styles["ReleaseSmall"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Conclusion : {payload['headline']}<br/>ready={str(payload['ready']).lower()} ; ready_scope={payload['ready_scope']}.",
        styles["ReleaseStatus"],
    ))
    counts = payload["counts"]
    story.append(
        _table(
            [{"panel": counts["panel_units"], "elections": counts["elections"], "krt": counts["krt_pairs"], "nls": counts["nls_pairs"], "rows": counts["krt_commune_rows"]}],
            [("panel", "Communes"), ("elections", "Scrutins"), ("krt", "Couples KRT"), ("nls", "Couples NLS"), ("rows", "Lignes KRT communales")],
            [2.5 * cm, 2.5 * cm, 3 * cm, 3 * cm, 5.5 * cm],
            font,
        )
    )
    story.append(Paragraph("1. Périmètre et interprétation", styles["ReleaseH1"]))
    story.append(Paragraph(
        "La release conserve 52 couples KRT (H0A et H1 pour 26 scrutins) et 270 couples NLS. Les 22 RxC restent audités mais différés. Les diagnostics de convergence MCMC, d’identification écologique et de stabilité entre spécifications sont maintenus comme trois verdicts distincts.",
        styles["ReleaseBody"],
    ))
    story.append(Paragraph(
        "Convergence MCMC canonique : " + ", ".join(f"{key}={value}" for key, value in counts["mcmc"].items())
        + ". Identification écologique : " + ", ".join(f"{key}={value}" for key, value in counts["identification"].items()) + ".",
        styles["ReleaseSmall"],
    ))
    story.append(Paragraph("2. Panel et département 54", styles["ReleaseH1"]))
    story.append(Paragraph(payload["department54"]["conclusion"], styles["ReleaseBody"]))
    story.append(Paragraph(
        f"Couverture : {payload['coverage']['rows']} lignes élection × département. Les mêmes 2 000 unit_id sont présents aux 26 scrutins "
        f"(52 000 clés) ; SMD maximal={payload['panel_validation']['max_abs_smd_all_elections']:.4f}, écart catégoriel maximal={payload['panel_validation']['max_abs_category_gap_all_elections']:.4f}. "
        f"Hash du panel : {payload['hashes']['panel_2000_master_file']}.",
        styles["ReleaseSmall"],
    ))

    story.append(Paragraph("3. Sensibilité H1", styles["ReleaseH1"]))
    story.append(Paragraph(
        "La mention pipeline_only n’est utilisée que lorsque les hashes des matrices X, Y et N sont identiques. Les différences entre tirages issus de fits indépendants sont des distributions descriptives, pas des intervalles formels d’un effet causal.",
        styles["ReleaseBody"],
    ))
    story.append(Paragraph(
        "Anomalies historiques V2 : 59473 en 1962 (178 inscrits, 149 votants, 150 exprimés), puis 02643, 06149 et 14606 en 1986, "
        "dont les exprimés dépassent les votants. Elles restent uniquement dans les cellules diagnostiques de l’ancien panel V2 afin de préserver "
        "les matrices effectivement estimées ; les partitions X/Y/N ferment exactement et le panel canonique n’est pas concerné.",
        styles["ReleaseBody"],
    ))
    nls_sensitivity = payload.get("sensitivity_nls", [])
    if nls_sensitivity:
        story.append(Paragraph("Contrôles rapides NLS et composition", styles["ReleaseH1"]))
        story.append(_table(
            nls_sensitivity,
            [
                ("election_id", "Scrutin"), ("cell", "Cellule"), ("n_communes", "n"),
                ("nls_contrast", "Contraste NLS"), ("target_group_share_unweighted", "Part groupe"),
                ("left_vote_share", "Vote gauche"), ("vbbm_mean", "VBBM moyen"), ("n_departments", "Départ."),
            ],
            [2.4 * cm, 5.3 * cm, 1 * cm, 1.8 * cm, 1.8 * cm, 1.7 * cm, 1.7 * cm, 1 * cm],
            font,
        ))
    sensitivity = payload.get("sensitivity", [])
    if sensitivity:
        display = []
        for row in sensitivity:
            if row.get("row_type") == "estimate":
                display.append({
                    "election": row.get("election_id"), "cell": row.get("cell_label"), "mean": row.get("mean"),
                    "interval": f"[{_fmt(row.get('q025'))} ; {_fmt(row.get('q975'))}]", "scope": "estimation",
                })
            else:
                display.append({
                    "election": row.get("election_id"), "cell": row.get("comparison_label"), "mean": row.get("difference_mean"),
                    "interval": f"[{_fmt(row.get('difference_q025_descriptive'))} ; {_fmt(row.get('difference_q975_descriptive'))}]", "scope": "différence descriptive",
                })
        story.append(_table(display, [("election", "Scrutin"), ("cell", "Cellule/comparaison"), ("mean", "Contraste/diff."), ("interval", "Intervalle 95 %"), ("scope", "Portée")], [2.5 * cm, 6.3 * cm, 2.6 * cm, 3.4 * cm, 3.1 * cm], font))
    else:
        story.append(Paragraph("Résultats KRT de sensibilité en cours.", styles["ReleaseSmall"]))

    story.append(Paragraph("4. Relances MCMC ciblées", styles["ReleaseH1"]))
    targeted = payload.get("targeted_reruns", [])
    if targeted:
        story.append(_table(targeted, [("election_id", "Scrutin"), ("scenario_id", "Hyp."), ("old_contrast_mean", "Ancien"), ("new_contrast_mean", "Nouveau"), ("new_mcmc_status", "MCMC"), ("identification_status", "Identification"), ("estimate_stability_status", "Stabilité"), ("selected_reason", "Sélection")], [2.4 * cm, 1.2 * cm, 1.7 * cm, 1.7 * cm, 1.5 * cm, 2.1 * cm, 1.7 * cm, 5.5 * cm], font))
    else:
        story.append(Paragraph("Relances ciblées en cours ou non finalisées.", styles["ReleaseSmall"]))

    story.append(PageBreak())
    story.append(Paragraph("5. Comparaison KRT–NLS", styles["ReleaseH1"]))
    story.append(Paragraph("Les points NLS sont présentés sans pseudo-intervalles postérieurs ; les intervalles appartiennent au KRT.", styles["ReleaseBody"]))
    comparison = payload.get("krt_nls", [])
    if comparison:
        rows = []
        for row in comparison:
            rows.append({
                "election": row.get("election_id"), "scenario": row.get("scenario_id"),
                "krt": row.get("krt_contrast_mean"),
                "interval": f"[{_fmt(row.get('krt_contrast_q025'))} ; {_fmt(row.get('krt_contrast_q975'))}]",
                "nls": row.get("nls_contrast"), "inside": row.get("nls_inside_krt_interval"),
                "mcmc": row.get("mcmc_status"), "ident": row.get("identification_status"),
            })
        story.append(_table(rows, [("election", "Scrutin"), ("scenario", "Hyp."), ("krt", "KRT"), ("interval", "IC KRT 95 %"), ("nls", "NLS"), ("inside", "NLS dans IC"), ("mcmc", "MCMC"), ("ident", "Identification")], [2.7 * cm, 1.2 * cm, 1.5 * cm, 3.3 * cm, 1.5 * cm, 2.1 * cm, 1.8 * cm, 2.7 * cm], font))
    story.append(Paragraph("6. Réplication NLS R/Python", styles["ReleaseH1"]))
    replication = payload.get("nls_replication", [])
    if replication:
        story.append(_table(replication, [(key, key.replace("_", " ")) for key in replication[0]], [17.7 * cm / len(replication[0])] * len(replication[0]), font))
    story.append(Paragraph("7. RxC différés", styles["ReleaseH1"]))
    rxc = payload["rxc"]
    story.append(Paragraph(
        f"{rxc['pairs']} couples audités ; {rxc['offenders_in_panel']} unité fautive appartient au panel 2 000 ; {rxc['panel_exact_closure_failures']} matrice panel échoue à la fermeture exacte. Exécution : {rxc['status']}.",
        styles["ReleaseBody"],
    ))

    for index, relative in enumerate(payload.get("figures", []), start=1):
        path = release_root / relative
        if not path.exists():
            continue
        story.append(PageBreak())
        story.append(Paragraph(f"Figure {index}. {path.stem.replace('_', ' ')}", styles["ReleaseH1"]))
        story.append(_scaled_image(path, 17.7 * cm, 22.5 * cm))

    story.append(PageBreak())
    story.append(Paragraph("8. Réserves et reproduction", styles["ReleaseH1"]))
    for reserve in payload["reserves"]:
        story.append(Paragraph(f"• {reserve}", styles["ReleaseBody"]))
    story.append(Paragraph("9. Empreintes de référence", styles["ReleaseH1"]))
    hash_records = [{"objet": key, "sha256": value} for key, value in payload["hashes"].items()]
    story.append(_table(hash_records, [("objet", "Objet"), ("sha256", "SHA-256")], [5 * cm, 12.7 * cm], font))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the v1.0.1 technical report PDF from its JSON payload.")
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--release-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    render(args.payload, args.release_root, args.output)
    print(args.output)


if __name__ == "__main__":
    main()

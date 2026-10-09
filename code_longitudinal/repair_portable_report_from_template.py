from __future__ import annotations

"""Repair a portable Data Analytics report from its prior validated template.

This is used only because the installed skill package contains the portable
report contract but not its delivery script.  The previous full report keeps
the official reader runtime and CSS; this script replaces the canonical
artifact payload and regenerates the semantic fallback from that same payload.
"""

import argparse
import base64
import gzip
import html
import json
import re
import zipfile
from pathlib import Path

import mistune
from reproducibility.replication_scope import get_scope


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_ZIP = ROOT / "deliverables" / "longitudinal_2000_release_professeur.zip"
DEFAULT_ARTIFACT = ROOT / "work" / "professor_report_build" / "artifact.json"
DEFAULT_OUTPUT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "01_RAPPORT" / "RAPPORT_LONGITUDINAL.html"
DEFAULT_FIGURES = ROOT / "work" / "longitudinal_2000_release_professeur_candidate" / "03_FIGURES"

STATIC_CHARTS: dict[str, list[str]] = {
    "h0a_chart": ["trajectoire_H0A/H0A_legislative.png", "trajectoire_H0A/H0A_presidential.png"],
    "h1_chart": ["trajectoire_H1/H1_legislative.png", "trajectoire_H1/H1_presidential.png"],
    "cov_summary_chart": [
        "sensibilite_NLS_covariables/sensibilite_nls_legislative.png",
        "sensibilite_NLS_covariables/sensibilite_nls_presidential.png",
    ],
    "krt_nls_chart": ["comparaison_KRT_NLS/comparaison_krt_nls.png"],
}
for _scenario in ("H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7"):
    STATIC_CHARTS[f"trajectory_{_scenario}_chart"] = [
        f"trajectoires_KRT_R_NLS_toutes_hypotheses/{_scenario}/{_scenario}_legislative.png",
        f"trajectoires_KRT_R_NLS_toutes_hypotheses/{_scenario}/{_scenario}_presidential.png",
    ]
TABULAR_CHARTS = frozenset({"gap_chart", "diagnostics_chart"})
DENSITY_SUMMARIES = [
    "atlas_densites_resumes/krt_python/H0A/legislative.png",
    "atlas_densites_resumes/r_eipack/H0A/legislative.png",
    "atlas_densites_resumes/krt_python/H1/presidential.png",
    "atlas_densites_resumes/r_eipack/H1/presidential.png",
]


def density_summary_paths() -> list[str]:
    """Keep the historical summary selection, restricted explicitly by scope."""
    scope = get_scope()
    if scope.is_full:
        return list(DENSITY_SUMMARIES)
    result = []
    for scenario, preferred in (("H0A", "legislative"), ("H1", "presidential")):
        families = {"legislative" if election.startswith("leg_") else "presidential"
                    for election, selected_scenario in scope.pairs if selected_scenario == scenario}
        if not families:
            raise ValueError("Density summary has no scoped source pairs: " + scenario)
        family = preferred if preferred in families else sorted(families)[0]
        result.extend(f"atlas_densites_resumes/{method}/{scenario}/{family}.png"
                      for method in ("krt_python", "r_eipack"))
    return result


def load_template(path: Path) -> str:
    if path.suffix.lower() in {".html", ".htm"}:
        return path.read_text(encoding="utf-8")
    with zipfile.ZipFile(path) as archive:
        member = "01_RAPPORT/RAPPORT_LONGITUDINAL.html"
        if member not in archive.namelist():
            raise FileNotFoundError(f"{member} is absent from {path}")
        return archive.read(member).decode("utf-8")


def scalar(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def source_label(manifest: dict[str, object], source_id: str | None) -> str:
    if not source_id:
        return ""
    for source in manifest.get("sources", []):
        if source.get("id") == source_id:
            label = html.escape(str(source.get("label", source_id)))
            path = html.escape(str(source.get("path", "")))
            return f'<p class="portable-source-context">Source : {label} — {path}</p>'
    return ""


def render_table(table: dict[str, object], datasets: dict[str, list[dict[str, object]]]) -> str:
    rows = datasets.get(str(table["dataset"]), [])
    columns = table.get("columns", [])
    head = "".join(f"<th>{html.escape(str(column.get('label', column['field'])))}</th>" for column in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(scalar(row.get(str(column['field']))))}</td>" for column in columns)
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<section class="portable-content-card"><h3>{html.escape(str(table.get("title", "Table")))}</h3>'
        f'<p class="portable-chart-description">{html.escape(str(table.get("subtitle", "")))}</p>'
        f'<div class="portable-table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div></section>'
    )


def image_data_uri(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def render_static_figures(
    paths: list[str],
    figures_root: Path,
    *,
    label: str,
    one_per_page: bool = False,
) -> str:
    figures = []
    image_style = (
        "display:block;width:100%;height:auto;max-height:185mm;object-fit:contain"
        if one_per_page
        else "display:block;width:88%;height:auto;max-height:175mm;object-fit:contain;margin:0 auto"
    )
    for index, relative in enumerate(paths):
        source = figures_root / relative
        caption = html.escape(Path(relative).stem.replace("_", " "))
        figures.append(
            f'<figure style="break-inside:avoid;page-break-inside:avoid;'
            f'{"break-before:page;page-break-before:always;" if one_per_page and index else ""}'
            'margin:12px 0 20px">'
            f'<img src="{image_data_uri(source)}" alt="{html.escape(label)} — {caption}" '
            f'style="{image_style}">'
            f'<figcaption style="font-size:0.82rem;color:#475569;margin-top:6px">{caption}</figcaption></figure>'
        )
    return "".join(figures)


def render_chart(
    chart: dict[str, object],
    datasets: dict[str, list[dict[str, object]]],
    figures_root: Path,
) -> str:
    rows = datasets.get(str(chart["dataset"]), [])
    fields: list[str] = []
    encodings = chart.get("encodings", {})
    for encoding in encodings.values():
        values = encoding if isinstance(encoding, list) else [encoding]
        for value in values:
            if isinstance(value, dict) and value.get("field") and value["field"] not in fields:
                fields.append(str(value["field"]))
    contextual = [key for key in (rows[0].keys() if rows else []) if key not in fields]
    fields.extend(contextual[:3])
    head = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(scalar(row.get(field)))}</td>" for field in fields) + "</tr>")
    chart_id = str(chart.get("id", ""))
    static_paths = STATIC_CHARTS.get(chart_id)
    if not static_paths and chart_id not in TABULAR_CHARTS:
        raise ValueError("No historical print renderer for chart: " + chart_id)
    if static_paths:
        representation = (
            '<p class="portable-chart-description">Version statique haute résolution du graphique interactif, '
            'incluse pour l’impression et le PDF.</p>'
            + render_static_figures(static_paths, figures_root, label=str(chart.get("title", "Graphique")))
        )
    else:
        representation = (
            '<p class="portable-chart-description">Données exactes du graphique interactif, présentées sous forme '
            'tabulaire pour l’impression et l’accessibilité.</p>'
            f'<div class="portable-table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>'
        )
    return (
        f'<section class="portable-content-card portable-chart-card"><h3>{html.escape(str(chart.get("title", "Graphique")))}</h3>'
        f'<p class="portable-chart-description">{html.escape(str(chart.get("subtitle", "")))}</p>'
        f'{representation}</section>'
    )


def render_fallback(artifact: dict[str, object], figures_root: Path) -> str:
    manifest = artifact["manifest"]
    datasets = artifact["snapshot"]["datasets"]
    cards = {card["id"]: card for card in manifest.get("cards", [])}
    charts = {chart["id"]: chart for chart in manifest.get("charts", [])}
    tables = {table["id"]: table for table in manifest.get("tables", [])}
    markdown = mistune.create_markdown(escape=False)
    blocks = []
    for block in manifest.get("blocks", []):
        block_type = block.get("type")
        content = ""
        if block_type == "markdown":
            content = f'<section class="portable-markdown">{markdown(str(block.get("body", "")))}</section>'
        elif block_type == "metric-strip":
            cells = []
            for card_id in block.get("cardIds", []):
                card = cards[card_id]
                rows = datasets.get(str(card["dataset"]), [])
                row = rows[0] if rows else {}
                metric = card.get("metrics", [])[0]
                value = scalar(row.get(str(metric["field"])))
                cells.append(
                    f'<article class="portable-metric-card"><strong>{html.escape(value)}</strong>'
                    f'<span>{html.escape(str(metric.get("label", metric["field"])))}</span></article>'
                )
            content = f'<section class="portable-metric-grid">{"".join(cells)}</section>'
        elif block_type == "chart":
            content = render_chart(charts[block["chartId"]], datasets, figures_root)
        elif block_type == "table":
            content = render_table(tables[block["tableId"]], datasets)
        else:
            continue
        if block.get("id") == "distribution":
            summaries = density_summary_paths()
            description = (
                'Quatre planches représentatives sont imprimées ci-dessous. '
                'L’annexe HTML reliée au rapport contient les 480 graphiques individuels KRT et R EI.'
                if get_scope().is_full else
                f'{len(summaries)} planches H0A/H1 issues des familles de scrutin présentes dans le périmètre sont imprimées ci-dessous. '
                f'L’annexe HTML contient les {get_scope().density_count} graphiques individuels KRT et R EI de ce périmètre.'
            )
            content += (
                '<section class="portable-content-card"><h3>Planches marginales intégrées au rapport</h3>'
                '<p class="portable-chart-description">' + description + '</p>'
                + render_static_figures(summaries, figures_root,
                                        label="Atlas des densités marginales", one_per_page=True)
                + "</section>"
            )
        content += source_label(manifest, block.get("sourceId"))
        break_style = "break-before:page;page-break-before:always;" if block.get("id") == "diagnostics" else ""
        blocks.append(
            f'<div class="portable-block portable-layout-full" data-artifact-block-id="{html.escape(str(block["id"]))}" '
            f'data-artifact-block-type="{html.escape(str(block_type))}" data-layout="full" '
            f'style="{break_style}">{content}</div>'
        )
    title = html.escape(str(manifest["title"]))
    description = html.escape(str(manifest.get("description", "")))
    generated = html.escape(str(manifest.get("generatedAt", "")))
    return (
        '<main id="data-analytics-portable-fallback" class="portable-fallback" data-portable-fallback="true" data-portable-surface="report">'
        f'<header class="portable-page-header"><div class="portable-page-heading"><p class="portable-surface-label">Rapport analytique</p><h1>{title}</h1>'
        f'<p class="portable-description">{description}</p></div><div class="portable-page-meta"><time datetime="{generated}">{generated}</time></div></header>'
        f'<div class="portable-block-stack">{"".join(blocks)}</div></main>'
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-zip", type=Path, default=DEFAULT_TEMPLATE_ZIP)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--figures", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    template = load_template(args.template_zip.resolve())
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    compact = json.dumps(artifact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = base64.b64encode(gzip.compress(compact, compresslevel=9, mtime=0)).decode("ascii")
    payload_wrapped = "\n".join(payload[index : index + 76] for index in range(0, len(payload), 76))
    template, payload_count = re.subn(
        r'(<template id="data-analytics-portable-artifact-payload-source"[^>]*>).*?(</template>)',
        lambda match: match.group(1) + "\n" + payload_wrapped + "\n" + match.group(2),
        template,
        count=1,
        flags=re.S,
    )
    if payload_count != 1:
        raise AssertionError("portable artifact payload template was not replaced exactly once")
    fallback = render_fallback(artifact, args.figures.resolve())
    start = template.index('<main id="data-analytics-portable-fallback"')
    end = template.index("</main>", start) + len("</main>")
    template = template[:start] + fallback + template[end:]
    template = re.sub(r"<title>.*?</title>", f"<title>{html.escape(str(artifact['manifest']['title']))}</title>", template, count=1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(template, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "output": str(args.output),
                "bytes": args.output.stat().st_size,
                "blocks": len(artifact["manifest"]["blocks"]),
                "charts": len(artifact["manifest"]["charts"]),
                "datasets": len(artifact["snapshot"]["datasets"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

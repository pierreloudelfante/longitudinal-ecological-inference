from __future__ import annotations

"""Integrate the 480 validated density figures into the professor release.

The main report can cite compact contact sheets, while the HTML atlas exposes
every full-size PNG at the election × scenario × method grain.
"""

import argparse
import html
import json
import os
import shutil
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from reproducibility.replication_scope import get_scope


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deliverables" / "longitudinal_2000_densites_completes"
LIGHT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate"
SCENARIOS = ["H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"]
METHOD_LABELS = {"krt_python": "KRT Python", "r_eipack": "R EI"}
FAMILY_LABELS = {"legislative": "Législatives", "presidential": "Présidentielles"}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windows = Path(os.environ.get("WINDIR", "")) / "Fonts"
    candidate = windows / ("arialbd.ttf" if bold else "arial.ttf")
    if candidate.is_file():
        return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def copy_full_size(catalog: pd.DataFrame, output: Path) -> pd.DataFrame:
    rows = []
    for row in catalog.itertuples(index=False):
        source = SOURCE / str(row.png)
        destination = (
            output
            / "03_FIGURES"
            / "densites_completes"
            / str(row.method)
            / str(row.scenario_id)
            / f"{row.election_id}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record = row._asdict()
        record["report_png"] = str(destination.relative_to(output)).replace("\\", "/")
        rows.append(record)
    return pd.DataFrame(rows)


def contact_sheet(frame: pd.DataFrame, destination: Path, title: str) -> None:
    frame = frame.sort_values(["year", "round", "election_id"])
    cell_width, cell_height = 440, 350
    columns = 4
    rows = (len(frame) + columns - 1) // columns
    header_height = 90
    canvas = Image.new("RGB", (columns * cell_width, header_height + rows * cell_height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 20), title, fill="#20242A", font=font(28, bold=True))
    draw.text(
        (30, 57),
        "Distributions des moyennes communales estimées β₁–β₂ ; ni individus observés ni posterior national.",
        fill="#5B6472",
        font=font(16),
    )
    for index, row in enumerate(frame.itertuples(index=False)):
        image = Image.open(LIGHT / str(row.report_png)).convert("RGB")
        image.thumbnail((cell_width - 22, cell_height - 46), Image.Resampling.LANCZOS)
        x0 = (index % columns) * cell_width
        y0 = header_height + (index // columns) * cell_height
        x = x0 + (cell_width - image.width) // 2
        y = y0 + 34
        canvas.paste(image, (x, y))
        draw.text((x0 + 12, y0 + 8), str(row.election_id), fill="#20242A", font=font(17, bold=True))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG", optimize=True)


def _html_catalog(catalog: pd.DataFrame) -> str:
    columns = [
        "method",
        "scenario_id",
        "election_type",
        "election_id",
        "year",
        "round",
        "finite_both",
        "total_rows",
        "warning",
        "report_png",
    ]
    records = catalog.loc[:, columns].copy()
    records["warning"] = records["warning"].fillna("").astype(str)
    for column in ("year", "round", "finite_both", "total_rows"):
        records[column] = pd.to_numeric(records[column], errors="raise").astype(int)
    # Avoid allowing an accidental closing script tag in catalog text.
    return json.dumps(records.to_dict("records"), ensure_ascii=False).replace("</", "<\\/")


def build_full_size_reader(catalog: pd.DataFrame, output: Path) -> None:
    """Write a local, full-width reader showing one election/scenario pair at a time."""

    data = _html_catalog(catalog)
    scope = get_scope()
    coverage_label = (
        "toutes les législatives de 1962 à 2022 et toutes les présidentielles de 1965 à 2022"
        if scope.is_full else "uniquement les scrutins sélectionnés : " + ", ".join(sorted(scope.election_ids))
    )
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lecteur plein format — densités communales, périmètre {scope.name}</title>
<style>
:root{{--ink:#20242a;--muted:#5b6472;--line:#d8dde5;--blue:#2457a7;--paper:#fff;--wash:#f4f6f9}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--wash);color:var(--ink);font-family:Arial,sans-serif}}
header{{background:var(--paper);border-bottom:1px solid var(--line);padding:22px 4vw}}
header h1{{margin:0 0 8px;font-size:clamp(24px,3vw,36px)}}header p{{max-width:1100px;margin:6px 0;color:var(--muted);line-height:1.45}}
.controls{{position:sticky;top:0;z-index:3;display:flex;flex-wrap:wrap;gap:12px;align-items:end;background:rgba(255,255,255,.98);border-bottom:1px solid var(--line);padding:14px 4vw}}
label{{display:grid;gap:4px;font-size:13px;color:var(--muted)}}select,button{{min-height:40px;border:1px solid #aeb6c2;border-radius:5px;background:white;color:var(--ink);font:inherit;padding:7px 10px}}
button{{cursor:pointer;font-weight:bold}}button:hover{{border-color:var(--blue);color:var(--blue)}}.position{{margin-left:auto;align-self:center;color:var(--muted);font-size:14px}}
main{{max-width:2200px;margin:20px auto;padding:0 24px 48px}}.pair-title{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;align-items:baseline;margin:0 0 14px}}
.pair-title h2{{margin:0;font-size:clamp(21px,2.5vw,30px)}}.pair-title a,.overview-link,a.direct{{color:var(--blue)}}
figure{{margin:0 0 24px;border:1px solid var(--line);padding:14px;background:var(--paper);box-shadow:0 2px 8px rgba(32,36,42,.06)}}
figure h3{{margin:0 0 10px;font-size:21px}}figure img{{display:block;width:100%;height:auto;border:1px solid #edf0f4}}
figcaption{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:14px;color:var(--muted);padding:10px 2px 0;line-height:1.4}}
.notice{{background:#eef4fb;border-left:4px solid var(--blue);padding:12px 14px;margin:0 0 18px;line-height:1.45}}
@media(max-width:760px){{.position{{width:100%;margin-left:0}}main{{padding:0 8px 30px}}figure{{padding:7px}}}}
</style></head><body>
<header><h1>Densités communales — lecteur plein format, périmètre {scope.name}</h1>
<p>Choisissez une hypothèse et un scrutin. Les deux méthodes sont affichées l'une sous l'autre en pleine largeur. Les {scope.pair_count} couples élection × hypothèse couvrent {coverage_label}; chaque couple possède une figure KRT Python et une figure King EI sous R, soit {scope.density_count} PNG.</p>
<p>Chaque planche contient la distribution 2D de β₁–β₂ et les deux densités marginales. Cliquez sur une image ou sur « ouvrir le PNG seul » pour l'afficher à sa résolution native de 2100 × 760 px.</p>
<p><a class="overview-link" href="ANNEXE_ATLAS_DENSITES_GRILLE.html">Voir aussi la grille d'ensemble</a>.</p></header>
<div class="controls">
<label>Hypothèse<select id="scenario"></select></label>
<label>Type de scrutin<select id="family"><option value="legislative">Législatives</option><option value="presidential">Présidentielles</option></select></label>
<label>Année et scrutin<select id="election"></select></label>
<button type="button" id="previous">← Précédent</button><button type="button" id="next">Suivant →</button>
<span class="position" id="position"></span>
</div>
<main><div class="notice">Lecture correcte : distributions de moyennes communales estimées, et non observations individuelles ni distribution postérieure nationale. Les éventuelles valeurs R non finies sont exclues sans imputation et la couverture figure sous l'image.</div>
<div class="pair-title"><h2 id="pairTitle"></h2></div><div id="figures"></div></main>
<script>
const records={data};
const methodLabels={{krt_python:"KRT Python",r_eipack:"King EI — R/eiPack"}};
const familyLabels={{legislative:"Législatives",presidential:"Présidentielles"}};
const scenarios=[...new Set(records.map(r=>r.scenario_id))];
const scenario=document.getElementById("scenario"),family=document.getElementById("family"),election=document.getElementById("election");
for(const value of scenarios) scenario.add(new Option(value,value));
function availablePairs(){{
  const byKey=new Map();
  for(const row of records){{
    if(row.scenario_id!==scenario.value||row.election_type!==family.value) continue;
    const key=row.election_id;
    if(!byKey.has(key)) byKey.set(key,{{election_id:key,year:row.year,round:row.round}});
  }}
  return [...byKey.values()].sort((a,b)=>a.year-b.year||a.round-b.round||a.election_id.localeCompare(b.election_id));
}}
function populateElections(preferred){{
  const pairs=availablePairs(); election.replaceChildren();
  for(const pair of pairs) election.add(new Option(`${{pair.year}} · ${{pair.election_id}}`,pair.election_id));
  if(preferred&&pairs.some(p=>p.election_id===preferred)) election.value=preferred;
  render();
}}
function escapeText(value){{const span=document.createElement("span");span.textContent=String(value);return span.innerHTML}}
function render(){{
  const pairs=availablePairs(),index=Math.max(0,pairs.findIndex(p=>p.election_id===election.value)),pair=pairs[index];
  if(!pair) {{document.getElementById("pairTitle").textContent="Hors périmètre : aucun scrutin sélectionné";document.getElementById("position").textContent="0 scrutin";document.getElementById("figures").replaceChildren();return;}}
  const rows=records.filter(r=>r.scenario_id===scenario.value&&r.election_id===pair.election_id).sort((a,b)=>Object.keys(methodLabels).indexOf(a.method)-Object.keys(methodLabels).indexOf(b.method));
  document.getElementById("pairTitle").textContent=`${{scenario.value}} · ${{familyLabels[family.value]}} · ${{pair.year}} (${{pair.election_id}})`;
  document.getElementById("position").textContent=`Scrutin ${{index+1}} / ${{pairs.length}} dans cette série · 2 figures plein format`;
  document.getElementById("figures").innerHTML=rows.map(row=>{{
    const path="../"+row.report_png,warning=row.warning?` · ${{escapeText(row.warning)}}`:"";
    return `<figure><h3>${{methodLabels[row.method]||escapeText(row.method)}}</h3><a href="${{path}}" target="_blank"><img src="${{path}}" alt="Densités ${{escapeText(row.method)}} ${{escapeText(row.election_id)}} ${{escapeText(row.scenario_id)}}"></a><figcaption><span>Couples β₁–β₂ finis : ${{row.finite_both}} / ${{row.total_rows}}${{warning}}</span><a class="direct" href="${{path}}" target="_blank">Ouvrir le PNG seul (2100 × 760)</a></figcaption></figure>`;
  }}).join("");
}}
function move(delta){{const pairs=availablePairs();if(!pairs.length)return;const index=pairs.findIndex(p=>p.election_id===election.value),target=pairs[(index+delta+pairs.length)%pairs.length];election.value=target.election_id;render()}}
scenario.addEventListener("change",()=>populateElections());family.addEventListener("change",()=>populateElections());election.addEventListener("change",render);
document.getElementById("previous").addEventListener("click",()=>move(-1));document.getElementById("next").addEventListener("click",()=>move(1));
document.addEventListener("keydown",event=>{{if(event.key==="ArrowLeft")move(-1);if(event.key==="ArrowRight")move(1)}});
scenario.value=scenarios.includes("H0A")?"H0A":scenarios[0];populateElections();
</script></body></html>
"""
    report_dir = output / "01_RAPPORT"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "ANNEXE_ATLAS_DENSITES.html").write_text(document, encoding="utf-8")


def build_overview_html(catalog: pd.DataFrame, output: Path) -> None:
    sections = []
    for method in METHOD_LABELS:
        sections.append(f'<section><h2 id="{method}">{METHOD_LABELS[method]}</h2>')
        for scenario in SCENARIOS:
            subset = catalog.loc[(catalog["method"] == method) & (catalog["scenario_id"] == scenario)]
            if subset.empty:
                continue
            sections.append(f'<h3 id="{method}-{scenario}">{scenario}</h3>')
            for family in ["legislative", "presidential"]:
                part = subset.loc[subset["election_type"] == family].sort_values(["year", "round"])
                if part.empty:
                    continue
                sections.append(f'<h4>{FAMILY_LABELS[family]}</h4><div class="gallery">')
                for row in part.itertuples(index=False):
                    image_path = "../" + str(row.report_png)
                    warning = "" if not isinstance(row.warning, str) or not row.warning else f" — {html.escape(row.warning)}"
                    caption = (
                        f"{row.election_id} · n finis conjoints {int(row.finite_both)}/{int(row.total_rows)}{warning}"
                    )
                    sections.append(
                        f'<figure><a href="{html.escape(image_path)}"><img loading="lazy" src="{html.escape(image_path)}" '
                        f'alt="Densités {METHOD_LABELS[method]} {row.election_id} {scenario}"></a>'
                        f'<figcaption>{html.escape(caption)}</figcaption></figure>'
                    )
                sections.append("</div>")
        sections.append("</section>")
    nav = " ".join(f'<a href="#{method}">{label}</a>' for method, label in METHOD_LABELS.items())
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grille d'ensemble — distributions des moyennes communales estimées β</title>
<style>
:root{{--ink:#20242a;--muted:#5b6472;--line:#d8dde5;--blue:#2457a7;--paper:#fff;--wash:#f4f6f9}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--wash);color:var(--ink);font-family:Arial,sans-serif}}
header{{position:sticky;top:0;z-index:2;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);padding:18px 4vw}}
header h1{{margin:0 0 8px;font-size:28px}}header p{{margin:0;color:var(--muted)}}nav{{margin-top:10px}}nav a{{margin-right:16px;color:var(--blue)}}
main{{max-width:1500px;margin:24px auto;padding:0 24px}}section{{background:var(--paper);padding:24px;margin-bottom:28px;border:1px solid var(--line)}}
h2{{font-size:25px;margin-top:0}}h3{{font-size:21px;border-top:1px solid var(--line);padding-top:20px}}h4{{color:var(--muted)}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:18px}}
figure{{margin:0;border:1px solid var(--line);padding:10px;background:white}}img{{display:block;width:100%;height:auto}}figcaption{{font-size:13px;color:var(--muted);padding:8px 3px 2px}}
@media(max-width:600px){{.gallery{{grid-template-columns:1fr}}main{{padding:0 10px}}}}
</style></head><body>
<header><h1>Grille d'ensemble — distributions des moyennes communales estimées β</h1>
<p>{get_scope().density_count} couples méthode × élection × hypothèse, périmètre {get_scope().name}. Ces figures décrivent des estimations au niveau communal, pas des observations individuelles ni une distribution postérieure nationale. Chaque vignette ouvre le PNG plein format. Les valeurs R non finies sont exclues sans imputation et leur couverture est indiquée.</p>
<p><a href="ANNEXE_ATLAS_DENSITES.html">Revenir au lecteur plein format</a>.</p>
<nav>{nav}</nav></header><main>{''.join(sections)}</main></body></html>
"""
    report_dir = output / "01_RAPPORT"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "ANNEXE_ATLAS_DENSITES_GRILLE.html").write_text(document, encoding="utf-8")


def write_density_readme(output: Path) -> None:
    destination = output / "03_FIGURES" / "densites_completes" / "00_LIRE_EN_PREMIER.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        f"""DENSITES PLEIN FORMAT — PERIMETRE {get_scope().name}

Les {get_scope().density_count} PNG de ce dossier sont les planches individuelles en résolution 2100 x 760.
Ils couvrent {get_scope().pair_count} couples élection x hypothèse, pour KRT Python et King EI sous R.
Scrutins : {', '.join(sorted(get_scope().election_ids))}.
Hypothèses : {', '.join(sorted(get_scope().scenario_ids))}.

Pour une lecture simple, ouvrir ../../01_RAPPORT/ANNEXE_ATLAS_DENSITES.html puis choisir
l'hypothèse, le type de scrutin et l'année. Les méthodes KRT et R sont affichées l'une sous l'autre.
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=LIGHT)
    args = parser.parse_args()
    output = args.output.resolve()
    catalog = pd.read_csv(SOURCE / "03_CATALOGUE_DENSITES.csv")
    expected = {(method, election, scenario) for method in METHOD_LABELS for election, scenario in get_scope().pairs}
    actual = set(map(tuple, catalog[["method", "election_id", "scenario_id"]].astype(str).values))
    if len(catalog) != get_scope().density_count or actual != expected:
        raise AssertionError(f"expected exactly {get_scope().density_count} scoped density rows, got {len(catalog)}")
    integrated = copy_full_size(catalog, output)
    contact_sheets = 0
    for method in METHOD_LABELS:
        for scenario in SCENARIOS:
            for family in ["legislative", "presidential"]:
                subset = integrated.loc[
                    (integrated["method"] == method)
                    & (integrated["scenario_id"] == scenario)
                    & (integrated["election_type"] == family)
                ]
                if subset.empty:
                    continue
                contact_sheet(
                    subset,
                    output / "03_FIGURES" / "atlas_densites_resumes" / method / scenario / f"{family}.png",
                    f"{METHOD_LABELS[method]} · {scenario} · {FAMILY_LABELS[family]}",
                )
                contact_sheets += 1
    build_full_size_reader(integrated, output)
    build_overview_html(integrated, output)
    write_density_readme(output)
    documentation = output / "06_DOCUMENTATION"
    documentation.mkdir(parents=True, exist_ok=True)
    integrated.to_csv(documentation / "CATALOGUE_DENSITES_COMPLET.csv", index=False, encoding="utf-8-sig")
    shutil.copy2(SOURCE / "03_COUVERTURE_BETA_PAR_COUPLE.csv", documentation / "COUVERTURE_BETA_PAR_COUPLE.csv")
    print(
        json.dumps(
            {
                "status": "complete",
                "figures": len(integrated),
                "contact_sheets": contact_sheets,
                "replication_scope": get_scope().as_dict(),
                "full_size_reader": "01_RAPPORT/ANNEXE_ATLAS_DENSITES.html",
                "overview_grid": "01_RAPPORT/ANNEXE_ATLAS_DENSITES_GRILLE.html",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

"""Build and validate the cleaned professor-facing interim results package."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .build_intermediate_professor_report_v3 import MD_PATH, PDF_PATH, REPORT_STEM
from .paths import FIGURE_DIR, OUTPUT_DIR, ROOT, ensure_runtime_dirs


DATA_DIR = OUTPUT_DIR / "v2" / "priority_3000_final"
FIG_DIR = FIGURE_DIR / "v2" / "priority_3000_final"
ZIP_PATH = ROOT / "deliverables" / "premiers_resultats_KRT_NLS_panel3000_1962_1986_2022.zip"
SHA_PATH = ZIP_PATH.with_suffix(".zip.sha256")
MAIN_FIGURES = (
    "within_period_contrasts_3000_v1.png",
    "aggregate_drawwise_corrected_3000_v1.png",
    "canonical_diagnostics_3000_v1.png",
    "estimand_diagnostics_3000_v1.png",
    "nls_contrasts_3000_v1.png",
    "nls_krt_comparison_3000_v1.png",
)
DENSITY_FIGURES = (
    "joint_beta_H0A_common_bandwidth_equal_communes.png",
    "joint_beta_H0A_common_bandwidth_N_total_weighted.png",
    "joint_beta_H1_common_bandwidth_equal_communes.png",
    "joint_beta_H1_common_bandwidth_N_total_weighted.png",
    "marginal_beta_H0A_group_population_weighted.png",
    "marginal_beta_H1_group_population_weighted.png",
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readme() -> str:
    return f"""# Premiers résultats KRT et NLS - panel de 3 000 communes

Ce paquet présente six estimations KRT (H0A et H1) et douze estimations NLS (H0A, H1, H2 et H4) pour 1962, 1986 et 2022.

Commencer par :

- `{REPORT_STEM}.pdf` pour le document autonome ;
- `{REPORT_STEM}.md` pour la version texte avec liens internes ;
- `figures_principales/` pour les six graphiques de synthèse, dont deux consacrés aux NLS ;
- `annexes/figures/` pour les densités jointes et marginales ;
- `resultats/` pour les tables et manifestes machine-lisibles.
- `controle_donnees/` pour l'audit des anomalies et le panel corrigé prévu pour les prochains calculs.

Une seule anomalie inter-dénominateurs apparaît parmi les 9 000 couples commune-année : pour `02643` en 1986, les 392 suffrages exprimés dépassent les 383 inscrits. Le panel reste équilibré. L'audit brut de la règle complète `0 <= exprimés <= votants <= inscrits` documente trois autres lignes du panel avec `exprimés > votants`, mais sans `exprimés > inscrits`. Un panel V3 de 3 000 communes est fourni pour les prochains calculs.

Réglages : 4 chaînes, 1 000 tune, 1 000 draws par chaîne, `target_accept=0,99`, `max_treedepth=14`, `king_lambda=0,5`.

NLS : modèle `rosen_nls_2x2_unadjusted`, 20 points de départ, tolérance `1e-9`, maximum de 5 000 évaluations et graine `20260802`. Les douze ajustements ont un diagnostic numérique `pass`. Les NLS sont présentés comme des estimations ponctuelles ; aucun intervalle du contraste n'est revendiqué à partir des exports disponibles.

Ce paquet compact ne contient ni les six traces NetCDF ni l'ensemble du code et ne constitue pas, à lui seul, le dépôt reproductible complet. Les traces et le code intégral restent dans le dossier technique du projet.
"""


def _transformed_markdown() -> str:
    text = MD_PATH.read_text(encoding="utf-8")
    text = text.replace(
        "../figures/v2/priority_3000_final/densities/", "annexes/figures/"
    )
    text = text.replace(
        "../figures/v2/priority_3000_final/", "figures_principales/"
    )
    text = text.replace(
        "../outputs/v2/priority_3000_final/", "resultats/"
    )
    return text


def _files() -> list[tuple[Path, str, str]]:
    files: list[tuple[Path, str, str]] = [
        (PDF_PATH, PDF_PATH.name, "rapport_pdf"),
    ]
    for name in MAIN_FIGURES:
        files.append((FIG_DIR / name, f"figures_principales/{name}", "figure_principale"))
    for name in DENSITY_FIGURES:
        files.append((FIG_DIR / "densities" / name, f"annexes/figures/{name}", "figure_annexe"))
    for path in sorted(DATA_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
            files.append((path, f"resultats/{path.name}", "resultat_machine_lisible"))
    for path in sorted((ROOT / "panel").glob("panel_3000_common_1962_1986_2022_v3*")):
        if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
            files.append((path, f"controle_donnees/{path.name}", "controle_donnees_futur"))
    missing = [str(path) for path, _, _ in files if not path.exists()]
    if missing:
        raise FileNotFoundError(f"package inputs missing: {missing}")
    return files


def build_package() -> dict[str, object]:
    ensure_runtime_dirs()
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = _files()
    readme = _readme()
    markdown = _transformed_markdown()
    entries = [
        {
            "path": arcname,
            "role": role,
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
        }
        for path, arcname, role in files
    ]
    entries.extend(
        [
            {
                "path": "README.md",
                "role": "orientation",
                "bytes": len(readme.encode("utf-8")),
                "sha256": hashlib.sha256(readme.encode("utf-8")).hexdigest(),
            },
            {
                "path": f"{REPORT_STEM}.md",
                "role": "rapport_markdown",
                "bytes": len(markdown.encode("utf-8")),
                "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            },
        ]
    )
    package_manifest = {
        "schema_version": "professor_first_results_package_v5.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "first_results",
        "scope": (
            "first results from six KRT H0A/H1 and twelve NLS H0A/H1/H2/H4 estimates for "
            "1962/1986/2022 on panel V2; "
            "known source anomalies disclosed; corrected panel V3 supplied for future runs"
        ),
        "self_contained_reproducible_repository": False,
        "king_lambda": 0.5,
        "nls_fit_count": 12,
        "entries": entries,
    }
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("README.md", readme.encode("utf-8"))
        archive.writestr(f"{REPORT_STEM}.md", markdown.encode("utf-8"))
        archive.writestr(
            "package_manifest.json",
            json.dumps(package_manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        for path, arcname, _ in files:
            archive.write(path, arcname)

    digest = _sha(ZIP_PATH)
    SHA_PATH.write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii")
    validate_package()
    return {
        "zip": str(ZIP_PATH),
        "sha256": digest,
        "bytes": ZIP_PATH.stat().st_size,
        "members": len(entries) + 1,
    }


def validate_package() -> None:
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise AssertionError(f"CRC failure: {bad_crc}")
        names = archive.namelist()
        lowered = "\n".join(names).lower()
        if "chatgpt" in lowered:
            raise AssertionError("forbidden product name in package member names")
        if any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in names):
            raise AssertionError("unsafe package member path")
        if f"{REPORT_STEM}.pdf" not in names or f"{REPORT_STEM}.md" not in names:
            raise AssertionError("autonomous report missing")
        for name in names:
            if Path(name).suffix.lower() not in {".md", ".json", ".csv"}:
                continue
            raw = archive.read(name)
            text = raw.decode("utf-8-sig", errors="replace")
            if re.search(r"[A-Za-z]:\\Users\\", text, flags=re.IGNORECASE):
                raise AssertionError(f"local Windows path found in {name}")
            if "chatgpt" in text.lower():
                raise AssertionError(f"forbidden product name found in {name}")
        if ZIP_PATH.stat().st_size >= 500 * 1024 * 1024:
            raise AssertionError("package exceeds 500 MiB")


if __name__ == "__main__":
    print(json.dumps(build_package(), ensure_ascii=False, indent=2))

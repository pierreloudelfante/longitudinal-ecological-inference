"""Orchestration portable du longitudinal complet; aucun estimateur redéfini.

plan/raw utilisent uniquement la bibliothèque standard. run/worker requièrent
l'environnement scientifique original. Les références ne sont jamais recalculées
puis substituées au contrat de comparaison.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile

from reproducibility.replication_scope import ENVIRONMENT_KEY, get_scope
from reproducibility.estimation_recovery import BatchEstimationError, execute_estimation_batch
from reproducibility.estimation_process import (
    ENVIRONMENT_BY_FAMILY,
    WindowsKillOnCloseJob,
    _terminate_process_tree,
    run_supervised,
    start_owned_process_tree,
    timeout_seconds,
)
from reproducibility.failure_report import write_failure_report, resolve_failure_report

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "reproducibility" / "contract_v2"
STATE_DIR = ROOT / ".runtime" / ("replication_v2" if get_scope().is_full else "replication_court")
LIGHT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate"
SCENARIOS = ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7")
STAGES = (
    "panel", "prepare", "nls270", "krt240", "canonical52", "consolidate240",
    "r240", "r_consolidate", "nls_rxc22", "coverage", "covariates960",
    "full_sources", "assets", "density480", "report", "verify", "package",
)
PREFLIGHT_IMPORTS = (
    "numpy", "pandas", "pyarrow", "scipy", "jax", "jaxlib", "numpyro",
    "pymc", "pyei", "arviz", "mistune",
)
GIB = 1024 ** 3
MIB = 1024 ** 2
PDF_RENDER_TIMEOUT_SECONDS = 15 * 60
# A completed reduced run stored about 128--257 MiB per KRT trace.  Reserve
# 160 MiB per requested KRT pair plus 5 GiB for panels, CSV mirrors, R outputs,
# figures, packaging and temporary files.  A stricter local threshold can be
# requested through the launcher; the conservative default cannot be lowered.
PREFLIGHT_FIXED_DISK_GIB = 5.0
PREFLIGHT_DISK_MIB_PER_KRT_PAIR = 160.0
PREFLIGHT_MIN_TOTAL_MEMORY_GIB = 15.0  # marketed/documented 16 GB Windows host
PREFLIGHT_R_PEAK_GIB = 1.0
PREFLIGHT_ABSOLUTE_MIN_DISK_GIB = 5.0
PREFLIGHT_ABSOLUTE_MIN_TOTAL_MEMORY_GIB = 7.5
PREFLIGHT_ABSOLUTE_MIN_AVAILABLE_MEMORY_GIB = 1.5
MODIFIED_ORIGINALS = {
    "COMMENCER_ICI.md", "PROVENANCE_SOURCE.md", "REPRODUIRE_TOUT.ps1", "DONNEES_BRUTES/LISEZ_MOI.txt",
    "reproducibility/README.md", "reproducibility/reproduce.ps1",
    "reproducibility/replication_complete.py", "reproducibility/estimation_process.py",
    "reproducibility/r-packages.lock.json",
    "code_longitudinal/build_professor_release_assets.py",
    "code_longitudinal/run_fast_nls_covariate_specs.py",
    "code_longitudinal/run_r_ei_all_2x2.py",
    "code_longitudinal/build_r_density_cross_validation.py",
    "code_longitudinal/consolidate_current_krt_all_2x2.py",
    "code_longitudinal/consolidate_r_ei_all_2x2.py",
    "code_longitudinal/compare_python_r_ei_full_240.py",
    "code_longitudinal/consolidate_rxc_panel_extension_v11.py",
    "code_longitudinal/build_current_estimation_coverage.py",
    "code_longitudinal/run_rxc_panel_extension_v11.py",
    "code_longitudinal/run_longitudinal_production.py",
    "code_longitudinal/build_full240_professor_release.py",
    "code_longitudinal/export_density_pair_inputs.py",
    "code_longitudinal/finalize_density_bundle.py",
    "code_longitudinal/build_density_report_atlas.py",
    "code_longitudinal/repair_portable_report_from_template.py",
    "r_replication/generate_all_pair_density_figures.R",
}
# Runtime-only replacement of the same cli 3.6.6 package by its official CRAN
# Windows binary. The current package receipt and R-library manifest authenticate
# every replacement byte; all other historical R packages remain immutable.
ALLOWED_RUNTIME_REPLACEMENT_PREFIXES = (".cache/R/library/cli/",)

class ReplicationError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=True,
                                    default=str, separators=(",", ":")).encode()).hexdigest()


def tree_fingerprint(path: Path) -> dict[str, object]:
    """Return the same deterministic package-tree fingerprint used at build time."""
    value = hashlib.sha256()
    files = 0
    total_bytes = 0
    items = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    for item in sorted(items, key=lambda candidate: candidate.relative_to(path).as_posix().casefold()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        item_sha = digest(item).encode("ascii")
        value.update(relative + b"\0" + item_sha + b"\n")
        files += 1
        total_bytes += item.stat().st_size
    return {"files": files, "bytes": total_bytes, "tree_sha256": value.hexdigest()}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ReplicationError(message)


def inspect_zip_archive(path: Path, label: str) -> tuple[dict[str, object], list[str]]:
    """Fully read a ZIP, rejecting CRC errors and duplicate logical file paths."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [entry for entry in archive.infolist() if not entry.is_dir()]
            names = [entry.filename.replace("\\", "/") for entry in infos]
            logical = [name.casefold() for name in names]
            duplicates = sorted(name for name, count in Counter(logical).items() if count > 1)
            check(bool(infos), f"{label}: archive ZIP vide")
            check(not duplicates, f"{label}: chemins ZIP dupliques: {', '.join(duplicates[:10])}")
            encrypted = [entry.filename for entry in infos if entry.flag_bits & 0x1]
            check(not encrypted, f"{label}: membres chiffres illisibles: {', '.join(encrypted[:10])}")
            bad_member = archive.testzip()
            check(bad_member is None, f"{label}: CRC/lecture ZIP en echec: {bad_member}")
            result = {
                "status": "pass", "file_count": len(infos),
                "uncompressed_bytes": sum(int(entry.file_size) for entry in infos),
                "duplicate_paths": 0, "crc_error": None, "encrypted_members": 0,
            }
            return result, names
    except ReplicationError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ReplicationError(f"{label}: archive ZIP illisible: {type(exc).__name__}: {exc}") from exc


def validate_r_runtime_library(root: Path = ROOT) -> dict[str, object]:
    """Authenticate every bundled non-base R package before any estimation."""
    manifest_path = root / "reproducibility" / "r-runtime-library-manifest.json"
    library = root / ".cache" / "R" / "library"
    check(manifest_path.is_file(), "Manifeste de la bibliotheque R fournie absent")
    check(library.is_dir(), "Bibliotheque R fournie absente: " + str(library))
    manifest = read_json(manifest_path)
    packages = manifest.get("packages", [])
    expected = {str(item.get("package")): item for item in packages}
    observed = {item.name for item in library.iterdir() if item.is_dir()}
    check(len(expected) == int(manifest.get("package_count", -1)) and len(expected) > 0,
          "Manifeste de la bibliotheque R incoherent")
    check(observed == set(expected),
          "Bibliotheque R differente du manifeste; manquants="
          + repr(sorted(set(expected) - observed)) + "; ajoutes=" + repr(sorted(observed - set(expected))))
    total_files = 0
    total_bytes = 0
    for package in sorted(expected):
        fingerprint = tree_fingerprint(library / package)
        recorded = expected[package]
        for key in ("files", "bytes", "tree_sha256"):
            check(fingerprint[key] == recorded.get(key),
                  f"Paquet R fourni modifie/corrompu: {package} ({key})")
        total_files += int(fingerprint["files"])
        total_bytes += int(fingerprint["bytes"])
    check(total_files == int(manifest.get("file_count", -1))
          and total_bytes == int(manifest.get("bytes", -1)),
          "Dimensions globales de la bibliotheque R differentes du manifeste")
    return {
        "status": "pass", "manifest": str(manifest_path),
        "r_version": manifest.get("r_version"), "platform": manifest.get("platform"),
        "packages": len(expected), "files": total_files, "bytes": total_bytes,
    }


def _positive_environment_number(name: str, default: float = 0.0) -> float:
    text = os.environ.get(name, "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except ValueError as exc:
        raise ReplicationError(f"{name} doit etre un nombre positif; observe: {text!r}") from exc
    check(value >= 0.0, f"{name} doit etre positif; observe: {value}")
    return value


def _environment_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    check(value in {"", "0", "1", "false", "true", "no", "yes"},
          f"{name} doit valoir 0/1, false/true ou no/yes")
    return value in {"1", "true", "yes"}


def validate_runtime_resources(root: Path = ROOT) -> dict[str, object]:
    """Fail fast on a host that cannot safely begin the requested scope."""
    import psutil
    scope = get_scope()
    disk_default_gib = PREFLIGHT_FIXED_DISK_GIB + (
        PREFLIGHT_DISK_MIB_PER_KRT_PAIR * scope.pair_count / 1024.0
    )
    disk_requested_gib = _positive_environment_number("LONGITUDINAL_MIN_FREE_DISK_GB")
    enforce_recommended = _environment_flag("LONGITUDINAL_ENFORCE_RESOURCE_RECOMMENDATIONS")
    required_disk_gib = max(PREFLIGHT_ABSOLUTE_MIN_DISK_GIB, disk_requested_gib,
                            disk_default_gib if enforce_recommended else 0.0)
    usage = shutil.disk_usage(root)
    free_disk_gib = usage.free / GIB
    check(free_disk_gib >= required_disk_gib,
          f"Espace disque libre insuffisant avant estimations: {free_disk_gib:.2f} GiB; "
          f"minimum impose {required_disk_gib:.2f} GiB pour le perimetre {scope.name}")

    memory = psutil.virtual_memory()
    total_memory_gib = memory.total / GIB
    available_memory_gib = memory.available / GIB
    requested_total_gib = _positive_environment_number("LONGITUDINAL_MIN_TOTAL_MEMORY_GB")
    total_required_gib = max(PREFLIGHT_ABSOLUTE_MIN_TOTAL_MEMORY_GIB, requested_total_gib,
                             PREFLIGHT_MIN_TOTAL_MEMORY_GIB if enforce_recommended else 0.0)
    limit_fraction = _positive_environment_number("LONGITUDINAL_R_MEMORY_LIMIT_FRACTION", 0.80)
    check(0.0 < limit_fraction < 1.0,
          "LONGITUDINAL_R_MEMORY_LIMIT_FRACTION doit etre strictement entre 0 et 1")
    # Match the later R guard: after a predicted 1 GiB job, at least the
    # configured fraction of total memory must remain outside the used share.
    r_gate_available_gib = total_memory_gib * (1.0 - limit_fraction) + PREFLIGHT_R_PEAK_GIB
    requested_available_gib = _positive_environment_number("LONGITUDINAL_MIN_AVAILABLE_MEMORY_GB")
    required_available_gib = max(PREFLIGHT_ABSOLUTE_MIN_AVAILABLE_MEMORY_GIB,
                                 requested_available_gib,
                                 r_gate_available_gib if enforce_recommended else 0.0)
    check(total_memory_gib >= total_required_gib,
          f"Memoire physique insuffisante: {total_memory_gib:.2f} GiB; "
          f"minimum {total_required_gib:.2f} GiB (ordinateur vendu comme 16 Go)")
    check(available_memory_gib >= required_available_gib,
          f"Memoire disponible insuffisante avant estimations: {available_memory_gib:.2f} GiB; "
          f"minimum {required_available_gib:.2f} GiB. Fermer les applications non indispensables puis relancer.")
    warnings = []
    if free_disk_gib < disk_default_gib:
        warnings.append(
            f"disque: {free_disk_gib:.2f} GiB libres, recommandation conservatrice "
            f"{disk_default_gib:.2f} GiB fondee sur 160 MiB par trace KRT + 5 GiB fixes"
        )
    if total_memory_gib < PREFLIGHT_MIN_TOTAL_MEMORY_GIB:
        warnings.append(
            f"memoire physique: {total_memory_gib:.2f} GiB, recommandation documentee "
            f"{PREFLIGHT_MIN_TOTAL_MEMORY_GIB:.2f} GiB (ordinateur vendu comme 16 Go)"
        )
    if available_memory_gib < r_gate_available_gib:
        warnings.append(
            f"memoire disponible: {available_memory_gib:.2f} GiB; la garde R attendra "
            f"{r_gate_available_gib:.2f} GiB avant un calcul R"
        )
    return {
        "status": "pass_with_warnings" if warnings else "pass", "scope": scope.name,
        "recommendations_enforced": enforce_recommended, "warnings": warnings,
        "disk": {"free_gib": free_disk_gib, "required_gib": required_disk_gib,
                 "recommended_gib": disk_default_gib, "volume_root": str(root.resolve().anchor)},
        "memory": {"total_gib": total_memory_gib, "available_gib": available_memory_gib,
                   "required_total_gib": total_required_gib,
                   "required_available_gib": required_available_gib,
                   "recommended_total_gib": PREFLIGHT_MIN_TOTAL_MEMORY_GIB,
                   "r_gate_available_gib": r_gate_available_gib,
                   "r_memory_limit_fraction": limit_fraction,
                   "predicted_r_peak_gib": PREFLIGHT_R_PEAK_GIB},
    }


def validate_writable_directories(root: Path = ROOT, state_dir: Path = STATE_DIR) -> dict[str, object]:
    """Exercise real create/write/fsync/atomic-rename/delete operations."""
    directories = [
        state_dir, root / "outputs", root / "panel", root / "work",
        root / "deliverables", root / "JOURNAUX_REPRODUCTION",
    ]
    checked = []
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            source = directory / ".preflight_write_probe.tmp"
            target = directory / ".preflight_write_probe.ok"
            for candidate in (source, target):
                if candidate.exists():
                    candidate.unlink()
            with source.open("wb") as stream:
                stream.write(b"replication preflight\n")
                stream.flush()
                os.fsync(stream.fileno())
            source.replace(target)
            check(target.read_bytes() == b"replication preflight\n",
                  "Lecture differente apres ecriture: " + str(directory))
            target.unlink()
        except (OSError, ReplicationError) as exc:
            for candidate in (directory / ".preflight_write_probe.tmp",
                              directory / ".preflight_write_probe.ok"):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ReplicationError(
                f"Dossier de travail non inscriptible avant estimations: {directory}: {exc}"
            ) from exc
        checked.append(str(directory.resolve()))
    return {"status": "pass", "directories_checked": checked, "atomic_replace_checked": True}


def pair_key(row: dict) -> tuple[str, str]:
    return str(row["election_id"]), str(row["scenario_id"])


def contract_plan() -> dict:
    raw = read_json(CONTRACT / "raw_sources_31.json")["raw_sources"]
    entries = read_json(CONTRACT / "krt_replay_240.json")["entries"]
    r_replay = read_json(CONTRACT / "r_replay_240.json")
    r_entries = r_replay["entries"]
    expected = read_json(CONTRACT / "expected_results_610.json")["files"]
    check(len(raw) == len({r["name"] for r in raw}) == 31, "Contrat des 31 sources invalide")
    check(len(expected) == len({r["path"] for r in expected}) == 610, "Contrat des 610 sorties invalide")
    check(len(entries) == len({pair_key(r) for r in entries}) == 240, "Plan KRT duplique ou incomplet")
    from code_longitudinal.spec_registry import ELECTIONS, SCENARIOS as SPECS, scenario_is_allowed
    pairs = {(e.election_id, s.scenario_id) for e in ELECTIONS for s in SPECS
             if s.model_family == "2x2" and scenario_is_allowed(s, e)}
    check(pairs == {pair_key(r) for r in entries}, "Le plan ne couvre pas le registre scientifique original")
    check(len(r_entries) == 240 and {pair_key(r) for r in r_entries} == pairs,
          "Le manifeste des graines R ne couvre pas exactement les 240 couples")
    check(all(isinstance(r["seed"], int) and not isinstance(r["seed"], bool)
              and 0 < r["seed"] < 2**31 for r in r_entries), "Graine R historique invalide")
    result_contract = read_json(CONTRACT / "expected_results_610.json")
    check(r_replay["source_archive_sha256"] == result_contract["source_archive_sha256"],
          "Les graines R ne sont pas liees a l'archive de reference fixee")
    for r in entries:
        computed = stable_hash(r["historical_hash_payload"])
        check(computed == r["historical_run_key"] and r["reference_run_id"].endswith(computed[:12]),
              "Reglage historique non verifie: " + r["reference_run_id"])
        a = r["arguments"]; historical = r["historical_hash_payload"]["parameters"]
        for name in ("draws", "tune", "chains", "cores", "target_accept", "max_treedepth", "random_seed", "king_lambda"):
            check(a[name] == historical[name], f"Reglage de rejeu different: {pair_key(r)} / {name}")
        check(a["sampler_backend"] == historical.get("sampler_backend", "numpyro"), "Moteur modifie")
        check(a["krt_parameterization_version"] == historical.get("krt_parameterization_version", "legacy_unversioned_pyei_king99"), "Parametrisation modifiee")
    scope = get_scope()
    selected = [r for r in entries if pair_key(r) in scope.pairs]
    return {
        "status": "plan_checked_not_estimated", "raw_archives": 31,
        "raw_bytes": sum(r["bytes"] for r in raw), "elections": len(scope.election_ids),
        "scope": scope.as_dict(),
        "krt_pairs": scope.pair_count, "krt_historical_hash_checks": len(entries),
        "backends": dict(Counter(r["arguments"]["sampler_backend"] for r in selected)),
        "r_ei_pairs": scope.pair_count, "r_historical_seed_pairs": len(r_entries),
        "nls_base": len(scope.base_nls_pairs), "nls_panel_extension": len(scope.extension_nls_pairs),
        "nls_delivered_pairs": len(scope.nls_pairs), "nls_covariates": 4 * scope.pair_count,
        "density_images": scope.density_count,
        "expected_result_files": len(result_contract_for_scope()["files"]), "stages": list(STAGES),
        "warning": "Plan et controles de structure; ce statut ne certifie pas une reestimation numerique.",
    }


def check_original_integrity(root: Path = ROOT) -> dict:
    original = read_json(CONTRACT / "original_package_files.json")["files"]
    bad = []
    for r in original:
        if (r["path"] in MODIFIED_ORIGINALS
                or any(r["path"].startswith(prefix)
                       for prefix in ALLOWED_RUNTIME_REPLACEMENT_PREFIXES)):
            continue
        p = root / r["path"]
        if not p.is_file() or digest(p) != r["sha256"]:
            bad.append(r["path"])
    check(not bad, "Fichiers historiques hors perimetre modifies/manquants: " + ", ".join(bad[:20]))
    unchanged = sum(
        r["path"] not in MODIFIED_ORIGINALS
        and not any(r["path"].startswith(prefix)
                    for prefix in ALLOWED_RUNTIME_REPLACEMENT_PREFIXES)
        for r in original
    )
    return {"unchanged_original_files": unchanged, "status": "pass"}


def check_package_manifest_integrity(root: Path = ROOT) -> dict[str, object]:
    """Verify every shipped file, including modified launchers and validators."""
    receipt_path = root / "reproducibility" / "contract_v2" / "CHANGEMENTS_FICHIERS.csv"
    check(receipt_path.is_file(), "Recu d'integrite des fichiers du paquet absent")
    with receipt_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    paths = [str(row.get("path", "")) for row in rows]
    check(paths and len(paths) == len(set(paths)), "Recu d'integrite vide ou chemins dupliques")
    bad = []
    for row in rows:
        relative = Path(str(row.get("path", "")))
        expected = str(row.get("new_sha256", ""))
        safe = (not relative.is_absolute() and relative.parts
                and all(part not in {"", ".", ".."} for part in relative.parts))
        if not safe or not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
            bad.append(str(relative) + " (ligne de manifeste invalide)")
            continue
        candidate = root / relative
        if not candidate.is_file() or digest(candidate) != expected:
            bad.append(relative.as_posix())
    check(not bad, "Fichiers du paquet modifies/manquants avant calcul: " + ", ".join(bad[:20]))
    return {"status": "pass", "receipt": str(receipt_path), "files_verified": len(rows),
            "receipt_self_hash_excluded_by_design": True}


def resolve_raw(search_root: Path, normalize: bool = True, sources: list | None = None,
                runtime: Path = STATE_DIR) -> dict:
    search_root = search_root.expanduser().resolve()
    check(search_root.is_dir(), f"Dossier de donnees absent: {search_root}")
    sources = sources if sources is not None else read_json(CONTRACT / "raw_sources_31.json")["raw_sources"]
    # Ne jamais envoyer les données privées sur le réseau. Aucun téléchargement implicite.
    names = {n for r in sources for n in (r["name"], r["download_name"])}
    found: dict[str, list[Path]] = {}
    for p in search_root.rglob("*.zip"):
        if p.name in names:
            found.setdefault(p.name, []).append(p)
    selected = {}; errors = []
    for r in sources:
        candidates = found.get(r["name"], []) + found.get(r["download_name"], [])
        valid = [p for p in candidates if p.stat().st_size == r["bytes"] and digest(p) == r["required_sha256"]]
        if not valid:
            errors.append(("MANQUANT" if not candidates else "TAILLE/SHA256 DIFFERENT") + ": " + r["name"])
        else:
            selected[r["name"]] = valid[0]
    check(not errors, "Archives sources non conformes (aucun calcul lance):\n" + "\n".join(errors))
    archive_receipts = []
    for source in sources:
        path = selected[source["name"]]
        zip_receipt, _ = inspect_zip_archive(path, "Source brute " + source["name"])
        archive_receipts.append({
            "name": source["name"], "path": str(path), "bytes": path.stat().st_size,
            "sha256": source["required_sha256"], **zip_receipt,
        })
    normalized = search_root
    if normalize and any(p.parent != search_root or p.name != name for name, p in selected.items()):
        normalized = runtime / "raw_archives"; normalized.mkdir(parents=True, exist_ok=True)
        for name, p in selected.items():
            q = normalized / name
            if q.exists():
                check(digest(q) == digest(p), f"Vue normalisee differente: {q}")
            else:
                try:
                    os.link(p, q)
                except OSError:
                    shutil.copy2(p, q)
    return {"status": "pass", "count": len(selected),
            "total_bytes": sum(int(source["bytes"]) for source in sources),
            "all_zip_crc_and_readability_pass": True,
            "archives": archive_receipts, "raw_dir": str(normalized),
            "fingerprint": stable_hash({r["name"]: r["required_sha256"] for r in sources}),
            "selected": {n: str(p) for n, p in selected.items()}}


def configure(raw_dir: Path, rscript: str = "", browser: str = "",
              reference_results: Path | None = None) -> None:
    os.chdir(ROOT)
    os.environ.update({"LONGITUDINAL_PROJECT_ROOT": str(ROOT), "LONGITUDINAL_RAW_ARCHIVES": str(raw_dir),
                       "JAX_PLATFORMS": "cpu", "JAX_PLATFORM_NAME": "cpu", "CUDA_VISIBLE_DEVICES": "",
                       "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8",
                       "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                       "JAX_ENABLE_X64": "1",
                       "LONGITUDINAL_ALLOW_VERIFIED_MODEL_READY_CACHE": "0"})
    if rscript:
        os.environ["LONGITUDINAL_RSCRIPT"] = str(Path(rscript).resolve())
    if browser:
        os.environ["LONGITUDINAL_BROWSER"] = str(Path(browser).resolve())
    if reference_results is not None:
        os.environ["LONGITUDINAL_REFERENCE_RESULTS"] = str(Path(reference_results).resolve())
    os.environ["R_LIBS_USER"] = str(ROOT / ".cache" / "R" / "library")
    os.environ["R_LIBS"] = ""
    os.environ["R_LIBS_SITE"] = ""


def external(args: list[str], *, timeout: int | None = None) -> None:
    print("COMMANDE:", subprocess.list2cmdline([str(x) for x in args]), flush=True)
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True, timeout=timeout)


def module(name: str, *args: str) -> None:
    external([sys.executable, "-m", "reproducibility.replication_complete", "original-module", name, *args])


def validate_panel_frame(frame) -> dict:
    import pandas as pd
    ref = read_json(CONTRACT / "panel_reference_ids.json")
    reference_path = CONTRACT / ref["master_csv"]
    check(digest(reference_path) == ref["master_csv_sha256"], "Reference semantique du panel modifiee")
    reference = pd.read_csv(reference_path, dtype={"unit_id": "string"}, float_precision="round_trip")
    observed = frame.copy().sort_values("master_draw_order").reset_index(drop=True)
    reference = reference.sort_values("master_draw_order").reset_index(drop=True)
    check(observed["unit_id"].astype(str).tolist() == reference["unit_id"].astype(str).tolist(), "Identifiants/ordre du panel maitre differents")
    check(observed.head(2000)["unit_id"].astype(str).tolist() == ref["unit_ids"], "Panel principal different")
    try:
        pd.testing.assert_frame_equal(observed, reference, check_dtype=False, check_exact=False, atol=1e-12, rtol=1e-12)
    except AssertionError as exc:
        raise ReplicationError("Valeurs du panel reconstruit differentes de la reference CSV: " + str(exc)) from exc
    return {"semantic_check": "all_rows_and_columns_pass", "master_rows": len(reference),
            "primary_rows": 2000, "reference_sha256": ref["expected_panel_sha256"],
            "reference_csv_sha256": ref["master_csv_sha256"], "float_atol": 1e-12, "float_rtol": 1e-12}


def validate_prepared_inputs(records: list[dict], panel) -> dict[str, object]:
    """Reopen and authenticate every model-ready input before estimator 1 starts."""
    import numpy as np
    import pandas as pd
    from code_longitudinal.build_longitudinal_panel import PANEL_PATH
    from code_longitudinal.prepare_inputs import (
        n_columns, validate_model_ready, x_columns, y_columns,
    )
    from code_longitudinal.spec_registry import SCENARIO_BY_ID

    scope = get_scope()
    expected_pairs_set = set(scope.nls_pairs)
    check(len(records) == len(expected_pairs_set)
          and {pair_key(record) for record in records} == expected_pairs_set,
          f"Controle final des matrices incomplet: {len(records)}/{len(expected_pairs_set)}")
    expected_units = (
        panel.sort_values("sample_rank").head(2000)["unit_id"].astype("string").tolist()
    )
    panel_id = str(panel["panel_id"].iloc[0])
    raw_root = Path(os.environ["LONGITUDINAL_RAW_ARCHIVES"])
    raw_contract = {
        row["name"]: row["required_sha256"]
        for row in read_json(CONTRACT / "raw_sources_31.json")["raw_sources"]
    }
    # One post-preflight recheck per archive, never one 1.62-GB rehash per
    # matrix.  These hashes are then reused across all 292 manifest checks.
    observed_raw_hashes = {}
    for source_name, expected_sha in raw_contract.items():
        source_path = raw_root / source_name
        check(source_path.is_file(), "Source absente apres preflight: " + source_name)
        observed_raw_hashes[source_name] = digest(source_path)
        check(observed_raw_hashes[source_name] == expected_sha,
              "Source modifiee apres preflight: " + source_name)
    validated = []
    for record in sorted(records, key=pair_key):
        election_id, scenario_id = pair_key(record)
        scenario = SCENARIO_BY_ID[scenario_id]
        parquet = Path(record["path"])
        csv_path = parquet.with_suffix(".csv")
        manifest_path = parquet.with_name(parquet.stem + "__manifest.json")
        exclusions_path = parquet.with_name(parquet.stem + "__excluded.csv")
        for required in (parquet, csv_path, manifest_path, exclusions_path):
            check(required.is_file() and required.stat().st_size > 0,
                  f"Fichier prepare absent/vide avant estimations: {required}")
        check(digest(parquet) == record["sha256"],
              f"Matrice modifiee depuis sa creation: {election_id}/{scenario_id}")
        manifest = read_json(manifest_path)
        check(manifest.get("election_id") == election_id
              and manifest.get("scenario_id") == scenario_id
              and manifest.get("panel_id") == panel_id,
              f"Identite du manifeste prepare differente: {election_id}/{scenario_id}")
        check(int(manifest.get("n_communes_requested", -1)) == 2000
              and int(manifest.get("n_communes_used", -1)) == 2000
              and int(manifest.get("n_communes_excluded", -1)) == 0,
              f"Couverture de la matrice preparee incorrecte: {election_id}/{scenario_id}")
        check(digest(PANEL_PATH) == manifest.get("panel_source_sha256"),
              f"Panel source different dans le manifeste: {election_id}/{scenario_id}")
        for source_name, source_sha in manifest.get("source_sha256", {}).items():
            check(raw_contract.get(source_name) == source_sha,
                  f"SHA source non contractuel: {election_id}/{scenario_id}/{source_name}")
            check(observed_raw_hashes.get(source_name) == source_sha,
                  f"Source modifiee apres preflight: {source_name}")

        frame = pd.read_parquet(parquet)
        frame["unit_id"] = frame["unit_id"].astype("string")
        check(frame["unit_id"].tolist() == expected_units,
              f"Identifiants/ordre differents dans la matrice: {election_id}/{scenario_id}")
        check(frame["election_id"].eq(election_id).all()
              and frame["scenario_id"].eq(scenario_id).all()
              and frame["panel_id"].astype(str).eq(panel_id).all(),
              f"Metadonnees de matrice differentes: {election_id}/{scenario_id}")
        checks = validate_model_ready(frame, scenario)
        check(checks == manifest.get("checks"),
              f"Controles numeriques differents du manifeste: {election_id}/{scenario_id}")

        # R consumes the CSV mirror; compare every actual model margin with the
        # Parquet used by Python rather than merely checking that the file exists.
        csv_frame = pd.read_csv(csv_path, dtype={"unit_id": "string"}, low_memory=False)
        check(csv_frame["unit_id"].tolist() == expected_units and len(csv_frame) == 2000,
              f"CSV prepare incomplet/desordonne: {election_id}/{scenario_id}")
        numeric = ["N_g", *x_columns(scenario), *n_columns(scenario), *y_columns(scenario)]
        check(all(column in csv_frame.columns and column in frame.columns for column in numeric),
              f"Colonnes modele absentes du CSV/Parquet: {election_id}/{scenario_id}")
        left = frame[numeric].to_numpy(dtype=float)
        right = csv_frame[numeric].to_numpy(dtype=float)
        check(np.isfinite(left).all() and np.isfinite(right).all()
              and np.allclose(left, right, rtol=1e-12, atol=1e-12),
              f"Valeurs modele CSV/Parquet differentes: {election_id}/{scenario_id}")
        validated.append({
            "election_id": election_id, "scenario_id": scenario_id, "rows": len(frame),
            "parquet": str(parquet), "parquet_sha256": digest(parquet),
            "csv_sha256": digest(csv_path), "manifest_sha256": digest(manifest_path),
            "exclusions_sha256": digest(exclusions_path), "checks": checks,
        })
    result = {
        "status": "pass_before_first_estimator", "scope": scope.name,
        "expected": len(expected_pairs_set), "validated": len(validated),
        "panel_sha256": digest(PANEL_PATH), "panel_id": panel_id,
        "csv_parquet_numeric_tolerance": {"rtol": 1e-12, "atol": 1e-12},
        "matrices": validated,
    }
    write_json(STATE_DIR / "prepared_inputs_pre_estimation_gate.json", result)
    return result


def activate_runtime_panel_hash() -> None:
    # Le panel historique a été écrit par Arrow 25, alors que le verrou livré
    # fixe Arrow 24. Vérifier les VALEURS avant de propager le SHA du nouveau
    # fichier; ne jamais copier le panel historique à la place du panel calculé.
    receipt = read_json(STATE_DIR / "panel_semantic_check.json")
    path = ROOT / "panel/longitudinal_2000_v1.parquet"
    check(receipt["semantic_check"] == "all_rows_and_columns_pass" and digest(path) == receipt["actual_sha256"],
          "Panel modifie depuis sa comparaison semantique")
    from code_longitudinal import run_rxc_panel_extension_v11 as rxc
    rxc.EXPECTED_PANEL_SHA256 = receipt["actual_sha256"]
    # Les modules suivants importent cette constante; tous les nouveaux
    # manifestes et contrôles de dépendance utilisent ainsi le SHA réellement lu.
    for name in ("consolidate_current_krt_all_2x2", "consolidate_rxc_panel_extension_v11",
                 "build_current_estimation_coverage", "audit_all_2x2_model_ready"):
        loaded = sys.modules.get("code_longitudinal." + name)
        if loaded is not None:
            loaded.EXPECTED_PANEL_SHA256 = receipt["actual_sha256"]


def validate_reference_archive(reference_results: Path) -> dict:
    reference_results = reference_results.expanduser().resolve()
    check(reference_results.is_file(),
          "Archive de resultats de reference absente: " + str(reference_results))
    expected = read_json(CONTRACT / "expected_results_610.json")
    observed_sha256 = digest(reference_results)
    check(observed_sha256 == expected["source_archive_sha256"],
          "SHA-256 de longitudinal_2000_results.zip different du contrat")
    zip_receipt, names = inspect_zip_archive(reference_results, "Archive de resultats de reference")
    expected_paths = {entry["path"] for entry in expected["files"]}
    check(len(names) == 610 and set(names) == expected_paths,
          "L'archive de reference ne contient pas exactement les 610 fichiers attendus")
    return {"path": str(reference_results), "bytes": reference_results.stat().st_size,
            "sha256": observed_sha256, "files": len(names), **zip_receipt}


def write_preflight_receipts(proof: dict[str, object]) -> dict[str, str]:
    """Persist one machine-readable and one professor-readable PASS receipt."""
    journal = ROOT / "JOURNAUX_REPRODUCTION"
    journal.mkdir(parents=True, exist_ok=True)
    state_json = STATE_DIR / "preflight.json"
    public_json = journal / "PREFLIGHT_DERNIER.json"
    public_text = journal / "PREFLIGHT_DERNIER.txt"
    paths = {"state_json": str(state_json), "public_json": str(public_json),
             "public_text": str(public_text)}
    payload = dict(proof, recorded_at_utc=now(), receipt_paths=paths)
    write_json(state_json, payload)
    write_json(public_json, payload)
    raw = payload["raw"]
    plan = payload["plan"]
    resources = payload["resources"]
    reference = payload.get("reference_results")
    lines = [
        "PREFLIGHT REUSSI - AUCUNE ESTIMATION N'A ETE LANCEE",
        "",
        f"Perimetre : {plan['scope']['name']}",
        f"Sources brutes : {raw['count']}/31; {raw['total_bytes']} octets; SHA-256 + lecture + CRC ZIP reussis",
        f"Plan : {plan['krt_pairs']} KRT; {plan['r_ei_pairs']} King R; "
        f"{plan['nls_delivered_pairs']} NLS; {plan['expected_result_files']} fichiers finaux attendus",
        f"Python : {payload['python']}; paquets verrouilles et imports scientifiques valides",
        f"R : {payload['r_runtime']['r_version']}; {payload['r_runtime']['packages']} paquets fournis authentifies",
        f"Disque libre : {resources['disk']['free_gib']:.2f} GiB "
        f"(minimum impose {resources['disk']['required_gib']:.2f} GiB; "
        f"recommande {resources['disk']['recommended_gib']:.2f} GiB)",
        f"Memoire disponible : {resources['memory']['available_gib']:.2f} GiB "
        f"(minimum impose {resources['memory']['required_available_gib']:.2f} GiB; "
        f"garde R {resources['memory']['r_gate_available_gib']:.2f} GiB)",
        f"Dossiers inscriptibles : {len(payload['writability']['directories_checked'])}; "
        "ecriture et renommage atomique testes",
        f"Archive de reference : {reference['files']} fichiers; SHA-256 + lecture + CRC ZIP reussis"
        if reference else "Archive de reference : non fournie",
        "Navigateur : production d'un PDF complet testee",
        "",
        "Le lanceur peut maintenant construire le panel et les matrices. Les matrices seront toutes",
        "relues et controlees une seconde fois avant le lancement du premier estimateur.",
    ]
    if resources.get("warnings"):
        lines.extend(["", "AVERTISSEMENTS DE RESSOURCES (non scientifiques) :"]
                     + ["- " + warning for warning in resources["warnings"]]
                     + ["Ajouter -ExigerRessourcesRecommandees pour rendre ces recommandations bloquantes."])
    public_text.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return paths


def preflight(raw_dir: Path, rscript: str, browser: str,
              reference_results: Path | None = None) -> dict:
    plan = contract_plan()
    integrity = {"historical": check_original_integrity(),
                 "package": check_package_manifest_integrity()}
    check(platform.python_version() == "3.12.10", "Le contrat fourni demande Python 3.12.10; observe: " + platform.python_version())
    check(os.name == "nt", "La bibliotheque R fournie est Windows x86_64. Ce parcours fige vise Windows.")
    mismatches = []
    pins = (ROOT / "reproducibility/requirements-python312.lock.txt").read_text().splitlines() + ["mistune==3.3.4"]
    for line in pins:
        if "==" not in line or line.startswith("#"):
            continue
        name, version = line.strip().split("==", 1)
        try:
            observed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            observed = "absent"
        if observed != version:
            mismatches.append(f"{name}: {observed} (attendu {version})")
    check(not mismatches, "Environnement different du verrou original:\n" + "\n".join(mismatches))
    # Une installation Windows entièrement neuve peut laisser PyMC tenter son
    # import optionnel de JAX avant que l'API publique de JAX soit initialisée.
    # Charger explicitement JAX puis NumPyro évite cet état partiel au tout
    # premier lancement, sans modifier aucun estimateur ni aucun paramètre.
    for name in PREFLIGHT_IMPORTS:
        importlib.import_module(name)
    resources = validate_runtime_resources()
    writability = validate_writable_directories()
    raw = resolve_raw(raw_dir)
    r_runtime = validate_r_runtime_library()
    from code_longitudinal.run_r_ei_all_2x2 import _reference_seeds
    check(len(_reference_seeds()) == 240, "Manifeste historique R incomplet")
    check(Path(rscript).is_file(), "Rscript introuvable; renseigner -RscriptExe")
    check(Path(browser).is_file(), "Edge/Chrome introuvable; renseigner -NavigateurExe pour le PDF recalcule")
    reference = validate_reference_archive(reference_results) if reference_results is not None else None
    execution_limits = {family + "_seconds": timeout_seconds(family)
                        for family in ENVIRONMENT_BY_FAMILY}
    for name, default in (("LONGITUDINAL_R_MEMORY_WAIT_SECONDS", 4 * 60 * 60),
                          ("LONGITUDINAL_HEARTBEAT_SECONDS", 30)):
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError as exc:
            raise ReplicationError(f"{name} doit etre un entier positif") from exc
        check(value > 0, f"{name} doit etre strictement positif")
        execution_limits[name.lower()] = value
    configure(Path(raw["raw_dir"]), rscript, browser, reference_results)
    external([sys.executable, "-m", "pip", "check"])
    external([rscript, "--vanilla", str(ROOT / "reproducibility/check_r_environment_v2.R"), str(ROOT)], timeout=120)
    # Contrôle réel de la génération PDF AVANT les longues estimations.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdf_preflight_", dir=STATE_DIR) as temp:
        p = Path(temp); html = p / "test.html"; pdf = p / "test.pdf"
        html.write_text("<!doctype html><meta charset='utf-8'><p>Contrôle PDF de réplication.</p>", encoding="utf-8")
        render_pdf(html, pdf, browser)
    result = {"status": "preflight_pass_no_estimations", "plan": plan, "integrity": integrity,
              "raw": raw, "reference_results": reference, "python": platform.python_version(),
              "rscript": rscript, "browser": browser, "r_runtime": r_runtime,
              "resources": resources, "writability": writability,
              "execution_limits_not_scientific_parameters": execution_limits,
              "determinism": {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1",
                              "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                              "NUMEXPR_NUM_THREADS": "1", "JAX_ENABLE_X64": "1"}}
    result["receipt_paths"] = write_preflight_receipts(result)
    return result


def render_pdf(html: Path, pdf: Path, browser: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    if pdf.exists():
        pdf.unlink()
    with tempfile.TemporaryDirectory(prefix="browser_", dir=STATE_DIR) as profile:
        external([browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                  "--allow-file-access-from-files", "--disable-extensions", "--no-first-run",
                  "--user-data-dir=" + profile, "--virtual-time-budget=10000",
                  "--print-to-pdf=" + str(pdf.resolve()), html.resolve().as_uri()],
                 timeout=PDF_RENDER_TIMEOUT_SECONDS)
    # Chrome attend normalement la fin de l'ecriture, mais certaines versions
    # Windows d'Edge rendent la main avant que le processus enfant ait ferme le
    # PDF. Attendre un PDF complet (en-tete + marqueur EOF), avec une borne
    # stricte, evite un faux echec tout en rejetant un fichier partiel ou ancien.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if pdf.is_file() and pdf.stat().st_size > 100:
                with pdf.open("rb") as f:
                    header = f.read(5)
                    f.seek(max(0, pdf.stat().st_size - 2048))
                    tail = f.read()
                if header == b"%PDF-" and b"%%EOF" in tail:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise ReplicationError("Le navigateur n'a pas produit un PDF complet dans les 60 secondes")


def validate_result_count(result: dict, expected: int, success_key: str, fail_key: str) -> None:
    check(int(result.get(success_key, -1)) == expected and int(result.get(fail_key, 0)) == 0,
          f"Calcul incomplet: attendu {expected}; resultat={result}")


def expected_pairs() -> set[tuple[str, str]]:
    return set(get_scope().pairs)


KRT_REQUIRED_OUTPUTS = (
    "trace.nc", "commune_latent_summaries.parquet", "commune_latent_summaries.csv",
    "aggregate_comparison_v2.csv", "longitudinal_estimates.csv", "model_diagnostics.csv",
    "identification_diagnostics.json", "identification_diagnostics.csv",
    "mcmc_diagnostics_v2.json", "mcmc_variable_metrics_v2.csv", "mcmc_block_metrics_v2.csv",
    "resource_ladder_gate.json", "resource_ladder_gate.csv",
)


def _validate_krt_saved_manifest(path: Path, manifest: dict, row: dict) -> None:
    """Check saved execution evidence, never turn a diagnostic caveat into a fit failure."""
    ref = row["reference_run_id"]
    check(manifest.get("status") == "success" and manifest.get("run_id") == path.parent.name,
          f"Manifeste KRT incoherent: {path}")
    expected = {**row["arguments"], "election_id": row["election_id"],
                "scenario_id": row["scenario_id"], "model_key": "krt_beta_binomial",
                "sample_size": 2000, "reference_run_id": ref, "run_role": "canonical",
                "public_schema_version": "longitudinal_public_schema_v1.0.2"}
    parameters = manifest.get("parameters", {})
    for key, value in expected.items():
        check(parameters.get(key) == value, f"Reglage recalcule different {ref}/{key}")
    missing = [name for name in KRT_REQUIRED_OUTPUTS
               if not (path.parent / name).is_file() or (path.parent / name).stat().st_size == 0]
    check(not missing,
          f"Sorties KRT absentes ou vides pour {ref}: {missing}. "
          "Calcul conserve sans reestimation automatique; recuperer ses fichiers ou utiliser une extraction vierge.")


def _validated_krt_run(row: dict, *, required: bool = False):
    matches = []
    for path in (ROOT / "outputs/runs").glob("*/manifest.json"):
        manifest = read_json(path)
        if (manifest.get("parameters", {}).get("reference_run_id") == row["reference_run_id"]
                and manifest.get("status") == "success"):
            _validate_krt_saved_manifest(path, manifest, row)
            matches.append((path.parent, manifest))
    check(len(matches) <= 1, f"Deux runs pour la meme reference: {row['reference_run_id']}")
    check(bool(matches) or not required, f"Aucun manifeste KRT reussi sauvegarde: {row['reference_run_id']}")
    return matches[0] if matches else None


def krt_manifest_map() -> dict:
    entries = [r for r in read_json(CONTRACT / "krt_replay_240.json")["entries"]
               if pair_key(r) in get_scope().pairs]
    target = {r["reference_run_id"]: r for r in entries}; found = {}
    for p in (ROOT / "outputs/runs").glob("*/manifest.json"):
        m = read_json(p); q = m.get("parameters", {}); ref = q.get("reference_run_id")
        if ref not in target or m.get("status") != "success":
            continue
        _validate_krt_saved_manifest(p, m, target[ref])
        check(ref not in found, f"Deux runs pour la meme reference: {ref}")
        found[ref] = (p.parent, m)
    return found


def _run_krt_contract_row(row: dict) -> dict:
    """Execute one unchanged historical KRT row inside an isolated worker."""
    from code_longitudinal.build_longitudinal_panel import PANEL_PATH
    from code_longitudinal.run_2x2_batch import run_2x2
    from code_longitudinal.spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
    _validated_krt_run(row)
    result = run_2x2(
        ELECTION_BY_ID[row["election_id"]], SCENARIO_BY_ID[row["scenario_id"]],
        "krt_beta_binomial", sample_size=2000, panel_path=PANEL_PATH,
        skip_preflight=True, preflight_override_reason="reproduction_exact_reference_contract_v2",
        progressbar=False, run_metadata={"reference_run_id": row["reference_run_id"],
        "run_role": "canonical", "public_schema_version": "longitudinal_public_schema_v1.0.2"},
        **row["arguments"],
    )
    check(result.get("status") in {"success", "skipped_existing_success"}, f"Echec KRT: {result}")
    _, saved = _validated_krt_run(row, required=True)
    check(not result.get("run_id") or result["run_id"] == saved["run_id"],
          f"Identite du resultat KRT differente du manifeste: {row['reference_run_id']}")
    return {"election_id": row["election_id"], "scenario_id": row["scenario_id"], "result": result}


def _estimation_process_paths(family: str, key: str) -> tuple[Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    directory = STATE_DIR / "estimation_processes" / family
    return directory / f"{safe}.log", directory / f"{safe}.heartbeat.json"


def execute_krt_contract_rows(rows: list[dict], *, supervise: bool | None = None) -> list[dict]:
    """Single unchanged estimator dispatch for complete and scoped replays.

    A scope may select historical pairs, never rewrite their sampling contract.
    """
    from code_longitudinal.run_longitudinal_production import _keep_system_awake
    if supervise is None:
        supervise = os.environ.get("LONGITUDINAL_SUPERVISE_ESTIMATIONS") == "1"
    contract = {row["reference_run_id"]: row
                for row in read_json(CONTRACT / "krt_replay_240.json")["entries"]}
    identifiers = [row["reference_run_id"] for row in rows]
    check(bool(rows) and len(identifiers) == len(set(identifiers)), "Plan KRT vide ou duplique")
    check(all(contract.get(row["reference_run_id"]) == row for row in rows),
          "Le scope KRT doit selectionner le contrat historique sans le modifier")
    positions = {row["reference_run_id"]: index for index, row in enumerate(rows, 1)}
    def run_one(row):
        reference_id = row["reference_run_id"]
        print(f"KRT {positions[reference_id]}/{len(rows)}: {pair_key(row)}", flush=True)
        # A registry success with lost files must fail before dispatch, including explicit retries.
        _validated_krt_run(row)
        if supervise:
            log, heartbeat = _estimation_process_paths("krt", reference_id)
            run_supervised(
                [sys.executable, "-m", "reproducibility.replication_complete", "estimation-worker",
                 "--scope", get_scope().name, "--estimation-family", "krt",
                 "--estimation-key", reference_id],
                family="krt", key=reference_id, cwd=ROOT, stdout_path=log,
                heartbeat_path=heartbeat, environment=os.environ.copy(),
            )
        else:
            _run_krt_contract_row(row)
        _, saved = _validated_krt_run(row, required=True)
        return {"election_id": row["election_id"], "scenario_id": row["scenario_id"],
                "result": {"status": "success", "run_id": saved["run_id"]}}
    with _keep_system_awake():
        return execute_estimation_batch(
            rows, batch_name="krt", key_fn=lambda row: "/".join(pair_key(row)), run=run_one,
            state_dir=STATE_DIR / "estimation_failures",
            retry_failed=os.environ.get("LONGITUDINAL_RETRY_FAILED") == "1",
        )


def worker(stage: str) -> None:
    """Appels effectifs au code original; les imports scientifiques sont différés."""
    import pandas as pd
    from code_longitudinal.build_longitudinal_panel import PANEL_PATH, load_longitudinal_panel_manifest
    from code_longitudinal.spec_registry import ELECTIONS, SCENARIOS as SPECS, ELECTION_BY_ID, SCENARIO_BY_ID, scenario_is_allowed
    scope = get_scope()
    if stage != "panel":
        activate_runtime_panel_hash()
    if stage == "panel":
        from code_longitudinal.build_longitudinal_panel import build_longitudinal_panel
        build_longitudinal_panel()  # Le module historique n'a PAS de point d'entrée __main__.
        panel = pd.read_parquet(PANEL_PATH)
        receipt = validate_panel_frame(panel)
        receipt.update(actual_sha256=digest(PANEL_PATH),
                       byte_identical_to_reference=digest(PANEL_PATH) == receipt["reference_sha256"],
                       actual_parquet_writer=importlib.metadata.version("pyarrow"))
        write_json(STATE_DIR / "panel_semantic_check.json", receipt)
    elif stage == "prepare":
        from code_longitudinal.prepare_inputs import prepare_model_ready
        records = []
        for e in ELECTIONS:
            for s in SPECS:
                if not scenario_is_allowed(s, e) or (e.election_id, s.scenario_id) not in scope.nls_pairs:
                    continue
                frame, _, manifest = prepare_model_ready(e, s, sample_size=2000, panel_path=PANEL_PATH)
                check(len(frame) == 2000 and not frame["unit_id"].duplicated().any(), f"Entree incomplete {e.election_id}/{s.scenario_id}")
                output = Path(manifest["output"])
                if not output.is_absolute():
                    output = ROOT / output
                records.append({"election_id": e.election_id, "scenario_id": s.scenario_id,
                                "rows": len(frame), "path": str(output), "sha256": digest(output)})
        check({pair_key(r) for r in records} == scope.nls_pairs,
              f"Matrices incompletes: attendu {len(scope.nls_pairs)}; observe {len(records)}")
        write_json(STATE_DIR / "prepared_292.json", records)
        # Hard gate: reopen every Parquet/CSV/manifest produced above and verify
        # all scientific margins before the first NLS/KRT/R estimator is called.
        validate_prepared_inputs(records, pd.read_parquet(PANEL_PATH))
    elif stage == "nls270":
        from code_longitudinal.run_longitudinal_production import run_nls_longitudinal
        result = run_nls_longitudinal(supervise=True)
        validate_result_count(result, len(scope.base_nls_pairs), "success_or_resumed", "failed")
        check(result["skipped_ineligible"] == len(scope.extension_nls_pairs), "Le partage NLS national/extension a change")
    elif stage == "krt240":
        plan = [r for r in read_json(CONTRACT / "krt_replay_240.json")["entries"]
                if pair_key(r) in scope.pairs]
        execute_krt_contract_rows(plan)
        mapping = krt_manifest_map()
        check(set(mapping) == {r["reference_run_id"] for r in plan}, f"{len(mapping)}/{scope.pair_count} KRT seulement")
        write_json(STATE_DIR / "krt_run_mapping.json", {k: m["run_id"] for k, (_, m) in mapping.items()})
    elif stage == "canonical52":
        from code_longitudinal.consolidation_core import build_krt_commune, build_krt_aggregate, build_nls
        from code_longitudinal.scoped_finalizer import _selected_nls_runs, _apply_public_schema
        from code_longitudinal.release_scope import load_release_scope
        mapping = krt_manifest_map(); runs = [(p, m) for p, m in mapping.values() if m["parameters"]["scenario_id"] in {"H0A", "H1"}]
        check(len(runs) == len(scope.canonical_pairs), "Socle H0A/H1 incomplet")
        nls_runs = _selected_nls_runs(str(load_longitudinal_panel_manifest()["panel_id"]), tuple(s.scenario_id for s in SPECS))
        check({pair_key(m["parameters"]) for _, m in nls_runs} == scope.base_nls_pairs,
              "NLS de base incomplets AVANT l'extension RxC")
        panel = pd.read_parquet(PANEL_PATH)
        c, a, n = _apply_public_schema(build_krt_commune(runs, panel), build_krt_aggregate(runs),
                                      build_nls(nls_runs), panel,
                                      load_release_scope(ROOT / "config/releases/v1.0.2.json"))
        check((len(c), len(a), len(n)) == (2000 * len(scope.canonical_pairs),
              3 * len(scope.canonical_pairs), scope.nls_rows(scope.base_nls_pairs)), "Dimensions canoniques incorrectes")
        dest = ROOT / "outputs/longitudinal_2000_v1/final/longitudinal_2000_v1.0.2_H0A_H1"; dest.mkdir(parents=True, exist_ok=True)
        for name, frame in (("commune", c), ("aggregate", a)):
            frame.to_parquet(dest / f"longitudinal_krt_{name}.parquet", index=False)
        n.to_parquet(dest / "longitudinal_nls.parquet", index=False)
    elif stage == "consolidate240":
        module("consolidate_current_krt_all_2x2", "--selection-policy", "initial_only")
        path = ROOT / "outputs/longitudinal_2000_v1/production/all_2x2_candidate/krt_240_candidate_selection.csv"
        df = pd.read_csv(path)
        check(set(map(tuple, df[["election_id", "scenario_id"]].values)) == expected_pairs()
              and len(df) == scope.pair_count, "Selection KRT incomplete")
    elif stage == "r240":
        from code_longitudinal.run_r_ei_all_2x2 import run
        result = run(scenarios=scope.scenario_ids, supervise=True)
        validate_result_count(result, scope.pair_count, "pairs_successful", "pairs_failed")
        check(result["status"] == "complete", f"R incomplet: {result}")
    elif stage == "r_consolidate":
        module("consolidate_r_ei_all_2x2", "--output-scope", "all_2x2", "--scenarios", *scope.scenario_ids)
        module("compare_python_r_ei_full_240")
    elif stage == "nls_rxc22":
        from code_longitudinal.run_rxc_panel_extension_v11 import run_extension
        rows = run_extension(audit_path=ROOT / "reproducibility/reference/rxc_ineligible_audit.csv",
                             panel_path=PANEL_PATH, supervise=True)
        check(len(rows) == len(scope.extension_nls_pairs) and all(r["execution_status"] == "success" for r in rows), "Extension RxC incomplete")
        from code_longitudinal import consolidate_rxc_panel_extension_v11 as extension
        result = extension.consolidate()
        write_json(STATE_DIR / "rxc_consolidation.json", result)
    elif stage == "coverage":
        module("build_current_estimation_coverage")
    elif stage == "covariates960":
        module("run_fast_nls_covariate_specs", "--supervise")
        df = pd.read_parquet(ROOT / "outputs/longitudinal_2000_v1/nls_covariates_fast/longitudinal_nls_covariates.parquet")
        check(len(df) == 12 * scope.pair_count, "4 sensibilites x 3 estimands par couple attendus")
    elif stage == "full_sources":
        from code_longitudinal import build_full240_professor_release as builder
        original_copy = builder._copy
        skipped = {"continue_r_ei_after_numpyro.ps1", "run_finalize_professor_release_after_240.ps1"}
        docs = {"PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md", "OUTPUT_SCHEMA.md"}
        def portable_copy(source, relative_target):
            if not source.is_file() and source.name in skipped:
                # Ces deux anciens lanceurs ne produisent aucune des 610 sorties.
                return builder.CANDIDATE / relative_target
            if not source.is_file() and source.name in docs:
                source = CONTRACT / "historical_docs" / source.name
            return original_copy(source, relative_target)
        builder._copy = portable_copy
        builder.prepare()
    elif stage == "assets":
        module("build_professor_release_assets")
    elif stage == "density480":
        module("export_density_pair_inputs")
        external([os.environ["LONGITUDINAL_RSCRIPT"], "--vanilla", str(ROOT / "r_replication/generate_all_pair_density_figures.R"), str(ROOT)])
        from code_longitudinal import finalize_density_bundle as density
        original_write_json = density.write_json
        def truthful_density_qa(path, obj):
            if isinstance(obj, dict) and "visual_samples_inspected" in obj:
                obj = dict(obj, visual_samples_inspected=0, visual_samples=[],
                           visual_inspection_complete_for_samples=False,
                           qa_scope="automated_file_and_dimension_checks_only")
            original_write_json(path, obj)
        density.write_json = truthful_density_qa
        density.main()
        module("build_density_report_atlas")
    elif stage == "report":
        module("repair_portable_report_from_template", "--template-zip", str(ROOT / "reproducibility/report/RAPPORT_LONGITUDINAL.template.html"))
        render_pdf(LIGHT / "01_RAPPORT/RAPPORT_LONGITUDINAL.html", LIGHT / "01_RAPPORT/RAPPORT_LONGITUDINAL.pdf", os.environ["LONGITUDINAL_BROWSER"])
        qa = {"schema_version": "replication_report_qa_v2", "created_at_utc": now(),
              "pdf_origin": "rendered_from_newly_generated_html_not_copied_from_reference",
              "visual_inspection_performed": False, "numeric_equality_to_historical_results": "not_certified",
              "reference_statistics_in_static_narrative": "historical_context_not_new_validation",
              "coverage_contract": "expected_results_610.json"}
        if not scope.is_full:
            qa["scope"] = scope.as_dict()
            qa["coverage_contract"] = "projection of expected_results_610.json for declared scope"
        write_json(LIGHT / "06_DOCUMENTATION/REPORT_QA.json", qa)
    elif stage == "verify":
        result = verify_outputs(LIGHT, allow_pending_manifest=True)
        write_json(STATE_DIR / "coverage_610.json", result)
    elif stage == "package":
        candidate = package_outputs()
        reference_text = os.environ.get("LONGITUDINAL_REFERENCE_RESULTS", "")
        check(bool(reference_text),
              "Archive de reference non configuree; utiliser le lanceur professeur")
        certify_results(Path(reference_text), candidate)
    else:
        raise ReplicationError("Etape inconnue: " + stage)


def inventory_missing(directory: Path, expected: list, allow_pending_manifest: bool = False) -> list[str]:
    return [r["path"] for r in expected if not (directory / r["path"]).is_file()
            and not (allow_pending_manifest and r["path"] == "06_DOCUMENTATION/DELIVERY_MANIFEST.json")]


def result_contract_for_scope() -> dict:
    from reproducibility.result_scope import project_result_contract
    return project_result_contract(read_json(CONTRACT / "expected_results_610.json"), get_scope())


def validate_nls_bounds(df) -> None:
    check(df["estimate"].notna().all(), "NLS non fini")
    kinds = df["estimand_type"]
    check(kinds.isin(["cell_probability", "group_contrast"]).all(), "Type d'estimand NLS inconnu")
    check(df.loc[kinds.eq("cell_probability"), "estimate"].between(0, 1).all(), "Probabilite NLS hors [0,1]")
    check(df.loc[kinds.eq("group_contrast"), "estimate"].between(-1, 1).all(), "Contraste NLS hors [-1,1]")


def verify_outputs(directory: Path, allow_pending_manifest: bool = False) -> dict:
    import pandas as pd
    import pyarrow.parquet as pq
    scope = get_scope()
    expected = result_contract_for_scope()["files"]
    missing = inventory_missing(directory, expected, allow_pending_manifest)
    check(not missing, "Sorties manquantes:\n" + "\n".join(missing))
    checks = []
    keys_nls = ["election_id", "scenario_id", "estimand_type", "social_group", "vote_category"]
    for row in expected:
        if "parquet" not in row:
            continue
        p = directory / row["path"]; meta = pq.ParquetFile(p)
        contract = row["parquet"]
        check(meta.metadata.num_rows == contract["rows"], f"Nombre de lignes incorrect: {p.name}")
        check(meta.schema_arrow.names == contract["columns"],
              f"Colonnes absentes, supplementaires ou desordonnees: {p.name}")
        check(str(meta.schema_arrow) == contract["schema"],
              f"Schema Arrow different du contrat: {p.name}")
        df = pd.read_parquet(p)
        if "unit_id" in df:
            key = ["election_id", "scenario_id", "unit_id"]
            check(not df.duplicated(key).any(), f"Cles communales dupliquees {p.name}")
            check(df.groupby(["election_id", "scenario_id"]).size().eq(2000).all(), f"Panel incomplet {p.name}")
            check(set(map(tuple, df[["election_id", "scenario_id"]].drop_duplicates().values)) == expected_pairs(), f"Couples manquants {p.name}")
        elif p.name == "longitudinal_nls.parquet":
            check(not df.duplicated(keys_nls).any(), "Cles NLS dupliquees")
            check(set(map(tuple, df[["election_id", "scenario_id"]].drop_duplicates().values)) == scope.nls_pairs,
                  "Couples NLS incomplets ou hors perimetre")
            validate_nls_bounds(df)
        elif "covariate" not in p.name:
            key = [x for x in ("election_id", "scenario_id", "model_key", "estimand") if x in df]
            check(not df.duplicated(key).any(), "Cles agregees dupliquees: " + p.name)
            check(set(map(tuple, df[["election_id", "scenario_id"]].drop_duplicates().values)) == expected_pairs(), "Couples incomplets: " + p.name)
        else:
            # Les identifiants de spécification restent ceux du script original.
            spec_col = next((c for c in ("covariate_spec", "covariate_spec_id", "spec_id", "specification", "specification_id") if c in df), None)
            check(spec_col is not None, "Colonne de specification absente: " + p.name)
            combos = df[["election_id", "scenario_id", spec_col]].drop_duplicates()
            check(len(combos) == 4 * scope.pair_count and combos[spec_col].nunique() == 4,
                  "Quatre specifications de sensibilite attendues par couple")
            check(set(map(tuple, combos[["election_id", "scenario_id"]].drop_duplicates().values)) == expected_pairs(), "Couples des sensibilites incomplets")
            keys = ["election_id", "scenario_id", spec_col] + [x for x in ("estimand", "social_group", "vote_category", "term") if x in df]
            check(not df.duplicated(keys).any(), "Sensibilites/coefficients dupliques")
        # Les incertitudes ne doivent pas disparaître lors de la consolidation.
        for group in (("b1_q025", "b1_q50", "b1_q975"), ("b2_q025", "b2_q50", "b2_q975"), ("q025", "median", "q975"), ("q025", "q50", "q975")):
            if all(c in df for c in group):
                finite = df[list(group)].notna().all(axis=1)
                # L'archive de référence conserve des valeurs R non finies et les
                # documente dans le catalogue; ne pas les imputer ni les supprimer.
                if "r_ei" not in p.name:
                    check(finite.all(), f"Quantiles manquants: {p.name}")
                sub = df.loc[finite]
                check(((sub[group[0]] <= sub[group[1]]) & (sub[group[1]] <= sub[group[2]])).all(), f"Quantiles incoherents: {p.name}")
        checks.append({"file": row["path"], "rows": len(df), "columns": len(df.columns), "status": "pass"})
    # Vérifier réellement la couverture des figures individuelles par méthode/couple.
    catalog = pd.read_csv(directory / "06_DOCUMENTATION/CATALOGUE_DENSITES_COMPLET.csv")
    check(len(catalog) == scope.density_count, "Catalogue des densites incomplet")
    return {"status": "complete_structure_not_numerical_equality", "created_at_utc": now(),
            "expected_files": len(expected), "scope": scope.as_dict(), "pending_generated_manifest": allow_pending_manifest,
            "main_tables": checks, "density_catalog_rows": len(catalog),
            "interpretation": "Completion informatique, pas validation scientifique ni egalite des tirages MCMC."}


def package_outputs() -> Path:
    verification = verify_outputs(LIGHT, allow_pending_manifest=True)
    expected = result_contract_for_scope()["files"]
    files = []
    for r in expected:
        if r["path"] == "06_DOCUMENTATION/DELIVERY_MANIFEST.json":
            continue
        p = LIGHT / r["path"]
        files.append({"path": r["path"], "bytes": p.stat().st_size, "sha256": digest(p),
                      **({"parquet": {"rows": r["parquet"]["rows"], "columns": r["parquet"]["columns"],
                                       "schema": r["parquet"]["schema"],
                                       "verification": "rows_column_order_and_arrow_schema_checked_against_reference"}}
                         if "parquet" in r else {})})
    manifest = {"schema_version": "longitudinal_results_recalculated_v2", "created_at_utc": now(),
                "files": files, "verification": verification,
                "source_reference_sha256": read_json(CONTRACT / "expected_results_610.json")["source_archive_sha256"],
                "not_a_claim_of_bitwise_or_monte_carlo_equality": True}
    scope = get_scope()
    manifest["replication_scope"] = scope.as_dict()
    if not scope.is_full:
        manifest["scope"] = scope.as_dict()
    write_json(LIGHT / "06_DOCUMENTATION/DELIVERY_MANIFEST.json", manifest)
    out = ROOT / "deliverables" / ("longitudinal_2000_results_recalcules.zip" if scope.is_full
                                    else "longitudinal_2000_controle_court.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for r in expected:
            z.write(LIGHT / r["path"], r["path"])
    with zipfile.ZipFile(temp) as z:
        names = z.namelist()
        check(len(names) == len(set(names)) == len(expected) and z.testzip() is None,
              "ZIP recalcule incomplet/duplique/corrompu")
    temp.replace(out)
    out.with_suffix(".zip.sha256").write_text(digest(out) + "  " + out.name + "\n", encoding="ascii")
    print("SORTIE RECALCULEE:", out, flush=True)
    return out


def certify_results(reference_results: Path, candidate_results: Path) -> dict:
    from reproducibility.certify_reproduction import compare_artifacts
    reference = validate_reference_archive(reference_results)
    scope = get_scope()
    comparison_reference = None
    if not scope.is_full:
        # Comparison-only: reference-derived renderings never enter candidate
        # scientific outputs. Tables/diagnostics still compare to the fixed ZIP.
        from reproducibility.render_scope_reference import render_scope_reference
        from reproducibility.certify_reproduction import COMPARISON_REFERENCE_RECEIPT
        comparison_reference = STATE_DIR / "comparison_reference"
        if not (comparison_reference / COMPARISON_REFERENCE_RECEIPT).is_file():
            print("COMPARAISON SEULEMENT: rendu de la reference au meme perimetre; aucun estimateur", flush=True)
            render_scope_reference(
                Path(reference["path"]), comparison_reference,
                rscript=Path(os.environ.get("LONGITUDINAL_RSCRIPT", "")),
                browser=Path(os.environ.get("LONGITUDINAL_BROWSER", "")), scope_name=scope.name,
            )
    result = compare_artifacts(
        Path(reference["path"]),
        candidate_results,
        CONTRACT / "certification_policy_v1.json",
        CONTRACT / "expected_results_610.json",
        scope=scope,
        comparison_reference_path=comparison_reference,
    )
    result["reference_archive"] = reference
    result["certification_level"] = (
        ("rejeu_binaire_exact" if get_scope().is_full else "rejeu_binaire_exact_perimetre_reduit") if result["exact_replay_pass"]
        else ("equivalence_scientifique_numerique" if get_scope().is_full else "equivalence_scientifique_perimetre_reduit") if result["scientific_equivalence_pass"]
        else "echec"
    )
    result["interpretation_fr"] = (
        "Les tables, diagnostics, figures et documents respectent les controles preregistres. "
        "Le niveau rejeu_binaire_exact implique 610 empreintes identiques; le niveau "
        "equivalence_scientifique_numerique autorise seulement les ecarts numeriques et visuels documentes."
    )
    if not get_scope().is_full:
        result["interpretation_fr"] = (
            "Controle borne de la chaine de production commune. Il ne certifie pas les 610 fichiers "
            "de la campagne complete. Les comparaisons de figures et documents restent bloquantes; "
            "les differences dues au perimetre ne sont pas silencieusement acceptees."
        )
    runtime_report = STATE_DIR / "certification_scientifique.json"
    sidecar = candidate_results.with_suffix(".certification.json")
    write_json(runtime_report, result)
    write_json(sidecar, result)
    check(result.get("reference_contract_check", {}).get("pass") is True,
          "Le contrat numerique n'est pas coherent avec l'archive de reference")
    check(result["scientific_equivalence_pass"],
          "Les resultats recalcules ne satisfont pas le contrat d'equivalence scientifique; voir " + str(sidecar))
    print("CERTIFICATION:", result["certification_level"], "; rapport", sidecar, flush=True)
    return result


@contextmanager
def exclusive_pipeline():
    """One live orchestrator per extraction, including across different scopes."""
    directory = ROOT / ".runtime"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "replication_pipeline.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ReplicationError("Une reproduction est deja active dans cette extraction; ne pas lancer de doublon.") from exc
            pipeline_job = None
            try:
                # The stable name is a second liveness barrier.  More
                # importantly, kill-on-close makes an abrupt orchestrator exit
                # terminate the current worker and all of its descendants.
                job_name = "Local\\longitudinal-replication-" + hashlib.sha256(
                    os.path.normcase(str(ROOT.resolve())).encode("utf-8")
                ).hexdigest()
                try:
                    pipeline_job = WindowsKillOnCloseJob(
                        name=job_name, reject_existing=True,
                    )
                except (OSError, RuntimeError) as exc:
                    raise ReplicationError(
                        "Impossible d'etablir la supervision Windows exclusive de la reproduction: "
                        + str(exc)
                    ) from exc
                yield pipeline_job
            finally:
                if pipeline_job is not None:
                    pipeline_job.close()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            # This keeps the non-estimation orchestration tests portable.
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ReplicationError("Une reproduction est deja active dans cette extraction.") from exc
            try:
                yield None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def run_pipeline(raw_dir: Path, rscript: str, browser: str,
                 reference_results: Path | None = None) -> None:
    with exclusive_pipeline() as pipeline_job:
        _run_pipeline(raw_dir, rscript, browser, reference_results, pipeline_job)


def _run_pipeline(raw_dir: Path, rscript: str, browser: str,
                  reference_results: Path | None = None,
                  pipeline_job: WindowsKillOnCloseJob | None = None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    proof = preflight(raw_dir, rscript, browser, reference_results)
    write_json(STATE_DIR / "preflight.json", proof)
    raw = proof["raw"]; configure(Path(raw["raw_dir"]), rscript, browser, reference_results)
    code = {p.relative_to(ROOT).as_posix(): digest(p)
            for folder in ("reproducibility", "code_longitudinal", "r_replication")
            for p in (ROOT / folder).rglob("*")
            if p.is_file() and p.suffix.lower() in {".py", ".ps1", ".r"}}
    if (ROOT / "REPRODUIRE_TOUT.ps1").is_file():
        code["REPRODUIRE_TOUT.ps1"] = digest(ROOT / "REPRODUIRE_TOUT.ps1")
    fingerprint = stable_hash({"raw": raw["fingerprint"], "scope": get_scope().as_dict(),
                               "contracts": {p.relative_to(CONTRACT).as_posix(): digest(p) for p in CONTRACT.rglob("*") if p.is_file()},
                               "code": code, "orchestrator": digest(Path(__file__)),
                               "python_lock": digest(ROOT / "reproducibility/requirements-python312.lock.txt")})
    state_path = STATE_DIR / "state.json"
    if state_path.exists():
        state = read_json(state_path)
        check(state["fingerprint"] == fingerprint, "Sources/code/contrat modifies depuis la premiere execution. Extraire un nouveau ZIP dans un dossier vide.")
    else:
        dirty = [x for x in ("outputs", "panel", "work") if (ROOT / x).exists() and any((ROOT / x).iterdir())]
        check(not dirty, "Premiere execution: extraire dans un nouveau dossier (sorties deja presentes: " + ", ".join(dirty) + ")")
        state = {"fingerprint": fingerprint, "scope": get_scope().as_dict(),
                 "created_at_utc": now(), "completed": [], "status": "running"}
        write_json(state_path, state)
    for stage in STAGES:
        if stage in state["completed"] and stage not in {"verify", "package"}:
            print("Etape deja achevee:", stage, flush=True); continue
        state.update(status="running", current_stage=stage)
        state.pop("error", None)
        write_json(state_path, state)
        log = STATE_DIR / f"{STAGES.index(stage)+1:02d}_{stage}.log"
        cmd = [sys.executable, "-m", "reproducibility.replication_complete", "worker", "--stage", stage]
        print(f"ETAPE {STAGES.index(stage)+1}/{len(STAGES)} {stage}; perimetre={get_scope().name}, "
              f"{get_scope().pair_count} couples 2x2; journal {log}", flush=True)
        try:
            with log.open("a", encoding="utf-8") as f:
                f.write("\nEXECUTION " + now() + "\n"); f.flush()
                worker_environment = os.environ.copy()
                # Only the official run path enables child-process isolation.
                # Direct library calls retain their historical API for tests
                # and expert tooling.
                worker_environment["LONGITUDINAL_SUPERVISE_ESTIMATIONS"] = "1"
                process, _, _ = start_owned_process_tree(
                    cmd, cwd=ROOT, environment=worker_environment,
                    stdout=f, stderr=subprocess.STDOUT, text=True,
                    job=pipeline_job,
                )
                try:
                    returncode = process.wait()
                except BaseException:
                    evidence = _terminate_process_tree(process, job=pipeline_job)
                    if not evidence["tree_termination_confirmed"]:
                        raise ReplicationError(
                            "Interruption: Windows n'a pas confirme l'arret de l'arbre du worker; "
                            "ne pas relancer avant verification des processus Python/R."
                        )
                    raise
                if returncode != 0:
                    evidence = _terminate_process_tree(process, job=pipeline_job)
                    if not evidence["tree_termination_confirmed"]:
                        raise ReplicationError(
                            "Echec du worker et arret incomplet de son arbre de processus; "
                            "ne pas relancer avant verification des processus Python/R."
                        )
                    raise subprocess.CalledProcessError(returncode, cmd)
                if pipeline_job is not None and not pipeline_job.wait_empty(1.0):
                    evidence = _terminate_process_tree(process, job=pipeline_job)
                    raise ReplicationError(
                        "Le worker a termine en laissant un descendant actif; arbre arrete, "
                        f"sorties de l'etape refusees (confirmation={evidence['tree_termination_confirmed']})."
                    )
        except (Exception, KeyboardInterrupt) as exc:
            state.update(status="failed_or_interrupted", error=str(exc)); write_json(state_path, state)
            write_failure_report(ROOT, STATE_DIR, exc, stage=stage, stage_log=log)
            raise ReplicationError(f"Arret a l'etape {stage}; consulter {log}. Relancer la meme commande apres correction/interruption.") from exc
        if stage not in state["completed"]:
            state["completed"].append(stage)
        write_json(state_path, state)
    if reference_results is not None:
        certification_path = STATE_DIR / "certification_scientifique.json"
        check(certification_path.is_file(), "Rapport de certification scientifique absent")
        certification = read_json(certification_path)
        check(certification.get("scientific_equivalence_pass") is True,
              "La reconstruction est complete mais la certification scientifique a echoue")
        state.update(status="complete_scientifically_certified" if get_scope().is_full
                     else "complete_scoped_scientifically_certified", finished_at_utc=now(),
                     certification_level=certification["certification_level"],
                     certification_report=str(certification_path))
        print("RECONSTRUCTION TERMINEE ET CERTIFIEE:", certification["certification_level"],
              "; perimetre", get_scope().name, "; voir", certification_path)
    else:
        # Utilisé uniquement par les tests d'orchestration qui substituent tous
        # les workers coûteux. Le lanceur professeur fournit toujours la référence.
        state.update(status="complete_test_dispatch_without_certification", finished_at_utc=now())
    write_json(state_path, state)
    if reference_results is not None:
        resolve_failure_report(ROOT, STATE_DIR, state["certification_level"])


def estimation_worker(family: str, key: str) -> None:
    """Internal one-item entrypoint; public users must use the main launcher."""
    check(os.environ.get("LONGITUDINAL_RAW_ARCHIVES", "") != "",
          "worker interne: utiliser REPRODUIRE_TOUT.ps1")
    activate_runtime_panel_hash()
    if family == "krt":
        matches = [row for row in read_json(CONTRACT / "krt_replay_240.json")["entries"]
                   if row["reference_run_id"] == key and pair_key(row) in get_scope().pairs]
        check(len(matches) == 1, f"Cle KRT interne absente ou hors perimetre: {key}")
        _run_krt_contract_row(matches[0])
        return
    if family in {"nls", "nls_rxc"}:
        parts = key.split("__")
        check(len(parts) == 2, f"Cle NLS interne invalide: {key}")
        election_id, scenario_id = parts
        scope = get_scope()
        allowed = scope.base_nls_pairs if family == "nls" else scope.extension_nls_pairs
        check((election_id, scenario_id) in allowed,
              f"Cle NLS interne absente ou hors perimetre {family}: {key}")
        from code_longitudinal.build_longitudinal_panel import PANEL_PATH, load_longitudinal_panel_manifest
        from code_longitudinal.run_nls_batch import run_nls
        from code_longitudinal.run_longitudinal_production import _nls_success_index, _require_nls_saved_outputs
        from code_longitudinal.spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
        result = run_nls(
            ELECTION_BY_ID[election_id], SCENARIO_BY_ID[scenario_id],
            sample_size=2000, panel_path=PANEL_PATH, force=False,
        )
        check(result.get("status") in {"success", "skipped_existing_success"},
              f"Echec NLS {key}: {result}")
        manifest = _nls_success_index(str(load_longitudinal_panel_manifest()["panel_id"])).get(
            (election_id, scenario_id), {}
        )
        _require_nls_saved_outputs(str(manifest.get("run_id", "")))
        return
    raise ReplicationError(f"Famille de worker d'estimation inconnue: {family}")


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "original-module":
        import runpy
        name = sys.argv[2]
        check(re.fullmatch(r"[A-Za-z0-9_]+", name) is not None, "Nom de module invalide")
        activate_runtime_panel_hash()
        sys.argv = ["code_longitudinal." + name, *sys.argv[3:]]
        runpy.run_module("code_longitudinal." + name, run_name="__main__")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "integrity", "raw", "preflight", "run", "worker",
                                            "estimation-worker", "verify", "certify"])
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "DONNEES_BRUTES")
    parser.add_argument("--rscript", default=os.environ.get("LONGITUDINAL_RSCRIPT", ""))
    parser.add_argument("--browser", default=os.environ.get("LONGITUDINAL_BROWSER", ""))
    parser.add_argument("--reference-results", type=Path,
                        default=ROOT / "longitudinal_2000_results.zip")
    parser.add_argument("--candidate-results", type=Path,
                        default=ROOT / "deliverables/longitudinal_2000_results_recalcules.zip")
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--scope", choices=("full", "court"), default=os.environ.get(ENVIRONMENT_KEY, "full"))
    parser.add_argument("--retry-failed", action="store_true",
                        help="Reessayer explicitement les estimations bloquees apres resolution de la cause; aucun reglage scientifique ne change")
    parser.add_argument("--estimation-family", choices=tuple(ENVIRONMENT_BY_FAMILY))
    parser.add_argument("--estimation-key")
    for family, environment_name in ENVIRONMENT_BY_FAMILY.items():
        parser.add_argument("--timeout-" + family.replace("_", "-") + "-seconds",
                            dest="timeout_" + family, type=int,
                            help=f"Delai mural positif par estimation ({environment_name})")
    args = parser.parse_args()
    os.environ[ENVIRONMENT_KEY] = args.scope
    for family, environment_name in ENVIRONMENT_BY_FAMILY.items():
        value = getattr(args, "timeout_" + family)
        if value is not None:
            check(value > 0, f"--timeout-{family.replace('_', '-')}-seconds doit etre positif")
            os.environ[environment_name] = str(value)
    if args.command not in {"worker", "estimation-worker"}:
        os.environ["LONGITUDINAL_RETRY_FAILED"] = "1" if args.retry_failed else "0"
    global STATE_DIR
    STATE_DIR = ROOT / ".runtime" / ("replication_v2" if args.scope == "full" else "replication_court")
    try:
        if args.command == "plan":
            result = contract_plan()
        elif args.command == "integrity":
            result = check_original_integrity()
        elif args.command == "raw":
            result = resolve_raw(args.raw_dir)
        elif args.command == "preflight":
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            result = preflight(args.raw_dir, args.rscript, args.browser, args.reference_results)
        elif args.command == "run":
            run_pipeline(args.raw_dir, args.rscript, args.browser, args.reference_results); return
        elif args.command == "worker":
            check(args.stage is not None, "--stage requis")
            check(os.environ.get("LONGITUDINAL_RAW_ARCHIVES", "") != "", "worker interne: utiliser run")
            os.chdir(ROOT); worker(args.stage); return
        elif args.command == "estimation-worker":
            check(bool(args.estimation_family) and bool(args.estimation_key),
                  "--estimation-family et --estimation-key requis")
            os.chdir(ROOT); estimation_worker(args.estimation_family, args.estimation_key); return
        elif args.command == "verify":
            result = verify_outputs(LIGHT)
        else:
            result = certify_results(args.reference_results, args.candidate_results)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except (Exception, KeyboardInterrupt) as exc:
        if args.command not in {"worker", "estimation-worker"}:
            try:
                # A worker failure already has a richer stage-specific report.
                if not (isinstance(exc, ReplicationError) and str(exc).startswith("Arret a l'etape ")
                        and (ROOT / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.json").is_file()):
                    write_failure_report(ROOT, STATE_DIR, exc, stage=args.command)
            except OSError as report_error:
                print("Impossible d'ecrire le rapport d'erreur: " + str(report_error), file=sys.stderr)
        if not isinstance(exc, (ReplicationError, BatchEstimationError, KeyboardInterrupt)):
            traceback.print_exc()
        print("ECHEC: " + str(exc), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

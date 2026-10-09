"""Human-readable local failure handoff; no estimator or repair is run here."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8-sig")
    temporary.replace(path)


def _scope(state_dir: Path) -> str:
    return "court" if state_dir.name == "replication_court" else "full"


def _command(scope: str, retry: bool = False) -> str:
    return ("powershell -ExecutionPolicy Bypass -File .\\REPRODUIRE_TOUT.ps1"
            + (" -ControleCourt" if scope == "court" else "")
            + (" -ReessayerEchecs" if retry else ""))


def _commands(scope: str) -> tuple[dict[str, str], bool]:
    """Prefer the exact launcher invocation exported by REPRODUIRE_TOUT.ps1."""
    exact = os.environ.get("LONGITUDINAL_RESUME_COMMAND", "").strip()
    normal = exact or _command(scope)
    retry = normal
    if not re.search(r"(?i)(?:^|\s)-ReessayerEchecs(?:\s|$)", retry):
        retry += " -ReessayerEchecs"
    return {"normal": normal, "retry_failed": retry}, bool(exact)


def write_failure_report(root: Path, state_dir: Path, error: BaseException, *,
                         stage: str | None = None, stage_log: Path | None = None) -> dict:
    root, state_dir = Path(root), Path(state_dir)
    folder = root / "JOURNAUX_REPRODUCTION"
    reports, failures = [], []
    receipts = state_dir / "estimation_failures" / "estimation_batches"
    for receipt_path in sorted(receipts.glob("*.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            reports.append({"path": str(receipt_path), "batch": receipt.get("batch_name"),
                            "status": receipt.get("status"), "counts": receipt.get("counts", {})})
            failures.extend({**item, "batch": receipt.get("batch_name"), "receipt": str(receipt_path)}
                            for item in receipt.get("errors", []))
        except (OSError, ValueError, TypeError) as exc:
            failures.append({"key": str(receipt_path), "type": type(exc).__name__,
                             "message": "Recu illisible : " + str(exc), "classification": "receipt_invalid",
                             "next_action": "Ne pas modifier le recu; transmettre les journaux a l'auteur."})
    scope = _scope(state_dir)
    commands, commands_are_exact = _commands(scope)
    payload = {
        "schema_version": "professor_failure_handoff_v1", "status": "failed_or_interrupted",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "scope": scope,
        "stage": stage, "error_type": type(error).__name__,
        "message": str(error) or "Execution interrompue.", "stage_log": str(stage_log) if stage_log else None,
        "state_path": str(state_dir / "state.json"), "batch_reports": reports,
        "unresolved_estimations": failures, "commands": commands,
        "commands_are_default_path_examples": not commands_are_exact,
        "preserve_completed_outputs": True, "scientific_certification": False,
        "instruction": "Corriger la cause avant toute nouvelle tentative; un bug du code exige une correction du paquet, pas une boucle de relances.",
    }
    lines = [
        "ECHEC DE CE LANCEMENT — AUCUNE NOUVELLE CERTIFICATION", "",
        f"Date UTC : {payload['recorded_at_utc']}", f"Etape : {stage or 'preparation'}",
        f"Erreur : {payload['error_type']} : {payload['message']}", "",
        "Les calculs deja termines restent sur disque. Ne supprimez ni le dossier ni les resultats.",
        "Un diagnostic scientifique caveat/fail n'est pas, a lui seul, une panne informatique.",
    ]
    if failures:
        lines += ["", "ESTIMATIONS / RECUS A EXAMINER :"]
        for item in failures:
            lines += [f"- {item.get('batch', '')} {item.get('key', '?')} : {item.get('type', '')} — {item.get('message', '')}",
                      "  " + item.get("next_action", "Transmettre les journaux a l'auteur.")]
        lines += ["", "Les erreurs enregistrees ne sont pas retentees par une relance ordinaire.",
                  "Apres avoir identifie et resolu la cause (ou confirme la fin du processus interrompu),", 
                  "ajouter -ReessayerEchecs a votre commande initiale (conserver tous vos chemins/options).",
                  ("Commande exacte avec reprise des seuls echecs :" if commands_are_exact else
                   "Exemple si vous utilisiez les chemins par defaut :"), commands["retry_failed"],
                  "Cette option ne corrige pas le code et ne change aucun reglage scientifique."]
    else:
        command_label = ("Commande exacte du lancement interrompu :" if commands_are_exact else
                         "Exemple avec les chemins par defaut :")
        lines += ["", "Apres une interruption entre etapes ou un prerequis corrige, reprendre votre commande initiale",
                  "dans ce meme dossier, avec tous vos chemins/options. " + command_label,
                  commands["normal"]]
    lines += ["", "Si l'erreur revient, ne pas relancer en boucle : contacter l'auteur.",
              "Envoyer DERNIER_ECHEC.txt et DERNIER_ECHEC.json, le dernier journal PowerShell",
              "de JOURNAUX_REPRODUCTION et le journal d'etape indique ci-dessous.",
              "Aucune donnee brute ni trace volumineuse n'est necessaire pour ce premier signalement.",
              "Ne pas modifier le code dans ce dossier : un paquet corrige doit etre extrait dans un nouveau dossier.",
              f"Journal d'etape : {stage_log or 'voir le journal PowerShell'}",
              f"Etat de reprise : {state_dir / 'state.json'}", ""]
    _write(folder / "DERNIER_ECHEC.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _write(folder / "DERNIER_ECHEC.txt", "\n".join(lines))
    print(f"ECHEC — consignes : {folder / 'DERNIER_ECHEC.txt'}", flush=True)
    return payload


def resolve_failure_report(root: Path, state_dir: Path, certification_level: str) -> None:
    """Retain the previous error as history, marking it resolved only after certification."""
    folder = Path(root) / "JOURNAUX_REPRODUCTION"
    path = folder / "DERNIER_ECHEC.json"
    if not path.is_file():
        return
    previous = json.loads(path.read_text(encoding="utf-8-sig"))
    # A short replay cannot resolve a failure of the complete campaign (and
    # conversely). The shared human-readable handoff must retain that warning.
    if previous.get("scope") != _scope(Path(state_dir)):
        return
    payload = {**previous, "status": "resolved_after_certification",
               "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
               "certification_level": certification_level, "resolved_scope": _scope(Path(state_dir)),
               "scientific_certification": True}
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _write(folder / "DERNIER_ECHEC.txt",
           "ANCIEN ECHEC RESOLU — REPLICATION TERMINEE ET CERTIFIEE POUR LE PERIMETRE INDIQUE\n"
           f"Perimetre : {payload['resolved_scope']}\nCertification : {certification_level}\n"
           "Le detail de l'ancien echec est conserve dans DERNIER_ECHEC.json.\n"
           "Une certification du controle court ne certifie pas la campagne integrale.\n")

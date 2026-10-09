"""Bounded per-estimation recovery; never changes an item or scientific settings.

The caller owns the batch lock and scientific validation/resume logic. Keys must
uniquely identify configurations within the caller's fingerprinted workspace.
This receipt stores provenance, not model inputs, outputs, or cached results.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from reproducibility.estimation_process import (
    EstimationTimeoutError,
    OrphanRiskError,
    ResourceWaitTimeoutError,
)


class BatchEstimationError(RuntimeError):
    def __init__(self, report: dict, report_path: Path):
        self.report = report
        self.report_path = report_path
        super().__init__(
            f"{report['batch_name']}: {len(report['errors'])} estimation(s) non resolue(s); "
            f"voir {report_path}"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict) -> None:
    """Same-directory replace keeps the previous complete receipt on a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers/scanners can briefly deny an atomic replacement.
        # Retry ONLY this receipt operation (five calls, 0.75 s maximum delay),
        # never the scientific callable. Persistent access denial still raises.
        delays = (0.05, 0.10, 0.20, 0.40)
        for attempt in range(len(delays) + 1):
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == len(delays):
                    raise
                time.sleep(delays[attempt])
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _classification(exc: BaseException) -> str:
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return "interrupted"
    # A wall-clock limit is deliberate, not an incidental transient error.
    # Never spend the one automatic transient retry on another immediately
    # identical long run; the professor must explicitly use -ReessayerEchecs.
    if isinstance(exc, (EstimationTimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(exc, ResourceWaitTimeoutError):
        return "systemic"
    if isinstance(exc, OrphanRiskError):
        return "systemic"
    if isinstance(exc, MemoryError) or (
        isinstance(exc, OSError) and (exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112)
    ):
        return "systemic"
    # Windows reports sharing violations as PermissionError too; these two
    # specific codes are retryable, ordinary access-denied errors are not.
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {32, 33}:
        return "transient"
    if isinstance(exc, PermissionError):
        return "systemic"
    if isinstance(exc, (ConnectionError, TimeoutError)) or (
        isinstance(exc, OSError) and exc.errno in {
            errno.EAGAIN, errno.EBUSY, errno.ETIMEDOUT, errno.ECONNRESET,
        }
    ):
        return "transient"
    return "permanent"


def _next_action(classification: str) -> str:
    if classification == "systemic":
        return "Corriger la memoire, le disque ou les permissions, puis relancer avec -ReessayerEchecs."
    if classification == "interrupted":
        return "Verifier que le precedent processus est arrete, puis relancer avec -ReessayerEchecs."
    if classification == "timeout":
        return ("Examiner le journal et le heartbeat. Si l'estimation progressait normalement, "
                "augmenter sa limite puis relancer avec -ReessayerEchecs; ne pas relancer en boucle.")
    return "Examiner l'erreur et corriger sa cause, puis relancer avec -ReessayerEchecs."


def execute_estimation_batch(items, *, batch_name, key_fn, run, state_dir, retry_failed=False):
    """Try independent items and fail closed if any estimation remains unresolved.

    Normal relaunches do not retry recorded failures. ``retry_failed=True``
    authorizes one new round per previously failed item; each round permits at
    most two calls, the second only after a recognized transient exception.
    Successful items ALWAYS call ``run`` again, allowing the scientific runner
    to validate and reuse its own completed work. An interrupted/in-flight call
    consumes its attempt, is never silently repeated, and needs explicit retry.
    """
    if not isinstance(batch_name, str) or not batch_name.strip():
        raise ValueError("batch_name must be a non-empty string")
    selected = list(items)
    keys = [json.loads(json.dumps(key_fn(item), ensure_ascii=False, allow_nan=False)) for item in selected]
    key_ids = [json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for key in keys]
    if len(set(key_ids)) != len(key_ids):
        raise ValueError("Duplicate estimation keys")
    suffix = hashlib.sha256(batch_name.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", batch_name)[:60] or "batch"
    path = Path(state_dir) / "estimation_batches" / f"{slug}_{suffix}.json"
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
        if (report.get("schema_version") != "estimation_recovery_v1"
                or report.get("batch_name") != batch_name or report.get("key_ids") != key_ids):
            raise ValueError(f"Incompatible estimation receipt: {path}")
    else:
        report = {
            "schema_version": "estimation_recovery_v1", "batch_name": batch_name,
            "created_at_utc": _now(), "key_ids": key_ids,
            "items": [{"key": key, "status": "pending", "attempts": 0,
                       "round": 0, "round_attempts": 0, "history": []} for key in keys],
        }
    if len(report["items"]) != len(selected):
        raise ValueError(f"Invalid estimation receipt item count: {path}")

    def save(status="running", abort_reason=None):
        report.update(status=status, updated_at_utc=_now(), abort_reason=abort_reason)
        report["errors"] = [dict(row["error"]) for row in report["items"] if row.get("error")]
        report["counts"] = {name: sum(row["status"] == name for row in report["items"])
                            for name in ("pending", "running", "success", "failed")}
        _atomic_json(path, report)

    def failed(row, exc):
        category = _classification(exc)
        error = {"key": row["key"], "type": type(exc).__name__, "message": str(exc),
                 "attempts": row["attempts"], "classification": category,
                 "next_action": _next_action(category)}
        if isinstance(exc, EstimationTimeoutError):
            error.update(timeout_seconds=exc.timeout_seconds, process_pid=exc.pid,
                         estimation_family=exc.family, estimation_key=exc.key)
        if isinstance(exc, ResourceWaitTimeoutError):
            error.update(timeout_seconds=exc.timeout_seconds, resource=exc.resource,
                         estimation_key=exc.key, resource_wait_expired=True)
        if isinstance(exc, OrphanRiskError):
            error.update(process_pid=exc.pid, estimation_family=exc.family,
                         estimation_key=exc.key, orphan_risk=True,
                         termination=exc.termination,
                         next_action=("Verifier et arreter les processus Python/R associes, "
                                      "puis relancer explicitement avec -ReessayerEchecs."))
        row.update(status="failed", error=error)
        row["history"][-1].update(status="failed", finished_at_utc=_now(), error=dict(error))
        try:
            save()
        except Exception as receipt_error:
            # A genuinely full/unwritable disk may prevent the failure receipt
            # itself. Stop immediately, expose the in-memory evidence, and keep
            # the previous atomic receipt (including its reserved attempt).
            report.update(status="aborted", abort_reason="Failure receipt could not be persisted",
                          receipt_write_error={"type": type(receipt_error).__name__,
                                               "message": str(receipt_error)})
            print(f"ARRET {batch_name}: erreur {type(exc).__name__}; "
                  f"impossible d'enregistrer le recu: {receipt_error}", flush=True)
            raise BatchEstimationError(report, path) from receipt_error
        print(f"ECHEC {batch_name} {row['key']}: {category}, essai {row['round_attempts']}/2; "
              f"{type(exc).__name__}: {str(exc)[:200]}", flush=True)
        return category

    # An abruptly terminated process may not have written its exception. Its
    # pre-call durable attempt still counts and cannot earn a fresh retry budget.
    for row in report["items"]:
        if row["status"] == "running":
            row.update(status="failed", error={
                "key": row["key"], "type": "InterruptedAttempt",
                "message": "Essai precedent interrompu sans statut final.",
                "attempts": row["attempts"], "classification": "interrupted",
                "next_action": _next_action("interrupted"),
            })
            row["history"][-1].update(status="interrupted", finished_at_utc=_now(), error=dict(row["error"]))
    save()
    results = []
    for item, row in zip(selected, report["items"]):
        if row["status"] == "failed" and not retry_failed:
            print(f"NON REESSAYE {batch_name} {row['key']}: erreur deja enregistree; -ReessayerEchecs requis.", flush=True)
            if row["error"]["classification"] == "systemic":
                save("aborted", "Prior unresolved systemic failure")
                raise BatchEstimationError(report, path)
            continue
        row["round"] += 1
        row["round_attempts"] = 0
        while row["round_attempts"] < 2:
            row["attempts"] += 1
            row["round_attempts"] += 1
            row.update(status="running", error=None)
            row["history"].append({"attempt": row["attempts"], "round": row["round"],
                                   "round_attempt": row["round_attempts"], "status": "running",
                                   "started_at_utc": _now()})
            save()  # Reserve the attempt durably BEFORE touching scientific work.
            try:
                result = run(item)
            except (KeyboardInterrupt, SystemExit) as exc:
                try:
                    failed(row, exc)
                    save("interrupted", type(exc).__name__)
                except Exception as receipt_error:
                    print(f"Recu non actualise apres interruption: {receipt_error}", flush=True)
                raise  # Never swallow or translate a user's interruption.
            except Exception as exc:
                category = failed(row, exc)
                if category == "systemic":
                    save("aborted", f"{type(exc).__name__}: {exc}")
                    print(f"ARRET {batch_name}: erreur systemique; autres estimations non lancees.", flush=True)
                    raise BatchEstimationError(report, path) from exc
                if category == "transient" and row["round_attempts"] < 2:
                    print(f"NOUVEL ESSAI {batch_name} {row['key']}: erreur transitoire reconnue (2/2).", flush=True)
                    continue
                break
            else:
                row.update(status="success", error=None)
                row["history"][-1].update(status="success", finished_at_utc=_now())
                save()
                results.append(result)
                break
    save("failed" if any(row["status"] == "failed" for row in report["items"]) else "complete")
    print(f"BILAN {batch_name}: {report['counts']['success']}/{len(selected)} reussies, "
          f"{len(report['errors'])} erreur(s) non resolue(s); {path}", flush=True)
    if report["errors"]:
        raise BatchEstimationError(report, path)
    return results

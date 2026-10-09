"""Injected failures only. No model, raw preparation, package download or install."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

from reproducibility import failure_report as handoff
from reproducibility import replication_complete as pipeline


def receipt(state, errors, status="failed"):
    path = state / "estimation_failures/estimation_batches/fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"batch_name": "fixture", "status": status,
                                "counts": {"success": 2, "failed": len(errors)}, "errors": errors}), encoding="utf-8")
    return path


def test_failure_handoff_is_readable_and_preserves_scope_and_model(tmp_path):
    state = tmp_path / ".runtime/replication_court"
    receipt(state, [{"key": "pre_2022_r1/H7", "type": "ValueError", "message": "injected failure",
                     "attempts": 1, "classification": "permanent", "next_action": "Contacter l'auteur."}])
    log = state / "04_krt240.log"
    result = handoff.write_failure_report(tmp_path, state, RuntimeError("fixture stage failed"),
                                         stage="krt240", stage_log=log)
    assert result["scientific_certification"] is False
    assert result["unresolved_estimations"][0]["key"] == "pre_2022_r1/H7"
    assert result["commands"]["retry_failed"].endswith("-ControleCourt -ReessayerEchecs")
    message = (tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt").read_text(encoding="utf-8-sig")
    for expected in ("pre_2022_r1/H7", "injected failure", "tous vos chemins/options",
                     "Ne supprimez", "ne pas relancer en boucle", str(log)):
        assert expected in message
    assert not (tmp_path / "deliverables").exists()


def test_bootstrap_handoff_does_not_invent_an_estimation_failure(tmp_path):
    state = tmp_path / ".runtime/replication_v2"
    result = handoff.write_failure_report(tmp_path, state, FileNotFoundError("R missing"), stage="preflight")
    assert result["unresolved_estimations"] == []
    assert "-ControleCourt" not in result["commands"]["normal"]
    message = (tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt").read_text(encoding="utf-8-sig")
    assert "-ReessayerEchecs" not in message
    assert "R missing" in message


def test_worker_handoff_preserves_exact_launcher_command(tmp_path, monkeypatch):
    state = tmp_path / ".runtime/replication_court"
    exact = ("powershell -ExecutionPolicy Bypass -File .\\REPRODUIRE_TOUT.ps1 "
             "-DossierDonneesBrutes 'D:\\donnees brutes' -ArchiveResultatsReference 'D:\\reference.zip' "
             "-PreflightSeulement -ControleCourt -LimiteKRTHeures 9")
    monkeypatch.setenv("LONGITUDINAL_RESUME_COMMAND", exact)
    result = handoff.write_failure_report(tmp_path, state, RuntimeError("fixture"), stage="preflight")
    assert result["commands"] == {
        "normal": exact,
        "retry_failed": exact + " -ReessayerEchecs",
    }
    assert result["commands_are_default_path_examples"] is False
    message = (tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt").read_text(encoding="utf-8-sig")
    assert "Commande exacte du lancement interrompu" in message
    assert "D:\\donnees brutes" in message


def test_corrupt_recovery_receipt_is_explicit_not_silently_ignored(tmp_path):
    state = tmp_path / ".runtime/replication_v2"
    path = receipt(state, [])
    path.write_text("not JSON", encoding="utf-8")
    result = handoff.write_failure_report(tmp_path, state, RuntimeError("fixture"))
    assert result["unresolved_estimations"][0]["classification"] == "receipt_invalid"


def test_successful_batch_is_not_reported_as_a_failure(tmp_path):
    state = tmp_path / ".runtime/replication_v2"
    receipt(state, [], status="complete")
    result = handoff.write_failure_report(tmp_path, state, RuntimeError("later report failure"), stage="report")
    assert result["unresolved_estimations"] == []


def test_certified_recovery_marks_old_error_resolved_without_deleting_history(tmp_path):
    state = tmp_path / ".runtime/replication_court"
    handoff.write_failure_report(tmp_path, state, ValueError("injected prior error"))
    handoff.resolve_failure_report(tmp_path, state, "equivalence_scientifique_perimetre_reduit")
    result = json.loads((tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.json").read_text(encoding="utf-8-sig"))
    assert result["status"] == "resolved_after_certification"
    assert result["message"] == "injected prior error"
    assert result["resolved_scope"] == "court"
    assert "ne certifie pas la campagne integrale" in (tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt").read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("failed_scope,certified_scope", [("replication_v2", "replication_court"),
                                                       ("replication_court", "replication_v2")])
def test_certification_does_not_resolve_a_different_scope_failure(tmp_path, failed_scope, certified_scope):
    handoff.write_failure_report(tmp_path, tmp_path / ".runtime" / failed_scope, ValueError("other scope failed"))
    paths = [tmp_path / "JOURNAUX_REPRODUCTION" / name
             for name in ("DERNIER_ECHEC.json", "DERNIER_ECHEC.txt")]
    before = [path.read_bytes() for path in paths]
    handoff.resolve_failure_report(tmp_path, tmp_path / ".runtime" / certified_scope, "fixture_certified")
    assert [path.read_bytes() for path in paths] == before


def test_failed_worker_writes_handoff_and_cannot_dispatch_deliverables(tmp_path):
    (tmp_path / "reproducibility").mkdir()
    (tmp_path / "reproducibility/requirements-python312.lock.txt").write_text("fixture", encoding="utf-8")
    state = tmp_path / ".runtime/replication_court"
    calls = []
    class FakeProcess:
        pid = 712345
        def __init__(self, returncode): self.returncode = returncode
        def wait(self, timeout=None): return self.returncode
        def poll(self): return self.returncode
        def kill(self): self.returncode = -9
    def dispatch(command, **kwargs):
        stage = command[-1]
        calls.append(stage)
        if stage == "krt240":
            receipt(state, [{"key": "fixture/B", "type": "ValueError", "message": "injected only"}])
            return FakeProcess(1), kwargs.get("job"), False
        return FakeProcess(0), kwargs.get("job"), False
    with patch.object(pipeline, "ROOT", tmp_path), patch.object(pipeline, "STATE_DIR", state), \
         patch.object(pipeline, "preflight", return_value={"raw": {"raw_dir": str(tmp_path), "fingerprint": "fixture"}}), \
         patch.object(pipeline, "configure"), patch.object(pipeline, "start_owned_process_tree", side_effect=dispatch):
        with pytest.raises(pipeline.ReplicationError, match="Arret a l'etape krt240"):
            pipeline.run_pipeline(tmp_path, "fixture_R", "fixture_browser")
    assert calls == ["panel", "prepare", "nls270", "krt240"]
    assert "package" not in calls
    assert (tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt").is_file()
    assert pipeline.read_json(state / "state.json")["status"] == "failed_or_interrupted"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell integration")
def test_actual_powershell_missing_python_produces_readable_failure_without_installing(tmp_path):
    # Copy only the launcher: absent Python must fail before data or science imports.
    launcher = tmp_path / "REPRODUIRE_TOUT.ps1"
    launcher.write_bytes((Path(pipeline.__file__).parents[1] / "REPRODUIRE_TOUT.ps1").read_bytes())
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
                             "-ControleCourt", "-PreflightSeulement", "-PythonExe", str(tmp_path / "missing_python.exe")],
                            cwd=tmp_path, capture_output=True, timeout=30)
    assert result.returncode != 0
    assert b"DERNIER_ECHEC.txt" in result.stdout + result.stderr
    assert b"KRT 24 h; NLS 120 min; NLS RxC 120 min" in result.stdout + result.stderr
    payload = json.loads((tmp_path / "JOURNAUX_REPRODUCTION/DERNIER_ECHEC.json").read_text(encoding="utf-8-sig"))
    assert payload["status"] == "launcher_failed"
    assert payload["scientific_certification"] is False
    assert "-PythonExe '" + str(tmp_path / "missing_python.exe") + "'" in payload["resume_command"]
    assert payload["resume_command"].endswith("-PreflightSeulement -ControleCourt")
    assert not (tmp_path / ".venv-reproduction").exists()
    assert not (tmp_path / "outputs").exists()


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe") or not shutil.which("py.exe"),
                    reason="Windows Python launcher integration")
def test_actual_powershell_rebuilds_interrupted_local_venv(tmp_path):
    probe = subprocess.run(["py.exe", "-3.12", "-I", "-c",
                            "import platform,struct; print(platform.python_version(), platform.machine(), struct.calcsize('P')*8)"],
                           capture_output=True, text=True, timeout=15)
    pip_probe = subprocess.run(["py.exe", "-3.12", "-I", "-m", "pip", "--version"],
                               capture_output=True, text=True, timeout=15)
    if probe.returncode or not probe.stdout.startswith("3.12.10 AMD64 64") or pip_probe.returncode:
        pytest.skip("Python 3.12.10 Windows x86-64 avec pip indisponible")
    launcher = tmp_path / "REPRODUIRE_TOUT.ps1"
    launcher.write_bytes((Path(pipeline.__file__).parents[1] / "REPRODUIRE_TOUT.ps1").read_bytes())
    partial = tmp_path / ".venv-reproduction"
    partial.mkdir()
    (partial / ".creation-in-progress").write_text("interrupted fixture", encoding="ascii")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher),
                             "-ControleCourt", "-PreflightSeulement"],
                            cwd=tmp_path, capture_output=True, timeout=90)
    # The copied launcher has no scientific package, so it must fail only after
    # replacing and validating the deliberately interrupted generated venv.
    assert result.returncode != 0
    assert not (partial / ".creation-in-progress").exists()
    python = partial / "Scripts/python.exe"
    assert python.is_file()
    check = subprocess.run([str(python), "-I", "-m", "pip", "--version"],
                           capture_output=True, timeout=20)
    assert check.returncode == 0
    assert b"reconstruction de .venv-reproduction" in result.stdout + result.stderr

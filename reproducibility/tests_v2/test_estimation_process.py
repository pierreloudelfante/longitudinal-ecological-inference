from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

import reproducibility.estimation_process as process_module
from reproducibility.estimation_process import (
    EstimationTimeoutError,
    OrphanRiskError,
    ResourceWaitTimeoutError,
    run_supervised,
    timeout_seconds,
)
from reproducibility.estimation_recovery import BatchEstimationError, execute_estimation_batch


def test_configured_timeout_must_be_positive(monkeypatch):
    monkeypatch.setenv("LONGITUDINAL_TIMEOUT_KRT_SECONDS", "17")
    assert timeout_seconds("krt") == 17
    monkeypatch.setenv("LONGITUDINAL_TIMEOUT_KRT_SECONDS", "0")
    with pytest.raises(ValueError, match="strictement positif"):
        timeout_seconds("krt")


def test_supervised_success_writes_terminal_heartbeat(tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    completed = run_supervised(
        [sys.executable, "-c", "print('ok', flush=True)"],
        family="nls", key="fixture", cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log", heartbeat_path=heartbeat,
        timeout=10, heartbeat_interval_seconds=0.05,
    )
    assert completed.returncode == 0
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["key"] == "fixture"
    assert "ok" in (tmp_path / "stdout.log").read_text(encoding="utf-8")


def test_timeout_kills_descendant_tree_and_is_durable(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii');"
        "time.sleep(60)"
    )
    heartbeat = tmp_path / "heartbeat.json"
    with pytest.raises(EstimationTimeoutError) as caught:
        run_supervised(
            [sys.executable, "-c", parent_code, str(child_pid_path)],
            family="krt", key="fixture-timeout", cwd=tmp_path,
            stdout_path=tmp_path / "stdout.log", heartbeat_path=heartbeat,
            timeout=1, heartbeat_interval_seconds=0.05,
        )
    assert caught.value.timeout_seconds == 1
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["status"] == "timeout"
    termination = payload["termination"]
    assert termination["tree_termination_requested"] is True
    assert termination["parent_terminated"] is True
    assert termination["tree_termination_confirmed"] is True
    if os.name == "nt":
        assert termination["job_object_assigned"] is True
        assert termination["job_terminate_succeeded"] is True
        assert termination["job_empty_confirmed"] is True
    child_pid = int(child_pid_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 5
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)


def test_timeout_receipt_requires_explicit_retry_and_does_not_loop(tmp_path):
    calls = []

    def timeout(_item):
        calls.append("called")
        raise EstimationTimeoutError(family="nls", key="A", timeout_seconds=3, pid=123)

    with pytest.raises(BatchEstimationError) as caught:
        execute_estimation_batch(
            [{"key": "A"}], batch_name="timeout fixture",
            key_fn=lambda item: item["key"], run=timeout,
            state_dir=tmp_path, retry_failed=False,
        )
    assert calls == ["called"]
    error = caught.value.report["errors"][0]
    assert error["classification"] == "timeout"
    assert error["timeout_seconds"] == 3
    assert error["attempts"] == 1

    calls.clear()
    with pytest.raises(BatchEstimationError):
        execute_estimation_batch(
            [{"key": "A"}], batch_name="timeout fixture",
            key_fn=lambda item: item["key"], run=timeout,
            state_dir=tmp_path, retry_failed=False,
        )
    assert calls == []


def test_resource_wait_expiry_is_systemic_and_aborts_before_next_pair(tmp_path):
    calls = []

    def run(item):
        calls.append(item["key"])
        if item["key"] == "first":
            raise ResourceWaitTimeoutError(
                resource="memoire_R", key="first", timeout_seconds=9,
            )
        return "must-not-run"

    with pytest.raises(BatchEstimationError) as caught:
        execute_estimation_batch(
            [{"key": "first"}, {"key": "second"}],
            batch_name="memory fixture", key_fn=lambda item: item["key"],
            run=run, state_dir=tmp_path,
        )
    assert calls == ["first"]
    error = caught.value.report["errors"][0]
    assert error["classification"] == "systemic"
    assert error["resource_wait_expired"] is True
    assert caught.value.report["items"][1]["status"] == "pending"


def test_real_cli_plan_accepts_every_timeout_override(tmp_path):
    root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable, "-m", "reproducibility.replication_complete", "plan",
        "--scope", "court", "--timeout-krt-seconds", "11",
        "--timeout-nls-seconds", "12", "--timeout-nls-rxc-seconds", "13",
        "--timeout-covariate-seconds", "14", "--timeout-king-r-seconds", "15",
    ]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "plan_checked_not_estimated"


def test_heartbeat_write_failure_kills_parent_and_descendant(tmp_path, monkeypatch):
    child_pid_path = tmp_path / "heartbeat-child.pid"
    observed_parent = []
    real_atomic = process_module._atomic_json

    def fail_first_heartbeat(path, payload):
        observed_parent.append(int(payload["pid"]))
        deadline = time.monotonic() + 3
        while not child_pid_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        raise OSError("injected heartbeat disk failure")

    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii');"
        "time.sleep(60)"
    )
    monkeypatch.setattr(process_module, "_atomic_json", fail_first_heartbeat)
    with pytest.raises(OSError, match="injected heartbeat"):
        run_supervised(
            [sys.executable, "-c", parent_code, str(child_pid_path)],
            family="nls", key="heartbeat-failure", cwd=tmp_path,
            stdout_path=tmp_path / "heartbeat-failure.log", timeout=30,
            heartbeat_interval_seconds=0.05,
        )
    monkeypatch.setattr(process_module, "_atomic_json", real_atomic)
    assert observed_parent and child_pid_path.is_file()
    pids = [observed_parent[0], int(child_pid_path.read_text(encoding="ascii"))]
    deadline = time.monotonic() + 5
    while any(psutil.pid_exists(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any(psutil.pid_exists(pid) for pid in pids)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_nonzero_parent_cannot_leave_a_live_descendant(tmp_path):
    child_pid_path = tmp_path / "nonzero-child.pid"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='ascii');"
        "time.sleep(0.2);sys.exit(7)"
    )
    heartbeat = tmp_path / "nonzero.json"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run_supervised(
            [sys.executable, "-c", parent_code, str(child_pid_path)],
            family="nls", key="nonzero-parent", cwd=tmp_path,
            stdout_path=tmp_path / "nonzero.log", heartbeat_path=heartbeat,
            timeout=10, heartbeat_interval_seconds=0.05,
        )
    assert caught.value.returncode == 7
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["termination"]["tree_termination_confirmed"] is True
    child_pid = int(child_pid_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 5
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_hard_killed_owner_cannot_leave_worker_tree(tmp_path):
    root = Path(__file__).resolve().parents[2]
    pids_path = tmp_path / "owned-tree.json"
    child_code = (
        "import json,pathlib,subprocess,sys,time,os;"
        "grand=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),grand.pid]),encoding='ascii');"
        "time.sleep(60)"
    )
    supervisor_code = (
        "import pathlib,sys,time;"
        "from reproducibility.estimation_process import WindowsKillOnCloseJob,start_owned_process_tree;"
        "job=WindowsKillOnCloseJob();"
        "process,_,_=start_owned_process_tree("
        "[sys.executable,'-c',sys.argv[2],sys.argv[1]],cwd=pathlib.Path.cwd(),job=job);"
        "time.sleep(60)"
    )
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_code, str(pids_path), child_code],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not pids_path.is_file() and time.monotonic() < deadline:
            if supervisor.poll() is not None:
                pytest.fail(f"owner helper exited before creating its tree: {supervisor.returncode}")
            time.sleep(0.05)
        assert pids_path.is_file()
        owned_pids = json.loads(pids_path.read_text(encoding="ascii"))
        assert all(psutil.pid_exists(pid) for pid in owned_pids)
        psutil.Process(supervisor.pid).kill()
        supervisor.wait(timeout=5)
        deadline = time.monotonic() + 8
        while any(psutil.pid_exists(pid) for pid in owned_pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not any(psutil.pid_exists(pid) for pid in owned_pids)
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=5)


def test_unconfirmed_tree_kill_is_orphan_risk_and_records_evidence(tmp_path, monkeypatch):
    heartbeat = tmp_path / "orphan-risk.json"
    real_terminate = process_module._terminate_process_tree

    def terminate_but_report_failure(process, *, grace_seconds=10.0, job=None):
        evidence = real_terminate(process, grace_seconds=grace_seconds, job=job)
        evidence.update(tree_termination_confirmed=False, taskkill_returncode=1,
                        taskkill_error="injected taskkill failure")
        return evidence

    monkeypatch.setattr(process_module, "_terminate_process_tree", terminate_but_report_failure)
    with pytest.raises(OrphanRiskError) as caught:
        run_supervised(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            family="nls", key="kill-not-proven", cwd=tmp_path,
            stdout_path=tmp_path / "orphan.log", heartbeat_path=heartbeat,
            timeout=1, heartbeat_interval_seconds=0.05,
        )
    assert caught.value.termination["taskkill_returncode"] == 1
    assert caught.value.termination["tree_termination_confirmed"] is False
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["status"] == "orphan_risk"
    assert payload["termination"]["taskkill_error"] == "injected taskkill failure"


def test_transient_heartbeat_replace_lock_retries_without_second_process(tmp_path, monkeypatch):
    launches = tmp_path / "launches.txt"
    real_replace = process_module.os.replace
    calls = []

    def transient_replace(source, destination):
        calls.append((source, destination))
        if len(calls) <= 2:
            error = OSError("injected sharing violation")
            error.winerror = 32
            raise error
        return real_replace(source, destination)

    monkeypatch.setattr(process_module.os, "replace", transient_replace)
    child = (
        "import pathlib,sys,time;"
        "p=pathlib.Path(sys.argv[1]);"
        "p.write_text((p.read_text() if p.exists() else '')+'one\\n',encoding='utf-8');"
        "time.sleep(0.2)"
    )
    completed = run_supervised(
        [sys.executable, "-c", child, str(launches)],
        family="covariate", key="replace-retry", cwd=tmp_path,
        stdout_path=tmp_path / "replace-retry.log", timeout=10,
        heartbeat_interval_seconds=0.05,
    )
    assert completed.returncode == 0
    assert len(calls) >= 3
    assert launches.read_text(encoding="utf-8").splitlines() == ["one"]


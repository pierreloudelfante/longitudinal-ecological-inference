"""Failure fixtures only: no scientific estimators, processes, or reference data."""
import errno
import json

import pytest

from reproducibility.estimation_recovery import BatchEstimationError, execute_estimation_batch


def execute(tmp_path, items, run, **kwargs):
    return execute_estimation_batch(items, batch_name="KRT / fixture", key_fn=lambda item: item["key"],
                                    run=run, state_dir=tmp_path, **kwargs)


def receipt(tmp_path):
    return json.loads(next((tmp_path / "estimation_batches").glob("*.json")).read_text(encoding="utf-8"))


def test_success_preserves_items_results_and_revalidates_on_resume(tmp_path):
    items = [{"key": ("pre_2022_r1", "H0A"), "settings": {"seed": 42, "draws": 2000}}]
    original = json.dumps(items)
    calls = []
    result = object()

    def run(item):
        assert item is items[0]
        calls.append(item)
        return result

    assert execute(tmp_path, items, run) == [result]
    assert execute(tmp_path, items, run) == [result]
    assert len(calls) == 2
    assert json.dumps(items) == original
    report = receipt(tmp_path)
    assert report["status"] == "complete" and not report["errors"]
    assert "settings" not in json.dumps(report)  # No scientific inputs copied.
    assert not list((tmp_path / "estimation_batches").glob("*.tmp"))


def test_permanent_failure_continues_and_is_not_retried_implicitly(tmp_path):
    items = [{"key": "bad"}, {"key": "good"}]
    calls = []

    def run(item):
        calls.append(item["key"])
        if item["key"] == "bad":
            raise ValueError("deterministic fixture error")
        return "actual success"

    for _ in range(2):
        with pytest.raises(BatchEstimationError) as caught:
            execute(tmp_path, items, run)
        error = caught.value.report["errors"][0]
        assert error == {"key": "bad", "type": "ValueError", "message": "deterministic fixture error",
                         "attempts": 1, "classification": "permanent", "next_action": error["next_action"]}
        assert caught.value.report_path.is_file()
    assert calls == ["bad", "good", "good"]


@pytest.mark.parametrize("error", [ConnectionError("reset"), TimeoutError("timeout"),
                                  OSError(errno.EAGAIN, "again"), OSError(errno.EBUSY, "busy"),
                                  OSError(errno.ETIMEDOUT, "timeout"), OSError(errno.ECONNRESET, "reset")])
def test_transient_once_then_success(tmp_path, error):
    calls = []

    def run(item):
        calls.append(item)
        if len(calls) == 1:
            raise error
        return 42

    assert execute(tmp_path, [{"key": "pair"}], run) == [42]
    row = receipt(tmp_path)["items"][0]
    assert row["attempts"] == 2 and row["history"][0]["error"]["classification"] == "transient"


@pytest.mark.parametrize("winerror", [32, 33])
def test_windows_sharing_violation_is_transient_even_as_permissionerror(tmp_path, winerror):
    error = PermissionError("sharing")
    error.winerror = winerror
    calls = []

    def run(item):
        calls.append(item)
        if len(calls) == 1:
            raise error
        return "ok"

    assert execute(tmp_path, [{"key": "pair"}], run) == ["ok"]
    assert len(calls) == 2


def test_repeated_transient_stops_at_two_and_explicit_retry_is_one_new_round(tmp_path):
    calls = []

    def run(item):
        calls.append(item)
        raise TimeoutError("still unavailable")

    for expected_calls, retry in [(2, False), (2, False), (4, True), (4, False)]:
        with pytest.raises(BatchEstimationError) as caught:
            execute(tmp_path, [{"key": "pair"}], run, retry_failed=retry)
        assert len(calls) == expected_calls
        assert caught.value.report["errors"][0]["attempts"] == expected_calls
    assert receipt(tmp_path)["items"][0]["round"] == 2


def test_explicit_retry_can_resolve_prior_failure(tmp_path):
    def fail(item):
        raise RuntimeError("not automatically retryable")

    with pytest.raises(BatchEstimationError):
        execute(tmp_path, [{"key": "pair"}], fail)
    assert execute(tmp_path, [{"key": "pair"}], lambda item: "fixed", retry_failed=True) == ["fixed"]
    assert receipt(tmp_path)["items"][0]["attempts"] == 2


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_interruption_propagates_and_consumes_attempt(tmp_path, exception):
    calls = []

    def run(item):
        calls.append(item)
        raise exception("stop")

    with pytest.raises(exception):
        execute(tmp_path, [{"key": "first"}, {"key": "next"}], run)
    assert len(calls) == 1
    assert receipt(tmp_path)["status"] == "interrupted"
    resumed = []
    with pytest.raises(BatchEstimationError) as caught:
        execute(tmp_path, [{"key": "first"}, {"key": "next"}], lambda item: resumed.append(item["key"]))
    assert resumed == ["next"]
    assert caught.value.report["errors"][0]["attempts"] == 1


def test_durable_inflight_attempt_survives_abrupt_crash(tmp_path):
    class SimulatedProcessDeath(BaseException):
        pass

    def crash(item):
        assert receipt(tmp_path)["items"][0]["attempts"] == 1  # Persisted before call.
        raise SimulatedProcessDeath()

    with pytest.raises(SimulatedProcessDeath):
        execute(tmp_path, [{"key": "pair"}], crash)
    with pytest.raises(BatchEstimationError) as caught:
        execute(tmp_path, [{"key": "pair"}], lambda item: pytest.fail("must not rerun"))
    assert caught.value.report["errors"][0]["type"] == "InterruptedAttempt"
    assert caught.value.report["errors"][0]["attempts"] == 1


@pytest.mark.parametrize("error", [MemoryError("oom"), PermissionError("denied"),
                                  OSError(errno.ENOSPC, "disk full")])
def test_systemic_failure_aborts_without_starting_other_items(tmp_path, error):
    calls = []

    def run(item):
        calls.append(item)
        raise error

    for _ in range(2):
        with pytest.raises(BatchEstimationError) as caught:
            execute(tmp_path, [{"key": "first"}, {"key": "not started"}], run)
        assert caught.value.report["status"] == "aborted"
        assert caught.value.report["errors"][0]["classification"] == "systemic"
    assert len(calls) == 1


def test_windows_disk_full_is_systemic(tmp_path):
    error = OSError("disk full")
    error.winerror = 112

    def run(item):
        raise error

    with pytest.raises(BatchEstimationError) as caught:
        execute(tmp_path, [{"key": "pair"}], run)
    assert caught.value.report["errors"][0]["classification"] == "systemic"


def test_duplicate_keys_and_changed_batch_selection_fail_before_calls(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        execute(tmp_path, [{"key": "same"}, {"key": "same"}], lambda item: pytest.fail("must not run"))
    execute(tmp_path, [{"key": "one"}], lambda item: None)
    with pytest.raises(ValueError, match="Incompatible"):
        execute(tmp_path, [{"key": "changed"}], lambda item: pytest.fail("must not run"))


@pytest.mark.parametrize("interrupt", [False, True])
def test_failure_receipt_disk_error_aborts_and_never_masks_interruption(tmp_path, monkeypatch, interrupt):
    from reproducibility import estimation_recovery as recovery
    original = recovery._atomic_json
    calls = []

    def disk_full_on_error(path, value):
        if value.get("errors"):
            raise OSError(errno.ENOSPC, "cannot save receipt")
        return original(path, value)

    def run(item):
        calls.append(item)
        if interrupt:
            raise KeyboardInterrupt("user stop")
        raise OSError(errno.ENOSPC, "actual model output disk full")

    monkeypatch.setattr(recovery, "_atomic_json", disk_full_on_error)
    with pytest.raises(KeyboardInterrupt if interrupt else BatchEstimationError) as caught:
        execute(tmp_path, [{"key": "first"}, {"key": "never called"}], run)
    assert len(calls) == 1
    previous = receipt(tmp_path)
    assert previous["items"][0]["status"] == "running"
    assert previous["items"][0]["attempts"] == 1
    if not interrupt:
        assert caught.value.report["status"] == "aborted"
        assert caught.value.report["errors"][0]["message"] == "[Errno 28] actual model output disk full"
        assert caught.value.report["receipt_write_error"]["type"] == "OSError"


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_atomic_receipt_retries_temporary_windows_replace_locks(tmp_path, monkeypatch, winerror):
    from reproducibility import estimation_recovery as recovery
    target = tmp_path / "receipt.json"
    recovery._atomic_json(target, {"old": True})
    original = recovery.os.replace
    calls, delays = [], []
    error = PermissionError("temporary Windows reader lock")
    error.winerror = winerror

    def replace(source, destination):
        calls.append((source, destination))
        assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
        if len(calls) < 3:
            raise error
        return original(source, destination)

    monkeypatch.setattr(recovery.os, "replace", replace)
    monkeypatch.setattr(recovery.time, "sleep", delays.append)
    recovery._atomic_json(target, {"new": True})
    assert len(calls) == 3 and delays == [0.05, 0.10]
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_persistent_replace_access_denied_raises_and_preserves_previous_receipt(tmp_path, monkeypatch):
    from reproducibility import estimation_recovery as recovery
    target = tmp_path / "receipt.json"
    recovery._atomic_json(target, {"old": True})
    error = PermissionError("persistent access denied")
    error.winerror = 5
    calls, delays = [], []

    def replace(source, destination):
        calls.append((source, destination))
        raise error

    monkeypatch.setattr(recovery.os, "replace", replace)
    monkeypatch.setattr(recovery.time, "sleep", delays.append)
    with pytest.raises(PermissionError) as caught:
        recovery._atomic_json(target, {"new": True})
    assert caught.value is error
    assert len(calls) == 5 and delays == [0.05, 0.10, 0.20, 0.40]
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_other_receipt_write_errors_are_not_retried(tmp_path, monkeypatch):
    from reproducibility import estimation_recovery as recovery
    calls = []

    def replace(source, destination):
        calls.append((source, destination))
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(recovery.os, "replace", replace)
    monkeypatch.setattr(recovery.time, "sleep", lambda delay: pytest.fail("must not retry"))
    with pytest.raises(OSError):
        recovery._atomic_json(tmp_path / "receipt.json", {})
    assert len(calls) == 1


def test_replace_failure_before_reserved_attempt_does_not_launch_estimation(tmp_path, monkeypatch):
    from reproducibility import estimation_recovery as recovery
    original = recovery.os.replace
    calls = []
    error = PermissionError("reservation cannot be committed")
    error.winerror = 5

    def replace(source, destination):
        calls.append((source, destination))
        if len(calls) > 1:  # The initial pending receipt exists, reservation does not.
            raise error
        return original(source, destination)

    monkeypatch.setattr(recovery.os, "replace", replace)
    monkeypatch.setattr(recovery.time, "sleep", lambda delay: None)
    with pytest.raises(PermissionError):
        execute(tmp_path, [{"key": "pair"}], lambda item: pytest.fail("scientific callable must not run"))
    assert len(calls) == 6
    row = receipt(tmp_path)["items"][0]
    assert row["status"] == "pending" and row["attempts"] == 0

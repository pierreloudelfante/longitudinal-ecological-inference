"""Bounded process supervision for one scientific estimation.

The timeout changes only orchestration.  The scientific command, inputs,
parameters, and random seeds remain owned by the existing estimator.  Each
estimation runs in its own process group so a timeout can terminate the whole
descendant tree instead of leaving Python, JAX, or R children behind.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Mapping, Sequence


DEFAULT_TIMEOUT_SECONDS = {
    # The historical KRT contract estimates at most 12 hours per fit.  A
    # 24-hour watchdog is deliberately conservative and only catches a hang.
    "krt": 24 * 60 * 60,
    "nls": 2 * 60 * 60,
    "nls_rxc": 2 * 60 * 60,
    "covariate": 60 * 60,
    "king_r": 12 * 60 * 60,
}
WINDOWS_CREATE_SUSPENDED = 0x00000004
ENVIRONMENT_BY_FAMILY = {
    "krt": "LONGITUDINAL_TIMEOUT_KRT_SECONDS",
    "nls": "LONGITUDINAL_TIMEOUT_NLS_SECONDS",
    "nls_rxc": "LONGITUDINAL_TIMEOUT_NLS_RXC_SECONDS",
    "covariate": "LONGITUDINAL_TIMEOUT_COVARIATE_SECONDS",
    "king_r": "LONGITUDINAL_TIMEOUT_KING_R_SECONDS",
}


class EstimationTimeoutError(TimeoutError):
    """One bounded estimation exceeded its declared wall-clock limit."""

    def __init__(self, *, family: str, key: str, timeout_seconds: int, pid: int):
        self.family = family
        self.key = key
        self.timeout_seconds = timeout_seconds
        self.pid = pid
        super().__init__(
            f"Estimation {family} {key} arretee apres {timeout_seconds} secondes "
            f"(PID {pid}); relance explicite avec -ReessayerEchecs requise."
        )


class ResourceWaitTimeoutError(RuntimeError):
    """A shared prerequisite stayed unavailable; continuing would repeat it."""

    def __init__(self, *, resource: str, key: str, timeout_seconds: int):
        self.resource = resource
        self.key = key
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Ressource {resource} indisponible pendant {timeout_seconds} secondes "
            f"avant {key}; liberer la ressource puis relancer avec -ReessayerEchecs."
        )


class OrphanRiskError(RuntimeError):
    """The supervisor could not prove that an estimator tree was terminated."""

    def __init__(self, *, family: str, key: str, pid: int, termination: dict):
        self.family = family
        self.key = key
        self.pid = pid
        self.termination = termination
        super().__init__(
            f"Risque de processus orphelin apres {family} {key} (PID {pid}); "
            "verifier et arreter les processus Python/R associes avant toute relance."
        )


class WindowsKillOnCloseJob:
    """Own a Windows process tree and kill every member when the handle closes.

    Children are assigned while suspended by :func:`start_owned_process_tree`,
    so they cannot create an unowned R/JAX/Python descendant first.  The class
    is instantiated only on Windows; keeping it here avoids another runtime
    dependency or an opaque launcher layer.
    """

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    ERROR_ALREADY_EXISTS = 183
    PROCESS_TERMINATE = 0x0001
    PROCESS_SET_QUOTA = 0x0100

    def __init__(self, *, name: str | None = None, reject_existing: bool = False):
        if os.name != "nt":
            raise OSError("Les Job Objects sont disponibles uniquement sous Windows")
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        handle = kernel32.CreateJobObjectW(None, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        existed = ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS
        if reject_existing and existed:
            kernel32.CloseHandle(handle)
            raise RuntimeError(
                "Une reproduction portant le meme verrou Windows est deja active dans cette extraction."
            )
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle, self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information), ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            raise ctypes.WinError(error)
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._accounting_type = BasicAccountingInformation
        self._handle = handle
        self.name = name

    @property
    def closed(self) -> bool:
        return self._handle is None

    def assign(self, pid: int) -> None:
        if self.closed:
            raise RuntimeError("Job Object deja ferme")
        process_handle = self._kernel32.OpenProcess(
            self.PROCESS_TERMINATE | self.PROCESS_SET_QUOTA, False, int(pid),
        )
        if not process_handle:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        try:
            if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
        finally:
            self._kernel32.CloseHandle(process_handle)

    def active_processes(self) -> int:
        if self.closed:
            raise RuntimeError("Job Object deja ferme")
        information = self._accounting_type()
        returned = self._ctypes.c_ulong(0)
        if not self._kernel32.QueryInformationJobObject(
            self._handle, self.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            self._ctypes.byref(information), self._ctypes.sizeof(information),
            self._ctypes.byref(returned),
        ):
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        return int(information.ActiveProcesses)

    def terminate(self, exit_code: int = 1) -> bool:
        if self.closed:
            return False
        return bool(self._kernel32.TerminateJobObject(self._handle, int(exit_code)))

    def wait_empty(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if self.active_processes() == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def close(self) -> None:
        if not self.closed:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
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


def timeout_seconds(family: str) -> int:
    """Return a positive configured timeout for a known estimation family."""
    if family not in DEFAULT_TIMEOUT_SECONDS:
        raise ValueError(f"Famille de delai inconnue: {family}")
    name = ENVIRONMENT_BY_FAMILY[family]
    raw = os.environ.get(name, str(DEFAULT_TIMEOUT_SECONDS[family])).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} doit etre un entier positif; observe: {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} doit etre strictement positif; observe: {value}")
    return value


def start_owned_process_tree(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str] | None = None,
    stdout=None, stderr=None, text: bool = True,
    job: WindowsKillOnCloseJob | None = None,
) -> tuple[subprocess.Popen, WindowsKillOnCloseJob | None, bool]:
    """Start a process that cannot escape its Windows owner before assignment."""
    owns_job = False
    if os.name == "nt":
        import psutil
        owner = job
        if owner is None:
            owner = WindowsKillOnCloseJob()
            owns_job = True
        process = None
        try:
            process = subprocess.Popen(
                [str(part) for part in command], cwd=cwd,
                env=dict(environment) if environment is not None else None,
                stdout=stdout, stderr=stderr, text=text,
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | WINDOWS_CREATE_SUSPENDED),
            )
            owner.assign(process.pid)
            psutil.Process(process.pid).resume()
            return process, owner, owns_job
        except BaseException:
            if owner is not None:
                try:
                    owner.terminate()
                    owner.wait_empty(5.0)
                except BaseException:
                    pass
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if owns_job and owner is not None:
                owner.close()
            raise
    process = subprocess.Popen(
        [str(part) for part in command], cwd=cwd,
        env=dict(environment) if environment is not None else None,
        stdout=stdout, stderr=stderr, text=text, start_new_session=True,
    )
    return process, None, False


def _terminate_process_tree(
    process: subprocess.Popen, *, grace_seconds: float = 10.0,
    job: WindowsKillOnCloseJob | None = None,
) -> dict:
    """Best-effort termination of the complete process tree on Windows/POSIX."""
    result = {
        "platform": "windows" if os.name == "nt" else "posix",
        "pid": process.pid,
        "tree_termination_requested": True,
        "taskkill_returncode": None,
        "taskkill_error": None,
        "parent_kill_fallback_requested": False,
        "job_object_assigned": job is not None,
        "job_active_before": None,
        "job_terminate_succeeded": None,
        "job_empty_confirmed": None,
    }
    already_finished = process.poll() is not None
    result["already_finished"] = already_finished
    if os.name == "nt" and job is not None:
        try:
            active = job.active_processes()
            result["job_active_before"] = active
            result["job_terminate_succeeded"] = True if active == 0 else job.terminate()
            result["job_empty_confirmed"] = job.wait_empty(grace_seconds)
        except BaseException as exc:
            result["taskkill_error"] = f"JobObject {type(exc).__name__}: {exc}"
            result["job_empty_confirmed"] = False
        try:
            process.wait(timeout=max(1.0, grace_seconds))
        except subprocess.TimeoutExpired:
            pass
        parent_terminated = process.poll() is not None
        result.update(parent_returncode=process.returncode, parent_terminated=parent_terminated)
        result["tree_termination_confirmed"] = bool(
            result["job_terminate_succeeded"] and result["job_empty_confirmed"]
            and parent_terminated
        )
        return result
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=max(1.0, grace_seconds),
            )
            result["taskkill_returncode"] = completed.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["taskkill_error"] = f"{type(exc).__name__}: {exc}"
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    if process.poll() is None:
        try:
            result["parent_kill_fallback_requested"] = True
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=max(1.0, grace_seconds))
    except subprocess.TimeoutExpired:
        pass
    parent_terminated = process.poll() is not None
    result.update(parent_returncode=process.returncode, parent_terminated=parent_terminated)
    if os.name == "nt":
        result["tree_termination_confirmed"] = bool(
            result["taskkill_returncode"] == 0 and parent_terminated
        )
    else:
        result["tree_termination_confirmed"] = parent_terminated
    return result


def run_supervised(
    command: Sequence[str], *, family: str, key: str, cwd: Path,
    stdout_path: Path, stderr_path: Path | None = None,
    environment: Mapping[str, str] | None = None,
    timeout: int | None = None, heartbeat_path: Path | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> subprocess.CompletedProcess:
    """Run exactly one estimator with a deadline and durable heartbeat."""
    seconds = timeout_seconds(family) if timeout is None else int(timeout)
    if seconds <= 0:
        raise ValueError("Le delai d'estimation doit etre strictement positif")
    interval = heartbeat_interval_seconds
    if interval is None:
        interval = float(os.environ.get("LONGITUDINAL_HEARTBEAT_SECONDS", "30"))
    if interval <= 0:
        raise ValueError("LONGITUDINAL_HEARTBEAT_SECONDS doit etre strictement positif")
    heartbeat = heartbeat_path or stdout_path.with_suffix(stdout_path.suffix + ".heartbeat.json")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if stderr_path is not None:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started_monotonic = time.monotonic()
    started_at = _utc_now()
    stderr_target = subprocess.STDOUT if stderr_path is None else None
    with stdout_path.open("a", encoding="utf-8") as stdout:
        stderr_stream = None
        process = None
        tree_job = None
        owns_tree_job = False
        try:
            if stderr_path is not None:
                stderr_stream = stderr_path.open("a", encoding="utf-8")
                stderr_target = stderr_stream
            process, tree_job, owns_tree_job = start_owned_process_tree(
                command, cwd=cwd, environment=environment,
                stdout=stdout, stderr=stderr_target, text=True,
            )
            termination_evidence = None
            next_heartbeat = 0.0
            while True:
                returncode = process.poll()
                elapsed = time.monotonic() - started_monotonic
                if elapsed >= next_heartbeat:
                    _atomic_json(heartbeat, {
                        "schema_version": "estimation_heartbeat_v1",
                        "status": "running" if returncode is None else "finished",
                        "family": family, "key": key, "pid": process.pid,
                        "started_at_utc": started_at, "updated_at_utc": _utc_now(),
                        "elapsed_seconds": round(elapsed, 3),
                        "timeout_seconds": seconds,
                        "stdout": str(stdout_path),
                        "stderr": str(stderr_path) if stderr_path is not None else str(stdout_path),
                    })
                    next_heartbeat = elapsed + interval
                if returncode is not None:
                    terminal_status = "success" if returncode == 0 else "failed"
                    if os.name == "nt" and tree_job is not None:
                        # A direct child exit is not proof that its descendants
                        # exited.  A nonzero child is drained immediately; a
                        # successful child must leave an empty Job Object.
                        if returncode != 0:
                            termination_evidence = _terminate_process_tree(
                                process, job=tree_job,
                            )
                        elif not tree_job.wait_empty(1.0):
                            termination_evidence = _terminate_process_tree(
                                process, job=tree_job,
                            )
                            terminal_status = "orphan_risk"
                    _atomic_json(heartbeat, {
                        "schema_version": "estimation_heartbeat_v1", "status": terminal_status,
                        "family": family, "key": key, "pid": process.pid,
                        "started_at_utc": started_at, "finished_at_utc": _utc_now(),
                        "elapsed_seconds": round(elapsed, 3), "timeout_seconds": seconds,
                        "returncode": returncode, "stdout": str(stdout_path),
                        "stderr": str(stderr_path) if stderr_path is not None else str(stdout_path),
                        **({"termination": termination_evidence} if termination_evidence is not None else {}),
                    })
                    if termination_evidence is not None and not termination_evidence["tree_termination_confirmed"]:
                        raise OrphanRiskError(
                            family=family, key=key, pid=process.pid,
                            termination=termination_evidence,
                        )
                    if terminal_status == "orphan_risk":
                        raise RuntimeError(
                            f"Estimation {family} {key}: le processus direct a reussi "
                            "mais a laisse un descendant actif; arbre arrete, sortie refusee."
                        )
                    if returncode != 0:
                        raise subprocess.CalledProcessError(returncode, [str(part) for part in command])
                    return subprocess.CompletedProcess([str(part) for part in command], returncode)
                if elapsed >= seconds:
                    termination_evidence = _terminate_process_tree(process, job=tree_job)
                    termination_status = ("timeout" if termination_evidence["tree_termination_confirmed"]
                                          else "orphan_risk")
                    _atomic_json(heartbeat, {
                        "schema_version": "estimation_heartbeat_v1", "status": termination_status,
                        "family": family, "key": key, "pid": process.pid,
                        "started_at_utc": started_at, "finished_at_utc": _utc_now(),
                        "elapsed_seconds": round(elapsed, 3), "timeout_seconds": seconds,
                        "termination": termination_evidence,
                        "stdout": str(stdout_path),
                        "stderr": str(stderr_path) if stderr_path is not None else str(stdout_path),
                    })
                    if not termination_evidence["tree_termination_confirmed"]:
                        raise OrphanRiskError(
                            family=family, key=key, pid=process.pid,
                            termination=termination_evidence,
                        )
                    raise EstimationTimeoutError(
                        family=family, key=key, timeout_seconds=seconds, pid=process.pid,
                    )
                time.sleep(min(1.0, interval))
        except BaseException as exc:
            # No supervisor-side error may orphan a still-running estimator.
            # This includes receipt/heartbeat I/O failures, KeyboardInterrupt,
            # and unexpected programming errors after Popen succeeded.
            if process is not None:
                evidence = (termination_evidence if "termination_evidence" in locals()
                            and termination_evidence is not None
                            else _terminate_process_tree(process, job=tree_job))
                if not evidence["tree_termination_confirmed"] and not isinstance(exc, OrphanRiskError):
                    raise OrphanRiskError(
                        family=family, key=key, pid=process.pid, termination=evidence,
                    ) from exc
            raise
        finally:
            if stderr_stream is not None:
                stderr_stream.close()
            if owns_tree_job and tree_job is not None:
                tree_job.close()


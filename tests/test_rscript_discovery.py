from __future__ import annotations

from pathlib import Path

import pytest

from code_longitudinal import run_r_king_ei_replication, run_r_nls_replication


@pytest.mark.parametrize(
    "module",
    (run_r_king_ei_replication, run_r_nls_replication),
)
def test_rscript_can_be_configured_by_environment(module, monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "Rscript.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("LONGITUDINAL_RSCRIPT", str(executable))
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    assert module._rscript_path() == executable.resolve()


def test_invalid_configured_rscript_is_explicit(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing-Rscript.exe"
    monkeypatch.setenv("LONGITUDINAL_RSCRIPT", str(missing))
    with pytest.raises(FileNotFoundError, match="LONGITUDINAL_RSCRIPT"):
        run_r_nls_replication._rscript_path()

from __future__ import annotations

from pathlib import Path

import pytest

from code_longitudinal.build_production_code_bundle_v101 import (
    EXPECTED_MODULES,
    PRODUCTION_ENTRYPOINTS,
    REPLICATION_ENTRYPOINTS,
    _safe_replace_directory,
    production_dependency_closure,
)


def test_production_bundle_dependency_closure_is_explicit_and_minimal() -> None:
    closure = production_dependency_closure()
    assert closure == EXPECTED_MODULES
    assert len(closure) == 31
    assert set(PRODUCTION_ENTRYPOINTS).issubset(closure)
    assert set(REPLICATION_ENTRYPOINTS).issubset(closure)
    assert not any("professor" in module for module in closure)
    assert not any("priority_results_3000" in module for module in closure)


def test_bundle_replacement_rejects_unexpected_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unexpected bundle path"):
        _safe_replace_directory(tmp_path / "not-the-production-bundle")

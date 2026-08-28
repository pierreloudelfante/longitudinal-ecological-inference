from __future__ import annotations

import pytest

from code_longitudinal.h23_supervisor import _memory_headroom_to_limit_mb


def test_memory_headroom_enforces_global_eighty_percent_ceiling() -> None:
    # 16 GB total and 4 GB available means 75% is already used. Only 0.8 GB
    # may be added before reaching the registered 80% ceiling.
    assert _memory_headroom_to_limit_mb(total_mb=16_000.0, available_mb=4_000.0) == pytest.approx(800.0)


def test_memory_headroom_is_zero_above_ceiling() -> None:
    assert _memory_headroom_to_limit_mb(total_mb=16_000.0, available_mb=2_000.0) == 0.0

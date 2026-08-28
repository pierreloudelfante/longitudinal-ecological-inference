from __future__ import annotations

import pandas as pd
import pytest

from code_longitudinal.run_rxc_panel_extension_v11 import DEFAULT_AUDIT, eligible_deferred_pairs


def test_authoritative_audit_selects_exactly_22_safe_pairs() -> None:
    audit = pd.read_csv(DEFAULT_AUDIT, dtype={"unit_id": "string"})
    pairs = eligible_deferred_pairs(audit)

    assert len(pairs) == 22
    assert len({election_id for election_id, _ in pairs}) == 11
    assert {scenario_id for _, scenario_id in pairs} == {"RXC1", "RXC2"}


@pytest.mark.parametrize(
    ("column", "unsafe_value"),
    [
        ("in_panel_2000", True),
        ("panel_raw_closure_within_tolerance", False),
        ("panel_model_ready_exact_closure", False),
        ("mapping_status", "mapping_error"),
        ("panel_scope_assessment", "inadmissible"),
        ("execution_status", "not_audited"),
    ],
)
def test_audit_rejects_any_unsafe_state(column: str, unsafe_value: object) -> None:
    audit = pd.read_csv(DEFAULT_AUDIT, dtype={"unit_id": "string"})
    audit.loc[audit.index[0], column] = unsafe_value

    with pytest.raises(ValueError, match="unsafe or ambiguous"):
        eligible_deferred_pairs(audit)


def test_audit_rejects_missing_pair() -> None:
    audit = pd.read_csv(DEFAULT_AUDIT, dtype={"unit_id": "string"}).iloc[:-1].copy()

    with pytest.raises(ValueError, match="exactly 22"):
        eligible_deferred_pairs(audit)

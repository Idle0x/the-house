"""F3 ScarCompiler tests (03-FEATURES F3).

test_repeated_failure_compiles_policy — 3 same-class failures → REFERENCE rule.
test_fresh_session_applies_cited_policy — new process, same route → hardened
action applies, response carries scar_cited.
test_deletion_f3 — SIBYL_DISABLED=1 → the same 3 failures compile nothing.
"""
import os
import uuid

import pytest

from core.memory import HouseMemory
from core.scars import ScarCompiler, SCAR_COMPILE_N, ACTIONS

ROUTE = "/intel/upstream"
FAIL = "5xx upstream timeout"


def _fresh(db_suffix: str = "") -> tuple[HouseMemory, ScarCompiler]:
    db = f"/tmp/house_f3_{db_suffix}_{uuid.uuid4().hex}.db"
    m = HouseMemory(db)
    return m, ScarCompiler(m)


def test_three_failures_below_threshold_no_policy():
    m, c = _fresh()
    for _ in range(SCAR_COMPILE_N - 1):
        c.record(ROUTE, FAIL, "provider timed out")
    rules = c.compile()
    assert rules == []
    assert c.active_rules() == {}


def test_repeated_failure_compiles_policy():
    m, c = _fresh()
    sids = [c.record(ROUTE, FAIL, "provider timed out") for _ in range(SCAR_COMPILE_N)]
    changed = c.compile()
    assert len(changed) == 1
    rule = c.active_rules()[changed[0]]
    assert rule["match"] == {"route": ROUTE, "failure_class": FAIL}
    assert rule["source_scar"] == sids[-1]  # most recent scar cited
    assert rule["action"] in ACTIONS
    # policy_delta stamped on the scars
    scar = m.get_entity("scar", sids[0])
    assert scar["policy_delta"]["rule_id"] == changed[0]


def test_fresh_session_applies_cited_policy():
    """New process (new memory client, same db) → hardened action applies."""
    db = f"/tmp/house_f3_fresh_{uuid.uuid4().hex}.db"
    m1 = HouseMemory(db)
    c = ScarCompiler(m1)
    for _ in range(SCAR_COMPILE_N):
        c.record(ROUTE, FAIL, "provider timed out")
    c.compile()

    # Fresh session: brand-new compiler/client over the same db.
    m2 = HouseMemory(db)
    c2 = ScarCompiler(m2)
    rule = c2.apply_policy(ROUTE, FAIL)
    assert rule is not None
    assert rule["action"] == "switch_upstream"
    assert rule["source_scar"].startswith("S-")
    # The response "cites the scar": apply_policy returns source_scar.
    assert rule["source_scar"] is not None


def test_policy_lapses_after_until():
    m, c = _fresh()
    for _ in range(SCAR_COMPILE_N):
        c.record(ROUTE, FAIL, "provider timed out")
    c.compile()
    # Advance time past the 24h sunset.
    future = __import__("time").time() + 25 * 3600
    assert c.apply_policy(ROUTE, FAIL, now=future) is None


def test_deletion_f3():
    """Deletion: the same 3 failures compile NOTHING; mistake repeats."""
    db = f"/tmp/house_f3_del_{uuid.uuid4().hex}.db"
    m, c = _fresh()
    # Build 3 scars with memory ON.
    for _ in range(SCAR_COMPILE_N):
        c.record(ROUTE, FAIL, "provider timed out")
    c.compile()
    assert len(c.active_rules()) == 1

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m_off = HouseMemory(db)
        c_off = ScarCompiler(m_off)
        # No policy survives, no new policy compiles, no rule applies.
        assert c_off.active_rules() == {}
        assert c_off.compile() == []
        assert c_off.apply_policy(ROUTE, FAIL) is None
        # A fresh failure records nothing.
        sid = c_off.record(ROUTE, FAIL, "again")
        assert m_off.get_entity("scar", sid) is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

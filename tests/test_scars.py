"""F3 ScarCompiler (03-FEATURES F3) — compile, apply, lapse, deletion — plus
the SERVE PATH where the compiled actions ACT (audit: switch_upstream /
retry_budget=0 were cosmetic; now they rotate a persisted upstream / refuse a
remembered failure).
"""
import os
import time
import uuid

from core.memory import HouseMemory
from core.scars import ScarCompiler, SCAR_COMPILE_N, ACTIONS

ROUTE = "/intel/upstream"
FAIL = "5xx upstream timeout"


def _fresh(db_suffix: str = "") -> tuple[HouseMemory, ScarCompiler]:
    db = f"/tmp/house_f3_{db_suffix}_{uuid.uuid4().hex}.db"
    m = HouseMemory(db)
    return m, ScarCompiler(m)


def test_three_failures_compile_policy_fresh_session_applies_and_lapses(tmp_path):
    """3 same-class failures (SCAR_COMPILE_N) compile exactly one REFERENCE
    rule citing the most-recent scar; below threshold nothing compiles; a
    FRESH session over the same db applies the rule (the hardening survives a
    restart); the rule lapses after its 24h sunset. THE GATE: SIBYL_DISABLED —
    the same 3 failures compile NOTHING, no rule applies, and a fresh failure
    records nothing (the mistake repeats)."""
    m, c = _fresh()
    for _ in range(SCAR_COMPILE_N - 1):
        c.record(ROUTE, FAIL, "provider timed out")
    assert c.compile() == [] and c.active_rules() == {}

    db = f"/tmp/house_f3_pol_{uuid.uuid4().hex}.db"
    m1 = HouseMemory(db)
    c1 = ScarCompiler(m1)
    sids = [c1.record(ROUTE, FAIL, "provider timed out") for _ in range(SCAR_COMPILE_N)]
    changed = c1.compile()
    assert len(changed) == 1
    rule = c1.active_rules()[changed[0]]
    assert rule["match"] == {"route": ROUTE, "failure_class": FAIL}
    assert rule["source_scar"] == sids[-1] and rule["action"] in ACTIONS
    assert m1.get_entity("scar", sids[0])["policy_delta"]["rule_id"] == changed[0]

    # Fresh session (new client, same db) applies it.
    c2 = ScarCompiler(HouseMemory(db))
    r2 = c2.apply_policy(ROUTE, FAIL)
    assert r2 is not None and r2["action"] == "switch_upstream"
    assert r2["source_scar"].startswith("S-")
    # Lapses after the 24h sunset.
    assert c2.apply_policy(ROUTE, FAIL, now=time.time() + 25 * 3600) is None

    # THE GATE: deletion — record + compile live (1 rule proves the scars WOULD
    # compile), then memory off: a FRESH (disabled) client over the same db
    # sees nothing, compiles nothing, and a fresh failure records nothing —
    # the mistake repeats.
    db_del = f"/tmp/house_f3_del_{uuid.uuid4().hex}.db"
    m_live = HouseMemory(db_del)
    c_live = ScarCompiler(m_live)
    for _ in range(SCAR_COMPILE_N):
        c_live.record(ROUTE, FAIL, "provider timed out")
    c_live.compile()
    assert len(c_live.active_rules()) == 1  # live: it compiles

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m_off = HouseMemory(db_del)  # FRESH + disabled (constructed after env)
        c_off = ScarCompiler(m_off)
        assert c_off.active_rules() == {}
        assert c_off.compile() == []
        assert c_off.apply_policy(ROUTE, FAIL) is None
        sid = c_off.record(ROUTE, FAIL, "again")
        assert m_off.get_entity("scar", sid) is None  # read via the disabled mem
    finally:
        os.environ.pop("SIBYL_DISABLED", None)


# --------------------------------------------------------------------------- #
# F3 in the SERVE PATH — the actions ACT, not decorate                        #
# --------------------------------------------------------------------------- #
def _flaky(payer: str) -> dict:
    raise TimeoutError("5xx upstream timeout")


def _healthy(payer: str) -> dict:
    return {"intel": "secondary answer", "src": "secondary"}


def test_failover_escapes_failing_primary_persists_and_deletion_repeats(tmp_path):
    """A compiled switch_upstream rule + a flaky primary: the serve escapes to
    the healthy secondary (200 + scar_cited + switched_upstream) and the
    switch PERSISTS — a fresh session inherits it. With a single upstream the
    switch is an honest no-op (still 502 + scar). THE GATE: SIBYL_DISABLED →
    no state, no rotation — the flaky primary is re-hit and 502s, and no
    failed-fp state is persisted (the mistake repeats)."""
    from core.house import House
    db = f"/tmp/house_f3_serve_{uuid.uuid4().hex}.db"
    h1 = House(HouseMemory(db), base_price=0.01,
               do_work=_flaky, do_work_secondary=_healthy)
    for _ in range(SCAR_COMPILE_N):
        h1.scars.record("/intel/quote", "5xx upstream timeout", "provider down")
    h1.scars.compile()

    st, body = h1.serve_intel("0x" + "1" * 40, {"q": "p1"})
    assert st == 200, f"failover must serve 200, got {st}: {body}"
    assert body["upstream"] == "secondary" and body.get("src") == "secondary"
    assert body.get("scar_cited") and body.get("switched_upstream")

    h2 = House(HouseMemory(db), base_price=0.01,
               do_work=_flaky, do_work_secondary=_healthy)
    assert h2._active_upstream_name() == "secondary"
    assert h2.serve_intel("0x" + "1" * 40, {"q": "p2"})[1]["upstream"] == "secondary"

    solo = House(HouseMemory(f"/tmp/house_f3_solo_{uuid.uuid4().hex}.db"),
                 base_price=0.01, do_work=_flaky)
    st, body = solo.serve_intel("0x" + "1" * 40, {"q": "solo"})
    assert st == 502 and body.get("failure_class")
    assert solo._active_upstream_name() == "primary"

    # THE GATE: deletion — no state, no rotation, no failover.
    db_del = f"/tmp/house_f3_del_serve_{uuid.uuid4().hex}.db"
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        h = House(HouseMemory(db_del), base_price=0.01,
                  do_work=_flaky, do_work_secondary=_healthy)
        st, body = h.serve_intel("0x" + "1" * 40, {"q": "del"})
        assert st == 502, "deletion must not persist/harden — the mistake repeats"
        assert h.m.get_state("failed_fps") is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)


def test_retry_budget_zero_refuses_failed_fingerprint_then_heals(tmp_path):
    """A compiled retry_budget=0 rule refuses (403, citing the source scar) a
    fingerprint the house REMEMBERS as failed, before doing the work again; a
    DIFFERENT fp is not blocked; a successful serve heals the failed fp."""
    from core.house import House
    from core.dedup import fingerprint
    h = House(HouseMemory(f"/tmp/house_f3_budget_{uuid.uuid4().hex}.db"),
              base_price=0.01)
    h.m.set_reference("policy", {
        "R-intel_quote-exception_Broken": {
            "match": {"route": "/intel/quote", "failure_class": "exception:Broken"},
            "action": "retry_budget=0",
            "until": time.time() + 3600,
            "source_scar": "S-abc123",
        },
    })
    fp = fingerprint("/intel/quote", {"q": "broken"})
    h.note_failed_fp(fp)
    st, body = h.serve_intel("0x" + "1" * 40, {"q": "broken"})
    assert st == 403, f"retry_budget=0 must refuse a failed fp, got {st}"
    assert body.get("scar_cited") == "S-abc123"
    assert h.serve_intel("0x" + "1" * 40, {"q": "fresh"})[0] == 200

    hp = House(HouseMemory(f"/tmp/house_f3_heal_{uuid.uuid4().hex}.db"),
               base_price=0.01)
    hfp = fingerprint("/intel/quote", {"q": "x"})
    hp.note_failed_fp(hfp)
    hp.serve_intel("0x" + "1" * 40, {"q": "x"})
    assert not hp.fp_has_failed(hfp)

"""F4 JobStateMachine tests (03-FEATURES F4).

test_kill_mid_serve_resumes — job persisted at phase=serving, "process dies"
(new client over same db = restart), resume_all() → settle called once.
test_no_double_charge_on_resume — settle() twice = one onchain settlement.
test_deletion_f4 — memory off after kill → restart has no job state.
"""
import os
import uuid

import pytest

from core.jobs import TERMINAL, JobStateMachine, job_id
from core.memory import HouseMemory

CALLER = "0x" + "F" * 40
ROUTE = "/intel/quote"
FP = "fp-intel-quote"


def _mk(db: str) -> tuple[HouseMemory, JobStateMachine]:
    m = HouseMemory(db)
    return m, JobStateMachine(m)


def test_kill_mid_serve_resumes():
    """Process A: start + advance to serving. Process B (restart): resume."""
    db = f"/tmp/house_f4_{uuid.uuid4().hex}.db"

    m1, sm1 = _mk(db)
    job = sm1.start(CALLER, ROUTE, FP)
    jid = job["id"]
    sm1.advance(jid, "serving", step="fetch", payment_state="verified")
    # "kill -9": process gone, state persisted in the db.

    # Restart: brand-new client + machine over the same db.
    m2, sm2 = _mk(db)
    resumed = sm2.resume_all()
    assert len(resumed) == 1
    assert resumed[0]["id"] == jid
    assert resumed[0]["phase"] == "serving"  # picked up mid-flight

    # Complete the serve (deliver while still serving) then settle exactly once.
    sm2.advance(jid, "serving", step="deliver")
    out = sm2.settle(jid, CALLER)
    assert out["phase"] == "settled"
    assert out["payment_state"] == "settled"
    assert out["settle_attempts"] == 1


def test_no_double_charge_on_resume():
    """settle() twice (resume race) → exactly one settlement."""
    db = f"/tmp/house_f4_idem_{uuid.uuid4().hex}.db"
    m, sm = _mk(db)
    job = sm.start(CALLER, ROUTE, FP)
    jid = job["id"]
    sm.settle(jid, CALLER)
    second = sm.settle(jid, CALLER)  # resumed duplicate call
    assert second["settle_attempts"] == 1  # no-op, no second charge


def test_job_id_deterministic_per_attempt():
    a = job_id(CALLER, ROUTE, FP, 1)
    b = job_id(CALLER, ROUTE, FP, 1)
    c = job_id(CALLER, ROUTE, FP, 2)
    assert a == b
    assert a != c


def test_fail_creates_new_attempt():
    db = f"/tmp/house_f4_fail_{uuid.uuid4().hex}.db"
    m, sm = _mk(db)
    job = sm.start(CALLER, ROUTE, FP)
    jid = job["id"]
    retry = sm.fail(jid, "upstream 5xx")
    assert retry["attempt"] == 2
    assert retry["id"] != jid
    # Original stays failed-able; retry is a fresh job row.
    assert sm.get(retry["id"])["attempt"] == 2


def test_failed_original_is_terminal_no_zombie():
    """C4 fix: fail() marks the original job FAILED (terminal) so
    resume_all never resurrects a failed attempt alongside its retry."""
    db = f"/tmp/house_f4_zombie_{uuid.uuid4().hex}.db"
    m, sm = _mk(db)
    job = sm.start(CALLER, ROUTE, FP)
    jid = job["id"]
    sm.advance(jid, "serving", step="fetch", payment_state="verified")
    retry = sm.fail(jid, "upstream 5xx")

    # Original is terminal (failed), NOT serving anymore.
    orig = sm.get(jid)
    assert orig is not None and orig["phase"] == "failed"
    assert orig["phase"] in TERMINAL
    # pending_count counts only the live retry, not the corpse.
    assert sm.pending_count() == 1
    # resume_all on restart must NOT resurrect the failed original.
    resumed = sm.resume_all()
    resumed_ids = {j["id"] for j in resumed}
    assert jid not in resumed_ids
    assert retry["id"] in resumed_ids


def test_deletion_f4():
    """Memory off after a kill → no job state; resume finds nothing."""
    db = f"/tmp/house_f4_del_{uuid.uuid4().hex}.db"
    m, sm = _mk(db)
    job = sm.start(CALLER, ROUTE, FP)
    jid = job["id"]
    sm.advance(jid, "serving", step="fetch", payment_state="verified")

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m_off = HouseMemory(db)
        sm_off = JobStateMachine(m_off)
        # The kill happened; memory is gone; nothing to resume.
        resumed = sm_off.resume_all()
        assert resumed == []
        # The mid-flight job's persisted state is UNREACHABLE — the house
        # cannot know the job was already in flight, so a client retry after
        # restart would re-serve AND re-settle (double charge). That is the
        # degradation: idempotency died with the memory.
        assert sm_off.get(jid) is None
        fresh = sm_off.start(CALLER, ROUTE, FP)
        assert fresh["phase"] == "accepted"  # re-executed from scratch
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

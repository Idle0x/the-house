"""F4 JobStateMachine (03-FEATURES F4) — the kill-resilient job store.

A job is persisted BEFORE the work so a ``kill -9`` mid-serve leaves a row a
restart can resume, and settle() is idempotent so the restart never
double-charges. A failed attempt is terminal (no zombie resurrected alongside
its retry). Deletion kills the idempotency (the gate).
"""
import os
import uuid

from core.jobs import TERMINAL, JobStateMachine, job_id
from core.memory import HouseMemory

CALLER = "0x" + "F" * 40
ROUTE = "/intel/quote"
FP = "fp-intel-quote"


def _mk(db: str) -> tuple[HouseMemory, JobStateMachine]:
    m = HouseMemory(db)
    return m, JobStateMachine(m)


def _db(prefix: str) -> str:
    return f"/tmp/house_f4_{prefix}_{uuid.uuid4().hex}.db"


def test_kill_mid_serve_resumes_settles_once_and_deletion_gate():
    """Process A: start + advance to serving, then dies. Process B (a fresh
    client over the same db) resumes the mid-flight job and settles it exactly
    once — settle() twice is a no-op (no double charge). THE GATE: with memory
    off after a kill, resume finds nothing and a client retry re-executes from
    scratch — idempotency dies with the memory that made it."""
    db = f"/tmp/house_f4_resume_{uuid.uuid4().hex}.db"
    m1, sm1 = _mk(db)
    jid = sm1.start(CALLER, ROUTE, FP)["id"]
    sm1.advance(jid, "serving", step="fetch", payment_state="verified")

    m2, sm2 = _mk(db)  # restart
    resumed = sm2.resume_all()
    assert len(resumed) == 1 and resumed[0]["id"] == jid
    assert resumed[0]["phase"] == "serving"
    out = sm2.settle(jid, CALLER)
    assert out["phase"] == "settled" and out["payment_state"] == "settled"
    assert out["settle_attempts"] == 1
    assert sm2.settle(jid, CALLER)["settle_attempts"] == 1  # idempotent

    # THE GATE: deletion kills the idempotency.
    db2 = _db("del")
    m3, sm3 = _mk(db2)
    jid2 = sm3.start(CALLER, ROUTE, FP)["id"]
    sm3.advance(jid2, "serving", step="fetch", payment_state="verified")
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        sm_off = JobStateMachine(HouseMemory(db2))
        assert sm_off.resume_all() == []
        assert sm_off.get(jid2) is None
        assert sm_off.start(CALLER, ROUTE, FP)["phase"] == "accepted"
    finally:
        os.environ.pop("SIBYL_DISABLED", None)


def test_failed_original_is_terminal_no_zombie():
    """C4: fail() marks the original job FAILED (terminal) and starts a fresh
    attempt-2 row, so resume_all never resurrects the corpse alongside its
    retry. job_id is deterministic per (caller, route, fp, attempt)."""
    m, sm = _mk(_db("zombie"))
    jid = sm.start(CALLER, ROUTE, FP)["id"]
    sm.advance(jid, "serving", step="fetch", payment_state="verified")
    retry = sm.fail(jid, "upstream 5xx")
    assert retry["attempt"] == 2 and retry["id"] != jid
    orig = sm.get(jid)
    assert orig["phase"] == "failed" and orig["phase"] in TERMINAL
    assert sm.pending_count() == 1  # only the live retry
    resumed_ids = {j["id"] for j in sm.resume_all()}
    assert jid not in resumed_ids and retry["id"] in resumed_ids
    assert job_id(CALLER, ROUTE, FP, 1) == job_id(CALLER, ROUTE, FP, 1)
    assert job_id(CALLER, ROUTE, FP, 1) != job_id(CALLER, ROUTE, FP, 2)

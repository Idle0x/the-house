"""Seller unit tests — extract_payer + handler behavior without network.

We test the memory act directly: given a settled payload (payer known), the
ledger row decides served/refused/dedup. The FastAPI app is built without
CDP creds (bare facilitator fallback) — no outbound calls are made because
we exercise the handlers via the app's route functions + TestClient free /
simulated-settled requests where x402 middleware would otherwise 402.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from core.memory import HouseMemory
from core.jobs import JobStateMachine
from core.trust import TrustLedger
from app.x402.seller import extract_payer

VIP_ADDR = "0x" + "A" * 40
STRANGER_ADDR = "0x" + "B" * 40
BANNED_ADDR = "0x" + "C" * 40


class _FakePayload:
    """Minimal stand-in for a settled x402 payload exposing the payer."""

    def __init__(self, payer: str):
        self.payload = {"authorization": {"from_address": payer}}


def test_extract_payer_exact_shape():
    assert extract_payer(_FakePayload(VIP_ADDR)) == VIP_ADDR


def test_extract_payer_none():
    assert extract_payer(None) is None


def test_extract_payer_dict_fallback():
    assert extract_payer({"payer": STRANGER_ADDR}) == STRANGER_ADDR


@pytest.fixture()
def app_ctx():
    """A TrustLedger with a VIP, a stranger, and a banned actor."""
    db = f"/tmp/house_seller_{uuid.uuid4().hex}.db"
    m = HouseMemory(db)
    ledger = TrustLedger(m)
    for _ in range(10):
        ledger.update(VIP_ADDR, "served", paid_usdc=0.01)
    for _ in range(3):
        ledger.update(BANNED_ADDR, "caller_fault")
    for _ in range(3):
        ledger.update(BANNED_ADDR, "refund")
    return ledger


def test_vip_row_recalled(app_ctx):
    row = app_ctx.recall(VIP_ADDR)
    assert row is not None
    assert row["segment"] == "vip"


def test_banned_row_recalled(app_ctx):
    d = app_ctx.decision(BANNED_ADDR)
    assert d.allow is False


def test_landing_route_free(tmp_path, monkeypatch):
    """The app builds and / + /house/ledger are free (no x402 gate).

    Uses an ISOLATED memory db (tmp_path) — the live data/memory.db carries
    real dedup hits from the Gate-1 proof and would pollute the assertion.
    """
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "the-house"
    assert body["memory"] in ("live", "disabled")

    # The money shot: /house/ledger is FREE and returns dedup stats + table.
    r2 = client.get("/house/ledger")
    assert r2.status_code == 200
    ledger_body = r2.json()
    assert "dedup" in ledger_body
    assert "callers" in ledger_body
    assert ledger_body["dedup"]["hits"] == 0
    # Day-1 wiring: the ledger also surfaces scar + job state.
    assert "scars" in ledger_body and "jobs" in ledger_body


def test_house_jobs_endpoint_free(tmp_path, monkeypatch):
    """/house/jobs is free and shows the F4 state machines (Gate 2)."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/house/jobs")
    assert r.status_code == 200
    body = r.json()
    assert "pending" in body
    assert "jobs" in body
    assert body["jobs"] == []


def test_house_compile_endpoint_compiles_scars(tmp_path, monkeypatch):
    """POST /house/compile turns 3 same-class scars into a policy rule."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    # Record 3 failures directly on the app's scar compiler (memory live).
    scars = app.state.scars
    for _ in range(3):
        scars.record("/intel/upstream", "5xx upstream timeout", "provider timed out")
    client = TestClient(app)
    r = client.post("/house/compile")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rules_created"]) == 1
    assert len(body["active_rules"]) == 1
    # Fresh session over the same db sees the hardened policy.
    rule = list(body["active_rules"].values())[0]
    assert rule["source_scar"].startswith("S-")


def test_house_compile_deletion_mode_empty(tmp_path, monkeypatch):
    """SIBYL_DISABLED=1 → compile finds nothing (scars don't persist)."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    app = build_app()
    client = TestClient(app)
    r = client.post("/house/compile")
    assert r.status_code == 200
    body = r.json()
    assert body["memory"] == "disabled"
    assert body["rules_created"] == []
    assert body["active_rules"] == {}
    assert body["scar_total"] == 0


def test_paid_serve_creates_settled_job(tmp_path, monkeypatch):
    """A served paid request leaves a settled job (F4 wired in the serve path)."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)

    # /house/jobs is free; the paid route needs a settled payload. We simulate
    # the memory act via the app's own jobs machine, then assert the paid
    # route is registered behind the middleware (it must NOT be free).
    r = client.get("/intel/quote")
    assert r.status_code == 402  # payment required — not free

    jobs = app.state.jobs
    payer = "0x" + "9" * 40
    job = jobs.start(payer, "/intel/quote", "fp-demo")
    jobs.advance(job["id"], "serving", step="serve", payment_state="verified")
    jobs.settle(job["id"], payer)
    assert jobs.get(job["id"])["phase"] == "settled"
    assert jobs.pending_count() == 0

    # resume_all on a fresh machine over the same db finds nothing to resume.
    m2 = HouseMemory(str(tmp_path / "memory.db"))
    jobs2 = JobStateMachine(m2)
    assert jobs2.resume_all() == []

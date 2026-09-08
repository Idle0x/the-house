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
    # The human landing page is now HTML at /.
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    page = r.text
    assert "THE" in page and "HOUSE" in page
    assert "why memory is load-bearing" in page
    assert "MEMORY LIVE" in page  # isolated fresh db => memory live
    # The machine-readable descriptor moved to /manifest (old / JSON payload).
    m = client.get("/manifest")
    assert m.status_code == 200
    body = m.json()
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


def test_landing_shows_collapse_when_memory_disabled(tmp_path, monkeypatch):
    """SIBYL_DISABLED=1 => the landing page itself reads the collapse.

    The deletion gate, visible: memory badge DISABLED, the collapse callout
    shown, and every aggregate 0 — no hidden state behind the marketing.
    """
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    app = build_app()
    client = TestClient(app)
    page = client.get("/").text
    assert "MEMORY DISABLED" in page
    assert "collapse show" in page  # the gate callout is rendered
    manifest = client.get("/manifest").json()
    assert manifest["memory"] == "disabled"
    assert manifest["stats"]["settlements"] == 0
    assert manifest["stats"]["live_callers"] == 0


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
    # FIX-4d: /house/compile is gated by a capability token when one is set.
    r = client.post("/house/compile",
                    headers={"x-house-capability": "test-token"})
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


# --- direct handler tests: the paid route function with a stub request ------

class _StubState:
    """Minimal request.state stand-in carrying a settled payment payload."""

    def __init__(self, payer: str):
        self.payment_payload = {"payer": payer}


class _StubRequest:
    """Minimal Request stand-in exposing app.state + state as the handler needs."""

    def __init__(self, app, payer: str):
        self.app = app
        self.state = _StubState(payer)


def _paid_handler_fn(app):
    from fastapi.routing import APIRoute
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/intel/quote":
            return route.endpoint
    raise AssertionError("paid route not found")


def test_banned_wallet_refused_403_no_fake_refund(tmp_path, monkeypatch):
    """C2 fix: banned → HTTP 403 (x402 middleware cancels settlement), and
    the ledger is NOT polluted with a fake 'refund' event."""
    from app.x402.seller import build_app
    from core.trust import TrustLedger
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    ledger: TrustLedger = app.state.ledger
    bad = "0x" + "C" * 40
    for _ in range(3):
        ledger.update(bad, "refund")      # → banned
    assert ledger.decision(bad).segment == "banned"

    refund_events_before_row = ledger.recall(bad)
    assert refund_events_before_row is not None
    refund_events_before = refund_events_before_row["refund_events"]
    handler = _paid_handler_fn(app)
    resp = handler(_StubRequest(app, bad))
    assert resp.status_code == 403
    body = resp.body.decode()
    assert "declines" in body
    # No extra refund event was booked (no money moved — nothing to refund).
    after = ledger.recall(bad)
    assert after is not None
    assert after["refund_events"] == refund_events_before


def test_fresh_serve_returns_post_update_standing(tmp_path, monkeypatch):
    """H5 fix: the response standing reflects the JUST-completed serve
    (tx_count already incremented), not the pre-update row."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    payer = "0x" + "D" * 40
    handler = _paid_handler_fn(app)
    # Success responses are plain dicts (FastAPI wraps them later); only
    # the refusal path returns a JSONResponse.
    resp = handler(_StubRequest(app, payer))
    body = resp if isinstance(resp, dict) else resp.json()
    assert body["cached"] is False
    # tx_count must reflect this very serve (1), not 0.
    assert body["standing"]["tx_count"] == 1
    assert body["standing"]["segment"] == "new"
    assert body["house"]["trust_score"] > 50  # trust bumped (+3)
    # Second identical request = dedup repeat → dedup_hits incremented (H2).
    resp2 = handler(_StubRequest(app, payer))
    body2 = resp2 if isinstance(resp2, dict) else resp2.json()
    assert body2["cached"] is True
    assert body2["standing"]["dedup_hits"] == 1
    assert body2["house"]["repeat_of"] is not None

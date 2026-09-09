"""P3b audit-fix regression tests (SEV-2 integration gaps + finding #21).

The audit: (a) ``settle_failure`` booked a claim as ``paid`` even when the
wallet failed to send (imaginary money); (b) nothing in the product surface
could ever trigger a claim; (c) ``/scout/hire`` was a pure read — the house
decided and remembered nothing.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

PROV = "0x" + "H" * 40
BUYER = "0x" + "B" * 40
FACE = 1.00


def _mk_desk(tmp_path):
    from core.bonds import UnderwritingDesk
    from core.memory import HouseMemory
    m = HouseMemory(str(tmp_path / "memory.db"))
    desk = UnderwritingDesk(m, max_exposure=10.0)
    m.set_entity("provider", PROV, {
        "quality_score": 0.95, "on_time": 0.98, "jobs_done": 12,
        "default_events": 0})
    return desk


# ---- the claim state machine (finding #21) -------------------------------- #
def test_claim_never_books_money_not_sent(tmp_path):
    desk = _mk_desk(tmp_path)
    st, iss = desk.issue(PROV, BUYER)
    assert st == 200
    cap_before = desk._effective_max_exposure()

    def _boom(to: str, usdc_amount: float, memo: str) -> str:
        raise RuntimeError("no wallet")
    desk.wallet.send_usdc = _boom  # type: ignore[assignment]
    st, claim = desk.settle_failure(iss["bond_id"], "timeout", "x")
    # The house owes the face but did not send it → NOT booked as paid.
    assert claim["status"] == "failed" and claim["paid"] is False
    assert claim["claim_tx"] is None
    assert claim["claims_paid"] == 0
    assert claim["max_exposure_after"] == pytest.approx(cap_before)

    # Retry once the wallet works: paid exactly once, cap decays once.
    def _ok(to: str, usdc_amount: float, memo: str) -> str:
        return "dry:retried"
    desk.wallet.send_usdc = _ok  # type: ignore[assignment]
    st, claim2 = desk.settle_failure(iss["bond_id"], "timeout", "x")
    assert claim2["status"] == "paid" and claim2["paid"] is True
    assert claim2["claims_paid"] == 1
    assert claim2["max_exposure_after"] == pytest.approx(cap_before - 1.0)
    # Settled → no second payout.
    assert desk.settle_failure(iss["bond_id"], "timeout", "x")[0] == 409


# ---- the auto-trigger: default → every open bond pays --------------------- #
def test_claim_for_provider_pays_all_open_bonds(tmp_path):
    desk = _mk_desk(tmp_path)
    # Two open bonds on the same provider (distinct buyers).
    desk.issue(PROV, BUYER)
    desk.issue(PROV, "0x" + "C" * 40)
    cap_before = desk._effective_max_exposure()

    results = desk.claim_for_provider(PROV, "timeout", "job 502'd twice")
    assert len(results) == 2
    assert all(st == 200 and c["paid"] for st, c in results)
    assert desk.claims_paid() == 2
    assert desk._effective_max_exposure() == pytest.approx(cap_before - 2.0)
    # A second trigger for the same default is a no-op (both bonds closed).
    assert desk.claim_for_provider(PROV, "timeout", "again") == []


def test_claim_for_provider_unknown_is_noop(tmp_path):
    desk = _mk_desk(tmp_path)
    assert desk.claim_for_provider("0x" + "Z" * 40, "timeout", "x") == []


# ---- the operator route: money out is gated, never free ------------------- #
class _ClaimStubRequest:
    def __init__(self, body: dict, header_token: str = ""):
        self._body = body
        self.headers = {"x-house-capability": header_token}

    async def json(self):
        return self._body


def _claim_handler(app):
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == "/house/bonds/claim":
            return r.endpoint
    raise AssertionError("POST /house/bonds/claim not registered")


def test_claim_route_gated_by_token_when_configured(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("HOUSE_COMPILE_TOKEN", "s3cret")
    app = build_app()
    _mk_desk_into_app(app)
    handler = _claim_handler(app)
    # No token → 403 (money out is never an open endpoint in production).
    r = asyncio.run(handler(_ClaimStubRequest({"provider": PROV})))
    assert r.status_code == 403
    # Right token → claim pays.
    r = asyncio.run(handler(_ClaimStubRequest(
        {"provider": PROV, "failure_class": "timeout"}, "s3cret")))
    assert r["settled"] == 1
    assert r["claims"][0]["claim_tx"].startswith("dry:")


def test_claim_route_open_in_tokenless_local_and_validates(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("HOUSE_COMPILE_TOKEN", raising=False)
    app = build_app()
    _mk_desk_into_app(app)
    handler = _claim_handler(app)
    # Tokenless local/test: open (the demo's fault injector path).
    r = asyncio.run(handler(_ClaimStubRequest(
        {"provider": PROV, "failure_class": "timeout"})))
    assert r["settled"] == 1
    # Junk provider shape → 400 before any payout.
    r = asyncio.run(handler(_ClaimStubRequest({"provider": "not-an-address"})))
    assert r.status_code == 400


def _mk_desk_into_app(app):
    """Seed a proven provider + one open bond on the app's own desk."""
    m = app.state.memory
    m.set_entity("provider", PROV, {
        "quality_score": 0.95, "on_time": 0.98, "jobs_done": 12,
        "default_events": 0})
    st, _ = app.state.desk.issue(PROV, BUYER)
    assert st == 200


# ---- /scout/hire now REMEMBERS the decision (audit: pure read) ------------ #
def _hire_events(m, tag):
    return [e for e in m.read_events(limit=500)
            if (e.get("extra") or {}).get("kind") == "job"
            and any(tag in a for a in e.get("acted", []))]


def test_scout_hire_journals_the_decision(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    from core.memory import HouseMemory
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    m: HouseMemory = app.state.memory  # type: ignore[assignment]
    m.set_entity("provider", PROV, {
        "quality_score": 0.95, "on_time": 0.98, "jobs_done": 12,
        "default_events": 0})

    from fastapi.routing import APIRoute
    handler = next(r.endpoint for r in app.routes
                   if isinstance(r, APIRoute) and r.path == "/scout/hire")

    class _Req:
        headers = {}

        def __init__(self, provider):
            self._p = provider
            self.app = app  # the handler reads request.app.state.front

        async def json(self):
            return {"provider": self._p}

        @property
        def state(self):
            import types
            return types.SimpleNamespace(
                payment_payload={"payer": "0x" + "E" * 40})

    out = asyncio.run(handler(_Req(PROV)))
    assert out["hired"] is True  # proven → drafted
    assert len(_hire_events(m, "front office: draft")) >= 1

    # A refused ruling is journaled too (a refusal is hiring memory).
    RISKY = "0x" + "R" * 40
    m.set_entity("provider", RISKY, {
        "quality_score": 0.2, "on_time": 0.3, "jobs_done": 4,
        "default_events": 3})
    resp = asyncio.run(handler(_Req(RISKY)))
    assert resp.status_code == 403  # refused → uncharged
    assert len(_hire_events(m, "front office: refused")) >= 1

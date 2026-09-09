"""Room 3 — the front office (scouting / hiring).

Drives the ``FrontOffice`` directly and the FastAPI boundary for the paid
report/hire + the free draft board + the capability-gated onchain delegation.

``terms_from_row`` is the shared pure function: the same row that would set
onchain job terms sets the draft ruling and the scout report, so the draft and
the job always agree. Deletion → recall is None → every provider is "unknown"
→ hiring blind (base price).

Audit invariants under test:
  * P3b — a rendered hire ruling (draft OR refusal) is HIRING MEMORY (note_hire).
  * ``ACPDelegator.delegate`` is now reachable on a capability-gated
    route (``POST /scout/delegate``); a risky provider is skipped BEFORE any
    onchain call, and the route is 403 without the capability token.
"""
from __future__ import annotations

import asyncio
import os
import types

import pytest

from app.x402.seller import build_app
from core.memory import HouseMemory
from core.scout import (
    SCOUT_HIRE_PRICE, SCOUT_REPORT_BASE, SCOUT_REPORT_PER_SCAR,
    SCOUT_REPORT_RISKY_PREMIUM, FrontOffice,
)

PROVEN = "0x" + "A" * 40          # good record → preferred terms
THIN = "0x" + "B" * 40            # thin record → standard + stricter
RISKY = "0x" + "C" * 40           # bad record → refuse


def _mem(tmp_path) -> HouseMemory:
    os.environ.pop("SIBYL_DISABLED", None)
    return HouseMemory(str(tmp_path / "memory.db"))


def _proven_row(m, addr):
    m.set_entity("provider", addr, {
        "address": addr, "first_seen": 0, "last_seen": 0,
        "jobs_done": 4, "on_time_jobs": 4, "quality_sum": 3.5,
        "quality_score": 0.875, "on_time": 1.0,
        "total_escrow_usdc": 4.0, "default_events": 0, "notes": ""})


def _risky_row(m, addr):
    m.set_entity("provider", addr, {
        "address": addr, "first_seen": 0, "last_seen": 0,
        "jobs_done": 2, "on_time_jobs": 1, "quality_sum": 1.0,
        "quality_score": 0.5, "on_time": 0.5,
        "total_escrow_usdc": 2.0, "default_events": 1, "notes": ""})


class _StubRequest:
    """Minimal stand-in for the FastAPI Request the paid handlers need:
    .json() (async), .state.payment_payload, .app.state.{front,acp}, .headers."""

    def __init__(self, payload: dict, front: FrontOffice,
                 headers: dict | None = None, acp=None) -> None:
        self._payload = payload
        self.state = types.SimpleNamespace(payment_payload={"payer": "0x" + "E" * 40})
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(
            front=front, acp=acp))
        self.headers = headers or {}

    async def json(self) -> dict:
        return self._payload


def _handler(app, method, path):
    for route in app.routes:
        if getattr(route, "path", "") == path \
                and method in getattr(route, "methods", set()):
            return getattr(route, "endpoint", None)
    return None


def _payload(resp) -> dict:
    """A success path returns a plain dict (FastAPI wraps it); a refusal
    returns a JSONResponse — normalize both to the body dict."""
    import json
    if isinstance(resp, dict):
        return resp
    return json.loads(resp.body)


# --------------------------------------------------------------------------- #
# Decision layer (memory-driven, not price-driven)
# --------------------------------------------------------------------------- #
def test_decision_segments_stricter_and_refuses_risky_and_boards(tmp_path):
    """The draft ruling is a pure function of the record: proven → preferred
    terms (hired); unknown/thin → standard + stricter evaluator (hired); risky
    → refused with its default scar counted. select() orders proven first,
    refused last (cheapest ≠ drafted). The board lists every provider."""
    m = _mem(tmp_path)
    _proven_row(m, PROVEN)
    _risky_row(m, RISKY)
    f = FrontOffice(m)

    d = f.decision(PROVEN)
    assert d["segment"] == "proven" and d["hired"] is True and d["refused"] is False
    assert d["strict_review"] is False and d["scars_against"] == 0

    assert f.decision("0x" + "F" * 40)["strict_review"] is True  # unknown → strict
    d = f.decision(RISKY)
    assert d["segment"] == "risky" and d["refused"] is True and d["scars_against"] == 1

    order = [x["provider_last6"] for x in f.select([RISKY, THIN, PROVEN])]
    assert order[0] == PROVEN[-6:] and order[-1] == RISKY[-6:]

    b = f.board()
    # The board lists only providers the house REMEMBERS (2 seeded here);
    # proven drafted, risky refused. (Unknown→strict is asserted above.)
    assert b["providers"] == 2 and b["drafted"] == 1 and b["refused"] == 1
    assert b["board"][0]["segment"] == "proven"


def test_report_pricing_reflects_record_scar_claims(tmp_path):
    """A costly memory quotes a premium: clean/proven → base; risky →
    +PER_SCAR (1 default) + RISKY_PREMIUM; a paid bond claim adds one more scar
    step (the bond book is the source of truth for claims_against)."""
    m = _mem(tmp_path)
    _proven_row(m, PROVEN)
    _risky_row(m, RISKY)
    f = FrontOffice(m)
    r = f.report(PROVEN)
    assert r["known"] is True and r["would_draft"] is True
    assert r["quoted_price_usdc"] == SCOUT_REPORT_BASE
    assert f.report("0x" + "D" * 40)["quoted_price_usdc"] == SCOUT_REPORT_BASE

    rr = f.report(RISKY)
    assert rr["quoted_price_usdc"] == round(
        SCOUT_REPORT_BASE + SCOUT_REPORT_PER_SCAR + SCOUT_REPORT_RISKY_PREMIUM, 6)
    assert rr["would_draft"] is False and rr["terms"]["skip"] is True

    # A paid claim against the provider raises the price by one scar step.
    m.set_entity("bond", "bond_1", {
        "bond_id": "bond_1", "provider": RISKY, "buyer": "0x" + "1" * 40,
        "face_usdc": 1.0, "premium": 0.11, "status": "claimed",
        "claim_tx": {"tx": "0xdead", "kind": "dry-run"}})
    with_claim = f.report_price(RISKY)
    m.set_entity("bond", "bond_1", {
        "bond_id": "bond_1", "provider": RISKY, "buyer": "0x" + "1" * 40,
        "face_usdc": 1.0, "premium": 0.11, "status": "open", "claim_tx": None})
    without = f.report_price(RISKY)
    assert with_claim - without == pytest.approx(SCOUT_REPORT_PER_SCAR)


# --------------------------------------------------------------------------- #
# Route wiring + P3b (the hire ruling is journaled)
# --------------------------------------------------------------------------- #
def test_hire_report_registered_and_hire_journals_the_ruling(tmp_path, monkeypatch):
    """POST /scout/report + /scout/hire + /house/front are registered and
    priced; a hire ruling — draft OR refusal — is journaled (kind=job
    "front office: …"), so the house remembers its decisions (audit P3b). A
    risky provider is refused 403, uncharged; a proven one is drafted."""
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/scout/report", "/scout/hire", "/house/front"} <= paths
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "x402", "seller.py")).read()
    assert '"POST /scout/report"' in src and '"POST /scout/hire"' in src
    assert SCOUT_REPORT_BASE > 0 and SCOUT_HIRE_PRICE > 0

    front: FrontOffice = app.state.front  # type: ignore[assignment]
    _proven_row(front.m, PROVEN)
    _risky_row(front.m, RISKY)
    handler = _handler(app, "POST", "/scout/hire")
    assert handler is not None

    # Proven → drafted; risky → 403 refused, uncharged.
    out = asyncio.run(handler(_StubRequest({"provider": PROVEN}, front)))
    assert out["hired"] is True and out["refused"] is False and out["segment"] == "proven"
    resp = asyncio.run(handler(_StubRequest({"provider": RISKY}, front)))
    assert getattr(resp, "status_code", 200) == 403
    import json
    data = json.loads(resp.body)
    assert data.get("refused") is True and data.get("uncharged") is True

    # The rulings are journaled (draft AND refusal).
    events = front.m.read_events(limit=500)
    text = lambda e: " ".join(e.get("acted") or [])  # noqa: E731
    kinds = [(e.get("extra") or {}).get("kind") for e in events]
    assert kinds.count("job") >= 2
    assert any("front office: draft" in text(e) for e in events)
    assert any("front office: refused" in text(e) for e in events)


def test_delegate_route_gated_skips_risky_before_onchain(tmp_path, monkeypatch):
    """ACPDelegator.delegate is reachable on the capability-gated
    POST /scout/delegate. With a token set it is 403 without the capability
    header. A RISKY provider is skipped BEFORE any onchain call (no delegate
    invoked, no job, no escrow) — the house does not hire it. A provable
    provider proceeds to delegate() (stubbed: no real CLI/escrow here)."""
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("HOUSE_COMPILE_TOKEN", "s3cret")
    app = build_app()
    front: FrontOffice = app.state.front  # type: ignore[assignment]
    acp = app.state.acp  # type: ignore[assignment]
    _risky_row(front.m, RISKY)
    _proven_row(front.m, PROVEN)

    calls = {"n": 0}
    def fake_delegate(provider, offering, requirements, **kw):
        calls["n"] += 1
        return {"job_id": "job-123", "funded_usdc": 0.05,
                "completion": "completed", "terms": acp.terms(provider).to_dict()}
    acp.delegate = fake_delegate  # type: ignore[assignment]

    handler = _handler(app, "POST", "/scout/delegate")
    assert handler is not None

    # 403 without the capability token.
    no_tok = asyncio.run(handler(_StubRequest(
        {"provider": PROVEN, "offering": "intel"}, front,
        headers={}, acp=acp)))
    assert getattr(no_tok, "status_code", 200) == 403

    # Risky → skipped BEFORE the onchain call (delegate never invoked).
    risky = asyncio.run(handler(_StubRequest(
        {"provider": RISKY, "offering": "intel"}, front,
        headers={"x-house-capability": "s3cret"}, acp=acp)))
    body = _payload(risky)
    assert body.get("skipped") is True and body.get("uncharged") is True
    assert calls["n"] == 0, "a risky provider must be skipped before delegate()"

    # Proven → delegate() runs, the ruling is journaled, receipt returned.
    ok = asyncio.run(handler(_StubRequest(
        {"provider": PROVEN, "offering": "intel"}, front,
        headers={"x-house-capability": "s3cret"}, acp=acp)))
    ok_body = _payload(ok)
    assert calls["n"] == 1
    assert ok_body["job_id"] == "job-123"
    kinds = [(e.get("extra") or {}).get("kind") for e in front.m.read_events(limit=500)]
    assert "job" in kinds  # the drafted ruling is journaled


def test_free_front_board_serves(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    _proven_row(app.state.front.m, PROVEN)
    _risky_row(app.state.front.m, RISKY)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/house/front")
        assert r.status_code == 200
        data = r.json()
        assert data["providers"] == 2 and data["drafted"] == 1 and data["refused"] == 1

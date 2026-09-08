"""M3 — Room 3: the front office (scouting / talent).

Drives the ``FrontOffice`` directly (no x402 middleware, no CDP) and the
FastAPI boundary for the paid report/hire + the free draft board.

The front office is the *decision* layer over the provider WARM rows the
ACP delegator already writes. ``terms_from_row`` is the shared pure function:
the same row that would set onchain job terms (Gate 4) sets the draft ruling
and the scout report, so the draft and the job always agree. Deletion →
recall is None → every provider is "unknown" → hiring blind (base price).
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.x402.seller import build_app  # noqa: E402
from core.memory import HouseMemory  # noqa: E402
from core.scout import (  # noqa: E402
    SCOUT_HIRE_PRICE, SCOUT_REPORT_BASE, SCOUT_REPORT_PER_SCAR,
    SCOUT_REPORT_RISKY_PREMIUM, FrontOffice,
)

PROVEN = "0x" + "A" * 40          # good record → preferred terms
THIN = "0x" + "B" * 40            # thin record → standard + stricter
RISKY = "0x" + "C" * 40           # bad record → refuse


def _mem(tmp_path) -> HouseMemory:
    """Memory with SIBYL re-ENABLED (the helper must not leak the flag into
    later tests — disabled-memory cases use monkeypatch directly)."""
    os.environ.pop("SIBYL_DISABLED", None)
    return HouseMemory(str(tmp_path / "memory.db"))


def _proven_row(m: HouseMemory, addr: str) -> None:
    m.set_entity("provider", addr, {
        "address": addr, "first_seen": 0, "last_seen": 0,
        "jobs_done": 4, "on_time_jobs": 4, "quality_sum": 3.5,
        "quality_score": 0.875, "on_time": 1.0,
        "total_escrow_usdc": 4.0, "default_events": 0, "notes": "",
    })


def _thin_row(m: HouseMemory, addr: str) -> None:
    m.set_entity("provider", addr, {
        "address": addr, "first_seen": 0, "last_seen": 0,
        "jobs_done": 1, "on_time_jobs": 1, "quality_sum": 0.7,
        "quality_score": 0.7, "on_time": 1.0,
        "total_escrow_usdc": 1.0, "default_events": 0, "notes": "",
    })


def _risky_row(m: HouseMemory, addr: str) -> None:
    m.set_entity("provider", addr, {
        "address": addr, "first_seen": 0, "last_seen": 0,
        "jobs_done": 2, "on_time_jobs": 1, "quality_sum": 1.0,
        "quality_score": 0.5, "on_time": 0.5,
        "total_escrow_usdc": 2.0, "default_events": 1, "notes": "",
    })


def _seed(m: HouseMemory) -> None:
    _proven_row(m, PROVEN)
    _thin_row(m, THIN)
    _risky_row(m, RISKY)


class _StubRequest:
    """Minimal stand-in for the FastAPI Request the paid handlers need:
    .json() (async), .state.payment_payload, .app.state.front."""

    def __init__(self, payload: dict, front: FrontOffice) -> None:
        import types
        self._payload = payload
        self.state = types.SimpleNamespace(payment_payload={"payer": "0x" + "E" * 40})
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(front=front))

    async def json(self) -> dict:
        return self._payload


# ---------------------------------------------------------------------------
# Decision layer
# ---------------------------------------------------------------------------
def test_decision_proven_prefers(tmp_path):
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    d = f.decision(PROVEN)
    assert d["segment"] == "proven"
    assert d["hired"] is True and d["refused"] is False
    assert d["strict_review"] is False
    assert d["scars_against"] == 0


def test_decision_unknown_stricter(tmp_path):
    m = _mem(tmp_path)
    f = FrontOffice(m)
    d = f.decision("0x" + "F" * 40)  # no row
    assert d["segment"] == "unknown"
    assert d["hired"] is True
    assert d["strict_review"] is True
    assert d["record"]["known"] is False


def test_decision_thin_stricter(tmp_path):
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    d = f.decision(THIN)
    assert d["segment"] == "unknown"
    assert d["strict_review"] is True
    assert d["hired"] is True


def test_decision_risky_refuses(tmp_path):
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    d = f.decision(RISKY)
    assert d["segment"] == "risky"
    assert d["refused"] is True and d["hired"] is False
    assert d["scars_against"] == 1  # one default


def test_select_orders_by_memory_not_price(tmp_path):
    """Cheapest ≠ drafted: proven first, unknown next, risky (refused) last."""
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    order = [d["provider_last6"] for d in
             f.select([RISKY, THIN, PROVEN])]
    assert order[0] == PROVEN[-6:]
    assert order[-1] == RISKY[-6:]
    assert THIN[-6:] in order[1:-1]


# ---------------------------------------------------------------------------
# Scout report + memory pricing
# ---------------------------------------------------------------------------
def test_report_clean_quotes_base(tmp_path):
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    r = f.report(PROVEN)
    assert r["known"] is True
    assert r["record"]["jobs_done"] == 4
    assert r["record"]["quality_score"] == 0.875
    assert r["scars_against"] == 0
    assert r["quoted_price_usdc"] == SCOUT_REPORT_BASE
    assert r["would_draft"] is True


def test_report_risky_quotes_premium(tmp_path):
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    r = f.report(RISKY)
    # 1 default scar → +PER_SCAR; risky segment → +RISKY_PREMIUM.
    expected = round(SCOUT_REPORT_BASE
                     + SCOUT_REPORT_PER_SCAR
                     + SCOUT_REPORT_RISKY_PREMIUM, 6)
    assert r["quoted_price_usdc"] == expected
    assert r["would_draft"] is False
    assert r["terms"]["skip"] is True


def test_report_unknown_quotes_base(tmp_path):
    m = _mem(tmp_path)
    f = FrontOffice(m)
    r = f.report("0x" + "D" * 40)
    assert r["known"] is False
    assert r["quoted_price_usdc"] == SCOUT_REPORT_BASE


def test_report_price_reflects_paid_claims(tmp_path):
    """A claim the house paid against the provider raises the report price.
    The bond book is the source of truth for claims_against."""
    m = _mem(tmp_path)
    _risky_row(m, RISKY)
    f = FrontOffice(m)
    # Record a paid claim on a bond against RISKY.
    m.set_entity("bond", "bond_1", {
        "bond_id": "bond_1", "provider": RISKY, "buyer": "0x" + "1" * 40,
        "face_usdc": 1.0, "premium": 0.11, "status": "claimed",
        "claim_tx": {"tx": "0xdead", "kind": "dry-run"},
    })
    price_with_claim = f.report_price(RISKY)
    m.set_entity("bond", "bond_1", {  # reset: claim not yet paid
        "bond_id": "bond_1", "provider": RISKY, "buyer": "0x" + "1" * 40,
        "face_usdc": 1.0, "premium": 0.11, "status": "open", "claim_tx": None,
    })
    price_without = f.report_price(RISKY)
    assert price_with_claim > price_without
    assert price_with_claim - price_without == pytest.approx(SCOUT_REPORT_PER_SCAR)


# ---------------------------------------------------------------------------
# Draft board
# ---------------------------------------------------------------------------
def test_board_lists_all_with_terms(tmp_path):
    m = _mem(tmp_path)
    _seed(m)
    f = FrontOffice(m)
    b = f.board()
    assert b["providers"] == 3
    assert b["drafted"] == 2   # proven + thin (unknown)
    assert b["refused"] == 1   # risky
    segs = [r["segment"] for r in b["board"]]
    assert segs[0] == "proven"      # sorted proven-first
    assert "risky" in segs


def test_board_empty_without_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m = HouseMemory(str(tmp_path / "memory.db"))
    f = FrontOffice(m)
    b = f.board()
    assert b["providers"] == 0
    assert b["board"] == []


# ---------------------------------------------------------------------------
# Deletion proof — memory load-bearing for hiring
# ---------------------------------------------------------------------------
def test_deletion_collapses_to_blind_hiring(tmp_path, monkeypatch):
    """With memory live, a scarred provider is refused and a proven one
    prefers. With memory disabled, EVERYONE is an unknown at base — the
    front office is blind. That collapse is the gate."""
    m_live = _mem(tmp_path / "live")
    _seed(m_live)
    f_live = FrontOffice(m_live)
    assert f_live.decision(RISKY)["refused"] is True
    assert f_live.decision(PROVEN)["segment"] == "proven"
    assert f_live.report_price(RISKY) > SCOUT_REPORT_BASE

    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m_off = HouseMemory(str(tmp_path / "off" / "memory.db"))
    f_off = FrontOffice(m_off)
    for addr in (PROVEN, THIN, RISKY):
        d = f_off.decision(addr)
        assert d["segment"] == "unknown"
        assert d["strict_review"] is True
        assert f_off.report_price(addr) == SCOUT_REPORT_BASE
    assert f_off.board()["providers"] == 0


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------
def test_routes_registered_and_priced(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/scout/report" in paths
    assert "/scout/hire" in paths
    assert "/house/front" in paths
    # Both paid routes are present in the x402 RouteConfig map (verb-prefixed).
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "x402", "seller.py")).read()
    assert '"POST /scout/report"' in src
    assert '"POST /scout/hire"' in src
    assert SCOUT_REPORT_BASE > 0 and SCOUT_HIRE_PRICE > 0


def _handler(app, method, path):
    for route in app.routes:
        if getattr(route, "path", "") == path \
                and method in getattr(route, "methods", set()):
            return getattr(route, "endpoint", None)
    return None


def test_report_handler_returns_record(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front: FrontOffice = app.state.front  # type: ignore[assignment]
    _proven_row(front.m, PROVEN)
    handler = _handler(app, "POST", "/scout/report")
    assert handler is not None
    out = asyncio.run(handler(_StubRequest({"provider": PROVEN}, front)))
    assert out["provider_last6"] == PROVEN[-6:]
    assert out["known"] is True
    assert out["segment"] == "proven"
    assert out["quoted_price_usdc"] == SCOUT_REPORT_BASE
    assert out["payer_last6"] == "E" * 6


def test_report_handler_requires_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front: FrontOffice = app.state.front  # type: ignore[assignment]
    handler = _handler(app, "POST", "/scout/report")
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest({"provider": "   "}, front)))
    assert getattr(resp, "status_code", 200) == 400


def test_hire_handler_refuses_risky_uncharged(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front: FrontOffice = app.state.front  # type: ignore[assignment]
    _risky_row(front.m, RISKY)
    handler = _handler(app, "POST", "/scout/hire")
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest({"provider": RISKY}, front)))
    assert getattr(resp, "status_code", 200) == 403
    body = resp.body if isinstance(resp.body, (bytes, bytearray)) else b""
    import json
    data = json.loads(body) if body else {}
    assert data.get("refused") is True
    assert data.get("uncharged") is True


def test_hire_handler_drafts_proven(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front: FrontOffice = app.state.front  # type: ignore[assignment]
    _proven_row(front.m, PROVEN)
    handler = _handler(app, "POST", "/scout/hire")
    assert handler is not None
    out = asyncio.run(handler(_StubRequest({"provider": PROVEN}, front)))
    assert out["hired"] is True
    assert out["refused"] is False
    assert out["segment"] == "proven"


def test_free_front_board_serves(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front: FrontOffice = app.state.front  # type: ignore[assignment]
    _seed(front.m)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/house/front")
        assert r.status_code == 200
        data = r.json()
        assert data["providers"] == 3
        assert data["drafted"] == 2
        assert data["refused"] == 1

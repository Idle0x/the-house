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


def test_landing_route_free():
    """The app builds and / + /house/ledger are free (no x402 gate)."""
    from app.x402.seller import build_app
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

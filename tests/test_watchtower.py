"""M2 — Room 4: the watchtower (market integrity).

The house refuses to launder. These drive the ``Watchtower`` directly (no
x402 middleware, no CDP) and the FastAPI boundary for the paid screen + free
verdict feed. Every rule is a pure function of per-caller memory, so a seeded
wash ring is refused with the ring drawn, and deletion re-admits it — the
before/after IS the gate.

Money model: the screen is PAID (POST /watch/screen, base screen price on the
402 quote); the serve-path refusal is UNCHARGED (403 before settlement, per
the exact-scheme model in core/house.py).
"""
from __future__ import annotations

import pytest

from core import config as C
from core.memory import HouseMemory
from core.watch import (
    R_COLD, R_FACTORY, R_METRONOME, R_SELF_PAY, R_SYBIL,
    VERDICT_ABORT, VERDICT_CLEAR, VERDICT_HOLD, Watchtower,
)

HOUSE_WALLET = "0x" + "A" * 40
ROOT = "0x" + "F" * 40


def _mem(tmp_path):
    return HouseMemory(str(tmp_path / "memory.db"))


def _tower(tmp_path, house_wallet: str = HOUSE_WALLET) -> Watchtower:
    return Watchtower(_mem(tmp_path), house_wallet=house_wallet)


def _caller(m: HouseMemory, addr: str, **fields) -> dict:
    row = {
        "address": addr, "first_seen": 1.0, "last_seen": 2.0,
        "tx_count": 3, "total_paid_usdc": 0.03, "served_count": 3,
        "dedup_hits": 0, "failure_events": 0, "refund_events": 0,
        "warning_events": 0, "trust_score": 55.0, "segment": "new",
        "dedup_fp": [], "notes": "",
    }
    row.update(fields)
    m.set_entity("caller", addr, row)
    return row


def _ring(m: HouseMemory, n: int = 3) -> list[str]:
    """A funding-cluster sybil ring: n callers funded by one root.
    Returns the member addresses."""
    addrs = []
    for i in range(n):
        addr = "0x" + str(i).zfill(2) + "B" * 37
        _caller(m, addr, funded_by=ROOT,
                dedup_fp=[f"fp-{i}", f"shared-{i % 7}"])
        addrs.append(addr)
    return addrs


# ---------------------------------------------------------------------------
# Rule: self-pay loop
# ---------------------------------------------------------------------------
def test_self_pay_when_wallet_is_the_house(tmp_path):
    t = _tower(tmp_path)
    s = t.screen(HOUSE_WALLET)
    assert s["verdict"] == VERDICT_ABORT
    assert R_SELF_PAY in [e["rule"] for e in s["evidence"]]
    assert s["ring"] == [HOUSE_WALLET]


def test_self_pay_when_funded_by_itself(tmp_path):
    m = _mem(tmp_path)
    addr = "0x" + "1" * 40
    _caller(m, addr, funded_by=addr)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen(addr)
    assert s["verdict"] == VERDICT_ABORT
    assert R_SELF_PAY in [e["rule"] for e in s["evidence"]]


# ---------------------------------------------------------------------------
# Rule: funding-cluster sybil
# ---------------------------------------------------------------------------
def test_sybil_ring_is_refused_with_ring_drawn(tmp_path):
    m = _mem(tmp_path)
    ring = _ring(m)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen(ring[0])
    assert s["verdict"] == VERDICT_ABORT
    assert R_SYBIL in [e["rule"] for e in s["evidence"]]
    # The ring is part of the verdict — drawn on screen, not implied.
    assert set(s["ring"]) == set(ring)
    ev = next(e for e in s["evidence"] if e["rule"] == R_SYBIL)
    assert str(len(ring)) in ev["detail"]


def test_two_members_under_threshold_is_clear(tmp_path):
    m = _mem(tmp_path)
    _ring(m, 2)  # below WATCH_SYBIL_CLUSTER_MIN (3)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen("0x00B" + "B" * 37)
    assert R_SYBIL not in [e["rule"] for e in s["evidence"]]


def test_clean_caller_is_clear(tmp_path):
    m = _mem(tmp_path)
    _caller(m, "0x" + "7" * 40, funded_by="0x" + "9" * 40)  # unique root
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen("0x" + "7" * 40)
    assert s["verdict"] == VERDICT_CLEAR
    assert s["evidence"] == []
    assert s["ring"] == []


# ---------------------------------------------------------------------------
# Rule: factory fingerprint
# ---------------------------------------------------------------------------
def test_factory_cluster_is_refused(tmp_path):
    m = _mem(tmp_path)
    fps = ["fp-1", "fp-2"]
    addrs = ["0x" + "C" * 40, "0x" + "D" * 40, "0x" + "E" * 40]
    for a in addrs:
        _caller(m, a, dedup_fp=fps)  # identical boilerplate
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen(addrs[0])
    assert s["verdict"] == VERDICT_ABORT
    assert R_FACTORY in [e["rule"] for e in s["evidence"]]
    assert len(s["ring"]) == 3


def test_diverse_fingerprints_not_factory(tmp_path):
    m = _mem(tmp_path)
    for i, a in enumerate(["0x" + "C" * 40, "0x" + "D" * 40, "0x" + "E" * 40]):
        _caller(m, a, dedup_fp=[f"unique-{i}"])  # one shared < OVERLAP (2)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen("0x" + "C" * 40)
    assert R_FACTORY not in [e["rule"] for e in s["evidence"]]


# ---------------------------------------------------------------------------
# Rule: cold-start with volume (HOLD, not a refusal)
# ---------------------------------------------------------------------------
def test_cold_start_with_volume_is_hold_not_abort(tmp_path):
    m = _mem(tmp_path)
    addr = "0x" + "3" * 40
    _caller(m, addr, tx_count=1, total_paid_usdc=0.10)  # volume, no history
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen(addr)
    assert s["verdict"] == VERDICT_HOLD
    assert R_COLD in [e["rule"] for e in s["evidence"]]
    # HOLD is evidence, not a refusal — the screen is published, the serve
    # continues (see test_serve_path: only ABORT refuses).
    assert t.consult(addr) is None


def test_history_with_volume_is_clear(tmp_path):
    m = _mem(tmp_path)
    _caller(m, "0x" + "3" * 40, tx_count=10, total_paid_usdc=0.10)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    assert t.screen("0x" + "3" * 40)["verdict"] == VERDICT_CLEAR


# ---------------------------------------------------------------------------
# Rule: metronome timing (HOLD)
# ---------------------------------------------------------------------------
def test_metronome_is_hold(tmp_path):
    m = _mem(tmp_path)
    addr = "0x" + "4" * 40
    _caller(m, addr)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    # Perfectly steady arrivals → CV 0 < WATCH_METRONOME_MAX_CV.
    ts = m.get_state("watch_serves") or {"items": []}
    m.set_state("watch_serves", {**ts, addr.lower(): [1.0, 2.0, 3.0, 4.0]})
    s = t.screen(addr)
    assert s["verdict"] == VERDICT_HOLD
    assert R_METRONOME in [e["rule"] for e in s["evidence"]]
    assert t.consult(addr) is None  # HOLD ≠ refusal


def test_irregular_timing_is_clear(tmp_path):
    m = _mem(tmp_path)
    addr = "0x" + "4" * 40
    _caller(m, addr)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    ts = m.get_state("watch_serves") or {"items": []}
    m.set_state("watch_serves",
                {**ts, addr.lower(): [1.0, 5.0, 7.0, 30.0]})  # high CV
    assert t.screen(addr)["verdict"] == VERDICT_CLEAR


# ---------------------------------------------------------------------------
# The serve path: the house refuses to be laundered
# ---------------------------------------------------------------------------
def test_serve_path_refuses_ring_member_uncharged(tmp_path):
    """The house's OWN serve path consults the tower: a ring member's payment
    is refused with the ring drawn, BEFORE settlement (genuinely uncharged)."""
    from core.house import House
    m = _mem(tmp_path)
    ring = _ring(m)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    house = House(m, base_price=0.01, watch=t)
    status, body = house.serve_intel(ring[0])
    assert status == 403
    assert body["house_declined"] is True
    assert "watchtower" in body["house_refused"]
    assert set(body["watch"]["ring"]) == set(ring)
    # The refusal is published on the feed (the money moment is on screen).
    feed = t.feed()
    assert any(e["verdict"] == VERDICT_ABORT for e in feed)


def test_serve_path_serves_clean_caller(tmp_path):
    from core.house import House
    m = _mem(tmp_path)
    addr = "0x" + "7" * 40
    _caller(m, addr, funded_by="0x" + "9" * 40)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    house = House(m, base_price=0.01, watch=t)
    status, body = house.serve_intel(addr)
    assert status == 200


# ---------------------------------------------------------------------------
# The gate: deletion re-admits the wash caller
# ---------------------------------------------------------------------------
def test_deletion_readmits_the_wash_caller(tmp_path, monkeypatch):
    """SIBYL_DISABLED → no caller rows → no clusters → the wash caller walks
    in fresh and is served like any other. That re-admission IS the gate."""
    from core.house import House
    m = _mem(tmp_path)
    ring = _ring(m)
    # Prove it WOULD refuse with memory on.
    t_live = Watchtower(m, house_wallet=HOUSE_WALLET)
    assert t_live.screen(ring[0])["verdict"] == VERDICT_ABORT
    # Now delete memory.
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m2 = HouseMemory(str(tmp_path / "memory.db"))
    t_dead = Watchtower(m2, house_wallet=HOUSE_WALLET)
    assert t_dead.screen(ring[0])["verdict"] == VERDICT_CLEAR
    house = House(m2, base_price=0.01, watch=t_dead)
    status, _ = house.serve_intel(ring[0])
    assert status == 200  # laundering works with the memory gone


def test_consult_never_writes_when_memory_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    t = Watchtower(_mem(tmp_path), house_wallet=HOUSE_WALLET)
    assert t.consult("0x" + "5" * 40) is None  # no feed, no serve timestamps


# ---------------------------------------------------------------------------
# Feed + stats (the public face of the room)
# ---------------------------------------------------------------------------
def test_feed_newest_first_and_capped(tmp_path):
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    for i in range(C.WATCH_FEED_MAX + 5):
        t.screen(f"0x{str(i).zfill(40)}")
    feed = t.feed()
    assert len(feed) == C.WATCH_FEED_MAX  # capped
    assert feed[0]["ts"] >= feed[-1]["ts"]  # newest first


def test_stats_organic_vs_manufactured(tmp_path):
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    ring = _ring(m)
    t.screen(ring[0])  # ABORT (manufactured)
    _caller(m, "0x" + "7" * 40, funded_by="0x" + "9" * 40)
    t.screen("0x" + "7" * 40)  # CLEAR (organic)
    s = t.stats()
    assert s["screens"] == 2
    assert s["refusals"] == 1
    assert s["organic"] == 1
    assert s["organic_pct"] == 50.0
    assert s["manufactured_pct"] == 50.0


def test_stats_empty_is_none_pcts(tmp_path):
    t = _tower(tmp_path)
    s = t.stats()
    assert s["screens"] == 0 and s["organic_pct"] is None


# ---------------------------------------------------------------------------
# FastAPI boundary: paid screen + free verdict feed
# ---------------------------------------------------------------------------
def test_paid_screen_route_is_402_unpaid(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/watch/screen", json={"wallet": "0x" + "5" * 40})
        assert r.status_code == 402  # the paywall gates the screen
        assert "PAYMENT-REQUIRED" in {k.upper() for k in r.headers}


def test_free_verdict_feed_serves_and_lists_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    with TestClient(app) as client:
        # Seed the tower directly (same memory instance the app uses).
        ring = _ring(app.state.memory)
        app.state.watch.screen(ring[0])
        r = client.get("/house/watch")
        assert r.status_code == 200
        body = r.json()
        assert body["stats"]["refusals"] == 1
        assert body["feed"][0]["verdict"] == VERDICT_ABORT
        assert set(body["feed"][0]["ring"]) == set(ring)
        # Manifest lists the new routes.
        manifest = client.get("/manifest").json()
        assert "POST /watch/screen" in manifest["paid"]
        assert "/house/watch" in manifest["free"]


def test_screen_handler_requires_wallet(tmp_path, monkeypatch):
    import asyncio
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()

    class _StubRequest:
        def __init__(self, payload: str):
            self._p = payload
            self.state = type("S", (), {"payment_payload": None})()
            self.query_params = {}

        async def json(self):
            import json
            return json.loads(self._p)

    handler = None
    for route in app.routes:
        if getattr(route, "path", "") == "/watch/screen" and "POST" in getattr(route, "methods", set()):
            handler = getattr(route, "endpoint", None)
            break
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest("{}")))
    assert resp.status_code == 400

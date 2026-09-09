"""Room 4 — the watchtower (market integrity).

Drives the ``Watchtower`` directly (no x402 middleware, no CDP) plus the
FastAPI boundary for the paid screen and the free verdict feed. Every rule is
a pure function of per-caller memory: a wash ring is refused WITH the ring
drawn, and deletion re-admits it — the before/after IS the gate.

Invariants under test:
  * P4b — the serve-path ``consult()`` publishes ONLY ABORT refusals (an
    ordinary CLEAR/HOLD serve must not pollute the public verdict feed).
  * ``funded_by`` now has a WRITER (``note_funding``), so the
    funding-cluster sybil + self-funding rules fire on real declared data,
    not only hand-seeded tests.
  * A watchtower ABORT refusal is a caller-attributable failure and
    books ``caller_fault`` in the trust ledger (a bad actor burns trust with
    every refused attempt).
"""
from __future__ import annotations

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
    """A funding-cluster sybil ring: n callers funded by one root."""
    addrs = []
    for i in range(n):
        addr = "0x" + str(i).zfill(2) + "B" * 37
        _caller(m, addr, funded_by=ROOT,
                dedup_fp=[f"fp-{i}", f"shared-{i % 7}"])
        addrs.append(addr)
    return addrs


# ---------------------------------------------------------------------------
# The rules (each a pure function of per-caller memory)
# ---------------------------------------------------------------------------
def test_self_pay_refused_when_wallet_is_or_funds_the_house(tmp_path):
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    assert t.screen(HOUSE_WALLET)["verdict"] == VERDICT_ABORT  # is the house
    _caller(m, "0x" + "1" * 40, funded_by="0x" + "1" * 40)  # funds itself
    s = t.screen("0x" + "1" * 40)
    assert s["verdict"] == VERDICT_ABORT
    assert any(e["rule"] == R_SELF_PAY for e in s["evidence"])


def test_sybil_ring_refused_with_ring_drawn_and_two_members_clear(tmp_path):
    m = _mem(tmp_path)
    ring = _ring(m)  # 3 members, shared root
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    s = t.screen(ring[0])
    assert s["verdict"] == VERDICT_ABORT
    assert R_SYBIL in [e["rule"] for e in s["evidence"]]
    assert set(s["ring"]) == set(ring)  # the ring is drawn, not implied
    # Threshold edge: 2 same-root members is below WATCH_SYBIL_CLUSTER_MIN.
    m2 = _mem(tmp_path)
    _ring(m2, 2)
    t2 = Watchtower(m2, house_wallet=HOUSE_WALLET)
    assert R_SYBIL not in [e["rule"] for e in
                           t2.screen("0x00B" + "B" * 37)["evidence"]]


def test_factory_cluster_refused_and_diverse_clears(tmp_path):
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    fps = ["fp-1", "fp-2"]
    addrs = ["0x" + "C" * 40, "0x" + "D" * 40, "0x" + "E" * 40]
    for a in addrs:
        _caller(m, a, dedup_fp=fps)  # identical boilerplate
    s = t.screen(addrs[0])
    assert s["verdict"] == VERDICT_ABORT and R_FACTORY in [e["rule"] for e in s["evidence"]]
    assert len(s["ring"]) == 3

    m2 = _mem(tmp_path)
    for i, a in enumerate(addrs):
        _caller(m2, a, dedup_fp=[f"unique-{i}"])  # one shared < OVERLAP (2)
    t2 = Watchtower(m2, house_wallet=HOUSE_WALLET)
    assert R_FACTORY not in [e["rule"] for e in t2.screen(addrs[0])["evidence"]]


def test_hold_rules_flag_without_refusing(tmp_path):
    """cold-start-with-volume and metronome-timing are HOLD — evidence, not a
    refusal. consult() returns None for them (the serve continues); with
    history / irregular timing the same caller clears."""
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)

    cold = "0x" + "3" * 40
    _caller(m, cold, tx_count=1, total_paid_usdc=0.10)  # volume, no history
    sc = t.screen(cold)
    assert sc["verdict"] == VERDICT_HOLD and R_COLD in [e["rule"] for e in sc["evidence"]]
    assert t.consult(cold) is None  # HOLD is evidence, not a refusal
    _caller(m, cold, tx_count=10, total_paid_usdc=0.10)
    assert t.screen(cold)["verdict"] == VERDICT_CLEAR  # history → clears

    met = "0x" + "4" * 40
    _caller(m, met)
    ts = m.get_state("watch_serves") or {}
    m.set_state("watch_serves", {**ts, met.lower(): [1.0, 2.0, 3.0, 4.0]})
    sm = t.screen(met)
    assert sm["verdict"] == VERDICT_HOLD and R_METRONOME in [e["rule"] for e in sm["evidence"]]
    assert t.consult(met) is None
    m.set_state("watch_serves", {**ts, met.lower(): [1.0, 5.0, 7.0, 30.0]})
    assert t.screen(met)["verdict"] == VERDICT_CLEAR  # high CV → organic


# ---------------------------------------------------------------------------
# The funded_by writer: the sybil rule fires on declared data
# ---------------------------------------------------------------------------
def test_note_funding_writer_makes_sybil_fire_on_declared_data(tmp_path):
    """Nothing ever WROTE ``funded_by`` (only tests seeded
    it), so the funding-cluster sybil rule could never fire live. The writer
    (a paid /watch/screen may declare the funding root) now makes it fire:
    declare three callers funded by one root → the sybil ring is drawn."""
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    addrs = [f"0x{str(i).zfill(2)}" + "B" * 36 for i in range(3)]
    # A single (below-threshold) declaration: observed, no ring yet.
    t.note_funding(addrs[0], ROOT)
    assert m.get_entity("caller", addrs[0])["funded_by"] == ROOT.lower()
    assert t.screen(addrs[0])["verdict"] != VERDICT_ABORT  # 1 member < min

    for a in addrs[1:]:
        t.note_funding(a, ROOT)
    s = t.screen(addrs[0])
    assert s["verdict"] == VERDICT_ABORT
    assert R_SYBIL in [e["rule"] for e in s["evidence"]]
    assert set(s["ring"]) == set(addrs)
    # The funding edge is journaled (kind=funding) — the cross-session memory.
    kinds = [(e.get("extra") or {}).get("kind") for e in m.read_events(limit=50)]
    assert "funding" in kinds


# ---------------------------------------------------------------------------
# The serve path: the house refuses to be laundered (uncharged) + caller_fault
# ---------------------------------------------------------------------------
def test_serve_path_refuses_ring_member_uncharged_books_fault_and_serves_clean(tmp_path):
    from core.house import House
    m = _mem(tmp_path)
    ring = _ring(m)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    house = House(m, base_price=0.01, watch=t)

    status, body = house.serve_intel(ring[0])
    assert status == 403 and body["house_declined"] is True
    assert "watchtower" in body["house_refused"]
    assert set(body["watch"]["ring"]) == set(ring)
    assert any(e["verdict"] == VERDICT_ABORT for e in t.feed())  # on screen
    # The refusal is a caller-attributable failure — the ledger books
    # caller_fault, so a bad actor burns trust with every refused attempt.
    row = m.get_entity("caller", ring[0])
    assert row["failure_events"] == 1 and row["warning_events"] == 1
    assert row["trust_score"] < 55.0  # the -8 caller_fault delta landed

    # A clean caller (unique funding root) is served — not refused.
    _caller(m, "0x" + "7" * 40, funded_by="0x" + "9" * 40)
    assert house.serve_intel("0x" + "7" * 40)[0] == 200


# ---------------------------------------------------------------------------
# The serve-path consult must NOT publish ordinary serves
# ---------------------------------------------------------------------------
def test_consult_publishes_only_abort_refusals(tmp_path):
    """A CLEAR and a HOLD consult leave NO feed entry and NO journal screen
    event; only an ABORT refusal is published + journaled."""
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    _caller(m, "0x" + "7" * 40, funded_by="0x" + "9" * 40)      # CLEAR
    _caller(m, "0x" + "3" * 40, tx_count=1, total_paid_usdc=0.10)  # HOLD
    assert t.consult("0x" + "7" * 40) is None
    assert t.consult("0x" + "3" * 40) is None
    assert t.feed() == []
    kinds = [(e.get("extra") or {}).get("kind") for e in m.read_events(limit=50)]
    assert "screen" not in kinds

    ring = _ring(m)  # ABORT
    assert t.consult(ring[0]) is not None
    assert len(t.feed()) == 1 and t.feed()[0]["verdict"] == VERDICT_ABORT
    kinds = [(e.get("extra") or {}).get("kind") for e in m.read_events(limit=50)]
    assert "refuse" in kinds


# ---------------------------------------------------------------------------
# The gate: deletion re-admits the wash caller + writers are no-ops
# ---------------------------------------------------------------------------
def test_deletion_readmits_wash_caller_and_writers_noop(tmp_path, monkeypatch):
    from core.house import House
    m = _mem(tmp_path)
    ring = _ring(m)
    assert Watchtower(m, house_wallet=HOUSE_WALLET).screen(ring[0])["verdict"] == VERDICT_ABORT
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m2 = HouseMemory(str(tmp_path / "memory.db"))
    t_dead = Watchtower(m2, house_wallet=HOUSE_WALLET)
    assert t_dead.screen(ring[0])["verdict"] == VERDICT_CLEAR  # re-admitted
    assert House(m2, base_price=0.01, watch=t_dead).serve_intel(ring[0])[0] == 200
    # The writers are no-ops with memory off: no consult, no funding edge.
    assert t_dead.consult(ring[0]) is None
    assert t_dead.note_funding(ring[0], ROOT) == {}
    assert m2.get_entity("caller", ring[0]) is None


# ---------------------------------------------------------------------------
# Feed + stats (the public face of the room)
# ---------------------------------------------------------------------------
def test_feed_newest_first_capped_and_stats_split(tmp_path):
    m = _mem(tmp_path)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    for i in range(C.WATCH_FEED_MAX + 5):
        t.screen(f"0x{str(i).zfill(40)}")
    feed = t.feed()
    assert len(feed) == C.WATCH_FEED_MAX and feed[0]["ts"] >= feed[-1]["ts"]

    m2 = HouseMemory(str(tmp_path / "stats.db"))
    t2 = Watchtower(m2, house_wallet=HOUSE_WALLET)
    ring = _ring(m2)
    t2.screen(ring[0])                                   # ABORT (manufactured)
    _caller(m2, "0x" + "7" * 40, funded_by="0x" + "9" * 40)
    t2.screen("0x" + "7" * 40)                            # CLEAR (organic)
    s = t2.stats()
    assert s["screens"] == 2 and s["refusals"] == 1 and s["organic"] == 1
    assert s["organic_pct"] == 50.0 and s["manufactured_pct"] == 50.0


# ---------------------------------------------------------------------------
# FastAPI boundary: paid screen + free verdict feed
# ---------------------------------------------------------------------------
def test_paid_screen_is_402_and_feed_serves_rings_and_manifest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/watch/screen", json={"wallet": "0x" + "5" * 40})
        assert r.status_code == 402
        assert "PAYMENT-REQUIRED" in {k.upper() for k in r.headers}

        ring = _ring(app.state.memory)
        app.state.watch.screen(ring[0])
        r = client.get("/house/watch")
        assert r.status_code == 200
        body = r.json()
        assert body["stats"]["refusals"] == 1
        assert body["feed"][0]["verdict"] == VERDICT_ABORT
        assert set(body["feed"][0]["ring"]) == set(ring)
        manifest = client.get("/manifest").json()
        assert "POST /watch/screen" in manifest["paid"]
        assert "/house/watch" in manifest["free"]

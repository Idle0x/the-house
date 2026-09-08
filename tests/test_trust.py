"""F1 TrustLedger tests (specs/trust-model.md + 03-FEATURES F1).

new→regular→vip escalation; risky→banned degradation; first-time pricing;
deletion mode → every caller priced identically at list price.
"""
import os
import uuid

import pytest

from core import config as C
from core.memory import HouseMemory
from core.trust import TrustLedger, compute_segment


@pytest.fixture()
def ledger():
    db = f"/tmp/house_f1_{uuid.uuid4().hex}.db"
    m = HouseMemory(db)
    return TrustLedger(m)


def _mem() -> HouseMemory:
    return HouseMemory(f"/tmp/house_f1_{uuid.uuid4().hex}.db")


def test_new_caller_gets_list_price(ledger):
    addr = "0x" + "1" * 40
    d = ledger.decision(addr)
    assert d.allow is True
    assert d.price_mult == 1.00
    assert d.segment == "new"
    assert d.prepay is False
    assert ledger.recall(addr) is None  # decision didn't mutate


def test_repeat_caller_escalates_to_regular_then_vip(ledger):
    addr = "0x" + "2" * 40
    for i in range(3):
        ledger.update(addr, "served", paid_usdc=0.01)
    d = ledger.decision(addr)
    assert d.segment == "regular"
    assert d.price_mult == C.PRICE_MULT["regular"]

    for i in range(7):  # total 10
        ledger.update(addr, "served", paid_usdc=0.01)
    d = ledger.decision(addr)
    assert d.segment == "vip"
    assert d.price_mult == C.PRICE_MULT["vip"]


def test_bad_actor_drops_to_risky_then_banned(ledger):
    addr = "0x" + "3" * 40
    # 3 caller-faults → risky (warning_events >= 3), prepay required.
    for i in range(3):
        ledger.update(addr, "caller_fault")
    d = ledger.decision(addr)
    assert d.segment == "risky"
    assert d.allow is True
    assert d.prepay is True
    # 3 refunds → banned → refused.
    for i in range(3):
        ledger.update(addr, "refund")
    d = ledger.decision(addr)
    assert d.segment == "banned"
    assert d.allow is False
    assert d.price_mult == 0.0


def test_compute_segment_pure():
    assert compute_segment({"trust_score": 90, "tx_count": 20}) == "vip"
    assert compute_segment({"trust_score": 90, "tx_count": 5}) == "regular"
    assert compute_segment({"trust_score": 30}) == "risky"
    assert compute_segment({"trust_score": 10}) == "banned"
    assert compute_segment({"trust_score": 60, "warning_events": 5}) == "risky"
    assert compute_segment({"trust_score": 60, "refund_events": 3}) == "banned"
    assert compute_segment({}) == "new"


def test_journal_kinds_written(ledger):
    addr = "0x" + "4" * 40
    ledger.update(addr, "served", paid_usdc=0.01)
    ledger.update(addr, "caller_fault")
    evs = ledger.m.read_events()
    kinds = [e.get("extra", {}).get("kind") for e in evs]
    assert "served" in kinds and "caller_fault" in kinds


def test_first_seen_and_last_seen_stamped():
    """H1 fix: caller rows carry real timestamps (was None forever)."""
    addr = "0x" + "7" * 40
    row = TrustLedger(_mem()).on_first(addr)
    assert isinstance(row["first_seen"], float) and row["first_seen"] > 0
    assert isinstance(row["last_seen"], float) and row["last_seen"] > 0
    # update() refreshes last_seen.
    led = TrustLedger(_mem())
    led.on_first(addr)
    led.update(addr, "served", paid_usdc=0.01)
    r2 = led.recall(addr)
    assert r2 is not None and r2["last_seen"] >= r2["first_seen"]


def test_note_dedup_increments_caller_counter():
    """H2 fix: per-caller dedup_hits counter actually increments."""
    addr = "0x" + "8" * 40
    led = TrustLedger(_mem())
    led.on_first(addr)
    led.note_dedup(addr)
    led.note_dedup(addr)
    row = led.recall(addr)
    assert row is not None and row["dedup_hits"] == 2


def test_deletion_mode_vip_and_stranger_price_identically():
    """THE GATE. With memory disabled: a VIP and a stranger are identical.

    First build a real vip row, then disable memory and assert both are
    treated as new at list price — the product's differentiation vanishes.
    """
    db = f"/tmp/house_f1_del_{uuid.uuid4().hex}.db"
    m = HouseMemory(db)
    ledger = TrustLedger(m)
    vip_addr = "0x" + "5" * 40
    for i in range(10):
        ledger.update(vip_addr, "served", paid_usdc=0.01)
    # Sanity: with memory ON the vip is cheap.
    assert ledger.decision(vip_addr).segment == "vip"

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m_disabled = HouseMemory(db)
        ledger_disabled = TrustLedger(m_disabled)
        d_vip = ledger_disabled.decision(vip_addr)
        d_stranger = ledger_disabled.decision("0x" + "6" * 40)
        assert d_vip.allow is True
        assert d_stranger.allow is True
        assert d_vip.price_mult == d_stranger.price_mult == 1.00
        assert d_vip.segment == d_stranger.segment == "new"
        assert d_vip.reason == d_stranger.reason  # identical treatment
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

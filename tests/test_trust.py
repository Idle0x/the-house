"""F1 TrustLedger (specs/trust-model.md + 03-FEATURES F1).

The load-bearing contract: ``compute_segment`` is the single PURE function
every decision surface reads (decision()/update()/serve) — it re-derives the
segment from the live counters, never the possibly-stale stored label (audit
finding 5/6). new→regular→vip escalation, risky→banned degradation, and the
deletion gate (VIP and stranger priced identically when memory is off).
"""
import os
import uuid

from core import config as C
from core.memory import HouseMemory
from core.trust import TrustLedger, compute_segment


def _mem() -> HouseMemory:
    return HouseMemory(f"/tmp/house_f1_{uuid.uuid4().hex}.db")


def test_segment_computation_transitions_and_deletion_gate():
    """One pure function (compute_segment) re-derives the segment from the live
    counters — never the stored label (audit finding 5/6) — and the ledger
    transitions drive it: new→regular (3 serves)→vip (10, trust≥80);
    3 caller_fault→risky (prepay), 3 refunds→banned. A first-time caller is
    allowed at list price. THE GATE: with memory disabled a real VIP and a
    stranger are identical — the product's differentiation vanishes."""
    # Pure function, never the stored label.
    assert compute_segment({"trust_score": 90, "tx_count": 20}) == "vip"
    assert compute_segment({"trust_score": 90, "tx_count": 5}) == "regular"
    assert compute_segment({"trust_score": 30}) == "risky"
    assert compute_segment({"trust_score": 10}) == "banned"
    assert compute_segment({"trust_score": 60, "warning_events": 5}) == "risky"
    assert compute_segment({"trust_score": 60, "refund_events": 3}) == "banned"
    assert compute_segment({}) == "new"

    ledger = TrustLedger(_mem())
    new = "0x" + "1" * 40
    d = ledger.decision(new)
    assert d.allow is True and d.price_mult == 1.00
    assert d.segment == "new" and d.prepay is False

    up = "0x" + "2" * 40
    for _ in range(3):
        ledger.update(up, "served", paid_usdc=0.01)
    assert ledger.decision(up).segment == "regular"
    for _ in range(7):  # total 10
        ledger.update(up, "served", paid_usdc=0.01)
    dv = ledger.decision(up)
    assert dv.segment == "vip" and dv.price_mult == C.PRICE_MULT["vip"]

    bad = "0x" + "3" * 40
    for _ in range(3):
        ledger.update(bad, "caller_fault")
    dr = ledger.decision(bad)
    assert dr.segment == "risky" and dr.allow is True and dr.prepay is True
    for _ in range(3):
        ledger.update(bad, "refund")
    db = ledger.decision(bad)
    assert db.segment == "banned" and db.allow is False and db.price_mult == 0.0

    # THE GATE: deletion collapses a VIP and a stranger to identical treatment.
    db_path = f"/tmp/house_f1_del_{uuid.uuid4().hex}.db"
    m = HouseMemory(db_path)
    vip_addr = "0x" + "5" * 40
    for _ in range(10):
        TrustLedger(m).update(vip_addr, "served", paid_usdc=0.01)
    assert TrustLedger(m).decision(vip_addr).segment == "vip"  # sanity (live)
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        off = TrustLedger(HouseMemory(db_path))
        d_vip = off.decision(vip_addr)
        d_stranger = off.decision("0x" + "6" * 40)
        assert d_vip.price_mult == d_stranger.price_mult == 1.00
        assert d_vip.segment == d_stranger.segment == "new"
        assert d_vip.reason == d_stranger.reason  # identical treatment
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

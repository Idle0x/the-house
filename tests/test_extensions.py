"""E1 SelfAuditor + E2 Calibrator tests (03-FEATURES E1/E2).

Both modules compute from real stores only, so a seeded journal/state must
produce a report that matches a hand calc. (The P4b invariant that the GETs
are read-only and the mutation lives on a token-gated POST /run is tested in
test_seller.) These pin the report CONTRACTS, not every finding code.
"""
import os
import uuid

from core.audit import SelfAuditor
from core.calibrate import Calibrator
from core.memory import HouseMemory


def _mem() -> HouseMemory:
    return HouseMemory(f"/tmp/house_e_{uuid.uuid4().hex}.db")


# ---------------------------------------------------------------------- #
# E1 — SelfAuditor
# ---------------------------------------------------------------------- #
def test_audit_baseline_healthy_and_flags_degradation():
    """The auditor sets a baseline on the first run, then reports healthy with
    no findings; after a baseline, a cluster of route failures (citing the
    compiled scar) + a trust collapse are both detected as degraded findings."""
    # Phase 1: the first audit sets a baseline; with no failures/callers the
    # follow-up is healthy with no findings.
    m = _mem()
    a = SelfAuditor(m)
    assert a.audit()["status"] == "baseline_set"
    assert m.get_state("baseline") is not None
    assert a.audit()["status"] == "healthy"
    assert a.audit()["findings"] == []

    # Phase 2: baseline against a seeded caller, then a cluster of route
    # failures (citing a scar) + a trust collapse → degraded.
    m2 = _mem()
    a2 = SelfAuditor(m2)
    m2.set_entity("caller", "0x" + "1" * 40,
                  {"address": "0x" + "1" * 40, "served_count": 10,
                   "trust_score": 70.0, "tx_count": 10, "segment": "regular"})
    a2.audit()  # baseline (against the seeded caller)

    for i in range(3):
        m2.set_entity("scar", f"S-{i}", {"id": f"S-{i}", "route": "/intel/upstream",
                                         "failure_class": "5xx upstream timeout",
                                         "occurred_at": 1,
                                         "policy_delta": {"rule_id": None, "action": None}})
    m2.set_entity("caller", "0x" + "2" * 40,
                  {"address": "0x" + "2" * 40, "served_count": 5,
                   "trust_score": 30.0, "tx_count": 5, "segment": "risky"})
    report = a2.audit()
    assert report["status"] == "degraded"
    codes = [f["code"] for f in report["findings"]]
    assert "route_failures" in codes and "trust_drift" in codes
    route = next(f for f in report["findings"] if f["code"] == "route_failures")
    assert "/intel/upstream" in route["message"]
    assert route["cites_scar"] is not None


# ---------------------------------------------------------------------- #
# E2 — Calibrator
# ---------------------------------------------------------------------- #
def _seed_known_journal(m: HouseMemory) -> None:
    """Deterministic journal for hand-calc verification.

    served=3, caller_fault=2, refund=1, failure=4 (3 scars + 1 explicit).
    Trust precision = 3/(3+2+1+4) = 0.3. Pricing: 0.02 over 4 txs → avg
    0.005 vs base 0.01 → 50% loyalty discount. Dedup: 2 hits / 4 txs = 50%.
    Scars: 3 recorded, never compiled → 0 policy rules.
    """
    from core.dedup import DedupEngine
    from core.scars import ScarCompiler
    from core.trust import TrustLedger
    ledger = TrustLedger(m)
    addr = "0x" + "3" * 40
    for _ in range(3):
        ledger.update(addr, "served", paid_usdc=0.01)
    for _ in range(2):
        m.write_event("x caller_fault (Δ-8)", kind="caller_fault")
    m.write_event("x refund (Δ-15)", kind="refund")
    m.write_event("scar S-x on /intel/upstream", kind="failure")
    m.set_entity("caller", addr, {"address": addr, "tx_count": 4,
                                  "total_paid_usdc": 0.02, "served_count": 3,
                                  "trust_score": 55, "segment": "new"})
    m.set_entity("caller", "0x" + "4" * 40, {"address": "0x" + "4" * 40,
                                             "tx_count": 0, "total_paid_usdc": 0.0,
                                             "served_count": 0, "trust_score": 50,
                                             "segment": "new"})
    DedupEngine(m).note_repeat(0.01)
    DedupEngine(m).note_repeat(0.01)
    for i in range(3):
        ScarCompiler(m).record("/intel/upstream", "5xx upstream timeout", f"cause {i}")


def test_calibrate_hand_calc_after_compile_and_empty_is_safe():
    """A seeded journal produces a report that matches a hand calc (trust
    precision, realized avg price, loyalty discount, dedup hit-rate, scars); a
    COMPILED scar → a policy rule (rule_rate 1/3); and an empty store
    calibrates to None/zero without erroring. Persists for the next session."""
    m = _mem()
    _seed_known_journal(m)
    r = Calibrator(m, base_price=0.01).calibrate()
    dc = r["decision_counts"]
    assert dc["served"] == 3 and dc["caller_fault"] == 2 and dc["refund"] == 1
    assert abs(r["trust_decision_precision"] - 0.3) < 1e-9
    assert abs(r["pricing"]["realized_avg_usdc"] - 0.005) < 1e-9
    assert abs(r["pricing"]["loyalty_discount"] - 0.5) < 1e-9
    assert abs(r["dedup"]["hit_rate"] - 0.5) < 1e-9
    assert r["scars"]["total"] == 3 and r["scars"]["policy_rules"] == 0
    assert r["report"].startswith("THE HOUSE — calibration report")
    assert m.get_reference("calibration") is not None  # persisted for next session

    # A compiled scar → a policy rule (rule_rate 1/3).
    from core.scars import ScarCompiler
    m2 = _mem()
    s = ScarCompiler(m2)
    for _ in range(3):
        s.record("/intel/upstream", "5xx upstream timeout", "cause")
    s.compile()
    r2 = Calibrator(m2).calibrate()
    assert r2["scars"]["policy_rules"] == 1 and abs(r2["scars"]["rule_rate"] - 1 / 3) < 1e-9

    # An empty store calibrates to None/zero without erroring.
    empty = Calibrator(_mem()).calibrate()
    assert empty["trust_decision_precision"] is None
    assert empty["pricing"]["realized_avg_usdc"] is None
    assert empty["dedup"]["hits"] == 0 and empty["scars"]["total"] == 0

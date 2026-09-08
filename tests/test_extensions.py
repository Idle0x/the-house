"""E1 SelfAuditor + E2 Calibrator tests (03-FEATURES E1/E2).

The spec's test contract: seed a known journal/state → the report numbers
must match a hand calc. Both modules compute from real stores only.
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
def test_first_audit_records_baseline():
    m = _mem()
    a = SelfAuditor(m)
    report = a.audit()
    assert report["status"] == "baseline_set"
    assert report["memory"] == "live"
    # Baseline persisted; second run has something to diff against.
    assert m.get_state("baseline") is not None
    last = a.last_audit()
    assert last is not None and last["status"] == "baseline_set"


def test_audit_healthy_when_nothing_changed():
    m = _mem()
    a = SelfAuditor(m)
    a.audit()  # baseline
    # No new failures, no new callers: healthy.
    report = a.audit()
    assert report["status"] == "healthy"
    assert report["findings"] == []


def test_audit_flags_route_failures_and_cites_scar():
    m = _mem()
    a = SelfAuditor(m)
    # Establish baseline with a couple of served callers (low failure share).
    m.set_entity("caller", "0x" + "1" * 40,
                 {"address": "0x" + "1" * 40, "served_count": 10,
                  "trust_score": 70.0, "tx_count": 10, "segment": "regular"})
    a.audit()

    # After baseline: 3 scarred failures on /intel/upstream (the threshold).
    for i in range(3):
        a.m.set_entity("scar", f"S-{i}", {
            "id": f"S-{i}", "route": "/intel/upstream",
            "failure_class": "5xx upstream timeout", "occurred_at": 1,
            "policy_delta": {"rule_id": None, "action": None}})
    report = a.audit()
    assert report["status"] == "degraded"
    route_findings = [f for f in report["findings"]
                      if f["code"] == "route_failures"]
    assert len(route_findings) == 1
    assert "/intel/upstream" in route_findings[0]["message"]
    assert route_findings[0]["cites_scar"] is not None
    assert "failure_share_rise" in [f["code"] for f in report["findings"]]


def test_audit_trust_drift_detected():
    m = _mem()
    a = SelfAuditor(m)
    m.set_entity("caller", "0x" + "2" * 40,
                 {"address": "0x" + "2" * 40, "served_count": 5,
                  "trust_score": 70.0, "tx_count": 5, "segment": "regular"})
    a.audit()
    # Trust collapses (refunds) after baseline.
    m.set_entity("caller", "0x" + "2" * 40,
                 {"address": "0x" + "2" * 40, "served_count": 5,
                  "trust_score": 30.0, "tx_count": 5, "segment": "risky"})
    report = a.audit()
    codes = [f["code"] for f in report["findings"]]
    assert "trust_drift" in codes


def test_audit_deletion_mode_empty():
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m = _mem()
        a = SelfAuditor(m)
        report = a.audit()
        assert report["status"] == "baseline_set"  # nothing to store, still safe
        # No baseline actually persisted.
        assert a.m.get_state("baseline") is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)


# ---------------------------------------------------------------------- #
# E2 — Calibrator
# ---------------------------------------------------------------------- #
def _seed_known_journal(m: HouseMemory) -> None:
    """Deterministic journal for hand-calc verification.

    Journal kinds (each ScarCompiler.record ALSO journals kind="failure"):
      served=3, caller_fault=2, refund=1, failure=3(scars)+1(explicit)=4.
    Cohort: 2 callers; addr has tx_count=4, total_paid 0.02 ($0.005 avg vs
    base 0.01 → 50% discount). Dedup: 2 hits / 4 txs → 50%. Scars: 3
    recorded (never compiled) → 0 policy rules, rate 0/3.
    Trust precision = served/(served+faults+refunds+failures) = 3/10 = 0.3.
    """
    from core.dedup import DedupEngine
    from core.scars import ScarCompiler
    from core.trust import TrustLedger

    ledger = TrustLedger(m)
    addr = "0x" + "3" * 40
    for _ in range(3):
        ledger.update(addr, "served", paid_usdc=0.01)   # 3 served events
    # Directly journal the rest via the wrapper (kinds are the contract).
    for _ in range(2):
        m.write_event("x caller_fault (Δ-8)", kind="caller_fault")
    m.write_event("x refund (Δ-15)", kind="refund")
    m.write_event("scar S-x on /intel/upstream", kind="failure")
    # Caller rows for cohort + pricing (tx total includes the 3 above + 1).
    m.set_entity("caller", addr, {"address": addr, "tx_count": 4,
                                  "total_paid_usdc": 0.02,
                                  "served_count": 3, "trust_score": 55,
                                  "segment": "new"})
    m.set_entity("caller", "0x" + "4" * 40,
                 {"address": "0x" + "4" * 40, "tx_count": 0,
                  "total_paid_usdc": 0.0, "served_count": 0,
                  "trust_score": 50, "segment": "new"})
    dedup = DedupEngine(m)
    dedup.note_repeat(0.01)
    dedup.note_repeat(0.01)
    scars = ScarCompiler(m)
    for i in range(3):
        scars.record("/intel/upstream", "5xx upstream timeout", f"cause {i}")


def test_calibrate_hand_calc_matches():
    m = _mem()
    _seed_known_journal(m)
    c = Calibrator(m, base_price=0.01)
    r = c.calibrate()

    # served = 3 (ledger) + 0 direct = 3; faults 2, refund 1, failure 4
    # (3 scar records journal kind=failure + 1 explicit).
    assert r["decision_counts"]["served"] == 3
    assert r["decision_counts"]["caller_fault"] == 2
    assert r["decision_counts"]["refund"] == 1
    assert r["decision_counts"]["failure"] == 4
    # trust precision = 3 served / (3+2+1+4) = 3/10
    assert abs(r["trust_decision_precision"] - 0.3) < 1e-9
    # pricing: total paid 0.02 over 4 txs → avg 0.005 → discount 50%.
    assert abs(r["pricing"]["realized_avg_usdc"] - 0.005) < 1e-9
    assert abs(r["pricing"]["loyalty_discount"] - 0.5) < 1e-9
    # dedup: 2 hits / 4 txs → 50%.
    assert abs(r["dedup"]["hit_rate"] - 0.5) < 1e-9
    # scars: 3 recorded + 1 rule compiled after compile() … but we only
    # recorded 3 scars without compiling → rules = 0 unless seeded. Here the
    # seed records scars but never compiles, so rule_rate = 0/3 = 0.
    assert r["scars"]["total"] == 3
    assert r["scars"]["policy_rules"] == 0
    assert r["report"].startswith("THE HOUSE — calibration report")
    # Persisted to REFERENCE for the next session to read.
    ref = m.get_reference("calibration")
    assert ref is not None
    cal = c.last_calibration()
    assert cal is not None and cal["cohort"]["callers"] == 2


def test_calibrate_after_compile_sees_rule():
    m = _mem()
    from core.scars import ScarCompiler
    scars = ScarCompiler(m)
    for _ in range(3):
        scars.record("/intel/upstream", "5xx upstream timeout", "cause")
    scars.compile()
    c = Calibrator(m)
    r = c.calibrate()
    assert r["scars"]["policy_rules"] == 1
    assert abs(r["scars"]["rule_rate"] - 1 / 3) < 1e-9


def test_calibrate_empty_is_safe():
    m = _mem()
    c = Calibrator(m)
    r = c.calibrate()
    assert r["trust_decision_precision"] is None
    assert r["pricing"]["realized_avg_usdc"] is None
    assert r["dedup"]["hits"] == 0
    assert r["scars"]["total"] == 0

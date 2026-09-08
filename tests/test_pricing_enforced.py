"""M0 — the money is real (elevation FIX-1/2/3/4, C1/C2 money-honesty).

These drive the ``House`` engine directly — no x402 middleware, no CDP
facilitator, no network, no acp shell-out. The money claims are the point, so
each asserts what is ACTUALLY owed / refused / journaled, not what a doc says.

Money model under test (verified against the installed x402 2.x exact scheme):
  * onchain settlement is ALWAYS the 402 quote (BASE) — the buyer signs
    EIP-3009 for exactly that and the facilitator re-verifies it at settle.
  * loyalty pricing = settle base, then rebate (base − base×mult) back as a
    real tx. Net = base×mult, reconciles to Basescan.
  * risky ×1.30 → prepay: a risky wallet without a prepay credit is refused
    (403, settlement cancelled → genuinely uncharged); with a credit it serves.
  * repeat → net $0 (base rebated back in full).
  * banned → refused, nothing charged, no fake refund event.
"""
import uuid

import pytest

from core.memory import HouseMemory
from core.house import House
from core.trust import TrustLedger
from core.wallet import DryRunWallet

BASE = 0.01  # USDC list price


def _mk(monkeypatch, tmp_path, *, base=BASE):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(str(tmp_path / "memory.db"))
    return House(m, base_price=base)


# --------------------------------------------------------------------------- #
# VIP / regular — settle base onchain, rebate back, net = base × mult          #
# --------------------------------------------------------------------------- #
def test_vip_settles_base_rebates_back_net_0p80(monkeypatch, tmp_path):
    """A VIP paid base onchain; the house rebates 20% back. Net = 0.80×base.
    The rebate is a real (dry-run here, real acp in prod) journaled tx — not a
    ledger fiction."""
    h = _mk(monkeypatch, tmp_path)
    vip = "0x" + "A" * 40
    # Build VIP standing: 10 successful serves (VIP_MIN_TX) at trust ≥ 80.
    for i in range(10):
        h.serve_intel(vip, {"q": f"vip-{i}"})  # distinct fp each time
    row = h.ledger.recall(vip)
    assert row["segment"] == "vip", row

    # A NEW intel request (new fp) from the VIP:
    status, body = h.serve_intel(vip, {"q": "vip-new-intel"})
    assert status == 200
    assert body["cached"] is False
    # Onchain settlement is base; the house keeps base×0.80; rebates the rest.
    assert body["paid_usdc"] == BASE          # what settled onchain
    assert body["segment_price"] == pytest.approx(BASE * 0.80, abs=1e-9)
    assert body["mult_applied"] == pytest.approx(0.80)
    assert body["rebate_usdc"] == pytest.approx(BASE * 0.20, abs=1e-9)
    # The rebate is a real, journaled tx (dry-run hash — never a fake onchain one)
    assert body["rebate_tx"]
    assert not body["rebate_tx"].startswith("0x")  # dry-run, clearly marked
    # The rebate hit the COLD journal as a real "paid" event.
    events = h.m.read_events()
    assert any("loyalty rebate" in (e.get("acted") or [""])[0]
               for e in events if isinstance(e, dict))


def test_regular_settles_base_rebates_back_net_0p95(monkeypatch, tmp_path):
    """A regular (3+ serves, trust ≥ 40) keeps 95% of base; rebates 5% back."""
    h = _mk(monkeypatch, tmp_path)
    reg = "0x" + "B" * 40
    for i in range(3):
        h.serve_intel(reg, {"q": f"reg-{i}"})
    row = h.ledger.recall(reg)
    assert row["segment"] == "regular", row
    status, body = h.serve_intel(reg, {"q": "reg-new"})
    assert status == 200
    assert body["segment_price"] == pytest.approx(BASE * 0.95, abs=1e-9)
    assert body["rebate_usdc"] == pytest.approx(BASE * 0.05, abs=1e-9)
    assert body["rebate_tx"]


def test_new_caller_pays_full_base_no_rebate(monkeypatch, tmp_path):
    """A stranger pays the full base; nothing is rebated (mult 1.00)."""
    h = _mk(monkeypatch, tmp_path)
    status, body = h.serve_intel("0x" + "1" * 40, {"q": "hello"})
    assert status == 200
    assert body["segment_price"] == pytest.approx(BASE)
    assert body["mult_applied"] == pytest.approx(1.0)
    assert body["rebate_usdc"] == 0.0
    assert body["rebate_tx"] is None


# --------------------------------------------------------------------------- #
# FIX-4a — a repeat is net $0 and does NOT dilute the ledger                  #
# --------------------------------------------------------------------------- #
def test_repeat_is_net_zero_and_does_not_dilute(monkeypatch, tmp_path):
    """C1 money: a repeat settles base onchain but the house rebates the FULL
    base back (net $0) AND the repeat must not bump tx_count / served / trust
    (the old code booked it as a $0 'served' — diluting trust + revenue)."""
    h = _mk(monkeypatch, tmp_path)
    caller = "0x" + "2" * 40
    h.serve_intel(caller, {"q": "same"})           # first serve (counts)
    before = h.ledger.recall(caller)
    tx_before, trust_before = before["tx_count"], before["trust_score"]

    status, body = h.serve_intel(caller, {"q": "same"})   # REPEAT (same fp)
    assert status == 200
    assert body["cached"] is True
    assert body["segment_price"] == 0.0            # net charged: $0
    assert body["mult_applied"] == 0.0
    assert body["rebate_usdc"] == pytest.approx(BASE, abs=1e-9)  # full refund
    after = h.ledger.recall(caller)
    # FIX-4a: tx_count and trust are UNCHANGED by the repeat.
    assert after["tx_count"] == tx_before
    assert after["trust_score"] == pytest.approx(trust_before, abs=1e-9)
    assert after["served_count"] == before["served_count"]
    # Only the dedup hit counter moved.
    assert after["dedup_hits"] == before["dedup_hits"] + 1
    # The repeat's saved revenue is booked on the dedup money counter.
    assert h.dedup.stats()["usdc_saved"] == pytest.approx(BASE, abs=1e-9)


# --------------------------------------------------------------------------- #
# banned — refused, uncharged, no fake refund (C2)                            #
# --------------------------------------------------------------------------- #
def test_banned_refused_no_fake_refund(monkeypatch, tmp_path):
    """C2: a banned wallet is refused with HTTP 403. The x402 middleware
    cancels settlement on >=400, so the buyer is genuinely uncharged. No fake
    'refund' event is booked (no money moved — nothing to refund)."""
    h = _mk(monkeypatch, tmp_path)
    bad = "0x" + "C" * 40
    for _ in range(3):
        h.ledger.update(bad, "refund")            # 3 refunds → banned
    assert h.ledger.decision(bad).segment == "banned"
    refund_events_before = h.ledger.recall(bad)["refund_events"]

    status, body = h.serve_intel(bad, {"q": "buy"})
    assert status == 403
    assert body.get("house_declined") is True
    assert body.get("house_refused")
    # No extra refund event — the money story stays clean.
    assert h.ledger.recall(bad)["refund_events"] == refund_events_before


# --------------------------------------------------------------------------- #
# risky ×1.30 — enforced as Decision.prepay (the money consequence)           #
# --------------------------------------------------------------------------- #
def _make_risky(h, addr):
    """Drive a caller into the risky segment (trust < 40 via 3 warnings)."""
    for _ in range(3):
        h.ledger.update(addr, "caller_fault")
    return h.ledger.recall(addr)


def test_risky_without_prepay_is_refused_uncharged(monkeypatch, tmp_path):
    """The onchain settlement is fixed at base — the +30% cannot be extracted
    from the buyer's EIP-3009 signature. So a risky wallet without a prepay
    credit is refused (403, settlement cancelled → uncharged). The refusal
    carries the exact prepay amount owed."""
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "D" * 40
    row = _make_risky(h, risky)
    assert row["segment"] == "risky", row
    status, body = h.serve_intel(risky, {"q": "intel"})
    assert status == 403
    assert body.get("decision") == "prepay"
    assert body.get("prepay_required") == pytest.approx(BASE * 0.30, abs=1e-9)
    assert body.get("prepay_on_file", 0.0) == pytest.approx(0.0)
    # Refused → nothing served, no revenue booked, no job settled.
    after = h.ledger.recall(risky)
    assert after["served_count"] == 0
    assert after["total_paid_usdc"] == pytest.approx(0.0)


def test_risky_with_prepay_serves_and_debits(monkeypatch, tmp_path):
    """A risky wallet WITH a prepay credit covering the surcharge is served.
    The credit is debited (a real ledger debit, journaled). Net = base×1.30,
    and because the house only collected base onchain, the +30% comes out of
    the prepay credit — the money is real, not a label."""
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "E" * 40
    _make_risky(h, risky)
    surcharge = round(BASE * 0.30, 6)
    # Top up a prepay credit ≥ the surcharge.
    row = h.m.get_entity("caller", risky)
    row["prepay_usdc"] = surcharge
    h.m.set_entity("caller", risky, row)

    status, body = h.serve_intel(risky, {"q": "intel"})
    assert status == 200
    assert body["segment_price"] == pytest.approx(BASE * 1.30, abs=1e-9)
    assert body["mult_applied"] == pytest.approx(1.30)
    # The prepay credit was debited (covers the +30% the onchain tx didn't).
    after = h.ledger.recall(risky)
    assert after["prepay_usdc"] == pytest.approx(0.0, abs=1e-9)
    events = h.m.read_events()
    assert any("prepay debit" in (e.get("acted") or [""])[0]
               for e in events if isinstance(e, dict))


def test_risky_prepay_partial_still_refused(monkeypatch, tmp_path):
    """A prepay credit that does NOT fully cover the surcharge is still a
    refusal — no partial-credit edge case leaks a free serve."""
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "F" * 40
    _make_risky(h, risky)
    row = h.m.get_entity("caller", risky)
    row["prepay_usdc"] = round(BASE * 0.10, 6)   # only 10%, need 30%
    h.m.set_entity("caller", risky, row)
    status, body = h.serve_intel(risky, {"q": "intel"})
    assert status == 403
    assert body.get("decision") == "prepay"
    assert h.ledger.recall(risky)["served_count"] == 0


# --------------------------------------------------------------------------- #
# FIX-2 — scar policy cite: 3 same-class failures → hardening, cited on serve  #
# --------------------------------------------------------------------------- #
def test_scar_policy_cited_on_serve(monkeypatch, tmp_path):
    """3 same (route, failure_class) scars compile into a policy rule; the
    next serve consults it (apply_policy in the serve path) and the response
    carries scar_cited — the memory is cited in the response, not just in the
    ledger."""
    h = _mk(monkeypatch, tmp_path)
    caller = "0x" + "3" * 40
    # Inject 3 house-side failures on this route (deterministic, no network).
    for _ in range(3):
        h.scars.record("/intel/quote", "5xx upstream timeout", "provider timed out")
    h.scars.compile()
    rules = h.scars.active_rules()
    assert len(rules) >= 1
    # A fresh serve for this caller now cites the compiled rule.
    status, body = h.serve_intel(caller, {"q": "hello"})
    # Depending on the compiled action (retry_budget / prepay / refuse), the
    # serve either cites the rule and proceeds, or refuses with a cite. Either
    # way the memory is VISIBLE in the response — the core of FIX-2.
    assert status in (200, 403)
    cited = body.get("scar_cited")
    assert cited, f"expected a scar_cited field; got {body}"


# --------------------------------------------------------------------------- #
# FIX-3 — the executor actually re-drives a job killed mid-serve               #
# --------------------------------------------------------------------------- #
def test_executor_redrives_killed_serving_job_idempotently(monkeypatch, tmp_path):
    """F4: a job left at phase=serving by a kill -9 is re-driven by the
    executor on restart and settles idempotently (one settlement, no double
    charge). Before FIX-3, resume_all() found the job and stopped."""
    from core.executor import JobExecutor
    from core.jobs import JobStateMachine
    m = HouseMemory(str(tmp_path / "memory.db"))
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    jobs = JobStateMachine(m)
    caller = "0x" + "5" * 40
    # "Process A" starts a job and is killed mid-serve (stays at serving).
    job = jobs.start(caller, "/intel/quote", "fp-x")
    jid = job["id"]
    jobs.advance(jid, "serving", step="serve", payment_state="verified")
    assert jobs.get(jid)["phase"] == "serving"

    # "Process B" (restart): the executor re-drives it. _drive settles
    # idempotently.
    h = House(m, base_price=BASE)
    driven = h.startup()["driven"]
    assert jid in driven
    assert jobs.get(jid)["phase"] == "settled"
    # Idempotency: settling again is a no-op (no second settlement, no
    # duplicate job row).
    n_settled_before = len([j for j in jobs.snapshot(50)
                            if j.get("id") == jid])
    h.jobs.settle(jid, caller)
    assert jobs.get(jid)["phase"] == "settled"
    assert len([j for j in jobs.snapshot(50) if j.get("id") == jid]) == 1


def test_deletion_mode_executor_finds_nothing(monkeypatch, tmp_path):
    """SIBYL_DISABLED=1: no job state survives, so the executor re-drives
    nothing (the deletion degradation — idempotency died with the memory)."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    m = HouseMemory(str(tmp_path / "memory.db"))
    h = House(m, base_price=BASE)
    assert h.startup()["resumed"] == 0
    assert h.startup()["driven"] == []


# --------------------------------------------------------------------------- #
# FIX-4 — settlement journal is idempotent by tx (reconcile to Basescan)       #
# --------------------------------------------------------------------------- #
def test_settlement_journal_idempotent_by_tx(monkeypatch, tmp_path):
    """The journal records each settlement once; a re-delivered PAYMENT-
    RESPONSE header (same tx) must NOT double-count revenue."""
    from core.settle_journal import SettlementJournal, decode_settlement_header
    m = HouseMemory(str(tmp_path / "memory.db"))
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    j = SettlementJournal(m)
    entry = {"tx": "0x" + "9" * 64, "payer": "0x" + "A" * 40,
             "route": "/intel/quote", "amount_usdc": 0.01,
             "amount_atomic": 10000, "kind": "settlement"}
    assert j.record(entry) is True
    assert j.count() == 1
    assert j.total_usdc() == pytest.approx(0.01)
    # Same tx re-delivered → not recorded again.
    assert j.record(dict(entry)) is False
    assert j.count() == 1
    assert j.total_usdc() == pytest.approx(0.01)


def test_decode_settlement_header_roundtrip(monkeypatch):
    """decode_settlement_header parses a real PAYMENT-RESPONSE (base64
    SettleResponse) and normalizes the atomic USDC amount to dollars."""
    import base64, json
    from core.settle_journal import decode_settlement_header
    settle = {"success": True, "transaction": "0x" + "7" * 64,
              "payer": "0x" + "A" * 40, "amount": "10000",
              "network": "eip155:8453"}
    header = base64.b64encode(json.dumps(settle).encode()).decode()
    entry = decode_settlement_header(header)
    assert entry is not None
    assert entry["tx"] == "0x" + "7" * 64
    assert entry["payer"] == "0x" + "A" * 40
    assert entry["amount_usdc"] == pytest.approx(0.01)  # 10000 / 1e6
    assert decode_settlement_header(None) is None
    assert decode_settlement_header("not-base64!!!") is None


# --------------------------------------------------------------------------- #
# Deletion harness — the business model collapses (the gate)                   #
# --------------------------------------------------------------------------- #
def test_deletion_mode_all_callers_new_list_price(monkeypatch, tmp_path):
    """SIBYL_DISABLED=1: every caller is 'new' at list price, no dedup, no
    refusal, no rebate, no prepay. The house forgets everyone — the business
    model collapses to a stateless price list."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    m = HouseMemory(str(tmp_path / "memory.db"))
    h = House(m, base_price=BASE)
    caller = "0x" + "6" * 40
    # Even after 10 serves, the caller is still 'new' (nothing remembered).
    for i in range(3):
        h.serve_intel(caller, {"q": f"q{i}"})
    status, body = h.serve_intel(caller, {"q": "again"})
    assert status == 200
    assert body["standing"]["segment"] == "new"
    assert body["mult_applied"] == pytest.approx(1.0)
    assert body["rebate_usdc"] == 0.0
    # A repeat is NOT detected in deletion mode (no dedup memory).
    status2, body2 = h.serve_intel(caller, {"q": "again"})
    assert body2["cached"] is False


def test_deletion_mode_refuses_nothing(monkeypatch, tmp_path):
    """SIBYL_DISABLED=1: even a would-be banned wallet is treated as new
    (the refusal memory is gone) — the house declines nothing."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    m = HouseMemory(str(tmp_path / "memory.db"))
    h = House(m, base_price=BASE)
    # A wallet that would be banned with memory ON is 'new' with it OFF.
    status, body = h.serve_intel("0x" + "C" * 40, {"q": "buy"})
    assert status == 200
    assert body["standing"]["segment"] == "new"


# --------------------------------------------------------------------------- #
# DryRunWallet — the safe default never touches a real wallet                  #
# --------------------------------------------------------------------------- #
def test_dry_run_wallet_moves_no_money_and_marks_tx(monkeypatch, tmp_path):
    """DryRunWallet returns a clearly-marked pseudo hash (never a 0x… onchain
    one) and journals the intent — no acp call, no money moved."""
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(str(tmp_path / "memory.db"))
    w = DryRunWallet(m)
    tx = w.send_usdc("0x" + "A" * 40, 0.002, "loyalty rebate seg×0.8")
    assert not tx.startswith("0x")          # not a real onchain hash
    assert "dry" in tx
    events = m.read_events()
    assert any("[DRY-RUN]" in (e.get("acted") or [""])[0]
               for e in events if isinstance(e, dict))

"""Room 1 — the money engine (``core.house.House``), driven directly.

No x402 middleware, no CDP facilitator, no network, no acp shell-out. Every
test asserts what is ACTUALLY owed / refused / journaled / re-run, not what a
doc says. This is also where the serve-path integrity invariants from the
codebase audit live, because they are about the same ``serve_intel`` money
flow: a repeat is served from cache BEFORE work (and never resets the
original settled job), a refusal is a pure read that leaves no job, and a
mid-serve kill settles exactly once.

Money model (verified against the installed x402 2.x exact scheme):
  * onchain settlement is ALWAYS the 402 quote (base) — the buyer signs
    EIP-3009 for exactly that and the facilitator re-verifies at settle.
  * loyalty pricing = settle base, then rebate (base − base×mult) back as a
    real journaled tx. Net = base×mult, reconciles to Basescan.
  * risky ×1.30 → prepay: a risky wallet without a credit is refused
    (403, settlement cancelled → genuinely uncharged); with a credit it serves.
  * repeat → net $0 (base rebated back in full), served from cache, no work.
  * banned → refused, nothing charged, no fake refund event.
"""
import os

import pytest

from core.dedup import fingerprint
from core.memory import HouseMemory
from core.house import House
from core.wallet import DryRunWallet

BASE = 0.01  # USDC list price


def _mk(monkeypatch, tmp_path, *, base=BASE, watch=None):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(str(tmp_path / "memory.db"))
    return House(m, base_price=base, watch=watch)


# --------------------------------------------------------------------------- #
# Loyalty: settle base onchain, rebate the difference back                     #
# --------------------------------------------------------------------------- #
def test_loyalty_rebates_net_the_segment_price(monkeypatch, tmp_path):
    """Settle base onchain, rebate (base − base×mult) back as a real (dry)
    journaled tx: VIP nets 0.80 (rebate 0.20), regular nets 0.95 (rebate
    0.05), a stranger pays full base with no rebate. Net = base×mult."""
    h = _mk(monkeypatch, tmp_path)

    vip = "0x" + "A" * 40
    for i in range(10):  # 10 serves → vip (VIP_MIN_TX), trust ≥ 80
        h.serve_intel(vip, {"q": f"vip-{i}"})
    assert h.ledger.recall(vip)["segment"] == "vip"
    status, body = h.serve_intel(vip, {"q": "vip-new"})
    assert status == 200 and body["cached"] is False
    assert body["paid_usdc"] == BASE  # what settled onchain
    assert body["segment_price"] == pytest.approx(BASE * 0.80, abs=1e-9)
    assert body["rebate_usdc"] == pytest.approx(BASE * 0.20, abs=1e-9)
    assert body["rebate_tx"] and not body["rebate_tx"].startswith("0x")  # dry
    assert any("loyalty rebate" in (e.get("acted") or [""])[0]
               for e in h.m.read_events())

    reg = "0x" + "B" * 40
    for i in range(3):
        h.serve_intel(reg, {"q": f"reg-{i}"})
    _, b = h.serve_intel(reg, {"q": "reg-new"})
    assert b["segment_price"] == pytest.approx(BASE * 0.95, abs=1e-9)
    assert b["rebate_usdc"] == pytest.approx(BASE * 0.05, abs=1e-9)

    _, bn = h.serve_intel("0x" + "1" * 40, {"q": "hello"})  # stranger
    assert bn["segment_price"] == pytest.approx(BASE)
    assert bn["mult_applied"] == 1.0 and bn["rebate_usdc"] == 0.0


# --------------------------------------------------------------------------- #
# F2 repeat: net $0, served from cache, no re-run, no dilution, no job reset   #
# --------------------------------------------------------------------------- #
def test_repeat_served_from_cache_no_rerun_honest_counter_no_job_reset(monkeypatch, tmp_path):
    """The repeat path, end to end (the audited SEV-1 #1): the 2nd identical
    request is (a) served from the ORIGINAL answer, (b) net $0, (c) does NOT
    re-run the expensive work — even with the upstream down — and (d) does NOT
    bump tx_count/trust. The compute-avoided counter credits only the true
    cache hit, and the original serve's job row stays settled exactly once
    (a repeat never resets it / writes a second 'settled by')."""
    h = _mk(monkeypatch, tmp_path)
    calls = {"n": 0}

    def counting(p: str) -> dict:
        calls["n"] += 1
        return {"intel": f"answer-{calls['n']}", "seq": calls["n"]}
    h._do_work = counting

    st1, b1 = h.serve_intel("0x" + "2" * 40, {"q": "same"})
    before = h.ledger.recall("0x" + "2" * 40)
    orig_jid = h.jobs.snapshot(limit=500)[0]["id"]

    # Upstream dies AFTER the first serve cached a good answer.
    def down(p: str) -> dict:
        raise TimeoutError("5xx upstream timeout")
    h._do_work = down

    st2, b2 = h.serve_intel("0x" + "2" * 40, {"q": "same"})
    assert st2 == 200, f"repeat with down upstream must 200 from cache, got {st2}"
    assert b2["cached"] is True
    assert b2["seq"] == 1, "repeat served a recomputed answer, not the cache"
    assert calls["n"] == 1, "repeat re-ran the expensive work"
    assert b2["segment_price"] == 0.0 and b2["mult_applied"] == 0.0
    assert b2["rebate_usdc"] == pytest.approx(BASE, abs=1e-9)  # full refund

    after = h.ledger.recall("0x" + "2" * 40)
    assert after["tx_count"] == before["tx_count"]  # no dilution
    assert after["trust_score"] == pytest.approx(before["trust_score"], abs=1e-9)
    assert after["dedup_hits"] == before["dedup_hits"] + 1
    assert h.dedup.stats()["usdc_saved"] == pytest.approx(BASE, abs=1e-9)

    # The original serve's job row is untouched: one row, still settled once.
    jobs = h.jobs.snapshot(limit=500)
    assert len(jobs) == 1 and jobs[0]["id"] == orig_jid and jobs[0]["phase"] == "settled"
    settled = [" ".join(e.get("acted") or []) for e in h.m.read_events(limit=200)
               if "settled by" in " ".join(e.get("acted") or []) and orig_jid in
               " ".join(e.get("acted") or [])]
    assert len(settled) == 1, f"expected ONE settle for {orig_jid}, got {len(settled)}"

    # compute-avoided honesty: wipe the disk cache → a repair re-runs the work
    # once (no credit); the next true hit credits exactly one. A FRESH db so
    # the main scenario's repeat above does not pollute this counter.
    h2 = House(HouseMemory(str(tmp_path / "repair.db")), base_price=BASE)
    c2 = {"n": 0}
    h2._do_work = lambda p: (c2.__setitem__("n", c2["n"] + 1),
                             {"intel": f"a{c2['n']}"})[1]
    h2.serve_intel("0x" + "3" * 40, {"q": "y"})
    fp = fingerprint("/intel/quote", {"q": "y"})
    os.remove(h2.dedup._fp_path(fp))  # wipe the disk cache, keep the fp list
    h2.serve_intel("0x" + "3" * 40, {"q": "y"})   # repair re-run (work runs)
    assert c2["n"] == 2
    h2.serve_intel("0x" + "3" * 40, {"q": "y"})   # true cache hit (no work)
    assert c2["n"] == 2
    stats = h2.dedup.stats()
    assert stats["hits"] == 2
    assert stats["compute_avoided_usd"] == pytest.approx(0.001)  # only the hit


# --------------------------------------------------------------------------- #
# Refusals are PURE READS: uncharged, journaled, and leave NO job              #
# --------------------------------------------------------------------------- #
def test_banned_refused_uncharged_no_fake_refund_no_job(monkeypatch, tmp_path):
    """C2: a banned wallet is refused 403 (settlement cancelled → uncharged),
    journaled as kind=refuse, and — the audited SEV — leaves NO job the
    executor could later 'settle' as paid. No fake refund event either."""
    h = _mk(monkeypatch, tmp_path)
    bad = "0x" + "C" * 40
    for _ in range(3):
        h.ledger.update(bad, "refund")  # 3 refunds → banned
    refunds_before = h.ledger.recall(bad)["refund_events"]

    status, body = h.serve_intel(bad, {"q": "buy"})
    assert status == 403 and body.get("house_declined") is True
    assert h.jobs.pending_count() == 0, "a refusal must leave no job"
    assert h.ledger.recall(bad)["refund_events"] == refunds_before  # no fake refund
    kinds = [(e.get("extra") or {}).get("kind") for e in h.m.read_events()]
    assert "refuse" in kinds


def test_risky_prepay_refused_then_served_with_credit(monkeypatch, tmp_path):
    """Risky ×1.30 can't ride the buyer's fixed EIP-3009 signature, so it is
    enforced as Decision.prepay: without a credit → 403 (uncharged, no job,
    journaled); with a credit covering the surcharge → served at ×1.30, credit
    debited (kind=prepay), net = base×1.30."""
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "E" * 40
    for _ in range(3):
        h.ledger.update(risky, "caller_fault")  # → risky
    assert h.ledger.recall(risky)["segment"] == "risky"

    status, body = h.serve_intel(risky, {"q": "intel"})
    assert status == 403 and body.get("decision") == "prepay"
    assert body.get("prepay_required") == pytest.approx(BASE * 0.30, abs=1e-9)
    assert h.jobs.pending_count() == 0, "a refusal must leave no job"
    assert h.ledger.recall(risky)["served_count"] == 0
    kinds = [(e.get("extra") or {}).get("kind") for e in h.m.read_events()]
    assert "refuse" in kinds

    # Fund a credit ≥ the surcharge (the top-up path) → served, debited.
    row = h.m.get_entity("caller", risky)
    row["prepay_usdc"] = round(BASE * 0.30, 6)
    h.m.set_entity("caller", risky, row)
    status, body = h.serve_intel(risky, {"q": "intel"})
    assert status == 200 and body["mult_applied"] == pytest.approx(1.30)
    assert h.ledger.recall(risky)["prepay_usdc"] == pytest.approx(0.0, abs=1e-9)
    kinds = [(e.get("extra") or {}).get("kind") for e in h.m.read_events()]
    assert "prepay" in kinds


def test_restart_after_refusal_settles_nothing(monkeypatch, tmp_path):
    """End-to-end (the audited SEV-1 #2): a refusal → process restart →
    startup() drives nothing and fabricates no 'settled by' event for the
    uncharged refusal. A refusal is a pure read, so there is nothing to settle."""
    db = str(tmp_path / "memory.db")
    monkeypatch.setenv("HOUSE_MEMORY_DB", db)
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(db)
    h = House(m, base_price=BASE)
    risky = "0x" + "4" * 40
    for _ in range(3):
        h.ledger.update(risky, "caller_fault")
    assert h.serve_intel(risky, {"q": "intel"})[0] == 403

    m2 = HouseMemory(db)
    h2 = House(m2, base_price=BASE)
    report = h2.startup()
    assert report["resumed"] == 0 and report["driven"] == []
    settled = [" ".join(e.get("acted") or []) for e in m2.read_events(limit=100)
               if "settled by" in " ".join(e.get("acted") or [])]
    assert settled == [], "executor fabricated a settle for an uncharged refusal"


# --------------------------------------------------------------------------- #
# F4 — the executor re-drives a job killed mid-serve, idempotently             #
# --------------------------------------------------------------------------- #
def test_executor_redrives_killed_serving_job_idempotently(monkeypatch, tmp_path):
    """A job left at phase=serving by a kill -9 is re-driven on restart and
    settles idempotently — one settlement, no double charge, no second row."""
    from core.jobs import JobStateMachine
    m = HouseMemory(str(tmp_path / "memory.db"))
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    jobs = JobStateMachine(m)
    caller = "0x" + "5" * 40
    jid = jobs.start(caller, "/intel/quote", "fp-x")["id"]
    jobs.advance(jid, "serving", step="serve", payment_state="verified")

    h = House(m, base_price=BASE)
    assert jid in h.startup()["driven"]
    assert jobs.get(jid)["phase"] == "settled"
    h.jobs.settle(jid, caller)  # idempotent: settling again is a no-op
    assert jobs.get(jid)["phase"] == "settled"
    assert len([j for j in jobs.snapshot(50) if j["id"] == jid]) == 1


# --------------------------------------------------------------------------- #
# FIX-4 — settlement journal is idempotent by tx (reconcile to Basescan)        #
# --------------------------------------------------------------------------- #
def test_settlement_journal_idempotent_by_tx_and_header_decode(monkeypatch, tmp_path):
    """The journal records each settlement tx once; a re-delivered header (same
    tx) does not double-count revenue. decode_settlement_header parses a real
    base64 PAYMENT-RESPONSE and normalizes atomic USDC → dollars."""
    import base64, json
    from core.settle_journal import SettlementJournal, decode_settlement_header
    m = HouseMemory(str(tmp_path / "memory.db"))
    j = SettlementJournal(m)
    entry = {"tx": "0x" + "9" * 64, "payer": "0x" + "A" * 40,
             "route": "/intel/quote", "amount_usdc": 0.01,
             "amount_atomic": 10000, "kind": "settlement"}
    assert j.record(entry) is True and j.count() == 1
    assert j.record(dict(entry)) is False and j.count() == 1  # idempotent
    assert j.total_usdc() == pytest.approx(0.01)

    settle = {"success": True, "transaction": "0x" + "7" * 64,
              "payer": "0x" + "A" * 40, "amount": "10000", "network": "eip155:8453"}
    decoded = decode_settlement_header(base64.b64encode(json.dumps(settle).encode()).decode())
    assert decoded["tx"] == "0x" + "7" * 64
    assert decoded["amount_usdc"] == pytest.approx(0.01)
    assert decode_settlement_header(None) is None


# --------------------------------------------------------------------------- #
# Deletion harness + the safe money-out default                                #
# --------------------------------------------------------------------------- #
def test_deletion_mode_forgets_everyone_refuses_nothing(monkeypatch, tmp_path):
    """SIBYL_DISABLED=1: every caller is 'new' at list price — no loyalty, no
    dedup (a repeat is not detected), and even a would-be banned wallet is
    served. The business model collapses to a stateless price list."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    h = House(HouseMemory(str(tmp_path / "memory.db")), base_price=BASE)
    caller = "0x" + "6" * 40
    for i in range(3):
        h.serve_intel(caller, {"q": f"q{i}"})
    status, body = h.serve_intel(caller, {"q": "again"})
    assert body["standing"]["segment"] == "new"
    assert body["mult_applied"] == pytest.approx(1.0) and body["rebate_usdc"] == 0.0
    assert h.serve_intel(caller, {"q": "again"})[1]["cached"] is False  # no dedup
    status, b2 = h.serve_intel("0x" + "C" * 40, {"q": "buy"})  # would-be banned
    assert status == 200 and b2["standing"]["segment"] == "new"


def test_dry_run_wallet_moves_no_money_and_marks_tx(monkeypatch, tmp_path):
    """DryRunWallet — the safe default — returns a clearly-marked pseudo hash
    (never a 0x… onchain one) and journals the intent: no acp call, no money."""
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(str(tmp_path / "memory.db"))
    w = DryRunWallet(m)
    tx = w.send_usdc("0x" + "A" * 40, 0.002, "loyalty rebate seg×0.8")
    assert not tx.startswith("0x") and "dry" in tx
    assert any("[DRY-RUN]" in (e.get("acted") or [""])[0] for e in m.read_events())

"""P0 audit-fix regression tests (Full Codebase Audit Report).

Each test pins one SEV finding that the old serve path violated:

* repeat must short-circuit to the cache BEFORE ``_do_work`` (SEV-1 #1) —
  a down upstream must not 502 / scar a repeat with a good cached answer;
* a risky-prepay refusal must NOT leave an accepted job that a restart
  later "settles" as paid (SEV-1 #2);
* a repeat must NOT reset the original serve's settled job row / double-
  journal "settled by …" for the same job id (SEV-1 #3);
* ``compute_avoided_usd`` is credited only when compute was truly avoided;
* banned / risky / policy refusals are COLD-journaled (kind=refuse).
"""
import uuid

import pytest

from core.memory import HouseMemory
from core.house import House
from core.dedup import fingerprint

BASE = 0.01
CALLER = "0x" + "1" * 40


def _mk(monkeypatch, tmp_path, *, do_work=None, watch=None):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(str(tmp_path / "memory.db"))
    return House(m, base_price=BASE, do_work=do_work, watch=watch)


def _count_work_calls(h: House, payer: str, q: str) -> tuple[int, dict, dict]:
    """Serve the same fp twice and count do_work invocations."""
    calls = {"n": 0}

    def counting(p: str) -> dict:
        calls["n"] += 1
        return {"intel": f"answer-{calls['n']}", "seq": calls["n"]}

    h._do_work = counting
    st, b1 = h.serve_intel(payer, {"q": q})
    assert st == 200 and b1["cached"] is False
    st, b2 = h.serve_intel(payer, {"q": q})
    assert st == 200 and b2["cached"] is True
    return calls["n"], b1, b2


# --------------------------------------------------------------------------- #
# SEV-1 #1 — the repeat path must not re-run the expensive work
# --------------------------------------------------------------------------- #
def test_repeat_does_not_invoke_do_work(monkeypatch, tmp_path):
    """F2: one serve + one repeat = exactly ONE do_work invocation."""
    h = _mk(monkeypatch, tmp_path)
    n, _, _ = _count_work_calls(h, CALLER, "same")
    assert n == 1, f"repeat re-ran the work: {n} invocations"


def test_repeat_serves_cached_answer_not_fresh(monkeypatch, tmp_path):
    """The repeat body must be the ORIGINAL answer (cache), not a recompute."""
    h = _mk(monkeypatch, tmp_path)
    _, b1, b2 = _count_work_calls(h, CALLER, "same")
    assert b1["seq"] == 1
    assert b2["seq"] == 1, "repeat served a recomputed answer, not the cache"


def test_repeat_with_down_upstream_still_serves_cache(monkeypatch, tmp_path):
    """The audited failure: healthy serve caches GOOD ANSWER, then upstream
    dies → the repeat must return 200 with the cached answer, NOT 502 + scar."""
    h = _mk(monkeypatch, tmp_path)
    st, b1 = h.serve_intel(CALLER, {"q": "x"})
    assert st == 200

    def down(payer: str) -> dict:
        raise TimeoutError("5xx upstream timeout")

    h._do_work = down
    st2, b2 = h.serve_intel(CALLER, {"q": "x"})
    assert st2 == 200, f"repeat with down upstream returned {st2}: {b2}"
    assert b2["cached"] is True
    assert "scar_id" not in b2
    # The repeat was genuinely served from cache → compute_avoided credited.
    assert h.dedup.stats()["compute_avoided_usd"] == pytest.approx(0.001)


def test_compute_avoided_not_credited_when_work_ran(monkeypatch, tmp_path):
    """A repeat whose cache file is missing (fp on row, file gone) re-runs the
    work once — so the compute counter must NOT claim it was avoided."""
    h = _mk(monkeypatch, tmp_path)
    calls = {"n": 0}

    def counting(p: str) -> dict:
        calls["n"] += 1
        return {"intel": f"answer-{calls['n']}", "seq": calls["n"]}

    h._do_work = counting
    st, _ = h.serve_intel(CALLER, {"q": "y"})
    assert st == 200 and calls["n"] == 1
    fp = fingerprint("/intel/quote", {"q": "y"})
    # Simulate the disk cache being wiped while the fp list survives.
    import os
    os.remove(h.dedup._fp_path(fp))

    # Repeat with NO cache → repair re-runs the work once, serves net $0.
    st2, b2 = h.serve_intel(CALLER, {"q": "y"})
    assert st2 == 200
    assert b2["cached"] is True and b2["segment_price"] == 0.0
    assert calls["n"] == 2  # original + one repair re-run
    # A THIRD identical request now hits the repaired cache → no work.
    st3, b3 = h.serve_intel(CALLER, {"q": "y"})
    assert st3 == 200 and b3["cached"] is True
    assert calls["n"] == 2, "post-repair repeat must serve from cache"
    stats = h.dedup.stats()
    assert stats["hits"] == 2  # two repeats (repair + cache hit)
    assert stats["usdc_saved"] == pytest.approx(BASE * 2)
    assert stats["compute_avoided_usd"] == pytest.approx(0.001), \
        "only ONE of three repeats avoided compute (the post-repair one); " \
        "the repair re-ran work and must not be credited"


# --------------------------------------------------------------------------- #
# SEV-1 #2 — a refusal must not leave a job the executor later settles
# --------------------------------------------------------------------------- #
def test_risky_refusal_leaves_no_pending_job(monkeypatch, tmp_path):
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "2" * 40
    for _ in range(3):
        h.ledger.update(risky, "caller_fault")  # → risky
    st, body = h.serve_intel(risky, {"q": "intel"})
    assert st == 403 and body.get("decision") == "prepay"
    assert h.jobs.pending_count() == 0, \
        "a refused request must not leave a job the executor will settle"


def test_banned_refusal_leaves_no_pending_job(monkeypatch, tmp_path):
    h = _mk(monkeypatch, tmp_path)
    bad = "0x" + "3" * 40
    for _ in range(3):
        h.ledger.update(bad, "refund")  # → banned
    st, _ = h.serve_intel(bad, {"q": "x"})
    assert st == 403
    assert h.jobs.pending_count() == 0


def test_restart_after_risky_refusal_settles_nothing(monkeypatch, tmp_path):
    """Probe 3 end-to-end: refusal → restart → startup() must drive nothing
    and write no 'settled by' paid event for the uncharged refusal."""
    db = str(tmp_path / "memory.db")
    monkeypatch.setenv("HOUSE_MEMORY_DB", db)
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(db)
    h = House(m, base_price=BASE)
    risky = "0x" + "4" * 40
    for _ in range(3):
        h.ledger.update(risky, "caller_fault")
    st, _ = h.serve_intel(risky, {"q": "intel"})
    assert st == 403

    m2 = HouseMemory(db)
    h2 = House(m2, base_price=BASE)
    report = h2.startup()
    assert report["resumed"] == 0 and report["driven"] == []
    settled_events = [
        " ".join(e.get("acted") or []) for e in m2.read_events(limit=100)
        if "settled by" in " ".join(e.get("acted") or [])
    ]
    assert settled_events == [], \
        f"executor fabricated a settle for an uncharged refusal: {settled_events}"


# --------------------------------------------------------------------------- #
# SEV-1 #3 — a repeat must not reset / re-settle the original job row
# --------------------------------------------------------------------------- #
def test_repeat_does_not_reset_original_job(monkeypatch, tmp_path):
    """The original serve's job id stays settled exactly once; a repeat must
    not create a second 'settled by' event for the same job id."""
    h = _mk(monkeypatch, tmp_path)
    h.serve_intel(CALLER, {"q": "z"})
    jobs_before = h.jobs.snapshot(limit=500)
    assert len(jobs_before) == 1
    orig_jid = jobs_before[0]["id"]

    h.serve_intel(CALLER, {"q": "z"})  # repeat
    jobs_after = h.jobs.snapshot(limit=500)
    # The repeat must not have created a new job row NOR reset the original.
    assert len(jobs_after) == 1
    assert jobs_after[0]["id"] == orig_jid
    assert jobs_after[0]["phase"] == "settled"

    settled = [
        " ".join(e.get("acted") or []) for e in h.m.read_events(limit=200)
        if "settled by" in " ".join(e.get("acted") or []) and orig_jid in
        " ".join(e.get("acted") or [])
    ]
    assert len(settled) == 1, \
        f"expected ONE settle event for {orig_jid}, got {len(settled)}"


# --------------------------------------------------------------------------- #
# Refusals are journaled (audit SEV-3 #4) + repeats journal (SEV-3 #3)
# --------------------------------------------------------------------------- #
def test_banned_refusal_is_journaled(monkeypatch, tmp_path):
    h = _mk(monkeypatch, tmp_path)
    bad = "0x" + "5" * 40
    for _ in range(3):
        h.ledger.update(bad, "refund")
    st, _ = h.serve_intel(bad, {"q": "x"})
    assert st == 403
    kinds = [(e.get("extra") or {}).get("kind")
             for e in h.m.read_events(limit=100)]
    assert "refuse" in kinds, "banned refusal was not journaled"


def test_risky_refusal_is_journaled(monkeypatch, tmp_path):
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "6" * 40
    for _ in range(3):
        h.ledger.update(risky, "caller_fault")
    st, _ = h.serve_intel(risky, {"q": "x"})
    assert st == 403
    kinds = [(e.get("extra") or {}).get("kind")
             for e in h.m.read_events(limit=100)]
    assert "refuse" in kinds, "risky-prepay refusal was not journaled"


def test_repeat_is_journaled_as_kind_repeat(monkeypatch, tmp_path):
    h = _mk(monkeypatch, tmp_path)
    h.serve_intel(CALLER, {"q": "r"})
    h.serve_intel(CALLER, {"q": "r"})  # repeat
    kinds = [(e.get("extra") or {}).get("kind")
             for e in h.m.read_events(limit=100)]
    assert kinds.count("repeat") == 1, "repeat event not journaled"


def test_prepay_debit_is_kind_prepay(monkeypatch, tmp_path):
    """Prepay debits get their own kind (audit finding 16) — not lumped into
    'paid' (which should mean onchain settlements/rebates)."""
    h = _mk(monkeypatch, tmp_path)
    risky = "0x" + "7" * 40
    for _ in range(3):
        h.ledger.update(risky, "caller_fault")
    row = h.ledger.recall(risky)
    assert row is not None
    row["prepay_usdc"] = round(BASE * 0.30, 6)
    h.m.set_entity("caller", risky, row)
    st, _ = h.serve_intel(risky, {"q": "ok"})
    assert st == 200
    kinds = [(e.get("extra") or {}).get("kind")
             for e in h.m.read_events(limit=100)]
    assert "prepay" in kinds

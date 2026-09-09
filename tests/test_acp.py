"""ACPDelegator tests — terms logic + memory recall (no network, no CLI).

``delegate()`` shells out to ``acp`` and moves real escrow; that is exercised
LIVE against Base mainnet (Gate 4) and via the capability-gated
``POST /scout/delegate`` route (test_front_office), not here. These lock the
load-bearing half: the recalled provider row is a pure function of memory, the
terms decision follows the spec thresholds (a default = never hire again), and
SIBYL_DISABLED makes every provider a stranger (deletion-safe).
"""
import os
import uuid

from core.acp import ACPDelegator, terms_from_row
from core.memory import HouseMemory

PROVEN = "0x436f324eff0b32a405c5b9102e1a6ef85451cec1"   # BitsAndBytesBack
NEWBIE = "0x" + "A" * 40
BAD = "0x" + "B" * 40


def _mem() -> HouseMemory:
    return HouseMemory(f"/tmp/house_acp_{uuid.uuid4().hex}.db")


def test_terms_pure_function_live_and_record_outcome(tmp_path):
    """The shared pure function every hiring surface reads: unknown → strict,
    proven → trusted, thin → unknown, a quality floor / any default → skip
    (never hire again). Live: no row → strict, proven → trusted, risky → skip
    AND delegate() refuses WITHOUT calling the CLI; record-outcome accumulates
    the running averages, escrow total, and journals an event."""
    assert terms_from_row(None).segment == "unknown"
    assert terms_from_row({"jobs_done": 5, "quality_score": 0.9, "on_time": 0.95}).segment == "proven"
    assert terms_from_row({"jobs_done": 1, "quality_score": 0.7, "on_time": 1.0}).segment == "unknown"  # thin
    assert terms_from_row({"jobs_done": 1, "quality_score": 0.5, "on_time": 1.0}).skip is True
    assert terms_from_row({"jobs_done": 3, "quality_score": 0.9, "on_time": 1.0,
                           "default_events": 1}).skip is True  # one default = never hire

    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    assert d.terms(PROVEN).segment == "unknown" and d.terms(PROVEN).strict_review is True

    d._upsert_provider(PROVEN, {"jobs_done": 3, "on_time": 1.0, "quality_score": 0.95})
    t = d.terms(PROVEN)
    assert t.segment == "proven" and t.strict_review is False and t.skip is False

    d._upsert_provider(BAD, {"jobs_done": 2, "quality_score": 0.4, "on_time": 0.5,
                             "default_events": 2})
    assert d.terms(BAD).segment == "risky" and d.terms(BAD).skip is True
    receipt = d.delegate(BAD, "anything", {"prompt": "x"})
    assert receipt["skipped"] is True and "job_id" not in receipt

    # Record two outcomes → running averages + escrow total + a journal event.
    d._record_outcome(NEWBIE, escrow_usdc=0.02, delivered_on_time=True, quality=0.9)
    d._record_outcome(NEWBIE, escrow_usdc=0.05, delivered_on_time=False, quality=0.6)
    row = d.recall_provider(NEWBIE)
    assert row["jobs_done"] == 2 and row["quality_score"] == 0.75
    assert row["on_time"] == 0.5 and row["total_escrow_usdc"] == 0.07
    assert any("acp job done" in str(e) for e in m.read_events())


def test_delegation_mode_forgets_providers(tmp_path):
    """SIBYL_DISABLED → recall returns None → unknown/strict terms, and a
    write in deletion mode is a no-op (nothing persists); lifting the flag
    shows the original record intact."""
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    d._record_outcome(PROVEN, escrow_usdc=0.02, delivered_on_time=True, quality=0.95)

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        d_off = ACPDelegator(_mem(), acp_bin="true")
        assert d_off.recall_provider(PROVEN) is None
        t = d_off.terms(PROVEN)
        assert t.segment == "unknown" and t.strict_review is True
        d_off._record_outcome(PROVEN, escrow_usdc=0.02,
                              delivered_on_time=True, quality=0.9)
        assert d_off.recall_provider(PROVEN) is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)
    assert d.recall_provider(PROVEN)["jobs_done"] == 1  # original intact

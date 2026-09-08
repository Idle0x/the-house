"""ACPDelegator tests — terms logic + memory recall (no network, no CLI).

The delegate() lifecycle shells out to `acp` and moves real escrow; that is
exercised LIVE against Base mainnet (Gate 4, proven providers), not in unit
tests. Here we lock the load-bearing half: the recalled provider row is a
pure function of memory, the terms decision follows the spec thresholds,
and SIBYL_DISABLED makes every provider a stranger (deletion-safe).
"""
import os
import uuid

from core.acp import (ACPDelegator, ProviderTerms, terms_from_row)
from core.memory import HouseMemory

PROVEN = "0x436f324eff0b32a405c5b9102e1a6ef85451cec1"   # BitsAndBytesBack
NEWBIE = "0x" + "A" * 40
BAD = "0x" + "B" * 40


def _mem() -> HouseMemory:
    return HouseMemory(f"/tmp/house_acp_{uuid.uuid4().hex}.db")


def test_no_row_is_unknown_strict_review():
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    t = d.terms(PROVEN)          # no provider row written yet
    assert t.segment == "unknown"
    assert t.skip is False
    assert t.strict_review is True   # stricter evaluator for strangers


def test_proven_row_gets_trusted_terms():
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    d._upsert_provider(PROVEN, {
        "jobs_done": 3, "on_time": 1.0, "quality_score": 0.95,
    })
    t = d.terms(PROVEN)
    assert t.segment == "proven"
    assert t.strict_review is False   # trusted evaluator
    assert t.skip is False


def test_quality_below_risky_threshold_skips():
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    d._upsert_provider(BAD, {"jobs_done": 2, "quality_score": 0.4,
                             "on_time": 0.5, "default_events": 2})
    t = d.terms(BAD)
    assert t.segment == "risky"
    assert t.skip is True
    # delegate() refuses without calling the CLI.
    receipt = d.delegate(BAD, "anything", {"prompt": "x"})
    assert receipt["skipped"] is True
    assert "job_id" not in receipt


def test_record_outcome_accumulates_and_writes_event():
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    d._record_outcome(NEWBIE, escrow_usdc=0.02, delivered_on_time=True, quality=0.9)
    row = d.recall_provider(NEWBIE)
    assert row is not None
    assert row["jobs_done"] == 1
    assert row["quality_score"] == 0.9
    assert row["on_time"] == 1.0
    # Second job moves the running averages.
    d._record_outcome(NEWBIE, escrow_usdc=0.05, delivered_on_time=False, quality=0.6)
    row = d.recall_provider(NEWBIE)
    assert row is not None
    assert row["jobs_done"] == 2
    assert row["quality_score"] == 0.75
    assert row["on_time"] == 0.5
    assert row["total_escrow_usdc"] == 0.07
    evs = m.read_events()
    assert any("acp job done" in str(e) for e in evs)


def test_deletion_mode_forgets_providers():
    """SIBYL_DISABLED=1 → recall returns None → unknown/strict terms, no writes."""
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    d._record_outcome(PROVEN, escrow_usdc=0.02, delivered_on_time=True, quality=0.95)

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m_off = HouseMemory(f"/tmp/house_acp_del_{uuid.uuid4().hex}.db")
        d_off = ACPDelegator(m_off, acp_bin="true")
        assert d_off.recall_provider(PROVEN) is None
        t = d_off.terms(PROVEN)
        assert t.segment == "unknown"
        assert t.strict_review is True
        # A write in deletion mode is a no-op (nothing persists).
        d_off._record_outcome(PROVEN, escrow_usdc=0.02,
                              delivered_on_time=True, quality=0.9)
        assert d_off.recall_provider(PROVEN) is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)
    # Original memory still has the record after the deletion window closes.
    row_after = d.recall_provider(PROVEN)
    assert row_after is not None
    assert row_after["jobs_done"] == 1


def test_terms_from_row_pure_function():
    assert terms_from_row(None).segment == "unknown"
    assert terms_from_row(
        {"jobs_done": 5, "quality_score": 0.9, "on_time": 0.95}
    ).segment == "proven"
    assert terms_from_row(
        {"jobs_done": 1, "quality_score": 0.7, "on_time": 1.0}
    ).segment == "unknown"          # thin record
    assert terms_from_row(
        {"jobs_done": 1, "quality_score": 0.5, "on_time": 1.0}
    ).skip is True                   # quality floor
    assert terms_from_row(
        {"jobs_done": 3, "quality_score": 0.9, "on_time": 1.0,
         "default_events": 1}
    ).skip is True                   # one default = never hire again


def test_acceptance_criterion_appends_to_first_string_field():
    m = _mem()
    d = ACPDelegator(m, acp_bin="true")
    req = d._with_acceptance_criterion({"prompt": "Optimize this."},
                                       "prompt_optimization")
    assert "[the-house evaluation criterion]" in req["prompt"]
    # Non-string fields untouched; schema stays valid.
    assert "limit" not in req

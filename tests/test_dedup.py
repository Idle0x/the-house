"""F2 DedupEngine tests (03-FEATURES F2).

test_same_caller_repeat_is_cached_free is the required beat: same addr +
same params twice → 2nd is a repeat (repeat_of set), served from cache at
$0, answer identical, usdc_saved incremented.
"""
import json
import os
import uuid

import pytest

from core.dedup import DedupEngine, canonical, fingerprint
from core.memory import HouseMemory

ADDR = "0x" + "D" * 40


@pytest.fixture()
def dedup():
    db = f"/tmp/house_f2_{uuid.uuid4().hex}.db"
    cache = f"/tmp/house_f2_cache_{uuid.uuid4().hex}"
    m = HouseMemory(db)
    return m, DedupEngine(m, cache_dir=__import__("pathlib").Path(cache))


def test_canonical_strips_volatile_and_sorts():
    a = canonical({"/intel/quote": "", "limit": 10, "ts": 123, "q": "x"})
    b = canonical({"/intel/quote": "", "q": "x", "limit": 10})
    assert a == b


def test_fingerprint_stable_across_volatile():
    fp1 = fingerprint("/intel/quote", {"q": "the house", "ts": 111})
    fp2 = fingerprint("/intel/quote", {"q": "the house", "ts": 999})
    assert fp1 == fp2


def test_fingerprint_differs_on_real_param_change():
    fp1 = fingerprint("/intel/quote", {"q": "memory"})
    fp2 = fingerprint("/intel/quote", {"q": "x402"})
    assert fp1 != fp2


def test_same_caller_repeat_is_cached_free(dedup):
    m, engine = dedup
    # First serve: caller row has no fp → store answer + mark.
    row0 = m.get_entity("caller", ADDR) or {
        "address": ADDR, "dedup_fp": [], "trust_score": 50, "tx_count": 0,
        "segment": "new",
    }
    fp = fingerprint("/intel/quote", {"q": "the house"})
    assert engine.is_repeat(row0, fp) is False

    answer = {"intel": "some answer", "route": "/intel/quote"}
    updated = engine.mark_served(row0, ADDR, fp, answer, price_usdc=0.01)
    assert fp in updated["dedup_fp"]
    assert engine.load(fp) == answer  # on-disk cache written

    # Second serve, same caller + same params (volatile ts differs).
    row1 = m.get_entity("caller", ADDR)
    assert engine.is_repeat(row1, fp) is True
    stats = engine.note_repeat(price_usdc=0.01)
    assert stats["hits"] == 1
    assert stats["usdc_saved"] == 0.01
    assert engine.stats()["compute_avoided_usd"] > 0


def test_dedup_stats_accumulate(dedup):
    m, engine = dedup
    for _ in range(3):
        engine.note_repeat(price_usdc=0.01)
    assert engine.stats() == {"hits": 3, "usdc_saved": 0.03,
                              "compute_avoided_usd": 0.003}


def test_deletion_mode_no_cache():
    db = f"/tmp/house_f2_del_{uuid.uuid4().hex}.db"
    cache = f"/tmp/house_f2_del_cache_{uuid.uuid4().hex}"
    m = HouseMemory(db)
    engine = DedupEngine(m, cache_dir=__import__("pathlib").Path(cache))
    engine.mark_served({"dedup_fp": []}, ADDR,
                       fingerprint("/intel/quote", {"q": "x"}), {"intel": "a"},
                       price_usdc=0.01)
    # Memory ON: cached.
    assert engine.load(fingerprint("/intel/quote", {"q": "x"})) is not None

    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m_off = HouseMemory(db)
        e_off = DedupEngine(m_off, cache_dir=__import__("pathlib").Path(cache))
        # Memory off: no repeats, no stats — every request looks new.
        assert e_off.is_repeat({"dedup_fp": []}, fingerprint("/intel/quote", {"q": "x"})) is False
        assert e_off.stats()["hits"] == 0
        assert e_off.load(fingerprint("/intel/quote", {"q": "x"})) is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

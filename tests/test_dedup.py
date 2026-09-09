"""F2 DedupEngine (03-FEATURES F2).

The required beat: same addr + same params twice → 2nd is a repeat, served
from cache at $0, answer identical, usdc_saved + compute_avoided credited.
Fingerprint canonicality is what makes a "repeat" mean the same query, not a
query with a different timestamp. Deletion → no cache, no repeats.
"""
import os
import pathlib
import uuid

from core.dedup import DedupEngine, canonical, fingerprint
from core.memory import HouseMemory

ADDR = "0x" + "D" * 40


def _engine(tmp: str) -> tuple[HouseMemory, DedupEngine]:
    m = HouseMemory(tmp)
    return m, DedupEngine(m, cache_dir=pathlib.Path(f"/tmp/house_f2_cache_{uuid.uuid4().hex}"))


def test_fingerprint_canonical_repeat_cached_free_and_deletion(tmp_path):
    """Volatile params (ts) are stripped and the rest sorted, so the same
    logical query fingerprints identically; a real param change does not. The
    first serve stores the answer + marks the fp; the identical repeat is
    detected, served from cache, and usdc_saved + compute_avoided are credited.
    THE GATE: SIBYL_DISABLED → no cache, no repeats — every request looks new."""
    a = canonical({"/intel/quote": "", "limit": 10, "ts": 123, "q": "x"})
    b = canonical({"/intel/quote": "", "q": "x", "limit": 10})
    assert a == b
    assert fingerprint("/intel/quote", {"q": "the house", "ts": 111}) == \
        fingerprint("/intel/quote", {"q": "the house", "ts": 999})
    assert fingerprint("/intel/quote", {"q": "memory"}) != \
        fingerprint("/intel/quote", {"q": "x402"})

    m, engine = _engine(str(tmp_path / "memory.db"))
    row0 = m.get_entity("caller", ADDR) or {
        "address": ADDR, "dedup_fp": [], "trust_score": 50, "tx_count": 0,
        "segment": "new"}
    fp = fingerprint("/intel/quote", {"q": "the house"})
    assert engine.is_repeat(row0, fp) is False

    answer = {"intel": "some answer", "route": "/intel/quote"}
    updated = engine.mark_served(row0, ADDR, fp, answer, price_usdc=0.01)
    assert fp in updated["dedup_fp"]
    assert engine.load(fp) == answer  # on-disk cache written

    row1 = m.get_entity("caller", ADDR)
    assert engine.is_repeat(row1, fp) is True
    stats = engine.note_repeat(price_usdc=0.01)
    assert stats["hits"] == 1 and stats["usdc_saved"] == 0.01
    assert engine.stats()["compute_avoided_usd"] > 0

    # THE GATE: deletion → no cache, no repeats.
    db = f"/tmp/house_f2_del_{uuid.uuid4().hex}.db"
    cache = pathlib.Path(f"/tmp/house_f2_del_cache_{uuid.uuid4().hex}")
    fp2 = fingerprint("/intel/quote", {"q": "x"})
    e = DedupEngine(HouseMemory(db), cache_dir=cache)
    e.mark_served({"dedup_fp": []}, ADDR, fp2, {"intel": "a"}, price_usdc=0.01)
    assert e.load(fp2) is not None  # memory ON: cached
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        e_off = DedupEngine(HouseMemory(db), cache_dir=cache)
        assert e_off.is_repeat({"dedup_fp": []}, fp2) is False
        assert e_off.stats()["hits"] == 0
        assert e_off.load(fp2) is None  # memory off: no cache
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

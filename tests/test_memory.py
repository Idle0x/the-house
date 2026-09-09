"""HouseMemory wrapper — the load-bearing seam over the Sibyl SDK.

Every room funnels reads/writes through this one class, and one env flag
(``SIBYL_DISABLED``) collapses all of them at once — so the wrapper's
normalization quirks, its event taxonomy, and its deletion no-op are the whole
deletion gate. These pin the wrapper contract, not each SDK quirk individually.
"""
import os

import pytest

from core.memory import HouseMemory, memory_disabled

DB = "/tmp/house_test_memory.db"


@pytest.fixture()
def mem():
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except FileNotFoundError:
            pass
    yield HouseMemory(DB)


def test_wrapper_read_write_contract_and_kind_guard(mem):
    """Every read/write shape each room uses round-trips, a miss returns
    None/empty (not an error), and an unknown event kind is rejected — no
    silent taxonomy drift. Entities (with upsert-merge), JSON reference values,
    dict state, list, and journaled events (kind: ``served`` AND the watchtower's
    ``funding`` writer, audit SEV-2)."""
    mem.upsert_entity("caller", "0xabc", {"tx_count": 1})
    mem.upsert_entity("caller", "0xabc", {"tx_count": 2, "segment": "regular"})
    assert mem.get_entity("caller", "0xabc") == {"tx_count": 2, "segment": "regular"}
    assert mem.get_entity("caller", "0xnone") is None

    mem.set_reference("pricing", {"new": 1.00, "vip": 0.80})
    assert mem.get_reference("pricing") == {"new": 1.00, "vip": 0.80}  # JSON parsed
    assert mem.get_reference("missing") is None

    mem.set_state("jobs", {"j1": {"phase": "accepted"}})
    assert mem.get_state("jobs") == {"j1": {"phase": "accepted"}}
    assert mem.get_state("missing") is None

    mem.set_entity("scar", "S-1", {"route": "/intel"})
    mem.set_entity("scar", "S-2", {"route": "/intel"})
    assert len(mem.list_entities("scar")) == 2

    # Events carry extra.kind (E2 calibration + the serve-path journaling
    # depend on it); an unknown kind is rejected.
    mem.write_event("0xabc served (Δ+2)", kind="served")
    mem.write_event("0xabc funded by 0xdef", kind="funding")
    kinds = [e.get("extra", {}).get("kind") for e in mem.read_events() if isinstance(e, dict)]
    assert "served" in kinds and "funding" in kinds
    with pytest.raises(ValueError):
        mem.write_event("x", kind="not-a-kind")


def test_memory_disabled_is_a_no_op():
    """SIBYL_DISABLED=1: memory_disabled() and HouseMemory.disabled() are True,
    every read returns empty/None, and every write is a silent no-op — nothing
    persists, nothing raises. Lifting the flag shows the writes never landed."""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except FileNotFoundError:
            pass
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        assert memory_disabled() is True
        m = HouseMemory(DB)
        assert m.disabled() is True
        assert m.get_entity("caller", "0xany") is None
        assert m.get_state("jobs") is None and m.get_reference("pricing") is None
        assert m.list_entities("scar") == []
        m.set_entity("caller", "0xany", {"trust_score": 50})   # no-op, no raise
        m.write_event("should-not-persist", kind="job")
    finally:
        os.environ.pop("SIBYL_DISABLED", None)
    m2 = HouseMemory(DB)
    assert m2.get_entity("caller", "0xany") is None  # the write never persisted

"""HouseMemory wrapper tests — normalization + deletion semantics.

Covers: NotFound→None, body unwrap, event journaling shape, reference JSON
parsing, state dict validation, SIBYL_DISABLED no-op mode.
"""
import json
import os

import pytest

from core.memory import HouseMemory, memory_disabled

DB = "/tmp/house_test_memory.db"


@pytest.fixture()
def mem():
    # Remove any pre-existing DB so each test starts clean.
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB + suffix)
        except FileNotFoundError:
            pass
    m = HouseMemory(DB)
    yield m


def test_get_entity_miss_returns_none(mem):
    assert mem.get_entity("caller", "0xnone") is None


def test_entity_round_trip_and_unwrap(mem):
    mem.set_entity("caller", "0xabc", {"trust_score": 50, "segment": "new"})
    body = mem.get_entity("caller", "0xabc")
    assert body == {"trust_score": 50, "segment": "new"}


def test_upsert_merges(mem):
    mem.upsert_entity("caller", "0xabc", {"tx_count": 1})
    mem.upsert_entity("caller", "0xabc", {"tx_count": 2, "segment": "regular"})
    body = mem.get_entity("caller", "0xabc")
    assert body["tx_count"] == 2
    assert body["segment"] == "regular"


def test_write_event_shape(mem):
    mem.write_event("0xabc served (Δ+2)", kind="served")
    evs = mem.read_events()
    assert len(evs) >= 1
    # extra.kind must survive for E2 calibration.
    kinds = [e.get("extra", {}).get("kind") if isinstance(e, dict) else None for e in evs]
    assert "served" in kinds


def test_write_event_rejects_unknown_kind(mem):
    with pytest.raises(ValueError):
        mem.write_event("x", kind="not-a-kind")


def test_reference_json_string_parsed(mem):
    mem.set_reference("pricing", {"new": 1.00, "vip": 0.80})
    parsed = mem.get_reference("pricing")
    assert parsed == {"new": 1.00, "vip": 0.80}


def test_state_requires_dict(mem):
    mem.set_state("jobs", {"j1": {"phase": "accepted"}})
    assert mem.get_state("jobs") == {"j1": {"phase": "accepted"}}
    assert mem.get_state("missing") is None


def test_list_entities_unwraps(mem):
    mem.set_entity("scar", "S-1", {"route": "/intel"})
    mem.set_entity("scar", "S-2", {"route": "/intel"})
    scars = mem.list_entities("scar")
    assert len(scars) == 2
    assert all("route" in s for s in scars)


def test_memory_disabled_env():
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        assert memory_disabled() is True
        m = HouseMemory(DB)
        assert m.disabled() is True
        assert m.get_entity("caller", "0xany") is None
        assert m.get_state("jobs") is None
        assert m.get_reference("pricing") is None
        assert m.list_entities("scar") == []
        m.set_entity("caller", "0xany", {"trust_score": 50})  # no-op, no raise
        m.write_event("should-not-persist", kind="job")
    finally:
        os.environ.pop("SIBYL_DISABLED", None)
    # After disable is lifted, the write above must not have persisted.
    m2 = HouseMemory(DB)
    assert m2.get_entity("caller", "0xany") is None

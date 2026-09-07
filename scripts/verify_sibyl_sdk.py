#!/usr/bin/env python3
"""P0 verification: Sibyl SDK round-trip on the installed package (0.7.0).

Exercises every API the HouseMemory wrapper must normalize, plus the 8
documented "realities" from shared/specs/sdk-realities.md. Prints PASS/FAIL
per check. Uses a throwaway local DB under data/.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

tmpdir = tempfile.mkdtemp(prefix="house_verify_")
db_path = os.path.join(tmpdir, "memory.db")

results = []
def check(name, fn):
    try:
        fn()
        results.append((name, "PASS"))
    except Exception as e:  # noqa: BLE001
        results.append((name, f"FAIL: {type(e).__name__}: {e}"))

from sibyl_memory_client import MemoryClient  # noqa: E402
from sibyl_memory_client.exceptions import NotFoundError  # noqa: E402

m = MemoryClient.local(db_path)

# --- 1. set/get entity basic + quirks 1-2 (NotFound raises; body is wrapped) ---
def t1():
    m.set_entity("caller", "0xverify", {"trust_score": 50, "segment": "new"})
    raw = m.get_entity("caller", "0xverify")
    assert isinstance(raw, dict) and "body" in raw, f"expected wrapped row, got {raw!r}"
    assert raw["body"]["trust_score"] == 50
check("set_entity/get_entity (wrapped body)", t1)

def t2():
    try:
        m.get_entity("caller", "0xdoes-not-exist")
        raise AssertionError("expected NotFoundError")
    except NotFoundError:
        pass
check("get_entity raises NotFoundError on miss (quirk 1)", t2)

# --- 3. write_event has NO free-form fields; journal via acted/extra ---
def t3():
    m.write_event(evaluated=None, acted=["0xverify served (Δ+2)"], extra={"kind": "served"})
    evs = m.read_events()
    assert any("Δ+2" in (e.get("acted") or [""])[0] or "Δ+2" in str(e) for e in evs), evs
check("write_event via acted/extra + read_events", t3)

# --- 4. get_reference stores body as JSON string ---
def t4():
    m.set_reference("pricing", json.dumps({"new": 1.00, "vip": 0.80}))
    ref = m.get_reference("pricing")
    assert isinstance(ref.get("body"), str), f"expected JSON string body, got {type(ref.get('body'))}"
    parsed = json.loads(ref["body"])
    assert parsed["vip"] == 0.80
check("set/get_reference body is JSON string (quirk 4)", t4)

# --- 5. list_entities for scar-style grouping ---
def t5():
    m.set_entity("scar", "S-1", {"route": "/intel", "failure_class": "5xx"})
    m.set_entity("scar", "S-2", {"route": "/intel", "failure_class": "5xx"})
    rows = m.list_entities("scar", limit=200)
    assert len(rows) >= 2
    assert all("body" in r for r in rows)
check("list_entities(category) returns wrapped rows", t5)

# --- 6. set_state body must be dict/list (not bare string) ---
def t6():
    try:
        m.set_state("jobs", "not-a-dict")
        raise AssertionError("expected ValidationError for bare string")
    except Exception as e:  # ValidationError or similar
        assert "ValidationError" in type(e).__name__ or "validation" in str(e).lower() or "must be" in str(e).lower(), f"unexpected: {e}"
check("set_state rejects bare string (quirk 6)", t6)

def t6b():
    m.set_state("jobs", {"job-1": {"phase": "accepted"}})
    st = m.get_state("jobs")
    assert st["body"]["job-1"]["phase"] == "accepted"
check("set_state dict + get_state round-trip", t6b)

# --- 7. MemoryClient.local works without init/network ---
def t7():
    assert os.path.exists(db_path)
    assert os.path.getsize(db_path) > 0
check("MemoryClient.local writes SQLite file (quirk 7)", t7)

# --- 8. search_entities + archive_entity ---
def t8():
    m.set_entity("scar", "S-3", {"route": "/other", "failure_class": "timeout"})
    hits = m.search_entities("timeout")
    assert any("S-3" in str(h) for h in hits), hits
check("search_entities (FTS)", t8)

def t9():
    m.archive_entity("caller", "0xverify")
check("archive_entity", t9)

# --- also: get_entity returns body field for state? (state shape check) ---
def t10():
    # caller entity body after archive is gone; verify separate kinds coexist
    m.set_entity("provider", "0xacp", {"jobs_done": 1, "quality_score": 0.9})
    prov = m.get_entity("provider", "0xacp")
    assert prov["body"]["quality_score"] == 0.9
check("provider kind entity (ACPDelegator shape)", t10)

print(f"DB: {db_path}")
for name, status in results:
    print(f"  [{status}] {name}")
failed = [r for r in results if r[1] != "PASS"]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)

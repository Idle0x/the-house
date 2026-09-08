"""P4b audit-fix regression tests.

* consult() must NOT publish CLEAR/HOLD feed entries for every ordinary
  serve (audit finding 19 — feed pollution); only ABORT publishes;
* GET /house/audit + /house/calibrate are READ-ONLY (findings 10) — GETs no
  longer mutate baseline/calibration state; the mutation lives on POST
  /house/audit/run + /house/calibrate/run, capability-gated when a token is
  configured;
* jobs.prune() bounds the HOT state document (finding 12) without touching
  non-terminal rows;
* startup() prunes + bootstraps the audit baseline (E1).
"""
import pytest

from core.memory import HouseMemory
from core.house import House
from core.watch import Watchtower, VERDICT_ABORT, VERDICT_CLEAR

HOUSE_WALLET = "0x" + "A" * 40
ROOT = "0x" + "F" * 40


def _mem(tmp_path):
    return HouseMemory(str(tmp_path / "memory.db"))


def _caller(m: HouseMemory, addr: str, **fields) -> dict:
    row = {
        "address": addr, "first_seen": 1.0, "last_seen": 2.0,
        "tx_count": 3, "total_paid_usdc": 0.03, "served_count": 3,
        "dedup_hits": 0, "failure_events": 0, "refund_events": 0,
        "warning_events": 0, "trust_score": 55.0, "segment": "regular",
        "dedup_fp": [], "notes": "",
    }
    row.update(fields)
    m.set_entity("caller", addr, row)
    return row


# --------------------------------------------------------------------------- #
# finding 19 — serve-path consult only publishes verdicts that MEAN something
# --------------------------------------------------------------------------- #
def test_consult_clean_caller_does_not_pollute_feed(tmp_path):
    m = _mem(tmp_path)
    addr = "0x" + "7" * 40
    _caller(m, addr, funded_by="0x" + "9" * 40)   # unique root → CLEAR
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    # A normal serve consults the tower and is CLEAR → no feed entry, no
    # journal screen event (the old code published every CLEAR).
    assert t.consult(addr) is None
    assert t.feed() == []
    kinds = [(e.get("extra") or {}).get("kind")
             for e in m.read_events(limit=50)]
    assert "screen" not in kinds


def test_consult_hold_does_not_pollute_feed(tmp_path):
    m = _mem(tmp_path)
    addr = "0x" + "3" * 40
    _caller(m, addr, tx_count=1, total_paid_usdc=0.10)  # cold-start → HOLD
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    assert t.consult(addr) is None          # HOLD is not a refusal
    assert t.feed() == []                   # and not published either


def test_consult_abort_still_publishes_refusal(tmp_path):
    m = _mem(tmp_path)
    ring = []
    for i in range(3):
        addr = "0x" + str(i).zfill(2) + "B" * 37
        _caller(m, addr, funded_by=ROOT)
        ring.append(addr)
    t = Watchtower(m, house_wallet=HOUSE_WALLET)
    refusal = t.consult(ring[0])
    assert refusal is not None
    feed = t.feed()
    assert len(feed) == 1 and feed[0]["verdict"] == VERDICT_ABORT
    kinds = [(e.get("extra") or {}).get("kind")
             for e in m.read_events(limit=50)]
    assert "refuse" in kinds


# --------------------------------------------------------------------------- #
# finding 10 — audit/calibrate GETs must not mutate
# --------------------------------------------------------------------------- #
def test_audit_get_is_readonly(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    app = build_app()
    client = TestClient(app)
    # GET must not CREATE the baseline by itself (no side effect).
    r = client.get("/house/audit")
    assert r.status_code == 200
    body = r.json()
    assert "last_audit" in body
    assert body["last_audit"] is None or body["last_audit"]["status"] in (
        "baseline_set", "healthy", "degraded")
    # The baseline was set by startup() (E1 boot) not by the GET… and a
    # second GET must not change it either.
    baseline = app.state.memory.get_state("baseline")
    r2 = client.get("/house/audit")
    assert r2.status_code == 200
    assert app.state.memory.get_state("baseline") == baseline


def test_audit_run_post_mutates(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    app = build_app()
    client = TestClient(app)
    r = client.post("/house/audit/run")
    assert r.status_code == 200
    assert r.json()["status"] in ("baseline_set", "healthy", "degraded")


def test_audit_run_requires_token_when_configured(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("HOUSE_COMPILE_TOKEN", "secret-token")
    app = build_app()
    client = TestClient(app)
    r = client.post("/house/audit/run")
    assert r.status_code == 403
    r = client.post("/house/audit/run",
                    headers={"x-house-capability": "secret-token"})
    assert r.status_code == 200


def test_calibrate_get_readonly_and_post_runs(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    app = build_app()
    client = TestClient(app)
    # GET before any calibration → no side effect, null report.
    r = client.get("/house/calibrate")
    assert r.status_code == 200
    assert r.json()["last_calibration"] is None
    assert app.state.memory.get_reference("calibration") is None
    # POST runs it and persists.
    r2 = client.post("/house/calibrate/run")
    assert r2.status_code == 200
    assert r2.json().get("cohort") is not None
    assert app.state.memory.get_reference("calibration") is not None


# --------------------------------------------------------------------------- #
# finding 12 — jobs state is bounded (prune)
# --------------------------------------------------------------------------- #
def test_jobs_prune_keeps_newest_terminal_drops_oldest(tmp_path):
    from core.jobs import JobStateMachine
    m = _mem(tmp_path)
    jobs = JobStateMachine(m)
    caller = "0x" + "8" * 40
    # Create 250 settled jobs (terminal), each with a distinct fp.
    for i in range(250):
        j = jobs.start(caller, "/intel/quote", f"fp-{i}")
        jobs.settle(j["id"], caller)
    assert jobs.pending_count() == 0
    # Prune down to keep=200 → 50 oldest terminal rows dropped.
    removed = jobs.prune(keep=200)
    assert removed == 50
    snap = jobs.snapshot(limit=500)
    assert len(snap) == 200
    # The most recent fps survived, the oldest were dropped.
    ids = {j["fp"] for j in snap}
    assert "fp-249" in ids and "fp-248" in ids
    assert "fp-0" not in ids and "fp-1" not in ids


def test_jobs_prune_never_drops_non_terminal(tmp_path):
    from core.jobs import JobStateMachine
    m = _mem(tmp_path)
    jobs = JobStateMachine(m)
    caller = "0x" + "9" * 40
    # One LIVE (serving) job + 250 settled.
    live = jobs.start(caller, "/intel/quote", "fp-live")
    jobs.advance(live["id"], "serving", step="serve", payment_state="verified")
    for i in range(250):
        j = jobs.start(caller, "/intel/quote", f"fp-{i}")
        jobs.settle(j["id"], caller)
    removed = jobs.prune(keep=200)
    assert removed == 51  # 250 terminal − 199 kept (200 keep − 1 live)
    live_row = jobs.get(live["id"])
    assert live_row is not None and live_row["phase"] == "serving"
    assert jobs.pending_count() == 1


def test_startup_prunes_and_sets_audit_baseline(tmp_path, monkeypatch):
    from core.jobs import JobStateMachine
    db = str(tmp_path / "memory.db")
    monkeypatch.setenv("HOUSE_MEMORY_DB", db)
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    m = HouseMemory(db)
    # Seed 250 settled jobs directly.
    jobs = JobStateMachine(m)
    caller = "0x" + "0" * 40
    for i in range(250):
        j = jobs.start(caller, "/intel/quote", f"fp-{i}")
        jobs.settle(j["id"], caller)
    h = House(m, base_price=0.01)
    report = h.startup()
    assert report["pruned"] == 50
    assert len(h.jobs.snapshot(limit=500)) == 200
    # E1 baseline exists after boot.
    assert m.get_state("baseline") is not None

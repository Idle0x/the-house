"""Seller — the FastAPI/x402 boundary, tested without network.

We test the memory act + the app wiring directly: the landing page, the
manifest, the free money-shot routes, the capability gate, the boundary
hardening (junk-id rejection + address masking), and the audited P4b
invariants that the self-auditor / calibrator GETs are READ-ONLY while the
mutation lives on a token-gated POST /run, and that startup prunes job state.
"""
import asyncio
import types
import uuid

import pytest
from fastapi.testclient import TestClient

from core.memory import HouseMemory
from core.jobs import JobStateMachine
from core.trust import TrustLedger
from app.x402.seller import extract_payer

VIP_ADDR = "0x" + "A" * 40
STRANGER_ADDR = "0x" + "B" * 40
BANNED_ADDR = "0x" + "C" * 40


class _FakePayload:
    """Minimal stand-in for a settled x402 payload exposing the payer."""

    def __init__(self, payer: str):
        self.payload = {"authorization": {"from_address": payer}}


def test_extract_payer_exact_and_dict_fallback():
    assert extract_payer(_FakePayload(VIP_ADDR)) == VIP_ADDR
    assert extract_payer({"payer": STRANGER_ADDR}) == STRANGER_ADDR
    assert extract_payer(None) is None


def test_landing_reads_state_live_and_collapses_disabled(tmp_path, monkeypatch):
    """The app builds; / (HTML) + /house/ledger + /manifest are free. An
    isolated fresh db ⇒ memory LIVE (badge, aggregates). SIBYL_DISABLED=1 ⇒
    the landing page itself reads the collapse: badge DISABLED, the collapse
    callout shown, every aggregate 0, the manifest says disabled."""
    from app.x402.seller import build_app

    # Live
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    page = r.text
    assert "THE" in page and "HOUSE" in page
    # new landing page: the section header is uppercased by CSS but stored
    # lowercase in the HTML; the memory status is injected into the state
    # blob (window.__HOUSE__) and rendered client-side.
    assert "why memory is load-bearing" in page
    assert '"memory": "live"' in page
    m = client.get("/manifest")
    assert m.status_code == 200 and m.json()["service"] == "the-house"
    assert m.json()["memory"] in ("live", "disabled")
    r2 = client.get("/house/ledger")
    lb = r2.json()
    assert "dedup" in lb and "callers" in lb and lb["dedup"]["hits"] == 0
    assert "scars" in lb and "jobs" in lb

    # Disabled — the collapse is the page's own reading of the state.
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "disabled.db"))
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    app2 = build_app()
    client2 = TestClient(app2)
    page2 = client2.get("/").text
    assert '"memory": "disabled"' in page2
    manifest2 = client2.get("/manifest").json()
    assert manifest2["memory"] == "disabled"
    assert manifest2["stats"]["settlements"] == 0
    assert manifest2["stats"]["live_callers"] == 0


def test_landing_survives_sparse_rows():
    """Sparse memory rows (e.g. a watch-screen upsert with null trust /
    quality) must not 500 the landing page — aggregates treat null as 0."""
    from app.x402.landing import build_landing_state
    st = build_landing_state(
        memory_mode="live",
        callers=[{"address": "0x3a10cab4", "address_last6": "3a10cab4",
                  "segment": None, "trust_score": None, "tx_count": None,
                  "net_charged_usdc": 0.0}],
        providers=[{"provider": "0xp", "provider_last6": "xxxxxx",
                    "segment": None, "hired": False, "jobs_done": 0,
                    "quality_score": None}],
        dedup={"hits": 0, "usdc_saved": 0.0}, scars_total=0, scars_rules=0,
        commit="abc1234", base_price=0.01, repo_url="", ts="t",
        wipe_status={}, public_url="")["stats"]
    assert st["trust"] == 0 and st["quality"] == 0 and st["callers"] == 1


def test_docs_renders_with_manual_and_links(tmp_path, monkeypatch):
    """/docs serves the formal manual: all ten sections, the trust rules,
    the on/off table, the API reference — and the landing page links it
    from the header nav, the hero, and the footer."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/docs")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    page = r.text
    for needle in ("Core concepts", "seven functions", "trust system",
                   "Anatomy of a transaction", "Memory on vs off",
                   "API reference", "Glossary", "/intel/quote", "PAYMENT-SIGNATURE"):
        assert needle in page, needle
    assert "/docs" in client.get("/manifest").json()["free"]
    landing = client.get("/").text
    assert 'href="/docs"' in landing and "Read the docs" in landing


def test_free_routes_gated_and_startup_prunes(tmp_path, monkeypatch):
    """/house/jobs is free (shows the F4 state machines); /intel/quote is PAID
    (402 without payment). POST /house/compile is capability-gated and turns 3
    same-class scars into a policy rule (nothing in deletion mode). A settled
    job resumes to nothing fresh, and startup prunes terminal job rows
    (250 → keep=200) and sets the E1 audit baseline."""
    from app.x402.seller import build_app
    from core.house import House
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/house/jobs")
    assert r.status_code == 200
    assert "pending" in r.json() and r.json()["jobs"] == []
    assert client.get("/intel/quote").status_code == 402  # not free

    # The F4 state machine: a settled job resumes to nothing fresh.
    jobs = app.state.jobs
    payer = "0x" + "9" * 40
    job = jobs.start(payer, "/intel/quote", "fp-demo")
    jobs.advance(job["id"], "serving", step="serve", payment_state="verified")
    jobs.settle(job["id"], payer)
    assert jobs.get(job["id"])["phase"] == "settled" and jobs.pending_count() == 0
    assert JobStateMachine(HouseMemory(str(tmp_path / "memory.db"))).resume_all() == []

    # Capability-gated compile: 3 same-class scars → 1 policy rule.
    for _ in range(3):
        app.state.scars.record("/intel/upstream", "5xx upstream timeout",
                               "provider timed out")
    rc = client.post("/house/compile",
                     headers={"x-house-capability": "test-token"})
    assert rc.status_code == 200
    assert len(rc.json()["rules_created"]) == 1
    assert rc.json()["active_rules"]

    # Deletion: nothing compiles.
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "disabled.db"))
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    app2 = build_app()
    r2 = TestClient(app2).post("/house/compile")
    assert r2.json()["memory"] == "disabled" and r2.json()["rules_created"] == []

    # P4b: startup prunes terminal rows + sets the baseline.
    db = str(tmp_path / "prune.db")
    monkeypatch.setenv("HOUSE_MEMORY_DB", db)
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    pm = HouseMemory(db)
    pjobs = JobStateMachine(pm)
    for i in range(250):
        j = pjobs.start("0x" + "0" * 40, "/intel/quote", f"fp-{i}")
        pjobs.settle(j["id"], "0x" + "0" * 40)
    report = House(pm, base_price=0.01).startup()
    assert report["pruned"] == 50
    assert len(pjobs.snapshot(limit=500)) == 200
    assert pm.get_state("baseline") is not None


# --------------------------------------------------------------------------- #
# P4b — the self-auditor / calibrator GETs are READ-ONLY; the mutation lives
# on a token-gated POST /run (finding #10).
# --------------------------------------------------------------------------- #
def test_audit_calibrate_gets_read_only_run_posts_gate(tmp_path, monkeypatch):
    """GET /house/audit + /house/calibrate must NOT mutate stored state (a
    second GET changes nothing). POST /run persists the report; when a token
    is configured the POSTs are 403 without the capability header."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    app = build_app()
    client = TestClient(app)
    assert client.get("/house/audit").status_code == 200
    baseline = app.state.memory.get_state("baseline")
    client.get("/house/audit")
    assert app.state.memory.get_state("baseline") == baseline  # read-only
    assert client.get("/house/calibrate").json()["last_calibration"] is None
    assert app.state.memory.get_reference("calibration") is None
    client.get("/house/calibrate")
    assert app.state.memory.get_reference("calibration") is None  # read-only

    r = client.post("/house/audit/run")
    assert r.status_code == 200
    assert r.json()["status"] in ("baseline_set", "healthy", "degraded")
    r2 = client.post("/house/calibrate/run")
    assert r2.status_code == 200 and r2.json().get("cohort") is not None
    assert app.state.memory.get_reference("calibration") is not None

    # Token-gated: 403 without, 200 with.
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "gated.db"))
    monkeypatch.setenv("HOUSE_COMPILE_TOKEN", "secret-token")
    app2 = build_app()
    c2 = TestClient(app2)
    assert c2.post("/house/audit/run").status_code == 403
    assert c2.post("/house/audit/run",
                   headers={"x-house-capability": "secret-token"}).status_code == 200


# --------------------------------------------------------------------------- #
# Boundary hardening (P4c + SEV-2): junk-id rejection + address masking
# --------------------------------------------------------------------------- #
def test_boundary_rejects_junk_and_masks_addresses(tmp_path, monkeypatch):
    """Every public route that takes a counterparty id rejects a non-0x-40 junk
    string with 400 BEFORE any memory is written (finding #25). AND the free
    public routes render full payer/wallet addresses masked to 0x…last4 while
    the COLD journal keeps them (Basescan reconciliation) and settlement tx
    hashes survive verbatim (SEV-2 P2)."""
    import asyncio
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    app = build_app()

    def handler(method, path):
        for r in app.routes:
            if getattr(r, "path", "") == path and method in getattr(r, "methods", set()):
                return getattr(r, "endpoint", None)
        raise AssertionError(f"{path} not found")

    class _Req(dict):
        def __init__(self, payload, owner, app):
            super().__init__()
            self._p = payload
            self.state = type("S", (), {"payment_payload": None})()
            self.app = types.SimpleNamespace(state=types.SimpleNamespace(**{
                "front": app.state.front, "desk": app.state.desk,
                "watch": app.state.watch}))
            self.query_params = {}

        async def json(self):
            return self._p

    # Junk-id rejection (one representative route per room) — uncharged, no write.
    assert getattr(asyncio.run(handler("POST", "/scout/hire")(
        _Req({"provider": "hello"}, "front", app))), "status_code", 200) == 400
    assert app.state.front.m.get_entity("provider", "hello") is None
    assert getattr(asyncio.run(handler("POST", "/watch/screen")(
        _Req({"wallet": "not-an-address"}, "watch", app))), "status_code", 200) == 400
    assert getattr(asyncio.run(handler("POST", "/bond/quote")(
        _Req({"provider": "junk"}, "desk", app))), "status_code", 200) == 400
    assert app.state.desk.m.get_entity("provider", "junk") is None

    # Address masking: full payer/tx stored, masked on the public wire.
    client = TestClient(app)
    FULL = "0x8A8a1234567890abcdef1234567890ABCDEF10Aa"
    assert len(FULL) == 42
    TX = "0x" + "deadbeef" * 5
    app.state.house.journal.record({"tx": TX, "payer": FULL,
                                    "route": "/intel/quote",
                                    "amount_usdc": 0.01, "kind": "settlement"})
    app.state.house.ledger.update(FULL, "served", paid_usdc=0.01)
    for route in ("/house/journal", "/house/ledger"):
        wire = client.get(route).text
        assert FULL not in wire, f"{route} leaked the full payer on the public wire"
    assert TX in client.get("/house/ledger").text  # tx hash preserved
    full_events = " ".join(" ".join(e.get("acted") or [])
                           for e in app.state.memory.read_events(limit=50))
    assert FULL in full_events  # the COLD journal must KEEP the full payer
    watch = app.state.watch
    watch.m.set_entity("caller", FULL, {"address": FULL, "tx_count": 10,
                                        "served_count": 10, "trust_score": 70.0,
                                        "segment": "regular",
                                        "funded_by": "0x" + "9" * 40})
    watch.screen(FULL)
    assert FULL not in client.get("/house/watch").text


class _StubState:
    def __init__(self, payer: str):
        self.payment_payload = {"payer": payer}


class _StubRequest:
    """Minimal Request stand-in exposing app.state + state as the handler needs."""

    def __init__(self, app, payer: str):
        self.app = app
        self.state = _StubState(payer)


def test_seller_handler_banned_refused_and_fresh_standing(monkeypatch, tmp_path):
    """C2: a banned wallet → 403 via the paid handler, no fake refund. A fresh
    serve returns post-update standing (tx_count already 1); a repeat is a
    dedup hit with repeat_of set. (Also the paid prepay-topup path: a bad
    amount is a 400, an in-cap amount credits the payer's own row.)"""
    from app.x402.seller import build_app
    from core.trust import TrustLedger
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    ledger: TrustLedger = app.state.ledger  # type: ignore[assignment]
    bad = "0x" + "C" * 40
    for _ in range(3):
        ledger.update(bad, "refund")
    refunds_before = ledger.recall(bad)["refund_events"]
    handler = next((getattr(r, "endpoint", None) for r in app.routes
                    if getattr(r, "path", "") == "/intel/quote"), None)
    assert handler is not None
    resp = handler(_StubRequest(app, bad))
    assert resp.status_code == 403 and "declines" in resp.body.decode()
    assert ledger.recall(bad)["refund_events"] == refunds_before  # no fake refund

    payer = "0x" + "D" * 40
    resp = handler(_StubRequest(app, payer))
    body = resp if isinstance(resp, dict) else resp.json()
    assert body["cached"] is False and body["standing"]["tx_count"] == 1
    assert body["house"]["trust_score"] > 50  # trust bumped (+3)
    resp2 = handler(_StubRequest(app, payer))
    body2 = resp2 if isinstance(resp2, dict) else resp2.json()
    assert body2["cached"] is True and body2["standing"]["dedup_hits"] == 1
    assert body2["house"]["repeat_of"] is not None

    # Prepay top-up: bad amount → 400 (uncharged); in-cap amount credits the
    # payer's OWN row (a buyer funds itself), capping at PREPAY_TOPUP_MAX.
    topup = next((getattr(r, "endpoint", None) for r in app.routes
                  if getattr(r, "path", "") == "/prepay/topup"), None)
    assert topup is not None
    r400 = asyncio.run(topup(_ReqTopup(app, payer, amount="not-a-number")))
    assert r400.status_code == 400
    rneg = asyncio.run(topup(_ReqTopup(app, payer, amount=-5)))
    assert rneg.status_code == 400
    rover = asyncio.run(topup(_ReqTopup(app, payer, amount=9999.0)))
    assert rover.status_code == 400  # exceeds PREPAY_TOPUP_MAX
    ok = asyncio.run(topup(_ReqTopup(app, payer, amount=0.02)))
    # Success returns a plain dict (FastAPI wraps it); 400s return JSONResponse.
    assert isinstance(ok, dict)
    out = ok
    assert out["credited_usdc"] == pytest.approx(0.02)
    assert out["prepay_on_file"] == pytest.approx(0.02)
    assert ledger.recall(payer)["prepay_usdc"] == pytest.approx(0.02)


class _ReqTopup(_StubRequest):
    """A top-up request: the x402 payer + a JSON body with ``amount``."""

    def __init__(self, app, payer: str, amount):
        super().__init__(app, payer)
        self._body = {"amount": amount}

    async def json(self):
        return self._body

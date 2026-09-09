"""M1 — Room 2: the underwriting desk (bonds).

Drives the ``UnderwritingDesk`` engine directly (no x402 middleware, no CDP,
no acp) and the thin FastAPI boundary, asserting what is ACTUALLY priced /
issued / paid out / refused — the money claims are the point.

Money model under test (verified against the installed x402 2.x exact scheme):
  * onchain settlement is ALWAYS the 402 quote = the BASE bond premium.
  * memory only discounts (proven → rebate back, net = premium×mult) or
    refuses (risky / over-exposure → 403 BEFORE settlement → uncharged).
  * a claim is real money-OUT: the house pays the face to the insured via its
    own wallet (dry: pseudo-hash here, a real onchain tx when live), journals
    it, and REMEMBERS it (the exposure cap decays one step per claim).

Face = $1.00, base premium = $0.05. premium = base × mult:
  proven → 0.50, standard → 1.00, risky → 2.20 (bad record; +$0.055/scar).
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from core.bonds import UnderwritingDesk
from core.memory import HouseMemory

PROVEN = "0x" + "P" * 40
STANDARD = "0x" + "S" * 40
BUYER = "0x" + "B" * 40
BASE = 0.05
FACE = 1.00


def _mk_desk(tmp_path, *, max_exposure=10.0):
    m = HouseMemory(str(tmp_path / "memory.db"))
    return UnderwritingDesk(m, max_exposure=max_exposure)


def _seed_proven(m, addr=PROVEN):
    m.set_entity("provider", addr, {
        "quality_score": 0.95, "on_time": 0.98, "jobs_done": 12,
        "default_events": 0,
    })


# --------------------------------------------------------------------------- #
# The actuarial table: premium is a pure function of memory                   #
# --------------------------------------------------------------------------- #
def test_premium_quote_is_a_pure_function_of_memory(tmp_path):
    """standard (no record) → base; proven (clean) → ×0.50; risky (a default)
    → ×2.20 and the house refuses to issue; each remembered bond scar adds a
    fixed step to the premium."""
    desk = _mk_desk(tmp_path)

    q = desk.premium_quote(STANDARD)  # unknown → flat standard
    assert q["segment"] == "standard" and q["premium"] == pytest.approx(BASE)

    _seed_proven(desk.m)
    q = desk.premium_quote(PROVEN)
    assert q["segment"] == "proven" and q["premium"] == pytest.approx(BASE * 0.5)
    assert q["mult"] == pytest.approx(0.5) and q["scars_against"] == 0

    desk.m.set_entity("provider", STANDARD, {
        "quality_score": 0.9, "on_time": 0.95, "jobs_done": 5, "default_events": 1})
    q = desk.premium_quote(STANDARD)
    assert q["segment"] == "risky" and q["premium"] == pytest.approx(BASE * 2.2)
    status, body = desk.issue(STANDARD, BUYER)  # the house will not bond risky
    assert status == 403 and body["house_declined"] is True

    # A bond scar raises the proven premium by one step (0.50 + 0.10 = 0.60).
    desk.scars.record(f"/bond/{PROVEN}", "timeout", "upstream 503")
    q = desk.premium_quote(PROVEN)
    assert q["scars_against"] == 1 and q["mult"] == pytest.approx(0.6)
    assert q["premium"] == pytest.approx(BASE * 0.6)


# --------------------------------------------------------------------------- #
# Issuing + the claim auto-pay (the differentiator: real money out)           #
# --------------------------------------------------------------------------- #
def test_issue_proven_bond_rebates_the_discount(tmp_path):
    """Proven: settle base onchain, rebate (base − premium) back; net =
    premium. The bond is recorded at the true (discounted) premium."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    status, body = desk.issue(PROVEN, BUYER)
    assert status == 200
    assert body["premium_usdc"] == pytest.approx(BASE * 0.5)
    assert body["status"] == "open" and body["open_exposure"] == pytest.approx(FACE)
    rebate = desk.wallet.send_rebate(BUYER, desk.base_premium, 0.5)
    assert rebate is not None and rebate.startswith("dry:")
    assert BASE * 0.5 == pytest.approx(body["premium_usdc"])


def test_claim_autopays_face_to_insured_and_remembers(tmp_path):
    """Provider defaults → the house pays the face to the INSURED, journals the
    tx + the scar, escalates the provider to risky, decays the exposure cap one
    step, and closes the bond (register shows the payout). A second claim on
    the same bond is a 409 (idempotent close)."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    st, iss = desk.issue(PROVEN, BUYER)
    assert st == 200
    bond_id = iss["bond_id"]

    cap_before = desk._effective_max_exposure()
    st, claim = desk.settle_failure(bond_id, "timeout", "upstream 503")
    assert st == 200
    assert claim["insured"] == BUYER
    assert claim["payout_usdc"] == pytest.approx(FACE)
    assert claim["claim_tx"].startswith("dry:")
    assert claim["scar_evidence"] is not None
    assert desk.premium_quote(PROVEN)["segment"] == "risky"  # default → risky
    assert claim["max_exposure_after"] == pytest.approx(cap_before - 1.0)
    reg = desk.register()
    assert reg["book"]["claims_paid"] == 1
    assert reg["book"]["payouts_usdc"] == pytest.approx(FACE)
    assert reg["bonds"][0]["status"] == "paid"
    assert reg["bonds"][0]["claim_tx"].startswith("dry:")
    # Idempotent: a settled claim cannot be paid again.
    st, body = desk.settle_failure(bond_id, "timeout", "x")
    assert st == 409 and body["status"] == "paid"


def test_unknown_claim_tx_not_phantom_when_wallet_raises(tmp_path, monkeypatch):
    """Finding #21: a claim the wallet can't send is NOT booked as paid — the
    bond closes as "failed" (retriable), no payout is booked, the cap does NOT
    decay, and claims_paid is not incremented. The house never books imaginary
    money. A retry with a working wallet pays exactly once."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    _, iss = desk.issue(PROVEN, BUYER)
    bid = iss["bond_id"]
    cap_before = desk._effective_max_exposure()
    orig_send = desk.wallet.send_usdc

    def boom(to, amt, memo):
        raise RuntimeError("no wallet configured")
    desk.wallet.send_usdc = boom  # type: ignore[assignment]

    st, claim = desk.settle_failure(bid, "timeout", "x")
    assert st == 200
    assert claim["status"] == "failed" and claim["paid"] is False
    assert claim["claim_tx"] is None  # not a fabricated hash
    assert claim["payout_usdc"] == pytest.approx(FACE)  # owed, not paid
    assert claim["claims_paid"] == 0
    assert claim["max_exposure_after"] == pytest.approx(cap_before)
    bond = desk.m.get_entity("bond", bid)
    assert bond["status"] == "failed" and bond["claim_tx"] is None

    # Retry with a working wallet: pays exactly once, decays the cap once.
    desk.wallet.send_usdc = orig_send  # type: ignore[assignment]
    st, claim2 = desk.settle_failure(bid, "timeout", "x")
    assert st == 200 and claim2["status"] == "paid" and claim2["paid"] is True
    assert claim2["claim_tx"] is not None and claim2["claims_paid"] == 1
    assert claim2["max_exposure_after"] == pytest.approx(cap_before - 1.0)
    assert desk.settle_failure(bid, "timeout", "x")[0] == 409  # no double payout


def test_claim_for_provider_pays_every_open_bond(tmp_path):
    """The spec's auto-trigger (Room 2's money moment): when a provider
    DEFAULTS, every OPEN bond on it is paid at once; each paid claim shrinks
    the cap. A second trigger for the same default is a no-op; a provider with
    no open bonds is a no-op."""
    desk = _mk_desk(tmp_path)
    desk.issue(PROVEN, BUYER)
    desk.issue(PROVEN, "0x" + "C" * 40)
    cap_before = desk._effective_max_exposure()

    results = desk.claim_for_provider(PROVEN, "timeout", "job 502'd twice")
    assert len(results) == 2
    assert all(st == 200 and c["paid"] for st, c in results)
    assert desk.claims_paid() == 2
    assert desk._effective_max_exposure() == pytest.approx(cap_before - 2.0)
    assert desk.claim_for_provider(PROVEN, "timeout", "again") == []  # no-op
    assert desk.claim_for_provider("0x" + "Z" * 40, "timeout", "x") == []


def test_max_exposure_refuses_over_leverage(tmp_path):
    """With a $10 cap and $1 faces, the 11th open bond is refused — the house
    does not over-leverage its remembered risk."""
    desk = _mk_desk(tmp_path, max_exposure=10.0)
    for i in range(10):
        status, _ = desk.issue(f"0x{'X' * 39}{i:01x}", BUYER)
        assert status == 200
    assert desk.open_exposure() == pytest.approx(10.0)
    status, body = desk.issue("0x" + "O" * 40, BUYER)
    assert status == 403 and body["house_declined"] is True
    assert "exposure" in body["reason"]


# --------------------------------------------------------------------------- #
# Deletion harness: the underwriting market collapses to a flat price list    #
# --------------------------------------------------------------------------- #
def test_deletion_mode_all_providers_price_flat(tmp_path, monkeypatch):
    """SIBYL_DISABLED=1 → no record, no scars → every provider is identical at
    the flat standard premium. Adverse selection: the book is unpriceable.
    Deleting memory collapses the whole underwriting market (the gate)."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m = HouseMemory(str(tmp_path / "mem.db"))
    desk = UnderwritingDesk(m)
    q1 = desk.premium_quote("0x" + "A" * 40)
    q2 = desk.premium_quote("0x" + "B" * 40)
    assert q1["segment"] == "standard" == q2["segment"]
    assert q1["premium"] == pytest.approx(BASE) and q1["premium"] == q2["premium"]
    assert desk.claims_paid() == 0


# --------------------------------------------------------------------------- #
# The thin HTTP boundary: paid POST is gated, the register is free            #
# --------------------------------------------------------------------------- #
def test_bond_quote_is_paid_not_free_and_register_is_free(tmp_path, monkeypatch):
    """POST /bond/quote is behind the x402 gate (402 without payment); GET
    /house/bonds is free and returns the book + bond list (empty until an
    issue lands)."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    assert client.post("/bond/quote", json={"provider": STANDARD}).status_code == 402

    r = client.get("/house/bonds")
    assert r.status_code == 200
    body = r.json()
    assert "book" in body and "bonds" in body
    assert body["book"]["bonds_issued"] == 0 and body["bonds"] == []
    _seed_proven(app.state.memory)
    st, iss = app.state.desk.issue(PROVEN, BUYER)
    assert st == 200
    r2 = client.get("/house/bonds")
    assert r2.json()["book"]["bonds_issued"] == 1
    assert r2.json()["bonds"][0]["provider_last6"] == PROVEN[-6:]


# --- direct handler tests: the paid POST route with a stub request ---------- #
class _BondStubRequest:
    """Minimal async Request stand-in for the paid /bond/quote handler."""

    def __init__(self, payer: str, provider: str):
        self.state = _StubState(payer)
        self._provider = provider

    async def json(self):
        return {"provider": self._provider}


class _StubState:
    def __init__(self, payer: str):
        self.payment_payload = {"payer": payer}


def _bond_handler(app):
    from fastapi.routing import APIRoute
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/bond/quote":
            return route.endpoint
    raise AssertionError("POST /bond/quote route not found")


def test_handler_risky_refused_403_uncharged(tmp_path, monkeypatch):
    """A risky provider is refused BEFORE settlement (403, uncharged); a
    missing provider is a 400 (bad request, not a silent charge)."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    app.state.memory.set_entity("provider", STANDARD, {
        "quality_score": 0.9, "on_time": 0.9, "jobs_done": 3, "default_events": 2})
    handler = _bond_handler(app)
    resp = asyncio.run(handler(_BondStubRequest(BUYER, STANDARD)))
    assert resp.status_code == 403
    body = resp.body.decode()
    assert "will not bond" in body and "uncharged" in body
    assert asyncio.run(handler(_BondStubRequest(BUYER, ""))).status_code == 400


# --------------------------------------------------------------------------- #
# The claim trigger: money OUT is gated, never a free/public endpoint           #
# --------------------------------------------------------------------------- #
class _ClaimStubRequest:
    def __init__(self, body: dict, token: str = ""):
        self._body = body
        self.headers = {"x-house-capability": token}

    async def json(self):
        return self._body


def _claim_handler(app):
    from fastapi.routing import APIRoute
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path == "/house/bonds/claim":
            return r.endpoint
    raise AssertionError("POST /house/bonds/claim not registered")


def _seed_open_bond(app):
    _seed_proven(app.state.memory)
    st, _ = app.state.desk.issue(PROVEN, BUYER)
    assert st == 200


def test_claim_route_gated_and_validates(tmp_path, monkeypatch):
    """Money out is NEVER a public endpoint: with HOUSE_COMPILE_TOKEN set the
    claim route is 403 without the capability header, and pays with it.
    Tokenless local/test (the demo's fault-injector path) it is open — but it
    still validates the provider shape (400, no payout)."""
    from app.x402.seller import build_app
    # Token-gated: 403 without, pays with.
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("HOUSE_COMPILE_TOKEN", "s3cret")
    app = build_app()
    _seed_open_bond(app)
    handler = _claim_handler(app)
    assert asyncio.run(handler(_ClaimStubRequest({"provider": PROVEN}))).status_code == 403
    out = asyncio.run(handler(_ClaimStubRequest(
        {"provider": PROVEN, "failure_class": "timeout"}, "s3cret")))
    assert out["settled"] == 1 and out["claims"][0]["claim_tx"].startswith("dry:")

    # Tokenless: open, but a junk provider is a 400 (no payout).
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "b.db"))
    monkeypatch.delenv("HOUSE_COMPILE_TOKEN", raising=False)
    app2 = build_app()
    _seed_open_bond(app2)
    handler2 = _claim_handler(app2)
    out2 = asyncio.run(handler2(_ClaimStubRequest(
        {"provider": PROVEN, "failure_class": "timeout"})))
    assert out2["settled"] == 1
    r = asyncio.run(handler2(_ClaimStubRequest(
        {"provider": "not-an-address", "failure_class": "timeout"})))
    assert r.status_code == 400

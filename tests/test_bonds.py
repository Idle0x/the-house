"""M1 — Room 2: the underwriting desk (bonds).

Sibyl enters insurance. These drive the ``UnderwritingDesk`` engine directly
(no x402 middleware, no CDP, no acp) and the thin FastAPI boundary via the
app's own route functions, asserting what is ACTUALLY priced / issued / paid
out / refused — the money claims are the point.

Money model under test (verified against the installed x402 2.x exact scheme,
same machinery as M0 /intel/quote):
  * onchain settlement is ALWAYS the 402 quote = the BASE bond premium
    (BOND_BASE_PREMIUM); the facilitator re-verifies the amount at settle.
  * memory only discounts (proven → rebate back, net = premium×mult) or
    refuses (risky / over-exposure → 403 BEFORE settlement → uncharged).
  * a claim is real money-OUT: the house pays the face to the insured via
    its own wallet (dry: pseudo-hash here, a real onchain tx when live),
    journals it next to the bond + the triggering scar, and REMEMBERS it
    (the exposure cap decays by one step per claim).

Face = $1.00, base premium = $0.05. Segments (premium = base × mult):
  proven  → mult 0.50 → $0.025   (clean record)
  standard→ mult 1.00 → $0.05    (unknown / thin record — the flat price)
  risky   → mult 2.20 → $0.11    (bad record; +$0.055 per bond scar)
"""
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
def test_unknown_provider_prices_flat_standard(tmp_path):
    """No record (or memory wiped) → the flat standard premium, no edge."""
    desk = _mk_desk(tmp_path)
    q = desk.premium_quote(STANDARD)
    assert q["segment"] == "standard"
    assert q["premium"] == pytest.approx(BASE * 1.0)


def test_proven_provider_discounts_to_half(tmp_path):
    """A clean record is priced low: base × 0.50 = $0.025."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    q = desk.premium_quote(PROVEN)
    assert q["segment"] == "proven"
    assert q["premium"] == pytest.approx(BASE * 0.5)
    assert q["mult"] == pytest.approx(0.5)
    assert q["scars_against"] == 0


def test_risky_provider_priced_high_and_unchargeable(tmp_path):
    """A bad record (a default) → base × 2.20 = $0.11, and the house refuses."""
    desk = _mk_desk(tmp_path)
    desk.m.set_entity("provider", STANDARD, {
        "quality_score": 0.9, "on_time": 0.95, "jobs_done": 5,
        "default_events": 1,
    })
    q = desk.premium_quote(STANDARD)
    assert q["segment"] == "risky"
    assert q["premium"] == pytest.approx(BASE * 2.2)
    # The house will not bond a risky provider — issue is refused (403).
    status, body = desk.issue(STANDARD, BUYER)
    assert status == 403
    assert body["house_declined"] is True


def test_bond_scar_raises_the_premium(tmp_path):
    """Each remembered bond scar adds a fixed step to the premium."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    # A proven provider with one bond scar: 0.50 + 0.10 = 0.60 → $0.03.
    desk.scars.record(f"/bond/{PROVEN}", "timeout", "upstream 503")
    q = desk.premium_quote(PROVEN)
    assert q["scars_against"] == 1
    assert q["mult"] == pytest.approx(0.6)
    assert q["premium"] == pytest.approx(BASE * 0.6)


# --------------------------------------------------------------------------- #
# Issuing + the claim auto-pay (the differentiator: real money out)           #
# --------------------------------------------------------------------------- #
def test_issue_proven_bond_rebates_the_discount(tmp_path):
    """Proven: settle base onchain, rebate (base − premium) back; net = premium.
    The bond is recorded at the true (discounted) premium."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    status, body = desk.issue(PROVEN, BUYER)
    assert status == 200
    assert body["premium_usdc"] == pytest.approx(BASE * 0.5)
    assert body["status"] == "open"
    assert body["open_exposure"] == pytest.approx(FACE)
    # The buyer overpaid onchain by (base − premium); rebate it back.
    rebate = desk.wallet.send_rebate(BUYER, desk.base_premium, 0.5)
    assert rebate is not None and rebate.startswith("dry:")
    net = BASE * 0.5
    assert net == pytest.approx(body["premium_usdc"])


def test_claim_autopays_face_to_insured_and_remembers(tmp_path):
    """Provider defaults → the house pays the face to the INSURED (not the
    provider), journals the tx + the scar, escalates the provider to risky,
    and decays the exposure cap by one step."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    st, iss = desk.issue(PROVEN, BUYER)
    assert st == 200
    bond_id = iss["bond_id"]

    cap_before = desk._effective_max_exposure()
    st, claim = desk.settle_failure(bond_id, "timeout", "upstream 503")
    assert st == 200
    # Money OUT: the face went to the insured, as a (dry) tx.
    assert claim["insured"] == BUYER
    assert claim["payout_usdc"] == pytest.approx(FACE)
    assert claim["claim_tx"].startswith("dry:")
    # The trigger was remembered: a scar against the provider + a default on
    # its record → its NEXT bond is priced off the failure.
    assert claim["scar_evidence"] is not None
    after = desk.premium_quote(PROVEN)
    assert after["segment"] == "risky"  # default_events now 1
    # The house remembers its limit: the cap decayed by one step.
    assert claim["max_exposure_after"] == pytest.approx(cap_before - 1.0)
    # The bond is closed and the register shows the payout.
    reg = desk.register()
    assert reg["book"]["claims_paid"] == 1
    assert reg["book"]["payouts_usdc"] == pytest.approx(FACE)
    assert reg["bonds"][0]["status"] == "paid"
    assert reg["bonds"][0]["claim_tx"].startswith("dry:")


def test_claim_only_pays_once(tmp_path):
    """A settled claim cannot be paid again (idempotent close)."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    _, iss = desk.issue(PROVEN, BUYER)
    bid = iss["bond_id"]
    assert desk.settle_failure(bid, "timeout", "x")[0] == 200
    st, body = desk.settle_failure(bid, "timeout", "x")
    assert st == 409
    assert body["status"] == "paid"


def test_unknown_claim_tx_not_phantom_when_wallet_raises(tmp_path, monkeypatch):
    """Finding #21: a claim the wallet can't send is NOT booked as paid —
    the bond closes as "failed" (retriable), the payout is not booked, the
    exposure cap does NOT decay, and claims_paid is not incremented. The
    house does not book imaginary money."""
    desk = _mk_desk(tmp_path)
    _seed_proven(desk.m)
    _, iss = desk.issue(PROVEN, BUYER)
    bid = iss["bond_id"]
    cap_before = desk._effective_max_exposure()
    orig_send = desk.wallet.send_usdc  # bound method, for the retry below

    def boom(to, amt, memo):
        raise RuntimeError("no wallet configured")
    desk.wallet.send_usdc = boom  # type: ignore[assignment]

    st, claim = desk.settle_failure(bid, "timeout", "x")
    assert st == 200
    assert claim["status"] == "failed"
    assert claim["paid"] is False
    assert claim["claim_tx"] is None  # not a fabricated hash
    assert claim["payout_usdc"] == pytest.approx(FACE)  # owed, not paid
    # No payout was sent → the cap did NOT decay and nothing was "paid".
    assert claim["claims_paid"] == 0
    assert claim["max_exposure_after"] == pytest.approx(cap_before)
    bond = desk.m.get_entity("bond", bid)
    assert bond["status"] == "failed"
    assert bond["claim_tx"] is None

    # Retry with a working wallet: pays exactly once, decays the cap once.
    desk.wallet.send_usdc = orig_send  # type: ignore[assignment]
    st, claim2 = desk.settle_failure(bid, "timeout", "x")
    assert st == 200
    assert claim2["status"] == "paid"
    assert claim2["paid"] is True
    assert claim2["claim_tx"] is not None
    assert claim2["claims_paid"] == 1
    assert claim2["max_exposure_after"] == pytest.approx(cap_before - 1.0)
    # Settled: a third attempt is refused (no double payout).
    assert desk.settle_failure(bid, "timeout", "x")[0] == 409


# --------------------------------------------------------------------------- #
# The house remembers its own limits (max open exposure)                      #
# --------------------------------------------------------------------------- #
def test_max_exposure_refuses_over_leverage(tmp_path):
    """With a $10 cap and $1 faces, the 11th open bond is refused — the house
    does not over-leverage its remembered risk."""
    desk = _mk_desk(tmp_path, max_exposure=10.0)
    for i in range(10):
        status, _ = desk.issue(f"0x{'X' * 39}{i:01x}", BUYER)
        assert status == 200
    assert desk.open_exposure() == pytest.approx(10.0)
    status, body = desk.issue("0x" + "O" * 40, BUYER)
    assert status == 403
    assert body["house_declined"] is True
    assert "exposure" in body["reason"]


def test_paid_claims_shrink_the_cap(tmp_path):
    """Each remembered claim shrinks the book's max-exposure cap."""
    desk = _mk_desk(tmp_path, max_exposure=10.0)
    assert desk._effective_max_exposure() == pytest.approx(10.0)
    _, iss = desk.issue(STANDARD, BUYER)
    desk.settle_failure(iss["bond_id"], "timeout", "x")
    assert desk._effective_max_exposure() == pytest.approx(9.0)


def test_issue_and_fail_twice_decays_cap_twice(tmp_path):
    """Drive the book via the public API: two paid claims (on distinct
    providers — a claim makes the provider risky, so it cannot be re-bonded)
    → the remembered cap decays by two."""
    desk = _mk_desk(tmp_path)
    for i, prov in enumerate(("0x" + "Q" * 39 + "1", "0x" + "Q" * 39 + "2")):
        status, iss = desk.issue(prov, BUYER)
        assert status == 200, f"issue {i} failed: {iss}"
        desk.settle_failure(iss["bond_id"], "timeout", "x")
    assert desk.claims_paid() == 2
    assert desk._effective_max_exposure() == pytest.approx(8.0)


# --------------------------------------------------------------------------- #
# Deletion harness: the underwriting market collapses to a flat price list    #
# --------------------------------------------------------------------------- #
def test_deletion_mode_all_providers_price_flat(tmp_path, monkeypatch):
    """SIBYL_DISABLED=1 → no record, no scars → every provider is identical at
    the flat standard premium. Adverse selection: the book is unpriceable. That
    is the gate — deleting memory collapses the whole underwriting market."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m = HouseMemory(str(tmp_path / "mem.db"))
    desk = UnderwritingDesk(m)
    q1 = desk.premium_quote("0x" + "A" * 40)
    q2 = desk.premium_quote("0x" + "B" * 40)
    assert q1["segment"] == "standard" == q2["segment"]
    assert q1["premium"] == pytest.approx(BASE)
    assert q1["premium"] == q2["premium"]
    # Nothing is remembered: the book is empty, claims can't be remembered.
    assert desk.claims_paid() == 0


# --------------------------------------------------------------------------- #
# The thin HTTP boundary: paid POST is gated, the register is free            #
# --------------------------------------------------------------------------- #
def test_bond_quote_is_paid_not_free(tmp_path, monkeypatch):
    """POST /bond/quote is behind the x402 gate (402 without payment)."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.post("/bond/quote", json={"provider": STANDARD})
    assert r.status_code == 402  # payment required — not free


def test_house_bonds_register_is_free(tmp_path, monkeypatch):
    """GET /house/bonds is free and returns the book + bond list."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/house/bonds")
    assert r.status_code == 200
    body = r.json()
    assert "book" in body and "bonds" in body
    assert body["book"]["bonds_issued"] == 0
    assert body["bonds"] == []
    # Issue one through the desk, then the free register shows it.
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
    """A risky provider is refused BEFORE settlement (403, uncharged)."""
    import asyncio
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    app.state.memory.set_entity("provider", STANDARD, {
        "quality_score": 0.9, "on_time": 0.9, "jobs_done": 3,
        "default_events": 2,
    })
    handler = _bond_handler(app)
    resp = asyncio.run(handler(_BondStubRequest(BUYER, STANDARD)))
    assert resp.status_code == 403
    body = resp.body.decode()
    assert "will not bond" in body
    assert "uncharged" in body


def test_handler_proven_issues_and_rebates(tmp_path, monkeypatch):
    """A proven provider: bond issued at the discounted premium + rebate tx."""
    import asyncio
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    _seed_proven(app.state.memory)
    handler = _bond_handler(app)
    resp = asyncio.run(handler(_BondStubRequest(BUYER, PROVEN)))
    # Success paths return plain dicts (FastAPI wraps them); only refusals
    # return a JSONResponse.
    assert not hasattr(resp, "status_code")
    data = resp if isinstance(resp, dict) else resp.json()
    assert data["premium_usdc"] == pytest.approx(BASE * 0.5)
    assert data["rebate_tx"].startswith("dry:")
    assert data["net_premium_usdc"] == pytest.approx(BASE * 0.5)


def test_handler_missing_provider_400(tmp_path, monkeypatch):
    """No provider in the body → 400 (bad request, not a silent charge)."""
    import asyncio
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    handler = _bond_handler(app)
    resp = asyncio.run(handler(_BondStubRequest(BUYER, "")))
    assert resp.status_code == 400

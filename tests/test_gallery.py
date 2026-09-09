"""Room 5 — the gallery + the real entity dossier, tested.

Two things are tested:

1. The DOSSIER engine (``core.dossier.Dossier``) — the cross-room read. One
   wallet's picture is assembled from trust (Room 1), the bond book (Room 2),
   the front office (Room 3), the watchtower (Room 4) and the settlement
   journal (Room 0). It only ever reports what the house has REMEMBERED, and
   every fact carries the timestamp it was observed. Deletion (memory
   disabled) → "no record": the dossier collapses with the memory that built
   it.

2. The thin HTTP BOUNDARY — the paid ``GET /intel/entity/{name}`` route runs
   the FULL engine (audit finding #9 parity): trust pricing, refusals, job
   state, and the money envelope — not a dossier-only shortcut. A 402 gate,
   a 404 for an unknown entity (uncharged), a 502 for an unresolvable payer,
   and the free /gallery + /house/journal endpoints.
"""
from __future__ import annotations

import os
import time
import types

from app.x402.seller import build_app
from core.bonds import UnderwritingDesk
from core.dossier import Dossier
from core.house import House
from core.memory import HouseMemory
from core.scout import FrontOffice
from core.watch import Watchtower

CALLER = "0x" + "1" * 40          # a wallet the house has served (caller)
PROV = "0x" + "2" * 40            # a provider the house has bonded
INSURED = "0x" + "3" * 40         # the insured (buyer) on a paid bond
UNKNOWN = "0x" + "9" * 40         # never seen → 404 uncharged


def _mem(tmp_path) -> HouseMemory:
    """Memory with SIBYL re-ENABLED (helper must not leak the flag)."""
    os.environ.pop("SIBYL_DISABLED", None)
    return HouseMemory(str(tmp_path / "memory.db"))


def _seed_vip(m: HouseMemory, addr: str) -> None:
    """Internally consistent VIP: trust>=80 AND tx>=10 → re-derives "vip"."""
    m.set_entity("caller", addr, {
        "address": addr, "first_seen": time.time() - 86400,
        "last_seen": time.time() - 3600,
        "tx_count": 12, "served_count": 12, "dedup_hits": 1,
        "total_paid_usdc": 0.055, "prepay_usdc": 0.0,
        "trust_score": 85.0, "segment": "vip",
        "failure_events": 0, "refund_events": 0, "warning_events": 0,
        "dedup_fp": [], "notes": "",
    })


def _seed_provider(m: HouseMemory) -> None:
    m.set_entity("provider", PROV, {
        "address": PROV, "first_seen": time.time() - 172800,
        "last_seen": time.time() - 7200,
        "jobs_done": 5, "on_time_jobs": 5, "quality_sum": 4.0,
        "quality_score": 0.8, "on_time": 1.0,
        "total_escrow_usdc": 5.0, "default_events": 1, "notes": "",
    })


def _seed_bond(m: HouseMemory) -> str:
    """A PAID bond: provider PROV, insured INSURED, claim tx present."""
    m.set_entity("bond", "B-test123456", {
        "id": "B-test123456", "provider": PROV, "buyer": INSURED,
        "face_usdc": 1.0, "premium_usdc": 0.05, "segment": "proven",
        "premium_mult": 0.5, "evidence": [], "status": "paid",
        "issued_at": time.time() - 5000,
        "claim_tx": "0x" + "D" * 64, "scar_evidence": "default",
        "closed_at": time.time() - 1000,
    })
    return "B-test123456"


def _make_dossier(m: HouseMemory, *, with_watch: bool = True) -> Dossier:
    from core.settle_journal import SettlementJournal
    desk = UnderwritingDesk(m)
    front = FrontOffice(m)
    watch = Watchtower(m, house_wallet="0x" + "F" * 40) if with_watch else None
    journal = SettlementJournal(m)
    return Dossier(m, desk=desk, front=front, watch=watch, journal=journal)


# --------------------------------------------------------------------------- #
# Dossier engine — the cross-room read
# --------------------------------------------------------------------------- #
def test_dossier_as_caller_provider_insured(tmp_path):
    """One wallet, assembled across all five rooms: the CALLER's trust row
    (vip, 12 tx, $0.055 net, aged last_seen); the PROVIDER's record + the PAID
    bond against it (status, claim_tx, claims_against); the INSURED sees the
    same bond from their side. Every fact is a dated observation."""
    m = _mem(tmp_path)
    _seed_vip(m, CALLER)
    _seed_provider(m)
    _seed_bond(m)

    c = _make_dossier(m).build(CALLER)["as_caller"]
    assert c["found"] is True
    assert c["segment"] == "vip" and c["trust_score"] == 85.0
    assert c["tx_count"] == 12 and c["dedup_hits"] == 1
    assert c["net_charged_usdc"] == 0.055
    assert c["last_seen_age_s"] is not None and c["last_seen_age_s"] >= 0

    d = _make_dossier(m).build(PROV)
    p = d["as_provider"]
    assert p["found"] is True and p["jobs_done"] == 5
    assert p["quality_score"] == 0.8 and p["default_events"] == 1
    bonds = p["bonds"]
    assert len(bonds) == 1 and bonds[0]["id"] == "B-test123456"
    assert bonds[0]["status"] == "paid" and bonds[0]["claim_tx"] == "0x" + "D" * 64
    assert bonds[0]["issued_age_s"] is not None
    assert p["claims_against"] == 1  # derived from the bond book

    insured = _make_dossier(m).build(INSURED)["bonds_as_insured"]
    assert len(insured) == 1
    assert insured[0]["provider_last6"] == PROV[-6:]
    assert insured[0]["insured_last6"] == INSURED[-6:]


def test_dossier_unknown_empty_timestamped_and_deletion(tmp_path, monkeypatch):
    """Unknown wallet → no record, every sub-view empty; a known wallet is a
    DATED snapshot (as_of + generated_at), not a claim. Deletion gate: memory
    disabled → the dossier knows nothing, even for a wallet it once knew."""
    m = _mem(tmp_path)
    _seed_vip(m, CALLER)
    u = _make_dossier(m).build(UNKNOWN)
    assert u["found"] is False and u["as_caller"]["found"] is False
    assert u["as_provider"]["found"] is False and u["bonds_as_insured"] == []
    assert u["settlements"] == []
    d = _make_dossier(m).build(CALLER)
    assert d["generated_at"] is not None and d["memory"] == "live"
    assert d["as_caller"]["as_of"] is not None

    # The deletion gate, inside the product.
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    dm = HouseMemory(str(tmp_path / "memory.db"))
    _seed_vip(dm, CALLER)
    dd = _make_dossier(dm).build(CALLER)
    assert dd["memory"] == "disabled" and dd["found"] is False
    assert "deletion gate" in dd["note"]


# --------------------------------------------------------------------------- #
# The real serve body — /intel/quote returns a memory-derived brief
# --------------------------------------------------------------------------- #
def test_serve_brief_is_real_for_vip_and_new_wallet(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    _seed_vip(app.state.memory, CALLER)
    house: House = app.state.house  # type: ignore[assignment]
    # A VIP gets a real brief naming their segment + tenure, not a canned line.
    status, body = house.serve_intel(CALLER, {})
    assert status == 200 and "vip" in body["intel"]
    assert body["standing"]["segment"] == "vip"
    assert "known you" in body["intel"] or "counterparty" in body["intel"]
    # A new wallet gets the "New wallet" brief.
    assert "New wallet" in house.serve_intel("0x" + "5" * 40, {})[1]["intel"]


# --------------------------------------------------------------------------- #
# The thin HTTP boundary — the paid entity route runs the FULL engine
# --------------------------------------------------------------------------- #
class _EntityRequest:
    """Minimal stand-in for the FastAPI Request the paid GET handler needs:
    .state.payment_payload, .app.state.house (no .json() for a GET)."""

    def __init__(self, house: House, payer: str | None = "0x" + "E" * 40):
        self.state = types.SimpleNamespace(
            payment_payload={"payer": payer} if payer else None)
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(house=house))


def _entity_handler(app):
    for route in app.routes:
        if getattr(route, "path", "") == "/intel/entity/{name}" \
                and "GET" in getattr(route, "methods", set()):
            return getattr(route, "endpoint", None)
    return None


def test_entity_route_registered_gated_and_full_engine(tmp_path, monkeypatch):
    """GET /intel/entity/:name is behind the x402 gate (402 without payment —
    the proof the :param pattern is resolved by the middleware) and is priced
    on the paid RouteConfig map. A paid read runs the FULL engine (finding #9):
    the cross-room dossier picture AND the money envelope (the VIP payer pays
    base onchain, net = 0.80×price, rebates 0.20)."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/intel/entity/{name}", "/gallery", "/house/journal"} <= paths
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "x402", "seller.py")).read()
    assert '"GET /intel/entity/:name"' in src
    from core.config import INTEL_ENTITY_PRICE
    assert INTEL_ENTITY_PRICE > 0
    client = TestClient(app)
    r = client.get(f"/intel/entity/{CALLER}")
    assert r.status_code == 402
    assert "PAYMENT-REQUIRED" in {k.upper() for k in r.headers}

    PAYER = "0x" + "E" * 40
    m: HouseMemory = app.state.memory  # type: ignore[assignment]
    _seed_vip(m, CALLER)               # the ENTITY the dossier is about (vip)
    _seed_vip(m, PAYER)                # the PAYER buying the dossier (vip)
    h: House = app.state.house  # type: ignore[assignment]
    out = _entity_handler(app)(CALLER, _EntityRequest(h, payer=PAYER))
    assert out["found"] is True
    assert out["as_caller"]["segment"] == "vip"
    assert out["payer_last6"] == PAYER[-6:]
    from core.config import INTEL_ENTITY_PRICE as P
    assert out["paid_usdc"] == P
    assert out["mult_applied"] == 0.80
    assert out["segment_price"] == round(P * 0.80, 6)
    assert out["rebate_usdc"] == round(P - round(P * 0.80, 6), 6)
    assert out["house"]["segment"] == "vip"


def test_entity_handler_unknown_404_and_no_payer_502(tmp_path, monkeypatch):
    """An entity the house never observed → 404, uncharged (no fabricated
    profile, no settlement). A verified payment with no recoverable payer →
    502 (server failure), so the settlement is cancelled and the buyer is
    uncharged — not a 200."""
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    h: House = app.state.house  # type: ignore[assignment]
    out = _entity_handler(app)(UNKNOWN, _EntityRequest(h))
    assert out.status_code == 404
    import json
    body = out.body if isinstance(out, dict) else json.loads(out.body)
    assert body.get("found") is False and body.get("uncharged") is True

    out2 = _entity_handler(app)(CALLER, _EntityRequest(h, payer=None))
    assert out2.status_code == 502


def test_gallery_renders_and_journal_free(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/gallery")
    assert r.status_code == 200 and "watchable" in r.text.lower()
    r2 = client.get("/house/journal")
    assert r2.status_code == 200
    assert r2.json()["memory"] in ("live", "disabled")
    assert "events" in r2.json()

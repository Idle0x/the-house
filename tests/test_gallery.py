"""M4 — Room 5: the gallery + the real entity dossier, tested.

Two things are tested here:

1. The DOSSIER engine (``core.dossier.Dossier``) — the cross-room read. One
   wallet's picture is assembled from trust (Room 1), the bond book (Room 2),
   the front office (Room 3), the watchtower (Room 4) and the settlement
   journal (Room 0). It only ever reports what the house has REMEMBERED, and
   every fact carries the timestamp it was observed. Deletion (memory
   disabled) → "no record": the dossier collapses with the memory that built
   it. That before/after is the deletion gate, inside the product.

2. The thin HTTP BOUNDARY — the paid ``GET /intel/entity/{name}`` route is
   402-gated (x402 resolves the :param pattern, verified); the handler 404s an
   unknown entity (uncharged) and returns the cross-room picture for a known
   one. The free ``/gallery`` + ``/house/journal`` endpoints render the watchable
   world and the season log.

The serve body (``House._default_work``) is tested too: /intel/quote returns a
memory-derived brief, not a canned line.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import types

from app.x402.seller import build_app  # noqa: E402
from core.bonds import UnderwritingDesk  # noqa: E402
from core.dossier import Dossier  # noqa: E402
from core.house import House  # noqa: E402
from core.memory import HouseMemory  # noqa: E402
from core.scout import FrontOffice  # noqa: E402
from core.watch import Watchtower  # noqa: E402

CALLER = "0x" + "1" * 40          # a wallet the house has served (caller)
PROV = "0x" + "2" * 40            # a provider the house has bonded
INSURED = "0x" + "3" * 40         # the insured (buyer) on a paid bond
UNKNOWN = "0x" + "9" * 40         # never seen → 404 uncharged


def _mem(tmp_path) -> HouseMemory:
    """Memory with SIBYL re-ENABLED (helper must not leak the flag)."""
    os.environ.pop("SIBYL_DISABLED", None)
    return HouseMemory(str(tmp_path / "memory.db"))


def _seed_caller(m: HouseMemory) -> None:
    # Internally consistent VIP: trust>=TRUST_VIP_MIN (80) AND tx>=VIP_MIN_TX (10)
    # → compute_segment re-derives "vip" at serve time, matching the stored field.
    m.set_entity("caller", CALLER, {
        "address": CALLER, "first_seen": time.time() - 86400,
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
    journal = SettlementJournal(m)  # the real object — only needs memory
    return Dossier(m, desk=desk, front=front, watch=watch, journal=journal)


# ---------------------------------------------------------------------------
# Dossier engine — the cross-room read
# ---------------------------------------------------------------------------
def test_dossier_as_caller(tmp_path):
    m = _mem(tmp_path)
    _seed_caller(m)
    d = _make_dossier(m).build(CALLER)
    assert d["found"] is True
    c = d["as_caller"]
    assert c["found"] is True
    assert c["segment"] == "vip"
    assert c["trust_score"] == 85.0
    assert c["tx_count"] == 12
    assert c["dedup_hits"] == 1
    assert c["net_charged_usdc"] == 0.055
    # freshness: a timestamp is carried and an age is derived
    assert c["last_seen"] is not None
    assert c["last_seen_age_s"] is not None
    assert c["last_seen_age_s"] >= 0


def test_dossier_as_provider_with_bond(tmp_path):
    m = _mem(tmp_path)
    _seed_provider(m)
    _seed_bond(m)
    d = _make_dossier(m).build(PROV)
    assert d["found"] is True
    p = d["as_provider"]
    assert p["found"] is True
    assert p["jobs_done"] == 5
    assert p["quality_score"] == 0.8
    assert p["default_events"] == 1
    # the paid bond against this provider is in the dossier
    bonds = p["bonds"]
    assert len(bonds) == 1
    assert bonds[0]["id"] == "B-test123456"
    assert bonds[0]["status"] == "paid"
    assert bonds[0]["claim_tx"] == "0x" + "D" * 64
    assert bonds[0]["issued_age_s"] is not None
    # claims_against is derived from the bond book (1 paid bond on PROV)
    assert p["claims_against"] == 1


def test_dossier_as_insured(tmp_path):
    m = _mem(tmp_path)
    _seed_provider(m)
    _seed_bond(m)
    d = _make_dossier(m).build(INSURED)
    assert d["found"] is True
    insured = d["bonds_as_insured"]
    assert len(insured) == 1
    assert insured[0]["insured_last6"] == INSURED[-6:]
    assert insured[0]["provider_last6"] == PROV[-6:]


def test_dossier_unknown_is_no_record(tmp_path):
    m = _mem(tmp_path)
    d = _make_dossier(m).build(UNKNOWN)
    assert d["found"] is False
    assert d["as_caller"]["found"] is False
    assert d["as_provider"]["found"] is False
    assert d["bonds_as_insured"] == []
    assert d["settlements"] == []


def test_dossier_deletion_collapses(tmp_path, monkeypatch):
    """The deletion gate, inside the product: memory disabled → the dossier
    knows nothing, so it assembles nothing — even for a wallet it once knew."""
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    m = HouseMemory(str(tmp_path / "memory.db"))
    # seed rows first (they'd be there before deletion), then disable
    _seed_caller(m)
    monkeypatch.setenv("SIBYL_DISABLED", "1")
    d = _make_dossier(m).build(CALLER)
    assert d["memory"] == "disabled"
    assert d["found"] is False
    assert "deletion gate" in d["note"]


def test_dossier_carrying_timestamps(tmp_path):
    """Every room field is dated — a dossier is a dated snapshot, not a claim."""
    m = _mem(tmp_path)
    _seed_caller(m)
    _seed_provider(m)
    _seed_bond(m)
    d = _make_dossier(m).build(CALLER)
    assert d["generated_at"] is not None
    assert d["memory"] == "live"
    # caller + provider both carry as_of + an age
    assert d["as_caller"]["as_of"] is not None
    p = _make_dossier(m).build(PROV)["as_provider"]
    assert p["as_of"] is not None
    assert p["last_seen_age_s"] is not None
    bond = p["bonds"][0]
    assert bond["as_of"] is not None and bond["issued_age_s"] is not None


# ---------------------------------------------------------------------------
# The real serve body — /intel/quote returns a memory-derived brief
# ---------------------------------------------------------------------------
def test_serve_brief_is_real_not_canned(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    m: HouseMemory = app.state.memory  # type: ignore[assignment]
    _seed_caller(m)
    house: House = app.state.house  # type: ignore[assignment]
    status, body = house.serve_intel(CALLER, {})
    assert status == 200
    # A real brief: names the segment and tenure, not the canned line.
    assert "intel" in body
    assert "vip" in body["intel"]
    assert "standing" in body
    assert body["standing"]["segment"] == "vip"
    assert "known you" in body["intel"] or "counterparty" in body["intel"]


def test_serve_brief_new_wallet(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    house: House = app.state.house  # type: ignore[assignment]
    status, body = house.serve_intel("0x" + "5" * 40, {})
    assert status == 200
    assert "New wallet" in body["intel"]


# ---------------------------------------------------------------------------
# The thin HTTP boundary
# ---------------------------------------------------------------------------
class _EntityRequest:
    """Minimal stand-in for the FastAPI Request the paid handler needs:
    .state.payment_payload, .app.state.dossier (no .json() for a GET)."""

    def __init__(self, dossier: Dossier, payer: str | None = "0x" + "E" * 40,
                 house: House | None = None):
        self.state = types.SimpleNamespace(
            payment_payload={"payer": payer} if payer else None)
        self.app = types.SimpleNamespace(
            state=types.SimpleNamespace(dossier=dossier, house=house))


def _entity_handler(app):
    for route in app.routes:
        if getattr(route, "path", "") == "/intel/entity/{name}" \
                and "GET" in getattr(route, "methods", set()):
            return getattr(route, "endpoint", None)
    return None


def test_entity_route_registered_and_priced(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/intel/entity/{name}" in paths
    assert "/gallery" in paths
    assert "/house/journal" in paths
    # The paid route is present in the x402 RouteConfig map (param pattern).
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "app", "x402", "seller.py")).read()
    assert '"GET /intel/entity/:name"' in src
    from core.config import INTEL_ENTITY_PRICE
    assert INTEL_ENTITY_PRICE > 0


def test_entity_route_is_402_unpaid(tmp_path, monkeypatch):
    """GET /intel/entity/:name is behind the x402 gate (402 without payment).
    This is the proof the :param pattern is resolved by the middleware."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get(f"/intel/entity/{CALLER}")
    assert r.status_code == 402
    assert "PAYMENT-REQUIRED" in {k.upper() for k in r.headers}


def test_entity_handler_unknown_404_uncharged(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    d: Dossier = app.state.dossier  # type: ignore[assignment]
    h: House = app.state.house  # type: ignore[assignment]
    handler = _entity_handler(app)
    assert handler is not None
    out = handler(UNKNOWN, _EntityRequest(d, house=h))
    assert out.status_code == 404
    body = out.body if isinstance(out, dict) else __import__("json").loads(out.body)
    assert body.get("found") is False
    assert body.get("uncharged") is True


def test_entity_handler_known_returns_picture(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    m: HouseMemory = app.state.memory  # type: ignore[assignment]
    _seed_caller(m)
    d: Dossier = app.state.dossier  # type: ignore[assignment]
    h: House = app.state.house  # type: ignore[assignment]
    handler = _entity_handler(app)
    assert handler is not None
    out = handler(CALLER, _EntityRequest(d, house=h))
    assert out["found"] is True
    assert out["payer_last6"] == "E" * 6
    assert out["as_caller"]["segment"] == "vip"


def test_entity_handler_requires_payer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    d: Dossier = app.state.dossier  # type: ignore[assignment]
    handler = _entity_handler(app)
    assert handler is not None
    out = handler(CALLER, _EntityRequest(d, payer=None))
    assert out.status_code == 502


# ---------------------------------------------------------------------------
# Free gallery + season log
# ---------------------------------------------------------------------------
def test_gallery_renders_and_journal_free(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    client = TestClient(app)
    r = client.get("/gallery")
    assert r.status_code == 200
    assert "watchable" in r.text.lower()
    # the free season log
    r2 = client.get("/house/journal")
    assert r2.status_code == 200
    assert r2.json()["memory"] in ("live", "disabled")
    assert "events" in r2.json()

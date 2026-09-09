"""P2 audit-fix regression tests (SEV-2 / FIX-4c: full addresses on the public
surface).

The COLD journal + watch feed STORE full payer/wallet addresses (required —
FIX-4: the ledger must reconcile against Basescan). The VIOLATION was that the
FREE public routes rendered them verbatim. The fix is redaction at the PUBLIC
BOUNDARY: the store keeps full, the public render masks to 0x<last4>.

These tests prove:
  * the public routes no longer leak a full 0x40 payer/wallet/caller;
  * the underlying store STILL holds the full address (reconciliation intact);
  * the onchain tx hash is preserved verbatim (it is public by design).
"""
import re
import uuid

from core.memory import HouseMemory
from core.house import House
from core.watch import Watchtower
from core.redact import redact_text, redact_address

FULL = "0x8A8a1234567890abcdef1234567890ABCDEF10Aa"  # 0x + 40 hex
assert len(FULL) == 42, f"FULL must be 0x + 40 hex, got {len(FULL)}"
_LAST4 = FULL[-4:]
_TX = "0x" + "deadbeef" * 5


def _addr40(tag: str) -> str:
    base = tag.upper() + "0" * 38
    return "0x" + base


# --------------------------------------------------------------------------- #
# redact helpers themselves
# --------------------------------------------------------------------------- #
def test_redact_text_masks_full_addresses_preserves_tx():
    # A settlement line has BOTH the tx hash and the full payer (0x40 hex).
    # The tx is passed in `preserve` (public onchain); the payer is masked.
    out = redact_text(
        f"settlement {_TX} /intel/quote 0.01USDC {FULL} (settlement)",
        preserve=frozenset({_TX}))
    assert FULL not in out
    assert _TX in out  # tx preserved verbatim
    assert ("0x" + _LAST4) in out  # payer masked to 0x<last4>
    remaining = re.findall(r"0x[0-9a-fA-F]{40}", out)
    assert remaining == [_TX]  # only the tx hash survives as full 0x40


def test_redact_text_masks_tx_when_not_preserved():
    # Without preserve, EVERY full 0x40 is masked (nothing survives).
    out = redact_text(f"a {FULL} b {_TX} c")
    assert re.findall(r"0x[0-9a-fA-F]{40}", out) == []


def test_redact_address_field():
    assert redact_address(FULL) == "0x" + FULL[-4:]
    # already-anonymized last-6 passes through untouched
    assert redact_address("abcd10") == "abcd10"
    assert redact_address(None) is None


def test_redact_text_leaves_non_addresses():
    assert redact_text("hello world 0x123") == "hello world 0x123"


# --------------------------------------------------------------------------- #
# the public routes — end-to-end, no full address on the wire
# --------------------------------------------------------------------------- #
def _build(tmp_path, monkeypatch):
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    from app.x402.seller import build_app
    app = build_app()
    return app


def _seed_settlement(app, payer: str):
    """Record a real settlement (full payer + tx) the way the middleware does."""
    house = app.state.house
    house.journal.record({"tx": _TX, "payer": payer, "route": "/intel/quote",
                          "amount_usdc": 0.01, "kind": "settlement"})
    # a serve so the journal also has event text with the full address
    house.ledger.update(payer, "served", paid_usdc=0.01)


def _all_text(obj) -> str:
    import json
    return json.dumps(obj)


def test_journal_route_redacts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    app = _build(tmp_path, monkeypatch)
    _seed_settlement(app, FULL)
    client = TestClient(app)
    r = client.get("/house/journal")
    assert r.status_code == 200
    wire = _all_text(r.json())
    assert FULL not in wire, "journal leaked the full payer on the public wire"
    # ...but the store still holds it (reconciliation intact).
    full_events = " ".join(" ".join(e.get("acted") or [])
                           for e in app.state.memory.read_events(limit=50))
    assert FULL in full_events, "the COLD journal must KEEP the full payer"


def test_ledger_recent_redacts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    app = _build(tmp_path, monkeypatch)
    _seed_settlement(app, FULL)
    client = TestClient(app)
    r = client.get("/house/ledger")
    assert r.status_code == 200
    wire = _all_text(r.json())
    assert FULL not in wire, "ledger money.recent leaked the full payer"
    # tx hash preserved on the wire (public onchain artifact)
    assert _TX in wire


def test_watch_feed_redacts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    app = _build(tmp_path, monkeypatch)
    watch = app.state.watch
    # a paid screen publishes a full wallet to the feed
    watch.m.set_entity("caller", FULL, {"address": FULL, "tx_count": 10,
                                        "served_count": 10, "trust_score": 70.0,
                                        "segment": "regular", "funded_by": "0x" + "9" * 40})
    watch.screen(FULL)
    client = TestClient(app)
    r = client.get("/house/watch")
    assert r.status_code == 200
    wire = _all_text(r.json())
    assert FULL not in wire, "watch feed leaked the full wallet on the public wire"


def test_jobs_route_redacts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    app = _build(tmp_path, monkeypatch)
    house = app.state.house
    house.jobs.start(FULL, "/intel/quote", "fp-x")
    client = TestClient(app)
    r = client.get("/house/jobs")
    assert r.status_code == 200
    wire = _all_text(r.json())
    assert FULL not in wire, "jobs snapshot leaked the full caller on the public wire"


# --------------------------------------------------------------------------- #
# the store keeps FULL for reconciliation even though the wire is redacted
# --------------------------------------------------------------------------- #
def test_store_keeps_full_payer_for_reconciliation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    app = _build(tmp_path, monkeypatch)
    _seed_settlement(app, FULL)
    # operator-facing: the journal.entries() (in-memory, not the public route)
    # still has the full payer + tx so the house reconciles against Basescan.
    entry = app.state.house.journal.entries(limit=1)[0]
    assert entry["payer"] == FULL
    assert entry["tx"] == _TX

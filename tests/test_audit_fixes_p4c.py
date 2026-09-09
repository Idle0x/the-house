"""P4c audit-fix regression tests (findings #14 hermetic cache + #25 address shape).

#14: tests are disk-hermetic — a ``House()``/``build_app()`` with no explicit
    cache_dir override writes into a session tmp dir (conftest), never the repo
    ``cache/`` tree.
#25: every public route that takes a counterparty identifier rejects a
    non-``0x``-40-char junk string with 400 BEFORE any memory is written. The
    shape validator is the single source of truth (``core.identity``).
"""
import asyncio

from core.identity import is_wallet, require_wallet
from core.memory import HouseMemory
from core.house import House
from core.dedup import fingerprint


# --------------------------------------------------------------------------- #
# core.identity — the shape validator itself
# --------------------------------------------------------------------------- #
def test_is_wallet_accepts_canonical_shapes():
    # Real EVM address (hex) and the codebase's non-hex 40-char placeholders.
    assert is_wallet("0x436f324eff0b32a405c5b9102e1a6ef85451cec1")
    assert is_wallet("0x" + "S" * 40)
    assert is_wallet("0x" + "1" * 40)
    # Surrounding whitespace is tolerated (stripped) — inputs are user text.
    assert is_wallet("  0x" + "A" * 40 + "  ")


def test_is_wallet_rejects_junk():
    assert not is_wallet("")
    assert not is_wallet("   ")
    assert not is_wallet("hello")
    assert not is_wallet("0x123")                        # too short
    assert not is_wallet("0x" + "A" * 41)                # too long
    assert not is_wallet("0x" + "A" * 39)                # too short
    assert not is_wallet("1" * 40)                       # no 0x prefix
    assert not is_wallet("0x" + "A" * 20 + " " * 20)     # non-alnum body
    assert not is_wallet(None)
    assert not is_wallet(123)
    assert not is_wallet(["0x" + "A" * 40])


def test_require_wallet_returns_normalized_or_none():
    assert require_wallet("  0x" + "B" * 40 + "  ") == "0x" + "B" * 40
    assert require_wallet("junk") is None
    assert require_wallet(None) is None


# --------------------------------------------------------------------------- #
# #14 — hermetic cache: a House with no override writes to the tmp dir, NOT
#       the repo cache tree.
# --------------------------------------------------------------------------- #
def test_house_default_cache_dir_is_env_overridden(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.delenv("SIBYL_DISABLED", raising=False)
    # conftest already set HOUSE_CACHE_DIR to a session tmp dir.
    cache_env = os.environ["HOUSE_CACHE_DIR"]
    assert "house_hermetic" in cache_env  # the session fixture won
    m = HouseMemory(str(tmp_path / "memory.db"))
    h = House(m, base_price=0.01)
    # A serve writes a cache file under the tmp dir, not the repo tree.
    h.serve_intel("0x" + "1" * 40, {"q": "hermetic"})
    fp = fingerprint("/intel/quote", {"q": "hermetic"})
    path = h.dedup._fp_path(fp)
    assert path.exists()
    assert str(path).startswith(cache_env), \
        f"cache file {path} landed outside the hermetic tmp dir"


# --------------------------------------------------------------------------- #
# #25 — each public route rejects a junk identifier with 400 (no memory write)
# --------------------------------------------------------------------------- #
from tests.test_front_office import _handler, _StubRequest  # noqa: E402


def test_scout_hire_rejects_junk_provider_uncharged(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front = app.state.front
    handler = _handler(app, "POST", "/scout/hire")
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest({"provider": "hello"}, front)))
    assert getattr(resp, "status_code", 200) == 400
    # A junk provider must NOT have created a provider row in memory.
    assert front.m.get_entity("provider", "hello") is None


def test_scout_report_rejects_junk_provider_uncharged(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    front = app.state.front
    handler = _handler(app, "POST", "/scout/report")
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest({"provider": "0x123"}, front)))
    assert getattr(resp, "status_code", 200) == 400
    assert front.m.get_entity("provider", "0x123") is None


def test_watch_screen_rejects_junk_wallet(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    watch = app.state.watch
    handler = _handler(app, "POST", "/watch/screen")
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest({"wallet": "not-an-address"}, watch)))
    assert getattr(resp, "status_code", 200) == 400


def test_bond_quote_rejects_junk_provider(tmp_path, monkeypatch):
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    desk = app.state.desk
    handler = _handler(app, "POST", "/bond/quote")
    assert handler is not None
    resp = asyncio.run(handler(_StubRequest({"provider": "junk"}, desk)))
    assert getattr(resp, "status_code", 200) == 400
    assert desk.m.get_entity("provider", "junk") is None


def test_entity_route_rejects_junk_name(tmp_path, monkeypatch):
    """The dossier route rejects a malformed entity id with 400 before any
    memory read. It is a paid GET, so a 400 also cancels the settlement."""
    from app.x402.seller import build_app
    monkeypatch.setenv("HOUSE_MEMORY_DB", str(tmp_path / "memory.db"))
    app = build_app()
    route = next(r for r in app.routes
                 if getattr(r, "path", "") == "/intel/entity/{name}")
    handler = getattr(route, "endpoint", None)
    assert handler is not None

    import types
    req = types.SimpleNamespace(state=types.SimpleNamespace(
        payment_payload=None), app=app)
    resp = handler("hello-world", req)
    assert getattr(resp, "status_code", 200) == 400

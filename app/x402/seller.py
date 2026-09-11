"""THE HOUSE — x402 seller on Base mainnet.

This module is the THIN FastAPI/x402 boundary (the F4 "not a god-object"
requirement). All money/memory logic lives in ``core.house.House`` so it is
unit-testable without the CDP facilitator or a network. The routes here are a
spoke: paid ``/intel/quote`` delegates to the House engine; the free ``/house/*``
routes are the observability surface.

Flow per 02-ARCHITECTURE §4 — verified against the installed x402 2.x exact
scheme (NOT assumed):
  * the buyer signs EIP-3009 for EXACTLY the 402 quote (BASE); the facilitator
    re-verifies the amount at settle, so the onchain settlement is always base.
  * the handler runs BEFORE settlement and a >=400 response CANCELS it, so a
    refusal (banned / risky prepay) is genuinely uncharged.
  * the settlement tx hash arrives in the PAYMENT-RESPONSE header AFTER the
    handler — ``JournalingPaymentMiddleware`` records it (FIX-4).

Loyalty pricing is settled base onchain + a real rebate tx back via the
house's own ACP wallet (VIP ×0.80, regular ×0.95, repeat net-$0). See
``core.house`` for the full money model.

Rail (CDP-verified): Base mainnet Exact scheme via the Coinbase X402
facilitator. Needs the house's OWN credentials in .env:
    CDP_API_KEY_ID, CDP_API_KEY_SECRET, HOUSE_WALLET
Deletion harness: SIBYL_DISABLED=1 → the memory collapses; every caller is
treated as new (list price, no dedup, no refusal, no rebate). The business
model collapses to a stateless price list (that is the gate).
"""
from __future__ import annotations

import logging
import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from core.identity import require_wallet
from core.redact import redact_text, redact_value

from app.x402.landing import build_landing_state, render_landing
from app.x402.gallery import render_gallery
from app.x402.docs import render_docs
from core.bonds import UnderwritingDesk
from core.acp import ACPDelegator
from core.config import (BOND_BASE_PREMIUM, INTEL_ENTITY_PRICE,
                         PREPAY_TOPUP_FEE, PREPAY_TOPUP_MAX, WATCH_SCREEN_PRICE)
from core.dossier import Dossier
from core.house import House
from core.memory import HouseMemory
from core.scout import SCOUT_HIRE_PRICE, SCOUT_REPORT_BASE, FrontOffice
from core.settle_journal import decode_settlement_header
from core.wallet import HouseWallet, USDC_BASE
from core.watch import Watchtower
from core.wipe import WipeController

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger("the-house.seller")

NETWORK = os.getenv("HOUSE_NETWORK", "eip155:8453")
BASE_PRICE = float(os.getenv("HOUSE_BASE_PRICE", "0.01"))  # USDC list price
SERVICE_NAME = os.getenv("HOUSE_SERVICE_NAME", "the-house")

# Recorded status of the three real ACP jobs (Sep 7 — verified on Base mainnet
# via the ACP index: all completed, escrow funded + released). Used ONLY when
# the acp CLI is unavailable; the response then carries live=false so the page
# never presents a recorded status as a live read.
_ACP_FALLBACK = {
    "77330": {"provider": "0x436f324eff0b32a405c5b9102e1a6ef85451cec1",
              "provider_name": "BitsAndBytesBack",
              "offering": "prompt_optimization", "escrow_usdc": 0.02,
              "escrow_tx": "0x939a1fc8ab94d5aeed5725aaca6e6c96122a5d95c624e835a045855b5492a277"},
    "77332": {"provider": "0xec4bc04310925326ff80daf419a3861173865689",
              "provider_name": "aiworker-data",
              "offering": "page_markdown", "escrow_usdc": 0.02,
              "escrow_tx": "0xebcf9d0c137b5216df45fe49a6187ae4a3e3c76bc378cdcece9003d283ec756a"},
    "77338": {"provider": "0xecf9773b50f01f3a97b087a6ecdf12a71afc558c",
              "provider_name": "TheMetaBot",
              "offering": "agentRiskCheck", "escrow_usdc": 0.05,
              "escrow_tx": "0xfce202ce19be3d9359e4ba4a5181342b1bd6f02153b0c05ee65a8c38a7206d30"},
}


def _ACP_FALLBACK_JOBS() -> list[dict]:
    return [{
        "job_id": jid,
        "status": "completed (recorded)",
        "offering": spec["offering"],
        "escrow_usdc": spec["escrow_usdc"],
        "escrow_tx": spec["escrow_tx"],
        "provider": spec["provider"],
        "provider_name": spec["provider_name"],
        "completed_reason": None,
        "recorded": True,
    } for jid, spec in _ACP_FALLBACK.items()]

# The x402 header that carries the base64 SettleResponse (tx hash, payer, amt).
# Imported lazily to avoid an import-time dependency in unit tests.
def _payment_response_header() -> str:
    from x402.http.constants import PAYMENT_RESPONSE_HEADER
    return PAYMENT_RESPONSE_HEADER


# 0xZERO — unmistakably not a funded wallet. Never a destination / sender.
HOUSE_WALLET_PLACEHOLDER = "0x" + "0" * 40


def _acp_wallet_check() -> dict:
    """FIX-4d startup self-check: the ACP wallet address MUST match the
    configured HOUSE_WALLET, else the house receives on the x402 pay_to but
    would send rebates from a different wallet (money split). Refuse boot.

    Shells out to `acp wallet address` (real CLI) — only called when live
    money-out is enabled. On any error, returns ok=False (fail-closed).
    """
    import shutil, subprocess, json
    acp = os.getenv("ACP_BIN") or shutil.which("acp") or "acp"
    expected = _house_wallet()
    try:
        proc = subprocess.run([acp, "wallet", "address", "--json"],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return {"ok": False, "reason": f"acp wallet address exit {proc.returncode}"}
        out = proc.stdout.strip()
        try:
            addr = json.loads(out).get("address", out)
        except json.JSONDecodeError:
            addr = out.split()[-1] if out else ""
        if not addr.startswith("0x"):
            # some builds print bare hex
            addr = "0x" + addr
        ok = addr.lower() == expected.lower()
        return {"ok": ok, "acp": addr, "expected": expected}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": str(exc)}


def _house_wallet() -> str:
    """Receiving address. Production MUST set HOUSE_WALLET (the house's own ACP
    wallet); when it's unset we fall back to an obvious NON-FUNDS placeholder
    so build_app works in tests/dev — and the engine's guard refuses to send
    any real rebate out of a placeholder, so a misconfigured env can never
    move real money (it just skips the rebate, which is safe to log)."""
    w = os.getenv("HOUSE_WALLET", "").strip()
    if not w:
        return HOUSE_WALLET_PLACEHOLDER
    return w


def extract_payer(payment_payload: Any) -> Optional[str]:
    """Payer address from a verified x402 payload (02-ARCHITECTURE step 1).

    Exact scheme: payload.payload.authorization.from_address (EIP-3009).
    Fallbacks: payload.payer / payload.from / payload.sender, or a bare dict.
    """
    if payment_payload is None:
        return None
    if isinstance(payment_payload, dict):
        auth = payment_payload.get("authorization") or {}
        if isinstance(auth, dict):
            for k in ("from_address", "from", "sender"):
                v = auth.get(k)
                if v:
                    return str(v)
        for k in ("payer", "from_address", "from", "sender"):
            v = payment_payload.get(k)
            if v:
                return str(v)
        return None
    p = getattr(payment_payload, "payload", None)
    if isinstance(p, dict):
        auth = p.get("authorization") or {}
        if isinstance(auth, dict):
            for k in ("from_address", "from", "sender"):
                v = auth.get(k)
                if v:
                    return str(v)
        for k in ("payer", "from_address", "from", "sender"):
            v = p.get(k)
            if v:
                return str(v)
    for attr in ("payer", "from_address", "from", "sender"):
        v = getattr(payment_payload, attr, None)
        if v:
            return str(v)
    return None


def make_journal_middleware(journal):  # type: ignore[no-untyped-def]
    """Return a ``PaymentMiddlewareASGI`` subclass that also journals every
    settlement (FIX-4).

    The x402 middleware settles AFTER the handler and returns the tx in the
    PAYMENT-RESPONSE header. The subclass wraps the normal payment flow, then
    decodes that header and records every settlement the house actually
    received (tx hash, payer, route, USDC) — what lets the house reconcile its
    own revenue against Basescan from its own state.

    Starlette binds ``self.dispatch_func = self.dispatch`` in
    ``BaseHTTPMiddleware.__init__``; we re-point it at ``journaling_dispatch``
    (which calls the real x402 ``dispatch`` directly — no recursion).
    Built here (inside build_app) so the x402 import stays lazy for tests.
    """
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI

    class JournalingPaymentMiddleware(PaymentMiddlewareASGI):  # type: ignore[misc]
        def __init__(self, app, routes, server,  # type: ignore[no-untyped-def]
                     paywall_config=None, paywall_provider=None):
            super().__init__(app, routes, server, paywall_config, paywall_provider)  # type: ignore[call-arg]
            self.journal = journal
            self._payment_response_header = _payment_response_header()
            self.dispatch_func = self.journaling_dispatch  # type: ignore[assignment]

        async def journaling_dispatch(self, request: Request,
                                      call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            response = await PaymentMiddlewareASGI.dispatch(self, request, call_next)  # type: ignore[arg-type]
            try:
                header = response.headers.get(self._payment_response_header)
                if header:
                    entry = decode_settlement_header(header)
                    if entry and entry.get("success") is not False and entry.get("tx"):
                        self.journal.record({
                            "tx": entry.get("tx"),
                            "payer": entry.get("payer"),
                            "route": request.url.path,
                            "amount_usdc": entry.get("amount_usdc", 0.0),
                            "amount_atomic": entry.get("amount_atomic"),
                            "network": entry.get("network"),
                            "kind": "settlement",
                        })
            except Exception:  # noqa: BLE001 - journaling never breaks the response
                log.exception("settlement journal record failed")
            return response

    return JournalingPaymentMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """F4: on startup verify the wallet and resume/re-drive stalled jobs
    (kill -9 → wake up, finish, settle idempotently). Under SIBYL_DISABLED the
    null memory holds no jobs — resume is a no-op (idempotency died with the
    memory, the deletion degradation).

    Also runs a background self-heal loop: a soft-off (disable) re-enables the
    house automatically after its 15-minute window, even if nobody is watching
    the landing page. Purge is permanent and never self-heals.
    """
    house: House = app.state.house  # type: ignore[attr-defined]
    info = house.startup()
    log.info("startup: wallet_ok=%s resumed=%d driven=%s",
             info["wallet_ok"], info["resumed"], info["driven"])

    # Boot re-seed (Model A: true deletion + re-seed): a FRESH, EMPTY store
    # re-learns the chain-proven caller set (who verifiably paid, how often)
    # from Base receipts before serving. Gates, in order:
    #   * memory disabled (SIBYL_DISABLED) → skip (reads are empty anyway)
    #   * purge marker present → skip (a purge stays blind, across restarts)
    #   * any caller rows exist → skip (never touch live state)
    #   * pytest running → skip (no network in unit tests)
    #   * HOUSE_RESEED_ON_BOOT=0 → skip (explicit opt-out)
    # Best-effort and non-fatal: RPC failure leaves a clean cold-start.
    try:
        memory: HouseMemory = app.state.memory  # type: ignore[attr-defined]
        marker = Path(memory.db_path).expanduser().parent / ".house-purged"
        reseed_off = os.getenv("HOUSE_RESEED_ON_BOOT", "1").strip().lower() in (
            "0", "false", "no")
        if (not memory.disabled() and not marker.exists()
                and not memory.list_entities("caller", limit=5)
                and not os.getenv("PYTEST_CURRENT_TEST")
                and not reseed_off):
            from core.reseed import reseed_from_chain
            summary = reseed_from_chain(memory, house_wallet=_house_wallet())
            log.info("startup: reseed restored=%s",
                     summary.get("restored", summary))
        elif marker.exists():
            log.info("startup: purge marker present — staying blind, no reseed")
    except Exception:  # noqa: BLE001 - reseed never breaks boot
        log.exception("startup: reseed failed (non-fatal)")

    # Background auto-re-enable for the reversible soft-off (disable). Purge
    # is permanent — this loop never touches a purged store.
    stop = asyncio.Event()

    async def _auto_reenable_loop() -> None:
        while not stop.is_set():
            try:
                wipe: WipeController = app.state.wipe  # type: ignore[attr-defined]
                memory: HouseMemory = app.state.memory  # type: ignore[attr-defined]
                if wipe.maybe_auto_reenable(memory):
                    log.info("memory: auto re-enabled after 5-min soft-off")
            except Exception:  # noqa: BLE001 - never kill the loop
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                continue

    task = asyncio.create_task(_auto_reenable_loop())
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


def _git_commit() -> str:
    """Short git SHA of the running checkout ("" outside a repo / on failure).
    Surfaced on the landing page as the build identity.

    Env ``HOUSE_COMMIT`` wins: production images exclude ``.git`` (see
    .dockerignore), so the deploy platform injects the SHA at build time
    (Dockerfile ``ARG GIT_SHA``) or via dashboard variables."""
    env = os.getenv("HOUSE_COMMIT", "").strip()
    if env:
        return env
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - build identity is best-effort
        return ""


# Fallback build identity when neither env nor git can provide one (a
# container built from this repo with .git excluded). This is the public
# submission repo — forks should set HOUSE_REPO_URL instead.
DEFAULT_REPO_URL = "https://github.com/Idle0x/the-house"


def _repo_url() -> str:
    """Public repo URL for the landing page.

    Precedence: explicit ``HOUSE_REPO_URL`` env (deploy dashboards) → git
    origin remote → DEFAULT_REPO_URL. Returns the default (never "") so a
    production build without git metadata still links the public repo
    instead of rendering the 'private build page' fallback line. (An empty
    string previously meant 'no remote yet'; the repo is public now.)"""
    env = os.getenv("HOUSE_REPO_URL", "").strip().rstrip("/")
    if env:
        return env
    import subprocess
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=5,
        )
        url = out.stdout.strip()
        if not url:
            return DEFAULT_REPO_URL
        # normalize git@github.com:user/repo.git -> https://github.com/user/repo
        if url.startswith("git@") and ":" in url:
            hostpath = url.split("@", 1)[1]
            url = "https://" + hostpath.replace(":", "/", 1)
        return url.rstrip("/").removesuffix(".git")
    except Exception:  # noqa: BLE001
        return DEFAULT_REPO_URL


def _client_ip(request: Request) -> str:
    """Best-effort client IP for the deletion gate's per-IP cooldown.

    Behind a proxy the real IP is in X-Forwarded-For; fall back to the peer.
    This is a demo-grade guard, not a security boundary — see core/wipe.py."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _public_url(request: Request) -> str:
    """Externally reachable origin for the try-it commands.

    Prefers the explicit ``HOUSE_PUBLIC_URL`` env (set to the Railway domain
    in production). When unset, derives the origin from the request's Host
    header (with the proxy's X-Forwarded-Proto), so the page works on any
    deploy without configuration. Never emits an internal IP/localhost: if
    the derived host looks internal, it is suppressed (try-it falls back to
    the relative /house/* form)."""
    env = os.getenv("HOUSE_PUBLIC_URL", "").strip().rstrip("/")
    if env:
        return env
    host = request.headers.get("host", "").strip()
    if not host:
        return ""
    scheme = (request.headers.get("x-forwarded-proto", "") or "").split(",")[0].strip().lower() or "https"
    # suppress internal-looking hosts — the try-it flow must not print a
    # raw IP / localhost / tunnel name
    h = host.split(":")[0].lower()
    if h in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or h.startswith("192.168.") or h.startswith("10.") or h.startswith("172.16.") or h.startswith("172.17.") or ".local" in h or ".internal" in h or ".duckdns" in h or h.endswith(".ngrok.io") or h.endswith(".localtunnel.me"):
        return ""
    return f"{scheme}://{host}"


def build_app() -> FastAPI:
    """Build the FastAPI app with the x402 payment middleware + journal."""
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient
    from x402.http.types import PaymentOption, RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    # ---- facilitator: CDP-verified mainnet rail -------------------------
    try:
        from cdp.x402 import create_facilitator_config
        facilitator = HTTPFacilitatorClient(create_facilitator_config())
        log.info("facilitator: CDP x402 (Base mainnet)")
    except Exception:  # noqa: BLE001 - env absent in tests/CI
        facilitator = HTTPFacilitatorClient(FacilitatorConfig())
        log.warning("facilitator: CDP creds missing — bare config (tests only)")

    server = x402ResourceServer(facilitator)
    server.register(NETWORK, ExactEvmServerScheme())

    # ---- the house: memory + trust + dedup + scars + jobs + money --------
    # Isolated house DB (gitignored data/) — the live ledger tells the house's
    # own story, not the shared ~/.sibyl default.
    db_path = os.getenv("HOUSE_MEMORY_DB",
                        str(Path(__file__).resolve().parents[2] / "data" / "memory.db"))
    memory = HouseMemory(db_path)

    # The public memory gate: anyone can really disable (soft-off, reversible,
    # self-heals after 15 min) or purge (true, permanent deletion) the memory
    # and watch the product collapse. Purge is irreversible and guarded — 2h
    # per-IP cooldown + 3/day per-IP cap. Disable is non-destructive with a
    # light 3-per-2h rolling limit. See core/wipe.py.
    wipe = WipeController()

    # ---- money-out: SAFE-BY-DEFAULT (DryRun) unless explicitly enabled ----
    # The house RECEIVES via CDP x402 (always, when CDP creds are present).
    # It SENDS (loyalty rebates / refunds) via its own ACP wallet ONLY when
    # HOUSE_LIVE_MONEY_OUT=1 AND a real HOUSE_WALLET is configured. Otherwise
    # rebates are dry-run (event + pseudo hash, no acp, no money) — so a
    # misconfigured env or a test can never move real money or shell out.
    live_money_out = (os.getenv("HOUSE_LIVE_MONEY_OUT", "").strip() == "1"
                      and _house_wallet() != HOUSE_WALLET_PLACEHOLDER)
    wallet_obj = None
    if live_money_out:
        wallet_obj = HouseWallet(
            memory, _house_wallet(),
            acp_bin=os.getenv("ACP_BIN"),
            usdc=os.getenv("HOUSE_USDC_BASE", USDC_BASE))
        log.info("money-out: LIVE (acp) — HOUSE_LIVE_MONEY_OUT=1 wallet=%s",
                 _house_wallet()[-6:])
    else:
        log.info("money-out: DRY-RUN (no acp, no money) — set "
                 "HOUSE_LIVE_MONEY_OUT=1 to enable real rebates")

    # Room 4: the watchtower — deterministic screens over the house's own
    # observed caller set. It guards the serve path (refuse to launder) and
    # sells standalone screens on /watch/screen.
    watch = Watchtower(memory, house_wallet=_house_wallet())
    # Room 3: the front office — memory-driven drafting/scouting over the
    # provider WARM rows the ACP delegator already writes (Gate 4 muscle).
    front = FrontOffice(memory)
    # The ACP delegator is the ONCHAIN half of Room 3 — the Virtuals ×1.25
    # "exercised" claim. It was previously reachable only by direct code/tests
    # (audit SEV-2: ACPDelegator.delegate called nowhere in the product). It
    # shells out to the `acp` CLI, so it is wired behind a capability token
    # (money/agent out is never a public, camera-free endpoint) and degrades
    # to a 503 when the CLI is absent.
    acp = ACPDelegator(memory)
    house = House(memory, base_price=BASE_PRICE, service_name=SERVICE_NAME,
                  wallet=wallet_obj,
                  wallet_check=_acp_wallet_check if live_money_out else None,
                  watch=watch)
    log.info("memory: disabled=%s db=%s", memory.disabled(), memory.db_path)

    # ---- room 2: the underwriting desk (bonds) --------------------------
    # Shares the house's memory and money-out wallet (same safe-by-default
    # policy: DryRun unless live money-out is enabled), so a claim payout is
    # a real onchain tx from the house wallet exactly like a rebate.
    desk = UnderwritingDesk(memory, wallet=wallet_obj)
    log.info("underwriting desk: face=$%.2f base_premium=$%.4f",
             desk.face, desk.base_premium)

    # Room 5: the dossier — the cross-room read every paid entity query serves.
    # One function reads all five rooms and assembles the house's complete,
    # timestamped picture of a single counterparty (caller, provider, insured,
    # payer). Deletion → "no record": the house only sells what it remembers.
    dossier = Dossier(memory, desk=desk, front=front, watch=watch,
                      journal=house.journal)
    # The engine needs the cross-room assembler for the paid /intel/entity
    # live read (finding #9: the entity route now runs the FULL engine, not a
    # dossier-only shortcut).
    house.dossier = dossier

    routes: dict[str, RouteConfig] = {
        "/intel/quote": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),  # static receiver (not a callback)
                price=BASE_PRICE,        # base quote; memory acts on the payer
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="A short intel brief. I remember who you are.",
            service_name=SERVICE_NAME,
            tags=["intel", "memory", "x402"],
            mime_type="application/json",
        ),
        # Room 2: the underwriting desk. x402 route keys support a verb
        # prefix ("POST /path" — verified in x402 _parse_route_pattern), so
        # this gates POST specifically. The onchain quote is the BASE bond
        # premium; memory only discounts (proven → rebate back) or refuses
        # (risky → 403, settlement cancelled, uncharged).
        "POST /bond/quote": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),
                price=BOND_BASE_PREMIUM,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description=("Underwrite a provider: a bond that the house pays "
                         "out of its own wallet if the provider fails. "
                         "Priced from what the house remembers."),
            service_name=SERVICE_NAME,
            tags=["bonds", "underwriting", "x402"],
            mime_type="application/json",
        ),
        # Room 4: the watchtower — a screen is a memory read with a money
        # consequence: the house forgoes dirty revenue on its own serve path
        # and sells its verdicts here. Deterministic; no ML, no census.
        "POST /watch/screen": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),
                price=WATCH_SCREEN_PRICE,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="Counterparty screen from the house's remembered "
                        "caller set: CLEAR / HOLD / ABORT + the evidence.",
            service_name=SERVICE_NAME,
            tags=["watchtower", "integrity", "x402"],
            mime_type="application/json",
        ),
        # Room 3: the front office — the house sells what it has experienced.
        # A scout report = the provider's remembered record (jobs, quality,
        # defaults, bond claims) + the terms it would offer. A hire decision
        # = the draft ruling. Both are pure memory: SIBYL_DISABLED quotes the
        # base for everyone (blind hiring). The onchain price is the base;
        # memory adds nothing on the wire (settlement = the quote) — the
        # premium the engine computes is the *reported* quote, visible in the
        # receipt, not a surcharge.
        "POST /scout/report": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),
                price=SCOUT_REPORT_BASE,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="Scout report: the house's hiring memory for a "
                        "provider (record + terms + memory-priced quote).",
            service_name=SERVICE_NAME,
            tags=["front-office", "scouting", "x402"],
            mime_type="application/json",
        ),
        "POST /scout/hire": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),
                price=SCOUT_HIRE_PRICE,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="Hire decision: draft the provider (preferred terms, "
                        "standard + stricter evaluator, or refuse) from the "
                        "house's own hiring memory.",
            service_name=SERVICE_NAME,
            tags=["front-office", "hiring", "x402"],
            mime_type="application/json",
        ),
        "GET /intel/entity/:name": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),
                price=INTEL_ENTITY_PRICE,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="The entity dossier: the house's complete remembered "
                        "picture of one wallet across its rooms (trust, dedup, "
                        "bonds, watch, journal), every field timestamped. "
                        "Unknown entity = 404, uncharged.",
            service_name=SERVICE_NAME,
            tags=["intel", "entity", "dossier", "memory", "x402"],
            mime_type="application/json",
        ),
        # Trust: the prepay top-up — the funding half of the risky-surcharge
        # path. The onchain quote is the HANDLING FEE (the price of the credit
        # itself, in USDC, is requested in the body); the credit lands on the
        # payer's caller row, spendable against the next risky serve.
        "POST /prepay/topup": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),
                price=PREPAY_TOPUP_FEE,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="Top up your prepay credit so the house will serve a "
                        "risky wallet. Pays the handling fee onchain; the "
                        "requested USDC lands as a spendable credit.",
            service_name=SERVICE_NAME,
            tags=["trust", "prepay", "x402"],
            mime_type="application/json",
        ),
    }

    # Note: docs_url=None frees the /docs path for the formal manual
    # below — the auto Swagger UI is unused anyway (every route here sets
    # include_in_schema=False).
    app = FastAPI(title="THE HOUSE", version="0.2.0", lifespan=lifespan,
                  docs_url=None)
    # app.state aliases — the House owns the real instances; the routes and the
    # tests both reach them through here so they act on the SAME memory.
    app.state.house = house
    app.state.memory = memory
    app.state.ledger = house.ledger
    app.state.dedup = house.dedup
    app.state.scars = house.scars
    app.state.jobs = house.jobs
    app.state.auditor = house.auditor
    app.state.calibrator = house.calibrator
    app.state.wallet = house.wallet
    app.state.journal = house.journal
    app.state.desk = desk
    app.state.watch = watch
    app.state.front = front
    app.state.acp = acp
    app.state.dossier = dossier
    app.state.wipe = wipe

    # ---- free routes (never gated) ---------------------------------------
    @app.get("/manifest", include_in_schema=False)
    def route_manifest():
        """The machine-readable service descriptor (was the old ``/`` JSON
        payload, now preserved here so nothing consuming it breaks). The
        human landing page lives at ``/``."""
        return {
            "service": SERVICE_NAME,
            "one_liner": "Every x402 payment is anonymous and stateless. "
                         "The house assumes nothing.",
            "memory": "disabled" if memory.disabled() else "live",
            "paid": ["/intel/quote", "GET /intel/entity/:name", "POST /bond/quote",
                     "POST /watch/screen", "POST /scout/report", "POST /scout/hire",
                     "POST /prepay/topup"],
            "free": ["/house/ledger", "/house/jobs", "/house/audit",
                     "/house/calibrate", "/house/bonds", "/house/watch",
                     "/house/front", "/house/journal", "/gallery", "/docs"],
            "money": {
                "settlements": house.journal.count(),
                "settled_usdc": house.journal.total_usdc(),
            },
            "stats": {
                "settlements": house.journal.count(),
                "usdc_settled": house.journal.total_usdc(),
                "repeats_cached": house.dedup.stats().get("hits", 0),
                "usdc_saved": house.dedup.stats().get("usdc_saved", 0.0),
                "scars": len(memory.list_entities("scar", limit=500)),
                "active_rules": len(house.scars.active_rules()),
                "live_callers": len(memory.list_entities("caller", limit=200)),
            },
        }

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def route_landing(request: Request):
        """The house's own landing page — a live mirror of the house's state.
        Every number is rendered from the real aggregates (memory entities,
        dedup, front office, onchain history, wipe controller), so in deletion
        mode the page itself reads the collapse."""
        ds = house.dedup.stats()
        callers = []
        for row in memory.list_entities("caller", limit=200):
            addr = row.get("address", "")
            callers.append({
                "address": addr,
                "address_last6": addr[-6:] if addr else "?",
                "segment": row.get("segment"),
                "trust_score": row.get("trust_score"),
                "tx_count": row.get("tx_count"),
                "net_charged_usdc": round(float(row.get("total_paid_usdc", 0.0) or 0.0), 6),
            })
        providers = []
        for row in (front.board().get("board") or []):
            providers.append({
                "provider": row.get("provider"),
                "provider_last6": row.get("provider_last6"),
                "segment": row.get("segment"),
                "hired": row.get("hired"),
                "jobs_done": row.get("jobs_done"),
                "quality_score": row.get("quality_score"),
            })
        wipe: WipeController = request.app.state.wipe  # type: ignore[assignment]
        state = build_landing_state(
            memory_mode=memory.mode,
            callers=callers,
            providers=providers,
            dedup=ds,
            scars_total=len(memory.list_entities("scar", limit=500)),
            scars_rules=len(house.scars.active_rules()),
            commit=_git_commit(),
            base_price=house.base_price,
            repo_url=_repo_url(),
            public_url=_public_url(request),
            ts=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            wipe_status=wipe.status(_client_ip(request)),
        )
        return HTMLResponse(render_landing(state))

    @app.get("/gallery", include_in_schema=False, response_class=HTMLResponse)
    def route_gallery():
        """Room 5: the gallery — the watchable world. Every room, live, in the
        house's own design language. Static HTML; the client keeps it fresh
        from the free /house/* ledgers. Deletion → the collapse, visible."""
        return HTMLResponse(render_gallery(
            memory_live=not memory.disabled(),
            commit=_git_commit(),
            base_price=house.base_price,
            ts=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            public_url=os.getenv("HOUSE_PUBLIC_URL", "").strip().rstrip("/"),
        ))

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    def route_docs():
        """The formal manual: concepts, functions, trust, transactions,
        memory on vs off, history, gate, API reference, reproduction.
        Static page; the commit token is the only dynamic bit."""
        return HTMLResponse(render_docs(commit=_git_commit()))

    @app.get("/house/journal", include_in_schema=False)
    def route_journal():
        """The season log: the house's cold journal, newest first, with the
        kind of every entry. The recall surface — the memory, readable by
        anyone. Deletion → empty (no events remembered)."""
        events = memory.read_events(limit=200)
        # FIX-4c / SEV-2: the cold journal stores FULL payer addresses (for
        # Basescan reconciliation). The PUBLIC view masks them — the operator
        # can still reconcile from the DB; anyone on the wire sees 0x<last4>.
        # Tx hashes are preserved verbatim (public onchain artifacts) so a
        # settlement line keeps its hash while the payer is masked.
        txs = frozenset(e.get("tx") for e in house.journal.entries(limit=200)
                        if e.get("tx"))
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "events": [{
                "id": e.get("id"),
                "ts": e.get("ts"),
                "kind": (e.get("extra") or {}).get("kind"),
                "text": redact_text(" ".join(e.get("acted") or []), preserve=txs),
            } for e in events],
        }

    @app.get("/house/ledger", include_in_schema=False)
    def route_ledger():
        """Free public money shot. Addresses are anonymized to last-6 (FIX-4c)
        — this endpoint is public; full addresses never leave the house."""
        callers = memory.list_entities("caller", limit=200)
        table = []
        for row in callers:
            addr = row.get("address", "?")
            table.append({
                "addr_last6": addr[-6:],
                "segment": row.get("segment"),
                "trust_score": row.get("trust_score"),
                "tx_count": row.get("tx_count"),
                "served": row.get("served_count", 0),
                "dedup_hits": row.get("dedup_hits", 0),
                "net_charged_usdc": round(
                    float(row.get("total_paid_usdc", 0.0) or 0.0), 6),
                "prepay_usdc": round(float(row.get("prepay_usdc", 0.0) or 0.0), 6),
                "fps": len(row.get("dedup_fp") or []),
            })
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "dedup": house.dedup.stats(),
            "money": {
                "settlements": house.journal.count(),
                "settled_usdc": house.journal.total_usdc(),
                # SEV-2: entries carry the full payer (kept for Basescan
                # reconciliation). Public view masks the payer to 0x<last4>;
                # the onchain tx hash is left verbatim (it is public by design).
                "recent": redact_value(house.journal.entries(limit=10)),
            },
            "callers": table,
            "scars": {"total": len(memory.list_entities("scar", limit=500)),
                      "rules": len(house.scars.active_rules())},
            "jobs": {"pending": house.jobs.pending_count()},
        }

    @app.get("/house/jobs", include_in_schema=False)
    def route_jobs():
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "pending": house.jobs.pending_count(),
            # SEV-2: job snapshots carry the full caller; public view masks it.
            "jobs": redact_value(house.jobs.snapshot(limit=50)),
        }

    @app.post("/house/compile", include_in_schema=False)
    def route_compile(request: Request):
        """On-demand F3 scar compile. Gated by a capability token when one is
        configured (FIX-4d — no unauthenticated mutation). Open only when no
        token is set (tests / local); production sets HOUSE_COMPILE_TOKEN."""
        token = os.getenv("HOUSE_COMPILE_TOKEN", "").strip()
        if token:
            given = request.headers.get("x-house-capability", "")
            if given != token:
                return JSONResponse(status_code=403,
                                    content={"error": "capability token required"})
        created = house.scars.compile()
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "rules_created": created,
            "active_rules": {rid: r for rid, r in house.scars.active_rules().items()},
            "scar_total": len(memory.list_entities("scar", limit=500)),
        }

    @app.get("/house/audit", include_in_schema=False)
    def route_audit():
        """E1 read-only view: the LAST self-audit report (baseline is set /
        refreshed at boot and on POST /house/audit/run). GETs never mutate —
        a cache-buster or crawler must not be able to move the baseline."""
        return {"house": SERVICE_NAME,
                **({"memory": "disabled"} if memory.disabled() else {}),
                "last_audit": house.auditor.last_audit()}

    @app.post("/house/audit/run", include_in_schema=False)
    def route_audit_run(request: Request):
        """E1 mutation: run the self-audit now (diff vs the stored baseline).
        Capability-gated when HOUSE_COMPILE_TOKEN is set (FIX-4d)."""
        token = os.getenv("HOUSE_COMPILE_TOKEN", "").strip()
        if token:
            given = request.headers.get("x-house-capability", "")
            if given != token:
                return JSONResponse(status_code=403,
                                    content={"error": "capability token required"})
        return {"house": SERVICE_NAME, **house.auditor.audit()}

    @app.get("/house/calibrate", include_in_schema=False)
    def route_calibrate():
        """E2 read-only view: the LAST calibration report. Calibration is
        computed on POST /house/calibrate/run (it writes REFERENCE), so this
        GET never mutates state."""
        return {"house": SERVICE_NAME,
                **({"memory": "disabled"} if memory.disabled() else {}),
                "last_calibration": house.calibrator.last_calibration()}

    @app.post("/house/calibrate/run", include_in_schema=False)
    def route_calibrate_run(request: Request):
        """E2 mutation: score the house's own past decisions now (writes the
        calibration REFERENCE). Capability-gated when a token is set."""
        token = os.getenv("HOUSE_COMPILE_TOKEN", "").strip()
        if token:
            given = request.headers.get("x-house-capability", "")
            if given != token:
                return JSONResponse(status_code=403,
                                    content={"error": "capability token required"})
        return {"house": SERVICE_NAME, **house.calibrator.calibrate()}

    @app.get("/house/bonds", include_in_schema=False)
    def route_bonds():
        """Room 2's public register: every bond, premium, claim, payout tx.
        Addresses anonymized to last-6 (the register is public)."""
        reg = desk.register()
        return {"house": SERVICE_NAME, **reg}

    @app.get("/house/watch", include_in_schema=False)
    def route_watch():
        """Room 4's public face: the verdict feed (recent screens + refusals
        with reasons) and the aggregate organic-vs-manufactured readout of the
        house's own observed traffic."""
        return {"house": SERVICE_NAME,
                "stats": watch.stats(),
                # SEV-2: the feed stores full wallets (ABORT refusals + paid
                # screens). Public view masks each to 0x<last4>.
                "feed": redact_value(watch.feed())}

    @app.post("/house/bonds/claim", include_in_schema=False)
    async def route_bond_claim(request: Request):
        """Room 2: the claim auto-pay. MONEY OUT — capability-gated when
        HOUSE_COMPILE_TOKEN is set (FIX-4d; open only in tokenless local/test).

        The trigger the spec describes: the guaranteed provider defaulted
        (scar recorded / job terminal-failed), so the house pays every OPEN
        bond on it from its own wallet. Body:
            {"provider": "0x…", "failure_class": "timeout",
             "root_cause": "…"}
        The payout tx (real when live, dry: in DryRun) is journaled next to
        each bond + the triggering scar; a payout the wallet can't send books
        the claim "failed" (retriable), never "paid" (finding #21).
        """
        token = os.getenv("HOUSE_COMPILE_TOKEN", "").strip()
        if token:
            given = request.headers.get("x-house-capability", "")
            if given != token:
                return JSONResponse(status_code=403,
                                    content={"error": "capability token required"})
        body = await request.json()
        provider = require_wallet(body.get("provider"), "provider")
        if provider is None:
            return JSONResponse(status_code=400,
                                 content={"error": "provider must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        failure_class = str(body.get("failure_class") or "timeout")
        root_cause = str(body.get("root_cause") or "provider default")
        desk = app.state.desk  # type: ignore[assignment]
        results = desk.claim_for_provider(provider, failure_class, root_cause)
        return {"house": SERVICE_NAME,
                "provider_last6": provider[-6:],
                "claims": [c for _st, c in results],
                "settled": sum(1 for _st, c in results if c.get("paid")),
                "book": desk.register()["book"]}

    @app.get("/house/front", include_in_schema=False)
    def route_front(request: Request):
        """Room 3's public ledger: the draft board — every provider the
        house remembers, with segment + terms. Deletion → empty board."""
        front: FrontOffice = request.app.state.front  # type: ignore[assignment]
        return {"house": SERVICE_NAME, **front.board()}

    # ---- the public memory gate (disable / purge) --------------------
    @app.get("/house/memory/status", include_in_schema=False)
    def route_memory_status(request: Request):
        """The memory gate's current state — for the landing page countdown."""
        wipe: WipeController = request.app.state.wipe  # type: ignore[assignment]
        return {"house": SERVICE_NAME, "memory": wipe.status(_client_ip(request))}

    @app.post("/house/memory/purge", include_in_schema=False)
    def route_memory_purge(request: Request):
        """TRUE, PERMANENT deletion gate. Anyone can purge the memory and watch
        the product collapse to cold-start. Irreversible — there is no restore
        and no countdown: once purged, the store is gone. Guarded (see
        core/wipe.py): 2h per-IP cooldown + 3/day per-IP cap. This is why the
        reversible soft-off (disable) exists."""
        wipe: WipeController = request.app.state.wipe  # type: ignore[assignment]
        memory: HouseMemory = request.app.state.memory  # type: ignore[assignment]
        ok, reason, st = wipe.try_purge(memory, ip=_client_ip(request))
        return JSONResponse(
            {"house": SERVICE_NAME, "ok": ok, "reason": reason, "memory": st},
            status_code=200 if ok else 429,
        )

    @app.post("/house/memory/disable", include_in_schema=False)
    def route_memory_disable(request: Request):
        """SOFT off (the recommended memory mode): memory stops reading and
        writing, but the store persists untouched. Reversible — it self-heals
        after 15 minutes in the background, or anyone can re-enable instantly
        via /enable. No re-seed, all remembered state returns. Non-destructive,
        so it carries only a light rolling rate limit (3 per 2h per IP)."""
        wipe: WipeController = request.app.state.wipe  # type: ignore[assignment]
        memory: HouseMemory = request.app.state.memory  # type: ignore[assignment]
        ok, reason, st = wipe.try_disable(memory, ip=_client_ip(request))
        return JSONResponse(
            {"house": SERVICE_NAME, "ok": ok, "reason": reason, "memory": st},
            status_code=200 if ok else 429,
        )

    @app.post("/house/memory/enable", include_in_schema=False)
    def route_memory_enable(request: Request):
        """Instant re-enable after a soft-off. Data was never destroyed, so
        nothing is re-seeded — the house simply starts remembering again."""
        wipe: WipeController = request.app.state.wipe  # type: ignore[assignment]
        memory: HouseMemory = request.app.state.memory  # type: ignore[assignment]
        st = wipe.enable(memory)
        return {"house": SERVICE_NAME, "ok": True, "memory": st}

    # ---- ACP agent rail (free reads) ------------------------------------- #
    app.state.acp_job_ids = ["77330", "77332", "77338"]  # real jobs, Sep 7
    app.state.acp_jobs_cache = {"at": 0.0, "jobs": [], "live": False}

    @app.get("/house/acp/jobs", include_in_schema=False)
    def route_acp_jobs(request: Request):
        """Live ACP job status straight from the onchain index (real CLI
        read, cached 60s so a page load costs one read). If the CLI is
        unavailable the response says so and falls back to the recorded
        Sep 7 statuses — never a silent fake 'live'."""
        acp = request.app.state.acp  # type: ignore[attr-defined]
        cache = request.app.state.acp_jobs_cache  # type: ignore[attr-defined]
        import time as _t
        now = _t.time()
        if cache["live"] and now - cache["at"] < 60:
            jobs, live = cache["jobs"], True
        else:
            try:
                jobs = acp.jobs_summary(request.app.state.acp_job_ids)
                cache.update(at=now, jobs=jobs, live=True)
                live = True
            except FileNotFoundError:
                jobs = _ACP_FALLBACK_JOBS()
                cache.update(at=now, jobs=jobs, live=False)
                live = False
        # Offering name + escrow tx are fixed job identity (not in the
        # history events) — annotate from the recorded map so cards always
        # carry the Basescan-verifiable proof.
        for j in jobs:
            spec = _ACP_FALLBACK.get(str(j.get("job_id")))
            if spec:
                j.setdefault("offering", spec["offering"])
                j.setdefault("escrow_tx", spec["escrow_tx"])
                j.setdefault("provider_name", spec["provider_name"])
        return {"house": SERVICE_NAME, "live": live,
                "chain_id": acp.chain_id, "jobs": jobs}

    @app.get("/house/acp/terms", include_in_schema=False)
    def route_acp_terms(request: Request):
        """Free live terms read: what the house WOULD offer a provider right
        now, from what it remembers. The same pure function the paid
        /scout/hire ruling and the real delegation use — exposed free so the
        agent rail can be exercised without paying. With memory disabled the
        recall returns nothing: every provider is a stranger at standard
        terms (the deletion-safe path, shown for real)."""
        provider = str(request.query_params.get("provider", "")).strip()
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", provider):
            return JSONResponse(status_code=400, content={
                "house": SERVICE_NAME,
                "error": "provider must be a 0x-prefixed 40-char address"})
        front: FrontOffice = request.app.state.front  # type: ignore[attr-defined]
        memory: HouseMemory = request.app.state.memory  # type: ignore[attr-defined]
        decision = front.decision(provider)
        # The no-memory comparison: the SAME terms function with no recalled
        # row (exactly what a disabled/purged recall returns). It is a
        # simulation of the deletion-safe path, not a live second read —
        # flagged as such so the page never blurs real vs computed.
        from core.acp import terms_from_row
        nm = terms_from_row(None)
        no_memory = {
            "segment": nm.segment,
            "hired": not nm.skip,
            "refused": nm.skip,
            "reason": nm.reason,
            "strict_review": nm.strict_review,
        }
        return {
            "house": SERVICE_NAME,
            "memory": memory.mode,  # live | disabled | purged
            "memory_live": not memory.disabled(),
            "no_memory_terms": no_memory,
            "no_memory_is_simulation": True,
            **decision,
        }

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.post("/bond/quote")
    async def route_bond_quote(request: Request):
        """Room 2: underwrite a provider. Paid (base premium quoted onchain).

        Memory acts before settlement:
          * proven provider  → bond issued at the discounted premium; the
            discount is rebated back as a real tx (net = premium×mult)
          * unknown/standard → bond issued at the flat base premium
          * risky provider   → 403 BEFORE settlement (the house refuses;
            the buyer is genuinely uncharged)
          * over the remembered exposure cap → 403, uncharged
        """
        body = await request.json()
        provider = require_wallet(body.get("provider"), "provider")
        if provider is None:
            return JSONResponse(status_code=400,
                                 content={"error": "provider must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            # A verified payment with no recoverable payer is a server
            # failure (5xx cancels settlement — the buyer is not charged).
            return JSONResponse(status_code=502,
                                 content={"error": "payer unknown after settlement"})
        quote = desk.premium_quote(provider)
        if quote["segment"] == "risky":
            return JSONResponse(status_code=403, content={
                "error": "the house will not bond this provider",
                "provider_last6": provider[-6:],
                "segment": "risky",
                "evidence": quote["evidence"],
                "uncharged": True,
            })
        status, issued = desk.issue(provider, payer, premium=quote["premium"])
        if status >= 400:
            return JSONResponse(status_code=status,
                                 content={**issued, "uncharged": True})
        # Memory acts on a proven buyer: settle the base premium onchain,
        # rebate back (base − premium) as a real tx. Net = premium.
        rebate_tx = None
        if quote["mult"] < 1.0:
            rebate_tx = desk.wallet.send_rebate(
                payer, desk.base_premium, quote["mult"])
        return {**issued, "rebate_tx": rebate_tx,
                "net_premium_usdc": round(
                    desk.base_premium * quote["mult"], 6)}

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.post("/watch/screen")
    async def route_watch_screen(request: Request):
        """Room 4: sell a counterparty screen. Paid (screen price quoted
        onchain). The screen itself is a deterministic memory read — CLEAR /
        HOLD / ABORT + the evidence (self-pay, funding-cluster sybil, factory
        fingerprint, cold-start volume, metronome timing)."""
        body = await request.json()
        wallet = require_wallet(body.get("wallet"), "wallet")
        if wallet is None:
            return JSONResponse(status_code=400,
                                 content={"error": "wallet must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            return JSONResponse(status_code=502,
                                 content={"error": "payer unknown after settlement"})
        # The funding-graph writer (audit SEV-2: nothing ever wrote funded_by).
        # A screen may declare the root that funds the wallet; the house
        # remembers it, so the sybil/self-funding rules fire across sessions.
        raw_funded = body.get("funded_by")
        if raw_funded:
            funded_by = require_wallet(raw_funded, "funded_by")
            if funded_by is None:
                return JSONResponse(status_code=400,
                                     content={"error": "funded_by must be a "
                                                       "0x-prefixed 40-char "
                                                       "address"})
        else:
            funded_by = ""
        watch.note_funding(wallet, funded_by)
        return {"house": SERVICE_NAME, **watch.screen(wallet)}

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.post("/prepay/topup")
    async def route_prepay_topup(request: Request):
        """Trust: fund the prepay credit a risky wallet needs to be served.

        The x402 middleware settles the HANDLING FEE onchain (PREPAY_TOPUP_FEE).
        The buyer also states how much credit to add (``amount``) in the body;
        the house caps it at PREPAY_TOPUP_MAX and credits it to the PAYER's
        caller row — spendable against the next risky serve's surcharge. A 400
        (bad amount) cancels settlement → the buyer is uncharged.
        """
        house_: House = request.app.state.house  # type: ignore[attr-defined]
        body = await request.json()
        try:
            amount = float(body.get("amount"))
        except (TypeError, ValueError):
            return JSONResponse(status_code=400,
                                 content={"error": "amount must be a number (USDC)"})
        if amount <= 0:
            return JSONResponse(status_code=400,
                                 content={"error": "amount must be positive"})
        if amount > PREPAY_TOPUP_MAX:
            return JSONResponse(status_code=400,
                                 content={"error": f"amount exceeds the {PREPAY_TOPUP_MAX:g} USDC top-up cap"})
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            return JSONResponse(status_code=502,
                                 content={"error": "payer unknown after settlement"})
        # Credit lands on the payer's OWN caller row (the wallet that will be
        # served), not on an arbitrary wallet — a buyer funds itself.
        row = house_.ledger.credit_prepay(payer, amount)
        segment, mult = house_.ledger.segment(row)
        return {"house": SERVICE_NAME,
                "credited_usdc": amount,
                "fee_usdc": PREPAY_TOPUP_FEE,
                "prepay_on_file": round(float(row.get("prepay_usdc", 0.0) or 0.0), 6),
                "segment": segment,
                "price_mult": mult}

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.post("/scout/report")
    async def route_scout_report(request: Request):
        """Room 3: sell a scout report. Paid (report base quoted onchain).
        The report is what the house has EXPERIENCED with the provider —
        jobs done, quality, on-time, defaults, bond claims — plus the terms
        it would offer. The receipt carries the memory-priced quote (a costly
        memory quotes a premium); the wire settles the base."""
        body = await request.json()
        provider = require_wallet(body.get("provider"), "provider")
        if provider is None:
            return JSONResponse(status_code=400,
                                 content={"error": "provider must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            return JSONResponse(status_code=502,
                                 content={"error": "payer unknown after settlement"})
        front: FrontOffice = request.app.state.front  # type: ignore[assignment]
        return {"house": SERVICE_NAME, "payer_last6": payer[-6:],
                **front.report(provider)}

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.post("/scout/hire")
    async def route_scout_hire(request: Request):
        """Room 3: sell a hire decision. Paid (hire decision quoted onchain).
        The draft ruling from the house's hiring memory: proven → preferred
        terms; unknown → standard + stricter evaluator; risky → refused."""
        body = await request.json()
        provider = require_wallet(body.get("provider"), "provider")
        if provider is None:
            return JSONResponse(status_code=400,
                                 content={"error": "provider must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            return JSONResponse(status_code=502,
                                 content={"error": "payer unknown after settlement"})
        front: FrontOffice = request.app.state.front  # type: ignore[assignment]
        decision = front.decision(provider)
        # A rendered hire decision is HIRING MEMORY: the ruling (draft or
        # refusal, and the record it drew from) is journaled on the COLD
        # trail. (The audit found the route was a pure read — the house
        # decided and remembered nothing.)
        front.note_hire(provider, outcome="refused" if decision["refused"]
                        else "draft")
        if decision["refused"]:
            # The house refuses to draft this provider — refuse BEFORE we
            # would have done work (403 cancels settlement: uncharged).
            return JSONResponse(status_code=403, content={
                "error": "the house will not draft this provider",
                "uncharged": True,
                **decision,
            })
        return {"house": SERVICE_NAME, "payer_last6": payer[-6:], **decision}

    # ---- operator trigger (capability-gated) ------------------------------
    @app.post("/scout/delegate", include_in_schema=False)
    async def route_scout_delegate(request: Request):
        """Room 3's onchain half: actually HIRE the provider via ACP.

        The audit (SEV-2) found ``ACPDelegator.delegate`` — the Virtuals ×1.25
        "exercised" claim — was called NOWHERE in the product; live ACP jobs
        existed only as manual Gate-4 runs. This route is the wiring. It is
        capability-gated (``HOUSE_COMPILE_TOKEN``; open only in tokenless
        local/test) because it shells out to the ``acp`` CLI and can move
        escrow — an agent/money-out act, never a public, camera-free endpoint.

        Terms are set by the house's REMEMBERED provider record
        (``front.decision`` / ``acp.terms_from_row``): a risky provider is
        skipped BEFORE any onchain call (no job, no escrow); proven/unknown
        proceed with the memory-priced evaluator. Deletion (SIBYL_DISABLED) →
        every provider is "unknown" at standard terms → the house hires blind,
        exactly the room's before/after.
        """
        token = os.getenv("HOUSE_COMPILE_TOKEN", "").strip()
        if token:
            given = request.headers.get("x-house-capability", "")
            if given != token:
                return JSONResponse(status_code=403,
                                     content={"error": "capability token required"})
        body = await request.json()
        provider = require_wallet(body.get("provider"), "provider")
        if provider is None:
            return JSONResponse(status_code=400,
                                 content={"error": "provider must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        offering = str(body.get("offering") or "").strip()
        if not offering:
            return JSONResponse(status_code=400,
                                 content={"error": "offering is required"})
        requirements = body.get("requirements") or {"offering": offering}
        if not isinstance(requirements, dict):
            return JSONResponse(status_code=400,
                                 content={"error": "requirements must be an object"})

        front: FrontOffice = request.app.state.front  # type: ignore[assignment]
        acp = request.app.state.acp  # type: ignore[assignment]
        decision = front.decision(provider)
        if decision["refused"]:
            # A risky provider is skipped before any onchain call — the house
            # does not hire it. The ruling is journaled (it is hiring memory).
            front.note_hire(provider, outcome="refused")
            return JSONResponse(status_code=403, content={
                "house": SERVICE_NAME,
                "skipped": True,
                "reason": decision["reason"],
                "uncharged": True,
                **decision,
            })
        try:
            receipt = acp.delegate(provider, offering, requirements)
        except FileNotFoundError:
            return JSONResponse(status_code=503, content={
                "house": SERVICE_NAME,
                "error": "acp CLI not available — delegation degraded (no "
                          "onchain job was created)"})
        except Exception as exc:  # noqa: BLE001 - surface the honest failure
            return JSONResponse(status_code=502, content={
                "house": SERVICE_NAME,
                "error": f"delegation failed: {exc}"})
        # The delegation is hiring memory: the ruling + the onchain receipt
        # (job id, funded amount, completion) are journaled on the COLD trail.
        front.note_hire(provider, outcome="drafted")
        acp.m.write_event(
            f"acp delegate → {provider} offering={offering} "
            f"job={receipt.get('job_id')} funded=${receipt.get('funded_usdc', 0):g} "
            f"completion={receipt.get('completion')}",
            kind="paid")
        return {"house": SERVICE_NAME,
                "provider_last6": provider[-6:],
                "decision": decision,
                **receipt}

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.get("/intel/quote")
    def route_intel_quote(request: Request):
        house_: House = request.app.state.house  # type: ignore[attr-defined]
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        # FIX-4b: a verified payment with no recoverable payer is a server
        # failure, not a 200. (The x402 middleware settles base only after we
        # return <400, so 5xx cancels the settlement — the buyer is not
        # charged for an undeliverable answer.)
        if payer is None:
            return JSONResponse(
                status_code=502, content={"error": "payer unknown after settlement"})
        qp = getattr(request, "query_params", None)
        params = dict(qp) if qp else {}
        status, body = house_.serve_intel(payer, params)
        if status >= 400:
            return JSONResponse(status_code=status, content=body)
        return body

    # ---- paid handler (only reachable after x402 verification) ------------
    @app.get("/intel/entity/{name}")
    def route_intel_entity(name: str, request: Request):
        """Room 5: the entity dossier — the house's complete remembered
        picture of one wallet, across every room (trust, dedup, bonds, watch,
        journal), every field timestamped. Paid (dossier price quoted onchain).

        The house only sells what it has: an entity it has never observed as a
        caller, provider, insured, or payer is a 404, uncharged (>=400 cancels
        the settlement). It never fabricates a profile it never remembered.
        """
        entity = require_wallet(name, "entity")
        if entity is None:
            return JSONResponse(status_code=400,
                                 content={"error": "entity must be a "
                                                   "0x-prefixed 40-char "
                                                   "address"})
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            # Verified payment, no recoverable payer is a server
            # failure (5xx cancels settlement — the buyer is not charged
            # for a dossier it cannot attribute to a payer).
            return JSONResponse(
                status_code=502, content={"error": "payer unknown after settlement"})
        # Finding #9 parity: the entity dossier runs the FULL engine (trust
        # pricing, refusals, watchtower, scar policy, job state, envelope) —
        # not a dossier-only shortcut. A 404 / refusal comes back uncharged.
        house_: House = request.app.state.house  # type: ignore[attr-defined]
        status, body = house_.serve_entity(payer, entity)
        if status >= 400:
            return JSONResponse(status_code=status, content=body)
        return {"house": SERVICE_NAME, "payer_last6": payer[-6:], **body}

    app.add_middleware(
        make_journal_middleware(house.journal),
        routes=routes, server=server)

    # ---- serve-time memory confirmation --------------------------------- #
    # Every response — paid or free — is stamped with the memory state the
    # house was actually in while it produced that response. This is the
    # public confirmation that a discount / dedup / refusal was decided with
    # memory ON, and that a flat base-price serve happened with it OFF. It is
    # a header (visible to anyone, checkable in devtools or curl), not a
    # toast the client could lie about.
    @app.middleware("http")
    async def _stamp_memory_state(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-House-Memory"] = memory.mode
        # the mode is also the reason: a discount/dedup means the house READ
        # memory; an off-mode means every wallet was treated as a stranger.
        response.headers["X-House-Memory-Note"] = (
            "decided with memory on; recall ran before pricing"
            if memory.mode == "live"
            else "decided with memory off; the house was blind to this wallet"
        )
        return response

    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("HOUSE_PORT", "8090")))

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
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from core.identity import require_wallet
from core.redact import redact_text, redact_value

from app.x402.landing import render_landing
from app.x402.gallery import render_gallery
from core.bonds import UnderwritingDesk
from core.config import BOND_BASE_PREMIUM, INTEL_ENTITY_PRICE, WATCH_SCREEN_PRICE
from core.dossier import Dossier
from core.house import House
from core.memory import HouseMemory
from core.scout import SCOUT_HIRE_PRICE, SCOUT_REPORT_BASE, FrontOffice
from core.settle_journal import decode_settlement_header
from core.wallet import HouseWallet, USDC_BASE
from core.watch import Watchtower

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger("the-house.seller")

NETWORK = os.getenv("HOUSE_NETWORK", "eip155:8453")
BASE_PRICE = float(os.getenv("HOUSE_BASE_PRICE", "0.01"))  # USDC list price
SERVICE_NAME = os.getenv("HOUSE_SERVICE_NAME", "the-house")

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
    memory, the deletion degradation)."""
    house: House = app.state.house  # type: ignore[attr-defined]
    info = house.startup()
    log.info("startup: wallet_ok=%s resumed=%d driven=%s",
             info["wallet_ok"], info["resumed"], info["driven"])
    yield


def _git_commit() -> str:
    """Short git SHA of the running checkout ("" outside a repo / on failure).
    Surfaced on the landing page as the build identity."""
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


def _repo_url() -> str:
    """Public repo URL for the landing page. Reads the origin remote when
    present; returns "" (page shows an honest 'private build page' line) when
    there is no remote yet (Gate 5 push not done)."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=5,
        )
        url = out.stdout.strip()
        if not url:
            return ""
        # normalize git@github.com:user/repo.git -> https://github.com/user/repo
        if url.startswith("git@") and ":" in url:
            hostpath = url.split("@", 1)[1]
            url = "https://" + hostpath.replace(":", "/", 1)
        return url.rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


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
    }

    app = FastAPI(title="THE HOUSE", version="0.2.0", lifespan=lifespan)
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
    app.state.dossier = dossier

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
                     "POST /watch/screen", "POST /scout/report", "POST /scout/hire"],
            "free": ["/house/ledger", "/house/jobs", "/house/audit",
                     "/house/calibrate", "/house/bonds", "/house/watch",
                     "/house/front", "/house/journal", "/gallery"],
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
    def route_landing():
        """The house's own landing page — a live mirror of the house's state.
        Every number is rendered server-side from the real aggregates, so in
        deletion mode (memory disabled) the page itself reads the collapse."""
        ds = house.dedup.stats()
        return HTMLResponse(render_landing(
            memory_live=not memory.disabled(),
            settlements=house.journal.count(),
            usdc_settled=house.journal.total_usdc(),
            repeats_cached=int(ds.get("hits", 0)),
            usdc_saved=float(ds.get("usdc_saved", 0.0)),
            scars=len(memory.list_entities("scar", limit=500)),
            active_rules=len(house.scars.active_rules()),
            live_callers=len(memory.list_entities("caller", limit=200)),
            commit=_git_commit(),
            base_price=house.base_price,
            repo_url=_repo_url(),
            ts=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        ))

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
        ))

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

    @app.get("/house/front", include_in_schema=False)
    def route_front(request: Request):
        """Room 3's public ledger: the draft board — every provider the
        house remembers, with segment + terms. Deletion → empty board."""
        front: FrontOffice = request.app.state.front  # type: ignore[assignment]
        return {"house": SERVICE_NAME, **front.board()}

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
        return {"house": SERVICE_NAME, **watch.screen(wallet)}

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
        if decision["refused"]:
            # The house refuses to draft this provider — refuse BEFORE we
            # would have done work (403 cancels settlement: uncharged).
            return JSONResponse(status_code=403, content={
                "error": "the house will not draft this provider",
                "uncharged": True,
                **decision,
            })
        return {"house": SERVICE_NAME, "payer_last6": payer[-6:], **decision}

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
        dossier: Dossier = request.app.state.dossier  # type: ignore[attr-defined]
        result = dossier.build(entity)
        if not result["found"]:
            # The house has no record of this entity. 404 cancels settlement
            # (uncharged) — honesty: we sell the memory we have, nothing more.
            return JSONResponse(status_code=404, content={
                "entity": entity,
                "found": False,
                "note": result["note"],
                "uncharged": True,
            })
        return {"house": SERVICE_NAME, "payer_last6": payer[-6:], **result}

    app.add_middleware(
        make_journal_middleware(house.journal),
        routes=routes, server=server)
    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("HOUSE_PORT", "8090")))

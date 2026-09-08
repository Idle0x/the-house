"""THE HOUSE — x402 seller on Base mainnet.

Flow per 02-ARCHITECTURE §4 (the 10-step request path):

  payer is unknown until payment settles (x402 is anonymous by design),
  so the 402 quote is BASE price. The memory act happens on the VERIFIED
  payer — the handler reads the trust row and memory decides what happens:
    - repeat buyer of the same intel (dedup_fp hit) → served from cache, $0
    - banned wallet → refused (no deliverable)
    - regular/vip → loyalty terms + row updated (tx_count++, trust Δ+3)
  Every handler is reached only AFTER x402 settlement, so
  `request.state.payment_payload` carries the payer.

Rail (CDP-verified, reused per plan anti-goals): Base mainnet Exact scheme
via the Coinbase X402 facilitator. Needs house's OWN credentials in .env:
    CDP_API_KEY_ID, CDP_API_KEY_SECRET, HOUSE_WALLET
Deletion harness: SIBYL_DISABLED=1 → recall() is None → every caller is
treated as new (list price, no dedup, no refusal). Business model collapses.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.audit import SelfAuditor
from core.calibrate import Calibrator
from core.dedup import DedupEngine, fingerprint
from core.jobs import JobStateMachine
from core.memory import HouseMemory
from core.scars import ScarCompiler
from core.trust import TrustLedger

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger("the-house.seller")

NETWORK = os.getenv("HOUSE_NETWORK", "eip155:8453")
BASE_PRICE = float(os.getenv("HOUSE_BASE_PRICE", "0.01"))  # USDC list price
SERVICE_NAME = os.getenv("HOUSE_SERVICE_NAME", "the-house")


def _house_wallet() -> str:
    w = os.getenv("HOUSE_WALLET", "").strip()
    if not w:
        raise RuntimeError("HOUSE_WALLET missing from .env (receiving address)")
    return w


def _price_str(usdc: float) -> str:
    return f"${usdc:.4f}"


def extract_payer(payment_payload: Any) -> Optional[str]:
    """Payer address from a settled x402 payload (02-ARCHITECTURE step 1).

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


def _failure_class(exc: BaseException) -> str:
    """Stable failure_class string for scar recording (03-FEATURES F3)."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "5xx upstream timeout"
    if "connection" in msg or "refused" in msg:
        return "upstream connection refused"
    return f"exception:{name}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """F4: on startup, resume every non-terminal job (kill -9 → wake up, finish).

    Under SIBYL_DISABLED the null memory holds no jobs — resume is a no-op
    (the deletion degradation: idempotency died with the memory).
    """
    jobs_: JobStateMachine = app.state.jobs  # type: ignore[attr-defined]
    resumed = jobs_.resume_all()
    if resumed:
        log.info("resume_all: %d in-flight job(s) picked up", len(resumed))
    else:
        log.info("resume_all: no in-flight jobs to resume")
    yield


def build_app() -> FastAPI:
    """Build the FastAPI app with x402 payment middleware."""
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
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

    # ---- memory + trust + dedup + scars + jobs (the whole point) ---------
    # Isolated house DB (gitignored data/) — not the shared ~/.sibyl default,
    # so the live ledger tells the house's own story.
    db_path = os.getenv("HOUSE_MEMORY_DB",
                        str(Path(__file__).resolve().parents[2] / "data" / "memory.db"))
    memory = HouseMemory(db_path)
    ledger = TrustLedger(memory)
    dedup = DedupEngine(memory)
    scars = ScarCompiler(memory)
    jobs = JobStateMachine(memory)
    auditor = SelfAuditor(memory)
    calibrator = Calibrator(memory, base_price=BASE_PRICE)
    log.info("memory: disabled=%s db=%s", memory.disabled(), memory.db_path)

    routes: dict[str, RouteConfig] = {
        "/intel/quote": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet(),  # static receiver (not a callback)
                price=BASE_PRICE,        # base quote; memory acts on payer
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="A short intel brief. I remember who you are.",
            service_name=SERVICE_NAME,
            tags=["intel", "memory", "x402"],
            mime_type="application/json",
        ),
    }

    app = FastAPI(title="THE HOUSE", version="0.1.0", lifespan=lifespan)
    app.state.memory = memory
    app.state.ledger = ledger
    app.state.dedup = dedup
    app.state.scars = scars
    app.state.jobs = jobs
    app.state.auditor = auditor
    app.state.calibrator = calibrator

    # ---- free routes (never gated) ---------------------------------------
    @app.get("/", include_in_schema=False)
    def route_landing():
        return {
            "service": SERVICE_NAME,
            "one_liner": "Every x402 payment is anonymous and stateless. "
                         "The house assumes nothing.",
            "memory": "disabled" if memory.disabled() else "live",
            "paid": ["/intel/quote"],
            "free": ["/house/ledger", "/house/jobs", "/house/audit",
                     "/house/calibrate"],
        }

    @app.get("/house/ledger", include_in_schema=False)
    def route_ledger():
        """Free public money shot: dedup stats + anonymized caller table."""
        callers = memory.list_entities("caller", limit=200)
        table = []
        for row in callers:
            table.append({
                "addr": row.get("address", "?"),
                "segment": row.get("segment"),
                "trust_score": row.get("trust_score"),
                "tx_count": row.get("tx_count"),
                "served": row.get("served_count", 0),
                "dedup_hits": row.get("dedup_hits", 0),
                "fps": len(row.get("dedup_fp") or []),
            })
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "dedup": dedup.stats(),
            "callers": table,
            "scars": {"total": len(memory.list_entities("scar", limit=500)),
                      "rules": len(scars.active_rules())},
            "jobs": {"pending": jobs.pending_count()},
        }

    @app.get("/house/jobs", include_in_schema=False)
    def route_jobs():
        """Free live view of F4 job state machines (the kill-resume surface)."""
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "pending": jobs.pending_count(),
            "jobs": jobs.snapshot(limit=50),
        }

    @app.post("/house/compile", include_in_schema=False)
    def route_compile():
        """Free on-demand F3 scar compile (demo trigger; also run on timer).

        Groups same (route, failure_class) scars into REFERENCE policy rules
        and returns the rules created this pass.
        """
        created = scars.compile()
        return {
            "house": SERVICE_NAME,
            "memory": "disabled" if memory.disabled() else "live",
            "rules_created": created,
            "active_rules": {rid: r for rid, r in scars.active_rules().items()},
            "scar_total": len(memory.list_entities("scar", limit=500)),
        }

    @app.get("/house/audit", include_in_schema=False)
    def route_audit():
        """E1 — the house audits the house (free). Diff now vs its memory
        of normal; first call records the baseline."""
        report = auditor.audit()
        return {"house": SERVICE_NAME, **report}

    @app.get("/house/calibrate", include_in_schema=False)
    def route_calibrate():
        """E2 — the house grades itself (free). One-page calibration."""
        report = calibrator.calibrate()
        return {"house": SERVICE_NAME, **report}

    # ---- paid handler (only reachable after x402 settlement) -------------
    @app.get("/intel/quote")
    def route_intel_quote(request: Request):
        memory_: HouseMemory = request.app.state.memory  # type: ignore[attr-defined]
        ledger_: TrustLedger = request.app.state.ledger  # type: ignore[attr-defined]
        dedup_: DedupEngine = request.app.state.dedup  # type: ignore[attr-defined]
        scars_: ScarCompiler = request.app.state.scars  # type: ignore[attr-defined]
        jobs_: JobStateMachine = request.app.state.jobs  # type: ignore[attr-defined]
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            return {"error": "payer unknown after settlement"}

        live = not memory_.disabled()
        params: dict[str, Any] = {}
        fp = fingerprint("/intel/quote", params)

        # F4 (02-ARCHITECTURE §4 step 2): persist the job BEFORE the memory
        # act, so a kill -9 mid-request resumes instead of double-serving.
        # Under SIBYL_DISABLED there is no job state to persist — the handler
        # degrades to list-price serve (the deletion demo).
        jid: Optional[str] = None
        if live:
            try:
                jid = jobs_.start(payer, "/intel/quote", fp, params=params)["id"]
            except Exception:  # noqa: BLE001 - never let job bookkeeping kill a paid serve
                log.exception("job start failed (continuing serve)")
                jid = None

        try:
            row = ledger_.recall(payer)
            if row is None:
                row = ledger_.on_first(payer)
            if row.get("segment") == "banned":
                # Refusal MUST be a >=400 response: the x402 middleware
                # cancels settlement on error statuses, so a refused wallet
                # is never charged. Do NOT book a ledger "refund" — no money
                # moved; a fake refund event would corrupt the money story.
                reason = ledger_.refuse_reason(payer) or "banned wallet"
                if jid:
                    jobs_.refund(jid, reason="banned refusal (settlement cancelled)")
                return JSONResponse(
                    status_code=403,
                    content={"error": "the house declines this wallet",
                             "house_refused": reason,
                             "segment": "banned",
                             "house": {"segment": "banned"}},
                )

            answer = {
                "intel": "The house remembers its counterparties. "
                         "That memory is the price, the refusal, the repeat.",
            }

            if dedup_.is_repeat(row, fp):
                cached = dedup_.load(fp) or answer
                dedup_.note_repeat(price_usdc=BASE_PRICE)
                updated = ledger_.update(payer, "served", paid_usdc=0.0)  # $0 repeat
                updated = ledger_.note_dedup(payer)  # per-caller counter (H2)
                if jid:
                    # Same deterministic job id as the first serve — settle
                    # idempotently so no non-terminal row survives (the
                    # original settlement already happened on serve #1).
                    jobs_.settle(jid, payer)
                return {"cached": True, "caller": payer, "standing": updated,
                        "house": {"segment": updated.get("segment"),
                                  "trust_score": updated.get("trust_score"),
                                  "repeat_of": fp},
                        **cached}

            if jid:
                jobs_.advance(jid, "serving", step="serve", payment_state="verified")
            ledger_.update(payer, "served", paid_usdc=BASE_PRICE)
            dedup_.mark_served(row, payer, fp, answer, price_usdc=BASE_PRICE)
            # Re-read so standing reflects EVERY write in this request
            # (trust bump + fingerprint append) — the demo's on-screen state.
            final_row = ledger_.recall(payer) or row
            if jid:
                jobs_.settle(jid, payer)  # idempotent — the double-charge killer
            return {"cached": False, "caller": payer, "standing": final_row,
                    "house": {"segment": final_row.get("segment"),
                              "trust_score": final_row.get("trust_score")},
                    **answer}
        except Exception as exc:  # noqa: BLE001 - F3: serve failure → scar
            # A paid serve that failed is the house's OWN failure — record a
            # scar (F3). We do NOT dock the caller's trust for a house-side
            # fault (that would corrupt the ledger's meaning); the job is
            # marked failed-terminal (no auto-retry — there is no executor
            # driving attempt 2; the scar/policy is the hardening path) and
            # the next session hardens via policy.
            failure_class = _failure_class(exc)
            scar_id: Optional[str] = None
            if live:
                try:
                    scar_id = scars_.record("/intel/quote", failure_class, str(exc))
                    if jid:
                        try:
                            jobs_.advance(jid, "failed",
                                          step=f"serve failed: {failure_class}")
                        except Exception:  # noqa: BLE001
                            log.exception("job terminal-fail failed")
                except Exception:  # noqa: BLE001
                    log.exception("scar recording failed")
            log.warning("serve failed payer=%s class=%s scar=%s",
                        payer, failure_class, scar_id)
            return JSONResponse(
                status_code=502,
                content={"error": "serve failed", "failure_class": failure_class,
                         "scar_id": scar_id},
            )

    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("HOUSE_PORT", "8090")))

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
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from core.memory import HouseMemory
from core.trust import TrustLedger

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

log = logging.getLogger("the-house.seller")

NETWORK = os.getenv("HOUSE_NETWORK", "eip155:8453")
BASE_PRICE = os.getenv("HOUSE_BASE_PRICE", "$0.01")
SERVICE_NAME = os.getenv("HOUSE_SERVICE_NAME", "the-house")


def _house_wallet() -> str:
    w = os.getenv("HOUSE_WALLET", "").strip()
    if not w:
        raise RuntimeError("HOUSE_WALLET missing from .env (receiving address)")
    return w


def extract_payer(payment_payload: Any) -> Optional[str]:
    """Payer address from a settled x402 payload (02-ARCHITECTURE step 1).

    Exact scheme: payload.payload.authorization.from_address (EIP-3009).
    Fallbacks: payload.payer / payload.from / payload.sender, or a bare dict.
    """
    if payment_payload is None:
        return None
    # Bare dict payloads (tests, some middleware versions).
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


def _caller_row(ledger: TrustLedger, payer: str) -> dict:
    row = ledger.recall(payer)
    if row is None:
        row = ledger.on_first(payer)
    return row


def build_app() -> FastAPI:
    """Build the FastAPI app with x402 payment middleware."""
    # Imported inside so module import doesn't require the full stack;
    # serving requires CDP creds + HOUSE_WALLET anyway.
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

    # ---- memory + trust (the whole point) -------------------------------
    memory = HouseMemory()
    ledger = TrustLedger(memory)
    log.info("memory: disabled=%s db=%s", memory.disabled(), memory.db_path)

    routes: dict[str, RouteConfig] = {
        "/intel/quote": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet,
                price=BASE_PRICE,  # base quote; memory decides on the payer
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="A short intel brief. I remember who you are.",
            service_name=SERVICE_NAME,
            tags=["intel", "memory", "x402"],
            mime_type="application/json",
        ),
        "/house/ledger": RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=_house_wallet,
                price=BASE_PRICE,
                network=NETWORK,
                max_timeout_seconds=600,
            ),
            description="Your standing with THE HOUSE — trust score, segment, repeats.",
            service_name=SERVICE_NAME,
            tags=["ledger", "memory", "x402"],
            mime_type="application/json",
        ),
    }

    app = FastAPI(title="THE HOUSE", version="0.1.0")
    app.state.memory = memory
    app.state.ledger = ledger
    app.state.intel_store = {}  # F2 dedup store: route+caller fingerprint → answer

    # ---- free routes (never gated) ---------------------------------------
    @app.get("/", include_in_schema=False)
    def route_landing():
        return {
            "service": SERVICE_NAME,
            "one_liner": "Every x402 payment is anonymous and stateless. "
                         "The house assumes nothing.",
            "memory": "disabled" if memory.disabled() else "live",
            "paid": ["/intel/quote", "/house/ledger"],
        }

    # ---- paid handlers (only reachable after x402 settlement) ------------
    @app.get("/intel/quote")
    def route_intel_quote(request: Request):
        ledger_: TrustLedger = request.app.state.ledger  # type: ignore[attr-defined]
        store = request.app.state.intel_store  # type: ignore[attr-defined]
        payer = extract_payer(getattr(request.state, "payment_payload", None))

        if payer is None:
            return {"error": "payer unknown after settlement"}  # should not happen

        # THE MEMORY ACT — every decision below is a function of the row.
        row = _caller_row(ledger_, payer)
        segment = row.get("segment", "new")

        if segment == "banned":
            # Refuse: no deliverable. (Row stays; caller was charged, house
            # refunds via E1 audit — the ledger story is refusal on memory.)
            ledger_.update(payer, "refund")
            return {"error": "the house declines this wallet", "segment": "banned"}

        # F2 dedup: same intel already bought by THIS caller → serve from
        # memory, charge $0 (repeat). Fingerprint = fixed quote route.
        fp = "intel:quote"
        if fp in (row.get("dedup_fp") or []):
            ledger_.update(payer, "served", paid_usdc=0.0)
            # NOTE: full F2 dedup_stats counter lands Day 1 (core/dedup.py).
            answer = store.get(fp, {
                "intel": "The house remembers its counterparties. "
                         "That memory is the price, the refusal, the repeat.",
            })
            return {"cached": True, "caller": payer, "standing": row, **answer}

        # First purchase of this intel: charge (already settled), journal,
        # remember the fingerprint.
        ledger_.update(payer, "served", paid_usdc=0.0)  # amount stamped at settle
        answer = {
            "intel": "The house remembers its counterparties. "
                     "That memory is the price, the refusal, the repeat.",
            "offer": "Come back — the second copy is free. Trust compounds.",
        }
        store[fp] = answer
        ledger_.m.upsert_entity("caller", payer, {
            "dedup_fp": list((row.get("dedup_fp") or []) + [fp]),
        })
        return {"cached": False, "caller": payer, "standing": row, **answer}

    @app.get("/house/ledger")
    def route_ledger(request: Request):
        ledger_: TrustLedger = request.app.state.ledger  # type: ignore[attr-defined]
        payer = extract_payer(getattr(request.state, "payment_payload", None))
        if payer is None:
            return {"error": "payer unknown after settlement"}
        row = _caller_row(ledger_, payer)
        return {"caller": payer, "row": row}

    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("HOUSE_PORT", "8090")))

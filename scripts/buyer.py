#!/usr/bin/env python3
"""THE HOUSE buyer — pays the house $0.01 and prints the settlement receipt.

Run:  HOUSE_BUYER_KEY=<hex key> .venv/bin/python scripts/buyer.py [route]

Hits the seller's paid route, auto-handles the 402 dance via the x402 HTTP
client wrapper, prints the Basescan settlement tx. This is the scripted,
reproducible Gate-1/Gate-3 payment.
"""
import asyncio
import base64
import json
import os
import sys
import time

from eth_account import Account

SELLER = os.environ.get("HOUSE_SELLER", "http://localhost:8090")


def ts():
    return time.strftime("%H:%M:%S")


async def main() -> int:
    route = sys.argv[1] if len(sys.argv) > 1 else "/intel/quote"
    url = f"{SELLER}{route}"

    key = os.environ.get("HOUSE_BUYER_KEY", "").strip()
    if not key:
        print("HOUSE_BUYER_KEY not set")
        return 2
    account = Account.from_key(key)

    from x402.client import x402Client
    from x402.http.clients.httpx import wrapHttpxWithPayment
    from x402.http.x402_http_client import x402HTTPClient
    from x402.mechanisms.evm import EthAccountSigner
    from x402.mechanisms.evm.exact.client import ExactEvmScheme
    import httpx

    signer = EthAccountSigner(account)
    client = x402Client()
    client.register("eip155:8453", ExactEvmScheme(signer))  # Base mainnet
    http_client = x402HTTPClient(client)
    paid = wrapHttpxWithPayment(http_client, timeout=90)

    print(f"=== THE HOUSE buyer ===")
    print(f"[{ts()}] buyer wallet : {account.address}")
    print(f"[{ts()}] paying $0.01 USDC → {url}")

    t0 = time.perf_counter()
    resp = await paid.get(url)
    dt = (time.perf_counter() - t0) * 1000

    print(f"[{ts()}] HTTP {resp.status_code}  ({dt:.0f} ms round trip)")

    if resp.status_code == 402:
        req = resp.headers.get("payment-required")
        if req:
            err = json.loads(base64.b64decode(req)).get("error")
            print(f"[{ts()}] facilitator: {err}")
        return 1

    body = resp.json()
    print(f"[{ts()}] PAID — response:")
    print(json.dumps(body, indent=2)[:1200])
    pr = resp.headers.get("payment-response")
    if pr:
        receipt = json.loads(base64.b64decode(pr))
        txh = receipt.get("transaction")
        print(f"\n[{ts()}] settlement tx : {txh}")
        if txh:
            print(f"[{ts()}] on-chain      : https://basescan.org/tx/{txh}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

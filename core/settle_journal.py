"""Settlement journal — the house's server-side money ledger (FIX-4).

The x402 settlement tx hash is NOT available to the route handler: the
middleware runs the handler FIRST, then settles, and the hash is returned in
the ``PAYMENT-RESPONSE`` response header (base64 SettleResponse). So the
journal lives in a thin ASGI wrapper that decodes that header and records
every settlement the house actually received.

This is what lets the house reconcile its own revenue against Basescan from
its own state — no more "dedup saved $0.04" while the chain shows the buyer
paid. Each entry carries the tx hash, payer, route, and USDC amount.

Entry shape: {tx, payer, route, amount_usdc, amount_atomic, network,
ts, kind} where kind ∈ {"settlement", "zero"}.

Deletion harness: SIBYL_DISABLED=1 → record() writes nothing (the journal is
memory-backed, so it collapses with the memory — consistent with the gate).
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Optional

from core.memory import HouseMemory
from core.wallet import USDC_DECIMALS

KEY = "settlements"


def decode_settlement_header(header_value: Optional[str]) -> Optional[dict[str, Any]]:
    """Decode a PAYMENT-RESPONSE header (base64 JSON SettleResponse) → dict.

    Returns None when absent/malformed. Normalizes the atomic USDC amount to
    dollars under "amount_usdc".
    """
    if not header_value:
        return None
    try:
        raw = base64.b64decode(header_value)
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - header is best-effort, never break the response
        return None
    if not isinstance(data, dict):
        return None
    out = {
        "success": data.get("success"),
        "tx": data.get("transaction") or "",
        "payer": data.get("payer"),
        "amount_atomic": data.get("amount"),
        "network": data.get("network"),
    }
    # atomic → USDC dollars (USDC is 6 decimals); tolerate absent/odd amounts
    amt = out.get("amount_atomic")
    if isinstance(amt, (int, float)) or (isinstance(amt, str) and amt.strip().isdigit()):
        try:
            out["amount_usdc"] = round(int(amt) / (10 ** USDC_DECIMALS), 6)
        except (TypeError, ValueError):
            out["amount_usdc"] = 0.0
    else:
        out["amount_usdc"] = 0.0
    return out


class SettlementJournal:
    """Append-only, idempotent (by tx hash) record of settled payments."""

    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    # ------------------------------------------------------------------ #
    def _ref(self) -> dict:
        return self.m.get_reference(KEY) or {}

    def record(self, entry: dict) -> bool:
        """Append a settlement entry. Returns True if recorded, False if it
        was a duplicate tx (or memory disabled). Idempotent by tx hash."""
        if self.m.disabled():
            return False
        tx = entry.get("tx") or ""
        if tx:
            for existing in self._ref().get("entries", []):
                if existing.get("tx") == tx:
                    return False  # already journaled — no double count
        ref = self._ref()
        entries = ref.get("entries", [])
        entry = {**entry, "ts": entry.get("ts") or time.time()}
        entries.append(entry)
        ref["entries"] = entries
        ref["total_usdc"] = round(
            float(ref.get("total_usdc", 0.0)) + float(entry.get("amount_usdc", 0.0)), 6)
        self.m.set_reference(KEY, ref)
        self.m.write_event(
            f"settlement {tx} {entry.get('route')} {entry.get('amount_usdc')}USDC "
            f"{entry.get('payer')} ({entry.get('kind', 'settlement')})",
            kind="paid")
        return True

    # ------------------------------------------------------------------ #
    def entries(self, limit: int = 100) -> list[dict]:
        return list(reversed(self._ref().get("entries", [])))[:limit]

    def total_usdc(self) -> float:
        return float(self._ref().get("total_usdc", 0.0))

    def count(self) -> int:
        return len(self._ref().get("entries", []))

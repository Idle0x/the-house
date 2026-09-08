"""HouseWallet — THE HOUSE's money-OUT path (rebates, refunds, claims).

The house RECEIVES via x402 (the CDP facilitator settles buyer → house). To
send money BACK — a VIP/regular loyalty rebate, a refund, an underwriting
claim payout — it uses its OWN ACP/Privy wallet:

    acp wallet send-transaction --chain-id 8453 --to <usdc> --data <calldata> --value 0

USDC is an ERC20, so a rebate is a `transfer(to, amount)` call: value 0,
calldata = 0xa9059cbb + pad32(recipient) + pad32(amount_atomic).

This is the real, journaled money-out — NOT a ledger fiction. We never
fabricate a tx hash: every send reads the acp CLI `--json` receipt, and a
send that returns no hash raises (the caller must not book a phantom rebate).

Deletion harness: with memory disabled the journal write is a no-op, but a
rebate is a real onchain transfer — the house does not stop sending money it
owes when memory is wiped (that would be a refund bug, not a feature).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Optional

from core.memory import HouseMemory

# Public constant (Base mainnet) — mirrors .env HOUSE_USDC_BASE.
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
CHAIN_ID = 8453
# ERC20 transfer(address,uint256) selector.
TRANSFER_SELECTOR = "0xa9059cbb"
USDC_DECIMALS = 6


def usdc_atomic(usdc: float) -> int:
    """USDC dollars → atomic units (6 decimals)."""
    return int(round(usdc * (10 ** USDC_DECIMALS)))


def erc20_transfer_calldata(recipient: str, amount_atomic: int) -> str:
    """ERC20 `transfer(recipient, amount)` calldata (0x-prefixed hex)."""
    to = recipient.lower().replace("0x", "")
    if len(to) != 40:
        raise ValueError(f"not a 20-byte address: {recipient!r}")
    return TRANSFER_SELECTOR + to.rjust(64, "0") + format(amount_atomic, "064x")


def discount_rebate(base_usdc: float, mult: float) -> float:
    """Loyalty rebate owed when a caller paid `base` but the memory-priced
    amount is `base * mult` (< base for vip/regular). 0 for mult >= 1."""
    if mult >= 1.0:
        return 0.0
    return round(base_usdc * (1.0 - mult), 6)


class DryRunWallet:
    """No-op money-out for tests/dev.

    Records the rebate intent as an event (so the ledger story is complete)
    and returns a CLEARLY-MARKED pseudo hash (``dry:…``) — never a real hash,
    so nothing can be mistaken for an onchain tx. No acp call, no money moved.
    This is the SAFE default: build_app() uses it unless live money-out is
    explicitly enabled (HOUSE_LIVE_MONEY_OUT=1 + a real HOUSE_WALLET).
    """

    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    def send_usdc(self, to: str, usdc_amount: float, memo: str) -> str:
        tx = f"dry:usdc{int(usdc_amount * 1e6)}to{to[-6:]}"
        self.m.write_event(
            f"[DRY-RUN] house→{to} USDC {usdc_amount:g} ({memo}) tx={tx}",
            kind="paid")
        return tx

    def send_rebate(self, payer: str, base_usdc: float, mult: float) -> Optional[str]:
        owed = discount_rebate(base_usdc, mult)
        if owed <= 0:
            return None
        return self.send_usdc(payer, owed, f"loyalty rebate seg×{mult:g}")


class HouseWallet:
    """Money-out from the house's own ACP wallet. Injectable for tests."""

    def __init__(self, m: HouseMemory, wallet_address: str,
                 acp_bin: Optional[str] = None,
                 usdc: Optional[str] = None) -> None:
        self.m = m
        self.wallet_address = wallet_address
        self.usdc = usdc or os.getenv("HOUSE_USDC_BASE", USDC_BASE)
        self.acp_bin = acp_bin or os.getenv("ACP_BIN") or shutil.which("acp") or "acp"

    # ------------------------------------------------------------------ #
    def _acp(self, *args: str, timeout: int = 90) -> dict[str, Any]:
        """Run an acp CLI command with --json; return the parsed dict or {}.

        Raises on nonzero exit (a failed send must never book a phantom tx).
        """
        cmd = [self.acp_bin, *args, "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"acp {' '.join(args)} failed to run: {exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"acp {' '.join(args)} exit {proc.returncode}: {detail}")
        out = proc.stdout.strip()
        if not out:
            return {}
        try:
            parsed = json.loads(out)
            return parsed if isinstance(parsed, dict) else {"raw": out}
        except json.JSONDecodeError:
            # Some CLI builds print the hash bare — tolerate it.
            return {"raw": out}

    @staticmethod
    def _extract_hash(res: dict[str, Any]) -> Optional[str]:
        for key in ("hash", "transaction", "transactionHash", "tx", "txHash", "id"):
            v = res.get(key)
            if isinstance(v, str) and v.startswith("0x") and len(v) == 66:
                return v
        raw = res.get("raw")
        if isinstance(raw, str):
            token = raw.split()[-1] if raw.split() else raw
            if token.startswith("0x") and len(token) == 66:
                return token
        return None

    # ------------------------------------------------------------------ #
    def send_usdc(self, to: str, usdc_amount: float, memo: str) -> str:
        """Send `usdc_amount` USDC from the house wallet to `to`.

        Returns the settlement tx hash. Journals the payment (kind="paid").
        Never fabricates: raises if acp returns no hash.

        SAFETY GUARD: if the house wallet is unset or the 0xZERO placeholder
        (misconfigured env / tests), we MUST NOT call the real acp CLI — that
        would move real money (or hammer a live wallet). We raise instead; the
        engine catches it, logs, and skips the rebate. A rebate you can't send
        is a logged gap, never a silent phantom or an accidental transfer.
        """
        if not self.wallet_address or self.wallet_address == "0x" + "0" * 40:
            raise RuntimeError(
                "HOUSE_WALLET is unset/placeholder — refusing to send a real "
                f"USDC {usdc_amount:g} rebate (no acp call). Set HOUSE_WALLET "
                "to the house's ACP wallet to enable money-out.")
        amount = usdc_atomic(usdc_amount)
        if amount <= 0:
            raise ValueError(f"rebate amount must be > 0 (got {usdc_amount})")
        data = erc20_transfer_calldata(to, amount)
        res = self._acp(
            "wallet", "send-transaction",
            "--chain-id", str(CHAIN_ID),
            "--to", self.usdc,
            "--data", data,
            "--value", "0",
        )
        txh = self._extract_hash(res)
        if not txh:
            raise RuntimeError(f"acp send returned no tx hash: {res}")
        self.m.write_event(
            f"house→{to} USDC {usdc_amount:g} ({memo}) tx={txh}", kind="paid")
        return txh

    def send_rebate(self, payer: str, base_usdc: float, mult: float) -> Optional[str]:
        """Send the loyalty rebate owed when `payer` paid `base` but their
        segment prices at `base * mult`. Returns the rebate tx hash, or None
        when nothing is owed (mult >= 1, or amount rounds to 0)."""
        owed = discount_rebate(base_usdc, mult)
        if owed <= 0:
            return None
        memo = f"loyalty rebate seg×{mult:g}"
        return self.send_usdc(payer, owed, memo)

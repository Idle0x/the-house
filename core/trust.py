"""F1 — Counterparty Trust Ledger (Lane A core).

Every pricing/refusal/prepay decision is a pure function of the caller's
WARM row (kind="caller", name=<wallet address>). No LLM in the hot path.

The deletion harness: with memory disabled, recall() returns None → every
caller is "new" at list price, no refusal, no prepay, no loyalty. That is
the hackathon gate, demonstrated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from core import config as C
from core.memory import HouseMemory


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_segment(row: dict) -> str:
    """Segment from counters/trust — pure, unit-tested (specs/trust-model.md)."""
    trust = float(row.get("trust_score", C.NEW_CALLER_TRUST))
    tx = int(row.get("tx_count", 0))
    refunds = int(row.get("refund_events", 0))
    warnings = int(row.get("warning_events", 0))
    if trust < C.TRUST_FLOOR or refunds >= C.REFUNDS_TO_BAN:
        return "banned"
    if trust < C.TRUST_RISKY or warnings >= C.WARNINGS_TO_RISKY:
        return "risky"
    if trust >= C.TRUST_VIP_MIN and tx >= C.VIP_MIN_TX:
        return "vip"
    if tx >= C.REGULAR_MIN_TX:
        return "regular"
    return "new"


@dataclass(frozen=True)
class Decision:
    """The per-request pricing/allowance verdict."""

    price_mult: float
    allow: bool
    segment: str
    reason: str = ""

    @property
    def prepay(self) -> bool:
        return self.allow and self.segment == "risky"


class TrustLedger:
    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    # ------------------------------------------------------------------ #
    def recall(self, addr: str) -> Optional[dict]:
        """Load the caller's WARM row (None = never seen / memory disabled)."""
        return self.m.get_entity("caller", addr)

    def on_first(self, addr: str) -> dict:
        """Create the row for a first-time caller."""
        row = {
            "address": addr,
            "first_seen": time.time(),
            "last_seen": time.time(),
            "tx_count": 0,
            "total_paid_usdc": 0.0,
            "served_count": 0,
            "dedup_hits": 0,
            "failure_events": 0,
            "refund_events": 0,
            "warning_events": 0,
            "trust_score": C.NEW_CALLER_TRUST,
            "segment": "new",
            "dedup_fp": [],
            "notes": "",
        }
        self.m.set_entity("caller", addr, row)
        return row

    def _ensure(self, addr: str) -> dict:
        row = self.recall(addr)
        return row if row is not None else self.on_first(addr)

    # ------------------------------------------------------------------ #
    def decision(self, addr: str) -> Decision:
        """Price/allow verdict from the recalled row.

        Memory disabled / unknown caller → "new" at list price (1.00), allowed.
        banned → refused before serving. risky → allowed but prepay-only.
        """
        row = self.recall(addr)
        if row is None:
            return Decision(price_mult=1.00, allow=True, segment="new",
                            reason="first-time or memory-disabled: list price")

        segment = compute_segment(row)
        mult = C.PRICE_MULT.get(segment)
        if mult is None:  # banned
            reason = f"banned: trust {row.get('trust_score')} or refunds {row.get('refund_events')}"
            return Decision(price_mult=0.0, allow=False, segment="banned",
                            reason=reason)
        if segment == "risky":
            return Decision(price_mult=mult, allow=True, segment="risky",
                            reason="prepay required (trust < floor or 3 warnings)")
        return Decision(price_mult=mult, allow=True, segment=segment, reason="")

    # ------------------------------------------------------------------ #
    def segment(self, row: Optional[dict]) -> tuple[str, float]:
        """(segment, price_multiplier) for a caller row. New/unknown →
        ("new", 1.0); banned → ("banned", 0.0). Pure read (no write).

        The segment is RE-DERIVED from the live counters (``compute_segment``)
        rather than trusted from the possibly-stale stored ``segment`` label —
        a row that was seeded or written before a threshold change can carry
        an outdated projection. Every pricing/refusal decision reads what the
        counters ACTUALLY imply right now, so the enforcement surface is
        consistent with ``decision()``/``update()`` (audit finding: the serve
        path priced off the stored label while docs claimed re-derivation).
        """
        if not row:
            return ("new", C.PRICE_MULT.get("new", 1.0))
        seg = compute_segment(row)
        mult = C.PRICE_MULT.get(seg, 1.0)
        return (seg, 0.0 if mult is None else mult)

    def credit_prepay(self, addr: str, usdc: float) -> dict:
        """Add to the caller's prepay credit balance.

        The audit found ``prepay_usdc`` was only ever DEBITED (the risky
        surcharge + the ``prepay_required`` scar policy), never credited — so
        a risky wallet could never actually satisfy the surcharge and the
        ``Decision.prepay`` enforcement was a permanent refusal, not a path
        the buyer could walk. This is the funding half: a buyer pays the house
        (onchain) and the credit lands here, spendable against a surcharge.
        """
        usdc = round(float(usdc), 6)
        if usdc <= 0:
            raise ValueError("prepay credit must be positive")
        row = self._ensure(addr)
        row["prepay_usdc"] = round(float(row.get("prepay_usdc", 0.0) or 0.0)
                                   + usdc, 6)
        row["last_seen"] = time.time()
        self.m.set_entity("caller", addr, row)
        self.m.write_event(f"prepay credit {addr} +{usdc:g}USDC "
                           f"(balance {row['prepay_usdc']:g})", kind="prepay")
        return row

    def update(self, addr: str, outcome: str, *, paid_usdc: float = 0.0) -> dict:
        """Apply an outcome to the caller's row. outcome in the KINDS set.

        Served/caller_fault/refund mirror D_SUCCESS / D_CALLER_FAULT /
        D_REFUND. Returns the updated row.
        """
        row = self._ensure(addr)
        delta = 0.0
        if outcome == "served":
            delta = C.D_SUCCESS
            row["tx_count"] = int(row.get("tx_count", 0)) + 1
            row["served_count"] = int(row.get("served_count", 0)) + 1
            row["total_paid_usdc"] = float(row.get("total_paid_usdc", 0.0)) + paid_usdc
        elif outcome == "caller_fault":
            delta = C.D_CALLER_FAULT
            row["warning_events"] = int(row.get("warning_events", 0)) + 1
            row["failure_events"] = int(row.get("failure_events", 0)) + 1
        elif outcome == "refund":
            delta = C.D_REFUND
            row["refund_events"] = int(row.get("refund_events", 0)) + 1
        else:
            raise ValueError(f"unknown outcome {outcome!r}")

        row["trust_score"] = clamp(
            float(row.get("trust_score", C.NEW_CALLER_TRUST)) + delta, 0.0, 100.0
        )
        row["segment"] = compute_segment(row)
        row["last_seen"] = time.time()
        self.m.set_entity("caller", addr, row)
        self.m.write_event(f"{addr} {outcome} (Δ{delta:+d})", kind=outcome)
        return row

    # ------------------------------------------------------------------ #
    def note_dedup(self, addr: str) -> dict:
        """Increment the per-caller dedup_hits counter (F2 money beat).

        Separate from the global dedup_stats state: this keeps the caller
        row's own story accurate (the schema always carried dedup_hits but
        nothing wrote it — H2 fix).
        """
        row = self._ensure(addr)
        row["dedup_hits"] = int(row.get("dedup_hits", 0)) + 1
        row["last_seen"] = time.time()
        self.m.set_entity("caller", addr, row)
        return row

    # ------------------------------------------------------------------ #
    def refuse_reason(self, addr: str) -> str:
        d = self.decision(addr)
        return d.reason if not d.allow else ""

"""Room 3 — THE FRONT OFFICE (Sibyl enters scouting / talent).

The house doesn't just sell — it drafts, develops, and prices other agents.

The front office productizes the ACP muscle the house already has
(``ACPDelegator`` recalls the provider's WARM row and sets onchain job terms
from it — Gate 4, live). M3 turns that existing decision into a *product*:

* ``decision(provider)`` — the draft decision for one provider: a pure
  function of the recalled row (``acp.terms_from_row``). A scarred provider
  is REFUSED with its record drawn on screen; a proven one is drafted at
  preferred terms. The house picks the REMEMBERED-BEST, not the cheapest.
* ``select(candidates)`` — the draft board ordering: proven first, unknown
  next, risky last (refused). Cheapest ≠ drafted.
* ``report(provider)`` — the scout report the house SELLS: what it has
  actually experienced with that provider (jobs_done, quality, on-time,
  defaults, bond claims) + the terms it would offer. "We don't rate the
  world; we rate who we've hired." Its price is a pure function of the
  house's memory of that provider — a costly memory (defaults, bond claims,
  a risky segment) quotes a premium over the base.
* ``board()`` — the front-office ledger: every provider the house has hired
  or considered, with terms + segment (the draft board, on screen).

Onchain execution (create-job / fund / complete) is the existing
``ACPDelegator.delegate`` — unchanged and live. The front office is the
decision layer that feeds it: the same ``terms_from_row`` that sets the
onchain terms sets the hire decision, so the draft and the job always agree.

Deletion proof: SIBYL_DISABLED → ``recall`` returns None → every provider is
"unknown" at standard terms → the draft board collapses to price-only
("hiring blind") — the disease the room cures, now visible as before/after.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core import config as C
from core.acp import terms_from_row
from core.memory import HouseMemory

# Report pricing — the memory-driven quote above the onchain base.
SCOUT_REPORT_BASE = 0.03      # onchain base quote for a scout report
SCOUT_HIRE_PRICE = 0.05       # onchain base quote for a hire decision
# A costly memory is worth more to know: each remembered failure (a default
# or a bond claim against the provider) adds to the report price, and a risky
# segment adds a flat premium. The house sells its experience; expensive
# experience quotes a premium over a clean record.
SCOUT_REPORT_PER_SCAR = 0.01  # + per remembered failure (default / claim)
SCOUT_REPORT_RISKY_PREMIUM = 0.02  # + flat, when the segment is risky


def _short(addr: str) -> str:
    a = (addr or "").lower()
    if len(a) > 12:
        return a[:6] + "…" + a[-4:]
    return addr or "?"


class FrontOffice:
    """The front office: memory-driven drafting, scouting, and pricing."""

    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    # ------------------------------------------------------------------ #
    # Memory I/O
    # ------------------------------------------------------------------ #
    def recall_provider(self, addr: str) -> Optional[dict]:
        return self.m.get_entity("provider", addr)

    def _claims_against(self, provider: str) -> int:
        """Bonds the house has actually paid out against this provider
        (a claim_tx on a bond where it is the provider). Derived from the
        bond book — the underwriting desk writes default_events, not a
        separate counter."""
        if self.m.disabled():
            return 0
        provider = (provider or "").strip()
        if not provider:
            return 0
        n = 0
        for bond in self.m.list_entities("bond"):
            if str(bond.get("provider", "")).strip() == provider \
                    and bond.get("claim_tx"):
                n += 1
        return n

    def _scars_against(self, row: Optional[dict], provider: str = "") -> int:
        """The provider's remembered failures: defaults + bond claims."""
        defaults = 0
        if row:
            defaults = int(row.get("default_events", 0))
        return defaults + self._claims_against(provider)

    # ------------------------------------------------------------------ #
    # The draft decision (pure function of the row)
    # ------------------------------------------------------------------ #
    def decision(self, provider: str) -> dict[str, Any]:
        """The hire decision for one provider, from what the house remembers.

        A risky record → refused (skip) with the record drawn; a proven record
        → drafted at preferred terms; unknown → standard terms + stricter
        evaluator. Deletion → every provider is unknown → hiring blind.
        """
        provider = (provider or "").strip()
        row = self.recall_provider(provider)
        terms = terms_from_row(row)
        scars = self._scars_against(row, provider)
        return {
            "provider_last6": provider[-6:] if provider else "?",
            "segment": terms.segment,
            "hired": not terms.skip,
            "refused": terms.skip,
            "reason": terms.reason,
            "strict_review": terms.strict_review,
            "scars_against": scars,
            "record": self._record_view(provider, row),
        }

    def _record_view(self, provider: str, row: Optional[dict]) -> dict[str, Any]:
        """The provider's remembered record, as the house has it (no memory →
        an empty record — the 'stranger' the house would hire blind)."""
        if row is None:
            return {"known": False, "provider_last6": provider[-6:] or "?"}
        return {
            "known": True,
            "provider_last6": provider[-6:],
            "jobs_done": int(row.get("jobs_done", 0)),
            "quality_score": round(float(row.get("quality_score", 0.0)), 3),
            "on_time": round(float(row.get("on_time", 0.0)), 3),
            "default_events": int(row.get("default_events", 0)),
            "claims_against": self._claims_against(provider),
            "bonded_work": int(row.get("bonded_work", 0)),
            "total_escrow_usdc": round(
                float(row.get("total_escrow_usdc", 0.0)), 4),
        }

    def select(self, candidates: list[str]) -> list[dict[str, Any]]:
        """The draft board ordering over candidate providers: proven first,
        unknown next, risky (refused) last. Cheapest ≠ drafted — memory ranks
        them, not price."""
        decisions = [self.decision(c) for c in candidates if c]
        order = {"proven": 0, "unknown": 1, "risky": 2}
        decisions.sort(key=lambda d: order.get(d["segment"], 1))
        return decisions

    # ------------------------------------------------------------------ #
    # The scout report (the house sells what it has experienced)
    # ------------------------------------------------------------------ #
    def report_price(self, provider: str) -> float:
        """The memory-driven quote for a report. A costly memory (defaults,
        bond claims, a risky segment) quotes a premium over the base; a clean
        or unknown record quotes the base. Pure function of the row."""
        row = self.recall_provider(provider)
        price = SCOUT_REPORT_BASE
        if row is None:
            return price
        scars = self._scars_against(row, provider)
        price += scars * SCOUT_REPORT_PER_SCAR
        if terms_from_row(row).segment == "risky":
            price += SCOUT_REPORT_RISKY_PREMIUM
        return round(price, 6)

    def report(self, provider: str) -> dict[str, Any]:
        provider = (provider or "").strip()
        row = self.recall_provider(provider)
        terms = terms_from_row(row)
        return {
            "provider_last6": provider[-6:] if provider else "?",
            "known": row is not None,
            "segment": terms.segment,
            "record": self._record_view(provider, row),
            "scars_against": self._scars_against(row, provider),
            "would_draft": not terms.skip,
            "terms": terms.to_dict(),
            "quoted_price_usdc": self.report_price(provider),
            "base_price_usdc": SCOUT_REPORT_BASE,
            "sourced_from": "the house's own hiring memory — we don't rate "
                            "the world; we rate who we've hired",
        }

    # ------------------------------------------------------------------ #
    # The draft board (the front-office ledger)
    # ------------------------------------------------------------------ #
    def board(self) -> dict[str, Any]:
        """Every provider the house remembers, with terms + segment.
        Deletion → empty board (nothing remembered → nothing drafted)."""
        providers = self.m.list_entities("provider")
        rows = []
        for p in providers:
            addr = str(p.get("address", ""))
            if not addr:
                continue
            terms = terms_from_row(p)
            rows.append({
                "provider_last6": addr[-6:],
                "segment": terms.segment,
                "hired": not terms.skip,
                "jobs_done": int(p.get("jobs_done", 0)),
                "quality_score": round(float(p.get("quality_score", 0.0)), 3),
                "default_events": int(p.get("default_events", 0)),
                "claims_against": self._claims_against(addr),
            })
        rows.sort(key=lambda r: (0 if r["segment"] == "proven"
                                 else 1 if r["segment"] == "unknown" else 2,
                                 -r["jobs_done"]))
        drafted = sum(1 for r in rows if r["hired"])
        return {"providers": len(rows), "drafted": drafted,
                "refused": len(rows) - drafted, "board": rows}

    # ------------------------------------------------------------------ #
    # Publishing a hire decision to the board (memory write)
    # ------------------------------------------------------------------ #
    def note_hire(self, provider: str, *, outcome: str) -> None:
        """Record a hire decision on the COLD journal (the audit trail)."""
        if self.m.disabled():
            return
        d = self.decision(provider)
        self.m.write_event(
            f"front office: {outcome} {_short(provider)} "
            f"({d['segment']}: {d['reason']})",
            kind="job")

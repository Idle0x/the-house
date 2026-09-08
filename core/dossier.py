"""M4 — the entity dossier (Room 5's data core).

The vision + demo always referenced ``/intel/entity/{name}``; before M4 that
was a canned string. This module is the REAL product: one function that reads
EVERY room the house has and assembles the house's complete, timestamped
picture of a single counterparty — caller, provider, insurer, payer — from
its own memory. No external census, no LLM: it is a pure join over the five
rooms (trust, dedup, bonds, watch, journal).

Every fact carries the timestamp at which the house observed it (``last_seen``
/ ``issued_at`` / ``ts``). That is the Room-B "freshness" idea made concrete:
a dossier is not a claim about the world, it is a dated snapshot of what the
house REMEMBERS, and the age of each source is part of the answer.

Deletion is the whole argument: with memory disabled ``build_dossier`` returns
a "no record" envelope — the house knows nothing, so it sells nothing. The
same input, memory live, returns the full cross-room picture. The before/after
is the deletion gate, visible in the product itself.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core.memory import HouseMemory


def _short(addr: str) -> str:
    addr = (addr or "").strip()
    return addr[-6:] if addr else "?"


def _age_s(ts: Optional[float]) -> Optional[float]:
    if not ts:
        return None
    return round(time.time() - float(ts), 1)


def _match(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


class Dossier:
    """Assemble the house's complete remembered picture of one entity.

    ``name`` is matched (case-insensitively) against the caller set and the
    provider set. An entity can be a CALLER (it paid the house), a PROVIDER
    (the house hired/bonded it), an INSURED (it bought a bond), or a PAYER
    (journal settlements). All four lookups run; whatever matches is the
    dossier. An unmatched name is an honest "no record" — the house does not
    fabricate a profile it never observed.
    """

    def __init__(self, memory: HouseMemory, *, desk: Any = None,
                 front: Any = None, watch: Any = None,
                 journal: Any = None) -> None:
        self.m = memory
        self.desk = desk          # UnderwritingDesk (bond book + register)
        self.front = front        # FrontOffice (provider terms)
        self.watch = watch        # Watchtower (side-effect-free assess)
        self.journal = journal    # SettlementJournal (payer txs)

    # ------------------------------------------------------------------ #
    def build(self, name: str) -> dict[str, Any]:
        name = (name or "").strip()
        now = time.time()
        live = not self.m.disabled()

        caller = self._caller_dossier(name)
        provider = self._provider_dossier(name)
        insured_bonds = self._bonds_as_insured(name)
        settlements = self._settlements(name)

        found = any([caller["found"], provider["found"],
                     insured_bonds, settlements])

        note = self._note(found, live)
        return {
            "entity": name,
            "generated_at": now,
            "memory": "live" if live else "disabled",
            "found": found,
            "as_caller": caller,
            "as_provider": provider,
            "bonds_as_insured": insured_bonds,
            "settlements": settlements,
            "note": note,
        }

    # ------------------------------------------------------------------ #
    def _note(self, found: bool, live: bool) -> str:
        if not live:
            return ("memory disabled — the house remembers nothing, so it "
                    "assembles nothing. This is the deletion gate: the "
                    "dossier collapses with the memory that built it.")
        if not found:
            return ("no record: the house has never seen this wallet as a "
                    "caller, provider, insurer, or payer. It does not rate "
                    "the world; it rates only what it has remembered.")
        return ("assembled live from the house's own memory across its rooms "
                "(trust, dedup, bonds, watch, journal). Every field carries "
                "the timestamp the house observed it at — a dated snapshot, "
                "not a claim about the world.")

    # ---- Room 1 (trust) + Room 4 (watch) : the entity as a CALLER --------
    def _caller_dossier(self, name: str) -> dict[str, Any]:
        row = self.m.get_entity("caller", name) if name else None
        if row is None:
            return {"found": False}
        last_seen = row.get("last_seen")
        verdict = None
        evidence: list[str] = []
        ring: list[str] = []
        if self.watch is not None:
            try:
                a = self.watch.assess(name)
                verdict = a.get("verdict")
                evidence = [e.get("rule") for e in a.get("evidence", [])]
                ring = [_short(x) for x in a.get("ring", [])]
            except Exception:  # noqa: BLE001 - watch is best-effort in a dossier
                verdict = None
        return {
            "found": True,
            "segment": row.get("segment"),
            "trust_score": row.get("trust_score"),
            "tx_count": row.get("tx_count"),
            "served_count": row.get("served_count"),
            "dedup_hits": row.get("dedup_hits"),
            "net_charged_usdc": round(float(row.get("total_paid_usdc", 0.0) or 0.0), 6),
            "prepay_usdc": round(float(row.get("prepay_usdc", 0.0) or 0.0), 6),
            "first_seen": row.get("first_seen"),
            "last_seen": last_seen,
            "last_seen_age_s": _age_s(last_seen),
            "watch_verdict": verdict,
            "watch_evidence": evidence,
            "watch_ring": ring,
            "as_of": last_seen,
        }

    # ---- Room 3 (front) + Room 2 (bonds) : the entity as a PROVIDER ------
    def _provider_dossier(self, name: str) -> dict[str, Any]:
        row = self.m.get_entity("provider", name) if name else None
        if row is None:
            return {"found": False, "bonds": self._bonds_as_provider(name)}
        last_seen = row.get("last_seen")
        segment = None
        refused = False
        if self.front is not None:
            try:
                d = self.front.decision(name)
                segment = d.get("segment")
                refused = bool(d.get("refused"))
            except Exception:  # noqa: BLE001
                segment = None
        return {
            "found": True,
            "address_last6": _short(str(row.get("address", name))),
            "jobs_done": int(row.get("jobs_done", 0)),
            "on_time_jobs": int(row.get("on_time_jobs", 0)),
            "quality_score": round(float(row.get("quality_score", 0.0) or 0.0), 4),
            "on_time": round(float(row.get("on_time", 0.0) or 0.0), 4),
            "default_events": int(row.get("default_events", 0)),
            "total_escrow_usdc": round(float(row.get("total_escrow_usdc", 0.0) or 0.0), 6),
            "claims_against": self._claims_against(name),
            "front_segment": segment,
            "refused": refused,
            "bonds": self._bonds_as_provider(name),
            "first_seen": row.get("first_seen"),
            "last_seen": last_seen,
            "last_seen_age_s": _age_s(last_seen),
            "as_of": last_seen,
        }

    def _claims_against(self, provider: str) -> int:
        """Bonds the house actually paid out against this provider."""
        if self.desk is None:
            return 0
        try:
            bonds = self.m.list_entities("bond", limit=500)
        except Exception:  # noqa: BLE001
            return 0
        return sum(1 for b in bonds
                   if _match(b.get("provider", ""), provider)
                   and b.get("status") == "paid")

    # ---- Room 2 (bonds): the entity on either side of a bond -------------
    def _all_bonds(self) -> list[dict]:
        if self.desk is None:
            return []
        try:
            return self.m.list_entities("bond", limit=500)
        except Exception:  # noqa: BLE001
            return []

    def _bonds_as_provider(self, name: str) -> list[dict]:
        out = []
        for b in self._all_bonds():
            if _match(b.get("provider", ""), name):
                out.append(self._bond_view(b))
        return out

    def _bonds_as_insured(self, name: str) -> list[dict]:
        out = []
        for b in self._all_bonds():
            if _match(b.get("buyer", ""), name):
                out.append(self._bond_view(b))
        return out

    @staticmethod
    def _bond_view(b: dict) -> dict:
        return {
            "id": b.get("id"),
            "provider_last6": _short(str(b.get("provider", ""))),
            "insured_last6": _short(str(b.get("buyer", ""))),
            "face_usdc": b.get("face_usdc"),
            "premium_usdc": b.get("premium_usdc"),
            "segment": b.get("segment"),
            "status": b.get("status"),
            "claim_tx": b.get("claim_tx"),
            "issued_at": b.get("issued_at"),
            "issued_age_s": _age_s(b.get("issued_at")),
            "as_of": b.get("closed_at") or b.get("issued_at"),
        }

    # ---- Room 0 (money): the entity as a PAYER on the settlement journal --
    def _settlements(self, name: str) -> list[dict]:
        if self.journal is None:
            return []
        try:
            entries = self.journal.entries(limit=200)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for e in entries:
            if _match(e.get("payer", ""), name):
                out.append({
                    "tx": e.get("tx"),
                    "route": e.get("route"),
                    "amount_usdc": e.get("amount_usdc"),
                    "network": e.get("network"),
                    "ts": e.get("ts"),
                    "age_s": _age_s(e.get("ts")),
                })
        return out

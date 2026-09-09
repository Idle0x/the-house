"""Room 4 — THE WATCHTOWER (Sibyl enters market integrity).

The house refuses to launder. It publishes why.

A deterministic, memory-backed counterparty screen. NO ML, NO whole-market
census — the scope is the house's OWN observed caller set (the recent window
+ its own traffic), which is exactly the scope its memory covers. Every rule
is a pure function of per-caller WARM rows, so:

* a seeded wash ring is refused ON CAMERA with the ring drawn (the member
  list is part of the verdict),
* the house's OWN serve path consults the tower: a caller that is itself,
  part of a funding-cluster sybil, or factory spam → the payment is refused
  and the reason is published (settlement cancelled → genuinely uncharged),
* deletion (SIBYL_DISABLED) → no caller rows → no clusters → the wash caller
  is re-admitted and served like any other. That before/after IS the gate.

Rules (each returns (rule, detail, ring) or None):
  * self-pay loop           — the wallet IS the house's own pay-to, or the
                              caller is funded by itself;
  * funding-cluster sybil   — >= WATCH_SYBIL_CLUSTER_MIN callers share one
                              `funded_by` root (a ring is invisible in one
                              session — definitionally cross-session memory);
  * factory fingerprint     — >= WATCH_FACTORY_MIN callers share the same
                              request fingerprints (boilerplate spam farm);
  * cold-start with volume  — real spend on <= a handful of tx before any
                              history (HOLD: watch, don't refuse);
  * metronome timing        — >= N arrivals at a near-perfectly steady
                              interval (HOLD: no human is this steady).

ABORT rules refuse; HOLD rules flag (evidence on the feed, serve continues).
Every screen lands on the verdict feed (state `watch_feed`, capped) and in
the COLD journal (kind `screen`; refusals also kind `refuse`).
"""
from __future__ import annotations

import statistics
import time
from typing import Any, Optional

from core import config as C
from core.memory import HouseMemory

VERDICT_CLEAR = "CLEAR"
VERDICT_HOLD = "HOLD"
VERDICT_ABORT = "ABORT"

# Stable rule ids — they are cited in refusals (the evidence surface).
R_SELF_PAY = "self-pay loop"
R_SYBIL = "funding-cluster sybil"
R_FACTORY = "factory fingerprint"
R_COLD = "cold-start with volume"
R_METRONOME = "metronome timing"

_ABORT_RULES = (R_SELF_PAY, R_SYBIL, R_FACTORY)


def _short(addr: str) -> str:
    a = (addr or "").lower()
    if len(a) > 12:
        return a[:6] + "…" + a[-4:]
    return addr or "?"


class Watchtower:
    """The watchtower: deterministic screens over the house's caller memory."""

    def __init__(self, m: HouseMemory, *, house_wallet: str) -> None:
        self.m = m
        self.house_wallet = (house_wallet or "").lower()

    # ------------------------------------------------------------------ #
    # Rules — pure functions of per-caller memory.
    # ------------------------------------------------------------------ #
    def _callers(self) -> list[dict]:
        """Every caller row the house remembers (its observed traffic)."""
        return [r for r in self.m.list_entities("caller") if r.get("address")]

    def _rule_self_pay(self, wallet: str) -> Optional[tuple[str, str, list[str]]]:
        w = wallet.lower()
        if w and w == self.house_wallet:
            return (R_SELF_PAY,
                    f"{_short(wallet)} is the house's own pay-to wallet — "
                    "this payment is the house paying itself",
                    [wallet])
        row = self.m.get_entity("caller", wallet) or {}
        funded = str(row.get("funded_by", "") or "").lower()
        if funded and funded == w:
            return (R_SELF_PAY,
                    f"{_short(wallet)} is funded by itself (self-funding loop)",
                    [wallet])
        return None

    def _rule_sybil(self, wallet: str) -> Optional[tuple[str, str, list[str]]]:
        row = self.m.get_entity("caller", wallet) or {}
        root = str(row.get("funded_by", "") or "").lower()
        if not root:
            return None
        cluster = sorted({str(r.get("address")) for r in self._callers()
                          if str(r.get("funded_by", "") or "").lower() == root})
        if len(cluster) >= C.WATCH_SYBIL_CLUSTER_MIN:
            return (R_SYBIL,
                    f"{len(cluster)} callers share one funding root "
                    f"{_short(root)} — a ring is invisible in one session",
                    cluster)
        return None

    def _rule_factory(self, wallet: str) -> Optional[tuple[str, str, list[str]]]:
        row = self.m.get_entity("caller", wallet) or {}
        fps = {str(f) for f in (row.get("dedup_fp") or [])}
        if len(fps) < C.WATCH_FACTORY_FP_OVERLAP:
            return None
        cluster = [wallet]
        for r in self._callers():
            addr = str(r.get("address", ""))
            if not addr or addr.lower() == wallet.lower():
                continue
            shared = fps & {str(f) for f in (r.get("dedup_fp") or [])}
            if len(shared) >= C.WATCH_FACTORY_FP_OVERLAP:
                cluster.append(addr)
        if len(cluster) >= C.WATCH_FACTORY_MIN:
            return (R_FACTORY,
                    f"{len(cluster)} callers share the same request "
                    "fingerprints (factory boilerplate)",
                    sorted(set(cluster)))
        return None

    def _rule_cold(self, wallet: str) -> Optional[tuple[str, str, list[str]]]:
        row = self.m.get_entity("caller", wallet) or {}
        spend = float(row.get("total_paid_usdc", 0.0) or 0.0)
        tx = int(row.get("tx_count", 0))
        if spend >= C.WATCH_COLD_MIN_SPEND and tx <= C.WATCH_COLD_MAX_TX:
            return (R_COLD,
                    f"paid ${spend:g} on {tx} tx — volume before any history",
                    [wallet])
        return None

    def _rule_metronome(self, wallet: str) -> Optional[tuple[str, str, list[str]]]:
        serves = (self.m.get_state("watch_serves") or {}).get(wallet.lower(), [])
        if len(serves) < C.WATCH_METRONOME_MIN_SERVES:
            return None
        intervals = [b - a for a, b in zip(serves, serves[1:])]
        mean = sum(intervals) / len(intervals)
        if mean <= 0:
            return None
        cv = statistics.pstdev(intervals) / mean
        if cv < C.WATCH_METRONOME_MAX_CV:
            return (R_METRONOME,
                    f"{len(serves)} arrivals at a metronome interval "
                    f"(CV {cv:.3f} — no human is this steady)",
                    [wallet])
        return None

    def _all_rules(self, wallet: str) -> list[Optional[tuple[str, str, list[str]]]]:
        return [self._rule_self_pay(wallet), self._rule_sybil(wallet),
                self._rule_factory(wallet), self._rule_cold(wallet),
                self._rule_metronome(wallet)]

    # ------------------------------------------------------------------ #
    # Screen + serve-path consult.
    # ------------------------------------------------------------------ #
    def assess(self, wallet: str) -> dict[str, Any]:
        """The pure screen: CLEAR / HOLD / ABORT + evidence + ring.

        NO memory writes — this is the read-only form, so the dossier (Room 5)
        can surface a counterparty's current verdict without publishing it to
        the public verdict feed. ``screen()`` = assess + publish.
        """
        wallet = (wallet or "").strip()
        evidence: list[dict[str, str]] = []
        ring: list[str] = []
        verdict = VERDICT_CLEAR
        if wallet:
            for hit in self._all_rules(wallet):
                if hit is None:
                    continue
                rule, detail, ring_part = hit
                evidence.append({"rule": rule, "detail": detail})
                if ring_part:
                    ring = ring_part
                if rule in _ABORT_RULES:
                    verdict = VERDICT_ABORT
                elif verdict != VERDICT_ABORT:
                    verdict = VERDICT_HOLD
        return {
            "wallet": wallet,
            "verdict": verdict,
            "evidence": evidence,
            "ring": ring,
            "scope": "own observed caller set (recent window) — no "
                     "whole-market census",
        }

    def screen(self, wallet: str) -> dict[str, Any]:
        """Deterministic counterparty screen: assess + PUBLISH.

        The verdict is a pure function of the house's remembered caller set.
        Deletion → no rows → no clusters → the wash caller is re-admitted.
        """
        result = self.assess(wallet)
        if wallet:
            self._feed_push({"ts": time.time(), "wallet": wallet,
                             "verdict": result["verdict"],
                             "rules": [e["rule"] for e in result["evidence"]],
                             "ring": result["ring"]})
            self.m.write_event(
                f"watch screen {_short(wallet)} -> {result['verdict']} "
                f"({', '.join(e['rule'] for e in result['evidence']) or 'clean'})",
                kind="screen")
        return result

    def note_serve(self, payer: str) -> None:
        """Record an arrival timestamp (the metronome's raw material)."""
        if self.m.disabled():
            return
        ts = self.m.get_state("watch_serves") or {}
        key = payer.lower()
        ts[key] = (ts.get(key, []) + [time.time()])[-20:]
        self.m.set_state("watch_serves", ts)

    def note_funding(self, addr: str, funded_by: str) -> dict:
        """Record who funds this caller — the funding-graph edge (Room 4).

        The audit (SEV-2) found nothing in the product ever WROTE
        ``funded_by`` — only tests seeded it — so the watchtower's
        funding-cluster sybil rule (``_rule_sybil``) and the self-funding
        branch of ``self-pay`` could never fire on live traffic. This is the
        writer. A paid ``/watch/screen`` may declare the root that funds the
        wallet, and the house REMEMBERS it on the caller row. A ring is
        invisible in one session (spec 08-ELEVATION Room 4), so the edge is
        declared on a screen and then honored by the serve path across
        sessions — the cross-session funding memory the room is built on.

        ``funded_by`` is stored lowercased (the rules compare lowercased). An
        empty declaration is a no-op that still (re)creates the row so the
        caller is observed as having been screened.
        """
        if self.m.disabled():
            return {}
        funded_by = (funded_by or "").strip().lower()
        # Upsert (merge) so an existing caller row keeps every field and only
        # gains/updates funded_by + last_seen. A fresh row is created for a
        # wallet the house has never served — the rules only need funded_by
        # (the cluster scan + the self-funding check read it; cold/metronome
        # default to 0/absent → CLEAR).
        row = self.m.upsert_entity("caller", addr, {
            "address": addr,
            "funded_by": funded_by,
            "last_seen": time.time(),
        })
        if funded_by:
            self.m.write_event(
                f"funding graph: {_short(addr)} funded by {_short(funded_by)}",
                kind="funding")
        return row

    def consult(self, payer: str) -> Optional[dict[str, Any]]:
        """Own-serve-path check: record the arrival, return the refusal body
        when the tower says ABORT. None → serve.

        Uses the pure ``assess()`` — it does NOT publish a CLEAR/HOLD verdict
        for every ordinary serve (audit finding: ``screen()`` on every paid
        serve wrote a CLEAR feed entry + journal event; the feed should show
        verdicts that MEAN something). Only an ABORT is published (feed +
        kind=refuse), because the refusal is the news.

        The refusal is returned to the handler BEFORE settlement, so the
        caller is genuinely uncharged — the house declines the payment and
        says why. Deletion: with memory disabled the house never consults,
        so the wash caller walks in fresh and is served. That re-admission
        IS the gate.
        """
        if self.m.disabled():
            return None
        self.note_serve(payer)
        s = self.assess(payer)
        if s["verdict"] != VERDICT_ABORT:
            return None
        rules = ", ".join(e["rule"] for e in s["evidence"])
        self._feed_push({"ts": time.time(), "wallet": payer,
                         "verdict": s["verdict"],
                         "rules": [e["rule"] for e in s["evidence"]],
                         "ring": s["ring"]})
        self.m.write_event(
            f"watchtower REFUSED payment from {_short(payer)} ({rules})",
            kind="refuse")
        return {
            "status": 403,
            "error": "the house declines this payment",
            "house_refused": f"watchtower: {rules}",
            "watch": {"verdict": s["verdict"], "evidence": s["evidence"],
                      "ring": s["ring"]},
            "house_declined": True,
            "house": {"room": "watchtower"},
        }

    # ------------------------------------------------------------------ #
    # Feed + aggregates (the public face of the room).
    # ------------------------------------------------------------------ #
    def _feed_push(self, entry: dict[str, Any]) -> None:
        # State is always stored as a DICT (memory contract) — the feed is a
        # list wrapped in one.
        feed: list[dict[str, Any]] = list(
            (self.m.get_state("watch_feed") or {}).get("items", []))
        self.m.set_state("watch_feed",
                         {"items": (feed + [entry])[-C.WATCH_FEED_MAX:]})

    def feed(self) -> list[dict[str, Any]]:
        """Verdict feed, newest first: screens + refusals with reasons."""
        items = list((self.m.get_state("watch_feed") or {}).get("items", []))
        return list(reversed(items))

    def stats(self) -> dict[str, Any]:
        feed = list((self.m.get_state("watch_feed") or {}).get("items", []))
        total = len(feed)
        manufactured = sum(1 for e in feed if e.get("verdict") == VERDICT_ABORT)
        organic = total - manufactured
        return {
            "screens": total,
            "refusals": manufactured,
            "organic": organic,
            "manufactured": manufactured,
            "organic_pct": round(100.0 * organic / total, 1) if total else None,
            "manufactured_pct": round(100.0 * manufactured / total, 1)
            if total else None,
        }

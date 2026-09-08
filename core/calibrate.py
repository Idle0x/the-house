"""E2 — Calibrator (03-FEATURES E2, 02-ARCHITECTURE §6).

The house grades itself. Reads the COLD journal + WARM/state stores and
scores the house's own past decisions:
  - trust decisions vs realized outcomes (served→repeat vs fault/refund)
  - pricing realized vs base (loyalty discount actually applied)
  - dedup hit-rate (repeats served from cache)
  - scar-rule hit-rate (compiled policy rules in force)
Writes REFERENCE key="calibration" and returns a one-page report.

Every number is computed from real stores (no invented telemetry). The
journal kinds are the stable contract (core/memory.py KINDS).
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core.memory import HouseMemory

CALIBRATION_KEY = "calibration"
BASE_PRICE_DEFAULT = 0.01


class Calibrator:
    def __init__(self, m: HouseMemory, base_price: float = BASE_PRICE_DEFAULT) -> None:
        self.m = m
        self.base_price = base_price

    # ------------------------------------------------------------------ #
    def _count_events(self, kind: str) -> int:
        return sum(1 for e in self.m.read_events(limit=2000)
                   if isinstance(e, dict)
                   and (e.get("extra") or {}).get("kind") == kind)

    def calibrate(self) -> dict:
        """One-page calibration of the house's own decisions."""
        served = self._count_events("served")
        faults = self._count_events("caller_fault")
        refunds = self._count_events("refund")
        failures = self._count_events("failure")
        paid_jobs = self._count_events("paid")

        callers = self.m.list_entities("caller", limit=500)
        total_paid = sum(float(c.get("total_paid_usdc", 0.0)) for c in callers)
        tx_total = sum(int(c.get("tx_count", 0)) for c in callers)
        vips = sum(1 for c in callers if c.get("segment") == "vip")
        banned = sum(1 for c in callers if c.get("segment") == "banned")

        dedup = self.m.get_state("dedup_stats") or {}
        dedup_hits = int(dedup.get("hits", 0))
        usdc_saved = float(dedup.get("usdc_saved", 0.0))

        rules = self.m.get_reference("policy") or {}
        scars_total = len(self.m.list_entities("scar", limit=500))

        # --- trust decision quality: what share of served work ended in
        # a fault/refund/failure vs clean repeats? -----------------------
        bad_outcomes = faults + refunds + failures
        total_outcomes = served + bad_outcomes
        trust_precision = (served / total_outcomes) if total_outcomes else None

        # --- pricing realized vs base -----------------------------------
        realized_avg = (total_paid / tx_total) if tx_total else None
        discount = (1 - realized_avg / self.base_price) \
            if realized_avg is not None and self.base_price else None

        # --- dedup hit-rate ----------------------------------------------
        dedup_rate = (dedup_hits / tx_total) if tx_total else None

        # --- scar-rule hit-rate ------------------------------------------
        scar_rule_rate = (len(rules) / scars_total) if scars_total else None

        report: dict[str, Any] = {
            "ts": time.time(),
            "memory": "live",
            "decision_counts": {
                "served": served, "caller_fault": faults, "refund": refunds,
                "failure": failures, "paid_jobs": paid_jobs,
            },
            "cohort": {"callers": len(callers), "vip": vips, "banned": banned,
                       "tx_total": tx_total},
            "trust_decision_precision": trust_precision,
            "pricing": {"base_price": self.base_price,
                        "realized_avg_usdc": realized_avg,
                        "loyalty_discount": discount},
            "dedup": {"hits": dedup_hits, "usdc_saved": usdc_saved,
                      "hit_rate": dedup_rate},
            "scars": {"total": scars_total, "policy_rules": len(rules),
                      "rule_rate": scar_rule_rate},
        }
        lines = [
            "THE HOUSE — calibration report",
            f"callers: {len(callers)} (vip {vips}, banned {banned}); "
            f"{tx_total} txs, ${total_paid:.4f} paid.",
            f"served {served} · faults {faults} · refunds {refunds} · "
            f"failures {failures} · paid jobs {paid_jobs}.",
            f"trust precision: {self._pct(trust_precision)} of outcomes were "
            f"clean serves (not fault/refund/failure).",
            f"pricing: realized avg {self._usd(realized_avg)} vs base "
            f"${self.base_price:.4f} → loyalty discount "
            f"{self._pct(discount)}.",
            f"dedup: {dedup_hits} repeats cached, ${usdc_saved:.4f} saved "
            f"({self._pct(dedup_rate)} of txs).",
            f"scars: {scars_total} recorded, {len(rules)} policy rules "
            f"compiled ({self._pct(scar_rule_rate)}).",
        ]
        report["report"] = "\n".join(lines)
        self.m.set_reference(CALIBRATION_KEY, report)
        return report

    def last_calibration(self) -> Optional[dict]:
        return self.m.get_reference(CALIBRATION_KEY)

    @staticmethod
    def _pct(x: Optional[float]) -> str:
        return f"{x:.1%}" if x is not None else "n/a"

    @staticmethod
    def _usd(x: Optional[float]) -> str:
        return f"${x:.4f}" if x is not None else "n/a"

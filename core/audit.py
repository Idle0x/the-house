"""E1 — SelfAuditor (03-FEATURES E1, 02-ARCHITECTURE §6).

The house audits the house. snapshot() writes the agent's operational
state to HOT key="baseline": route failure heatmap (from scars), failure
rate vs served work, trust drift, pending jobs, dedup money. audit()
re-snapshots and diffs against the baseline, emitting a degradation report
that cites the actual scar ids behind any route that worsened. A fresh
session inherits the baseline from memory and can tell the difference
between "normal" and "degraded" — that recall IS the memory act here.

Deletion harness: SIBYL_DISABLED=1 → no baseline survives, no findings
are computed, every audit starts from zero ("the house remembers no
normal, so nothing is abnormal").

Metric set is honest: we report exactly what the house stores (served,
failures/scars, trust, jobs, dedup). No invented p95 — the seller has no
upstream latency surface today, so we do not fake one.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from core.memory import HouseMemory

BASELINE_KEY = "baseline"
LAST_AUDIT_KEY = "last_audit"
FAILURE_RATE_RISE = 0.10   # report if route error share rises ≥ 10 pts
TRUST_DROP = 5.0           # report if mean caller trust drops ≥ 5


class SelfAuditor:
    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    # ------------------------------------------------------------------ #
    def _events(self, kind: str) -> int:
        return sum(1 for e in self.m.read_events(limit=2000)
                   if (e.get("extra") or {}).get("kind") == kind
                   if isinstance(e, dict))

    def snapshot(self) -> dict:
        """Current operational state — the thing the audit diffs against."""
        scars = self.m.list_entities("scar", limit=500)
        callers = self.m.list_entities("caller", limit=500)
        served = sum(int(c.get("served_count", 0)) for c in callers)
        failures = sum(1 for s in scars)
        by_route: dict[str, int] = {}
        for s in scars:
            r = s.get("route", "?")
            by_route[r] = by_route.get(r, 0) + 1
        trusts = [float(c.get("trust_score", 50.0)) for c in callers]
        jobs = self.m.get_state("jobs") or {}
        return {
            "ts": time.time(),
            "callers_total": len(callers),
            "served_total": served,
            "failure_total": failures,
            "failure_share": (failures / served) if served else 0.0,
            "scars_by_route": by_route,
            "mean_trust": round(sum(trusts) / len(trusts), 2) if trusts else None,
            "pending_jobs": sum(1 for j in jobs.values()
                                if j.get("phase") not in ("settled", "refunded")),
            "dedup_stats": self.m.get_state("dedup_stats") or {},
        }

    def _finding(self, severity: str, code: str, msg: str,
                 scar_id: Optional[str] = None) -> dict:
        f: dict[str, Any] = {"severity": severity, "code": code, "message": msg}
        if scar_id:
            f["cites_scar"] = scar_id
        return f

    # ------------------------------------------------------------------ #
    def audit(self) -> dict:
        """Diff now vs the stored baseline → degradation report.

        First run (no baseline): stores one and reports "baseline set" so
        the second run can tell normal from degraded.
        """
        now = self.snapshot()
        baseline = self.m.get_state(BASELINE_KEY)
        report: dict[str, Any] = {"ts": now["ts"], "memory": "live",
                                  "findings": []}
        if baseline is None:
            self.m.set_state(BASELINE_KEY, now)
            report["status"] = "baseline_set"
            report["message"] = ("First audit: baseline recorded. Run again "
                                 "after real traffic to diff normal vs now.")
            self.m.set_reference(LAST_AUDIT_KEY, report)
            return report

        findings = []
        # 1) Route failure heatmap vs baseline (cites real scar ids).
        before_routes = baseline.get("scars_by_route") or {}
        scars = {s.get("id"): s for s in self.m.list_entities("scar", limit=500)}
        for route, count in (now.get("scars_by_route") or {}).items():
            prev = before_routes.get(route, 0)
            if count > prev and count >= 3:
                # Cite the most recent scar for this route.
                sid = next((s.get("id") for s in reversed(
                    list(scars.values())) if s.get("route") == route), None)
                findings.append(self._finding(
                    "warning", "route_failures",
                    f"route {route}: {prev} → {count} scarred failures "
                    f"(memory baseline {prev})",
                    scar_id=sid))
        # 2) Global failure share rise.
        share_before = float(baseline.get("failure_share", 0.0))
        share_now = float(now.get("failure_share", 0.0))
        if share_now - share_before >= FAILURE_RATE_RISE:
            findings.append(self._finding(
                "critical", "failure_share_rise",
                f"failure share {share_before:.2f} → {share_now:.2f} "
                f"(threshold +{FAILURE_RATE_RISE:.0%})"))
        # 3) Trust drift.
        t_before = baseline.get("mean_trust")
        t_now = now.get("mean_trust")
        if t_before is not None and t_now is not None \
                and t_now <= t_before - TRUST_DROP:
            findings.append(self._finding(
                "warning", "trust_drift",
                f"mean caller trust {t_before} → {t_now} "
                f"(drop ≥ {TRUST_DROP})"))
        # 4) Stuck work.
        if now.get("pending_jobs", 0) > 0:
            findings.append(self._finding(
                "warning", "pending_jobs",
                f"{now.get('pending_jobs')} non-terminal job(s) in flight"))

        report["findings"] = findings
        report["status"] = "degraded" if findings else "healthy"
        report["now"] = {k: v for k, v in now.items() if k != "ts"}
        report["baseline"] = {k: v for k, v in baseline.items() if k != "ts"}
        self.m.set_reference(LAST_AUDIT_KEY, report)
        return report

    def last_audit(self) -> Optional[dict]:
        return self.m.get_reference(LAST_AUDIT_KEY)

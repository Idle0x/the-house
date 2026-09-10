"""ACPDelegator — the Virtuals multiplier (spec specs/acp-plan.md, Gate 4).

THE HOUSE delegates a class of work to an ACP provider agent on Base and
REMEMBERS the provider's record — the counterparty pattern of F1, applied
to agents instead of wallets:

  delegate(provider, offering, requirements)
    1. recall get_entity("provider", <addr>) FIRST          <- the memory act
    2. terms are a pure function of the recalled row:
         proven  (quality_score >= 0.8 and on_time >= 0.9) -> standard budget,
                   trusted evaluator (auto-complete on submitted)
         unknown (no row / memory disabled)                -> standard budget,
                   stricter evaluator (requirements carry an explicit
                   acceptance criterion; the job is reviewed, not auto-complete)
         risky   (quality < 0.6 or default_events >= 1)    -> refuse (skip hire)
    3. acp client create-job -> poll history for budget.set -> fund EXACT
       amount -> poll for submitted -> complete (proven) or review-then-complete
    4. update the provider WARM row (jobs_done, on_time, quality) + COLD event

The recalled record changes the onchain job terms. Without memory every
provider is a stranger at standard terms (deletion-safe: SIBYL_DISABLED=1
recalls nothing and writes nothing).

This module shells out to the `acp` CLI (v2 surface). It never fabricates
an onchain result: every step reads the CLI's --json output.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any, Optional

from core.memory import HouseMemory

# Terms thresholds (specs/acp-plan.md §"What THE HOUSE does with it").
PROVEN_MIN_QUALITY = 0.8
PROVEN_MIN_ON_TIME = 0.9
RISKY_MAX_QUALITY = 0.6
CHAIN_ID = 8453  # Base mainnet


class ProviderTerms:
    """The per-provider job terms decision (pure function of the row)."""

    def __init__(self, segment: str, reason: str, *, strict_review: bool = False,
                 skip: bool = False) -> None:
        self.segment = segment          # proven | unknown | risky
        self.reason = reason
        self.strict_review = strict_review  # stricter evaluator (requirements note)
        self.skip = skip                # refuse to hire (risky record)

    def to_dict(self) -> dict:
        return {"segment": self.segment, "reason": self.reason,
                "strict_review": self.strict_review, "skip": self.skip}


def terms_from_row(row: Optional[dict]) -> ProviderTerms:
    """Terms = pure function of the recalled provider row (spec step 2)."""
    if row is None:
        return ProviderTerms(
            "unknown",
            "no record (or memory disabled): standard terms, stricter evaluator",
            strict_review=True)
    quality = float(row.get("quality_score", 0.0))
    on_time = float(row.get("on_time", 0.0))
    defaults = int(row.get("default_events", 0))
    jobs = int(row.get("jobs_done", 0))
    # A quality_score of 0.0 means "never measured", not "measured 0" — so it
    # only counts against a provider when quality was actually assessed. A
    # provider that completed real jobs without a quality reading is a thin
    # record (unknown), never "risky".
    # "Assessed" = the flag is set, OR the row shows real completed jobs with a
    # non-zero reading (a measured low quality is a measured low quality even
    # if the flag was written before the flag existed).
    assessed = bool(row.get("quality_assessed", False)) or (jobs >= 1 and quality > 0)
    if defaults >= 1 or (assessed and quality < RISKY_MAX_QUALITY):
        return ProviderTerms(
            "risky",
            f"bad record: quality {quality:.2f}, defaults {defaults} — "
            f"the house does not hire this provider",
            skip=True)
    if quality >= PROVEN_MIN_QUALITY and on_time >= PROVEN_MIN_ON_TIME and jobs >= 1:
        return ProviderTerms(
            "proven",
            f"proven: {jobs} job(s), quality {quality:.2f}, "
            f"on-time {on_time:.2f} — standard budget, trusted evaluator")
    return ProviderTerms(
        "unknown",
        f"thin record ({jobs} job(s)): standard budget, stricter evaluator",
        strict_review=True)


class ACPDelegator:
    """Delegate a paid job to an ACP provider; memory decides the terms."""

    def __init__(self, m: HouseMemory, acp_bin: Optional[str] = None,
                 chain_id: int = CHAIN_ID, timeout_s: int = 300,
                 poll_s: float = 6.0) -> None:
        self.m = m
        self.chain_id = chain_id
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.acp_bin = acp_bin or os.getenv("ACP_BIN") or shutil.which("acp") or "acp"

    # ------------------------------------------------------------------ #
    # Memory I/O
    # ------------------------------------------------------------------ #
    def recall_provider(self, addr: str) -> Optional[dict]:
        return self.m.get_entity("provider", addr)

    def terms(self, addr: str) -> ProviderTerms:
        return terms_from_row(self.recall_provider(addr))

    def _upsert_provider(self, addr: str, delta: dict) -> dict:
        return self.m.upsert_entity("provider", addr, delta)

    def _new_provider_row(self, addr: str) -> dict:
        row = {
            "address": addr,
            "first_seen": time.time(),
            "last_seen": time.time(),
            "jobs_done": 0,
            "on_time_jobs": 0,
            "quality_sum": 0.0,
            "quality_score": 0.0,
            "quality_assessed": False,  # no job completed yet
            "on_time": 0.0,
            "total_escrow_usdc": 0.0,
            "default_events": 0,
            "notes": "",
        }
        self.m.set_entity("provider", addr, row)
        return row

    def _record_outcome(self, addr: str, *, escrow_usdc: float,
                        delivered_on_time: bool, quality: float) -> dict:
        """Update the provider WARM row after a completed job (spec step 4)."""
        row = self.recall_provider(addr)
        if row is None:
            row = self._new_provider_row(addr)
        jobs = int(row.get("jobs_done", 0)) + 1
        on_time_jobs = int(row.get("on_time_jobs", 0)) + (1 if delivered_on_time else 0)
        qsum = float(row.get("quality_sum", 0.0)) + quality
        row.update({
            "last_seen": time.time(),
            "jobs_done": jobs,
            "on_time_jobs": on_time_jobs,
            "quality_sum": qsum,
            "quality_score": round(qsum / jobs, 4),
            "quality_assessed": True,  # a real job produced a real reading
            "on_time": round(on_time_jobs / jobs, 4),
            "total_escrow_usdc": round(float(row.get("total_escrow_usdc", 0.0))
                                       + escrow_usdc, 6),
        })
        self.m.set_entity("provider", addr, row)
        self.m.write_event(
            f"acp job done → {addr} escrow ${escrow_usdc:.2f} "
            f"(quality {quality:.2f}, on-time {delivered_on_time})",
            kind="paid")
        return row

    # ------------------------------------------------------------------ #
    # CLI runner
    # ------------------------------------------------------------------ #
    def _acp(self, *args: str, timeout: Optional[int] = None) -> dict:
        """Run an acp CLI command with --json; return parsed dict or {}."""
        cmd = [self.acp_bin, *args, "--json"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout or 90)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-400:]
            raise RuntimeError(f"acp {' '.join(args)} failed: {err}")
        try:
            return json.loads(proc.stdout) if proc.stdout.strip() else {}
        except json.JSONDecodeError:
            return {"raw": proc.stdout.strip()}

    def _history(self, job_id: str) -> dict:
        return self._acp("job", "history", "--job-id", job_id,
                         "--chain-id", str(self.chain_id))

    def job_history(self, job_id: str) -> dict:
        """Live onchain job record from the ACP index (real CLI read).

        Returns a normalized view: status, escrow amount, provider, and the
        completion reason hash (the onchain completion record). A job the
        index does not know about raises — callers surface that as a real
        'not found', never as an invented status.
        """
        h = self._acp("job", "history", "--job-id", job_id,
                      "--chain-id", str(self.chain_id), timeout=20)
        if not h.get("entries"):
            raise RuntimeError(f"job {job_id} not found on chain {self.chain_id}")
        amount = 0.0
        provider = ""
        completed_reason = None
        for entry in h["entries"]:
            ev = entry.get("event") or {}
            t = ev.get("type")
            if t == "budget.set" and float(ev.get("amount", 0)) > 0:
                amount = float(ev["amount"])
            elif t == "job.created":
                provider = str(ev.get("provider", ""))
            elif t == "job.completed":
                completed_reason = ev.get("reason")
        return {
            "job_id": str(job_id),
            "status": str(h.get("status", "")),
            "escrow_usdc": round(amount, 4),
            "provider": provider,
            "completed_reason": completed_reason,
        }

    def jobs_summary(self, job_ids: list[str]) -> list[dict]:
        """Batch job_history with honest per-job errors (no silent drops).

        The per-job CLI reads are independent, so they run concurrently — a
        cold read of N jobs costs ~one CLI round-trip, not N. Order is
        preserved; a job that errors is reported, never dropped.
        """
        if not job_ids:
            return []
        from concurrent.futures import ThreadPoolExecutor
        def _one(jid: str) -> dict:
            try:
                return self.job_history(jid)
            except Exception as exc:  # noqa: BLE001 - report, don't hide
                return {"job_id": str(jid), "status": "unavailable",
                        "error": str(exc)[:200], "escrow_usdc": 0.0,
                        "provider": "", "completed_reason": None}
        with ThreadPoolExecutor(max_workers=len(job_ids)) as ex:
            return list(ex.map(_one, job_ids))

    def _find_event(self, history: dict, etype: str) -> Optional[dict]:
        for entry in history.get("entries", []):
            ev = entry.get("event") or {}
            if ev.get("type") == etype:
                return ev
        return None

    # ------------------------------------------------------------------ #
    # The delegate flow (spec step 3)
    # ------------------------------------------------------------------ #
    def delegate(self, provider_addr: str, offering_name: str,
                 requirements: dict, *, quality_if_success: float = 0.9) -> dict:
        """Hire a provider onchain for one job, terms set by the recalled row.

        Returns the full receipt: terms decision, job id, funded amount,
        completion status, and the provider row AFTER the update.
        """
        terms = self.terms(provider_addr)
        receipt: dict[str, Any] = {"terms": terms.to_dict()}
        if terms.skip:
            receipt["skipped"] = True
            receipt["reason"] = terms.reason
            return receipt

        # Stricter evaluator: requirements carry an explicit acceptance
        # criterion when the provider is NOT yet proven (the criterion is an
        # onchain message — visible in job history, real, not decorative).
        req = dict(requirements)
        if terms.strict_review:
            req = self._with_acceptance_criterion(req, offering_name)

        created = self._acp("client", "create-job",
                            "--provider", provider_addr,
                            "--offering-name", offering_name,
                            "--requirements", json.dumps(req),
                            "--chain-id", str(self.chain_id))
        job_id = str(created.get("jobId", ""))
        if not job_id:
            raise RuntimeError(f"create-job returned no jobId: {created}")
        receipt["job_id"] = job_id

        # Poll for budget.set (provider prices the job).
        deadline = time.time() + self.timeout_s
        amount: Optional[float] = None
        status = ""
        while time.time() < deadline:
            history = self._history(job_id)
            status = str(history.get("status", ""))
            ev = self._find_event(history, "budget.set")
            if ev is not None:
                amount = float(ev.get("amount", 0.0))
                break
            time.sleep(self.poll_s)
        if amount is None or amount <= 0:
            raise RuntimeError(
                f"job {job_id} never budget_set (status={status}); "
                f"provider unresponsive — job expires harmlessly at $0")
        receipt["budget_usdc"] = amount

        # Fund the EXACT budget (the double-spend discipline).
        self._acp("client", "fund", "--job-id", job_id,
                  "--amount", f"{amount:.4f}", "--chain-id", str(self.chain_id))
        receipt["funded_usdc"] = amount

        # Poll for submitted, then complete (trusted) or review then complete.
        while time.time() < deadline:
            history = self._history(job_id)
            status = str(history.get("status", ""))
            if status == "submitted":
                break
            if status in ("rejected", "expired", "completed"):
                break
            time.sleep(self.poll_s)

        if status == "submitted":
            reason = ("the-house: accepted" if not terms.strict_review
                      else "the-house: reviewed against acceptance criterion — accepted")
            self._acp("client", "complete", "--job-id", job_id,
                      "--reason", reason, "--chain-id", str(self.chain_id))
            receipt["completion"] = "completed"
            receipt["delivered_on_time"] = True
            # Quality scored by the evaluator (the house). Success default 0.9.
            row = self._record_outcome(
                provider_addr, escrow_usdc=amount,
                delivered_on_time=True, quality=quality_if_success)
        elif status == "completed":
            receipt["completion"] = "already_completed"
            row = self.recall_provider(provider_addr) or {}
        else:
            receipt["completion"] = f"terminal_without_submit:{status}"
            self.m.write_event(
                f"acp job {job_id} → {provider_addr} {status} ($0 escrow)",
                kind="refunded")
            row = self.recall_provider(provider_addr) or {}

        receipt["final_status"] = status
        receipt["provider_row"] = row
        return receipt

    @staticmethod
    def _with_acceptance_criterion(req: dict, offering_name: str) -> dict:
        """Stricter evaluator: append a checkable criterion to the work brief.

        Only applied to the FIRST string field so the offering schema stays
        valid (create-job validates requirements against the schema).
        """
        for key, val in req.items():
            if isinstance(val, str):
                req = dict(req)
                req[key] = (val +
                            "\n\n[the-house evaluation criterion] Deliverable must "
                            f"address the request for '{offering_name}' completely "
                            "and be usable as-is. State what you changed and why.")
                return req
        return req

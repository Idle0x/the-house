"""F4 — Restart-Resilient Execution (Lane B core), spec 03-FEATURES.md F4.

A job state machine persisted in Sibyl HOT state (key="jobs"). Every phase
transition is written to memory BEFORE the corresponding side effect, so a
kill -9 mid-flight can resume exactly where it stopped.

Settlement is keyed on job_id and is IDEMPOTENT: settle() once → settled;
calling it again is a no-op. That is the double-charge killer, and the demo's
cinematic beat (kill -9 → resume → "settling (idempotent)" → one tx).

Job id = sha256(caller|route|fp|attempt) — deterministic per attempt.

Deletion harness: SIBYL_DISABLED=1 → no job state survives a restart →
resume_all() finds nothing → the request is re-served from scratch (and would
double-serve). The degradation IS the point.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from core.memory import HouseMemory

PHASES = ("accepted", "serving", "verified", "settled", "refunded", "failed")
PAYMENT_STATES = ("pending", "verified", "settled", "refunded")
# Terminal phases: resume_all/pending_count/snapshot must ignore these.
TERMINAL = ("settled", "refunded", "failed")


def job_id(caller: str, route: str, fp: str, attempt: int) -> str:
    key = f"{caller}|{route}|{fp}|{attempt}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


class JobStateMachine:
    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    # ------------------------------------------------------------------ #
    def _jobs(self) -> dict[str, dict]:
        jobs = self.m.get_state("jobs")
        return jobs if isinstance(jobs, dict) else {}

    def _save(self, jobs: dict[str, dict]) -> None:
        self.m.set_state("jobs", jobs)

    def get(self, job_id_: str) -> Optional[dict]:
        return self._jobs().get(job_id_)

    # ------------------------------------------------------------------ #
    def start(self, caller: str, route: str, fp: str,
              attempt: int = 1, params: dict | None = None) -> dict:
        """Create + persist a job BEFORE serving. Returns the job row."""
        jid = job_id(caller, route, fp, attempt)
        now = time.time()
        job = {
            "id": jid,
            "caller": caller,
            "route": route,
            "fp": fp,
            "attempt": attempt,
            "params": params or {},
            "phase": "accepted",
            "payment_state": "pending",
            "steps_completed": [],
            "deliverable_ref": None,
            "created_at": now,
            "updated_at": now,
        }
        jobs = self._jobs()
        jobs[jid] = job
        self._save(jobs)
        return job

    def advance(self, job_id_: str, phase: str, *, step: str | None = None,
                payment_state: str | None = None) -> dict:
        """Persist a phase transition BEFORE the side effect happens."""
        if phase not in PHASES:
            raise ValueError(f"unknown phase {phase!r}")
        jobs = self._jobs()
        job = jobs.get(job_id_)
        if job is None:
            raise KeyError(f"no such job {job_id_}")
        job["phase"] = phase
        job["updated_at"] = time.time()
        if step:
            if step not in job["steps_completed"]:
                job["steps_completed"].append(step)
        if payment_state:
            if payment_state not in PAYMENT_STATES:
                raise ValueError(f"unknown payment_state {payment_state!r}")
            job["payment_state"] = payment_state
        jobs[job_id_] = job
        self._save(jobs)
        return job

    # ------------------------------------------------------------------ #
    def settle(self, job_id_: str, payer: str) -> dict:
        """IDEMPOTENT settlement keyed on (job_id, payer).

        Second call → no-op returning the already-settled job. This is the
        double-charge killer: a resumed job settles exactly once.
        """
        job = self.get(job_id_)
        if job is None:
            raise KeyError(f"no such job {job_id_}")
        if job["phase"] == "settled" or job["payment_state"] == "settled":
            job["settle_attempts"] = job.get("settle_attempts", 1)
            return job  # already settled — no-op (idempotent)
        # Persist BEFORE the onchain settle side effect.
        job["payment_state"] = "settled"
        job["phase"] = "settled"
        job["settled_by"] = payer
        job["settle_attempts"] = job.get("settle_attempts", 0) + 1
        job["updated_at"] = time.time()
        jobs = self._jobs()
        jobs[job_id_] = job
        self._save(jobs)
        self.m.write_event(f"job {job_id_} settled by {payer} (idempotent)",
                           kind="paid")
        return job

    def refund(self, job_id_: str, reason: str = "") -> dict:
        return self.advance(job_id_, "refunded", payment_state="refunded")

    def fail(self, job_id_: str, cause: str) -> dict:
        """Mark the job FAILED (terminal), then open attempt N+1.

        Persist the failed state BEFORE the retry side effect, so a crash
        between the two never leaves the original non-terminal (a zombie
        resume_all would double-serve). The retry is a NEW job row with its
        own id — resume_all will only ever see the live retry.
        """
        job = self.get(job_id_)
        if job is None:
            raise KeyError(f"no such job {job_id_}")
        self.advance(job_id_, "failed", step=f"failed: {cause}")
        attempt = int(job.get("attempt", 1)) + 1
        return self.start(job["caller"], job["route"], job["fp"],
                          attempt=attempt, params=job.get("params"))

    # ------------------------------------------------------------------ #
    def resume_all(self) -> list[dict]:
        """On startup: continue every non-terminal job from its last phase.

        Terminal = settled / refunded / failed (failed jobs have a live
        retry row of their own — never resurrect the corpse).
        Returns the list of resumed (non-terminal) jobs.
        """
        resumed = []
        jobs = self._jobs()
        for jid, job in jobs.items():
            if job.get("phase") in TERMINAL:
                continue
            # Persist the resumed marker BEFORE re-running the step.
            job["resumed_at"] = time.time()
            jobs[jid] = job
            resumed.append(job)
        if resumed:
            self._save(jobs)
        return resumed

    def pending_count(self) -> int:
        jobs = self._jobs()
        return sum(1 for j in jobs.values()
                   if j.get("phase") not in TERMINAL)

    def snapshot(self, limit: int = 50) -> list[dict]:
        """Non-terminal jobs first, then most recently updated — for /house/jobs."""
        jobs = self._jobs()
        ordered = sorted(jobs.values(),
                         key=lambda j: float(j.get("updated_at", 0)), reverse=True)
        ordered.sort(key=lambda j: 0 if j.get("phase") not in TERMINAL
                     else 1)
        return ordered[:limit]

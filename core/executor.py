"""F4 executor — the missing half of kill-resume (FIX-3).

Before this, ``resume_all()`` stamped ``resumed_at`` on non-terminal jobs and
stopped: a job left in phase="serving" by a kill -9 was *found* but never
*re-driven* — the cinematic beat was a state-machine simulation.

The executor closes the loop. It holds a reference to the real serve function
(the same code path a live request runs). On startup (after resume_all) it
re-drives every job sitting in a non-terminal phase exactly once:

    serve → job advances + settles idempotently (phase "serving" → "settled")
    serve fails → job is marked terminal "failed"

Idempotency is inherited: settle() is a no-op the second time, so a job that
was killed MID-settle cannot double-charge, and a job the original handler
already settled (the middleware settles after the handler returns) is not
re-served — it is in a terminal phase and the executor skips it.

Deletion harness: SIBYL_DISABLED=1 → no jobs survive → the executor finds
nothing (degradation: idempotency died with the memory, and a retry would
double-serve from scratch).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from core.jobs import JobStateMachine

log = logging.getLogger("the-house.executor")


class JobExecutor:
    def __init__(self, jobs: JobStateMachine,
                 serve: Callable[[dict], None]) -> None:
        self.jobs = jobs
        # serve(job) must: do the work, update ledger/dedup as a live serve
        # would, then jobs.settle(job["id"], job["caller"]).
        self.serve = serve

    def drive(self) -> list[str]:
        """Re-drive every non-terminal job exactly once. Returns job ids."""
        driven: list[str] = []
        for job in self.jobs.resume_all():
            jid = job.get("id")
            if not jid:
                continue
            try:
                self.serve(job)
                driven.append(jid)
                log.info("executor: re-driven job %s → settled", jid)
            except Exception as exc:  # noqa: BLE001 - terminal-fail, keep going
                try:
                    self.jobs.advance(jid, "failed",
                                      step=f"executor: {type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    log.exception("executor: failed to mark %s terminal", jid)
                driven.append(jid)
                log.warning("executor: job %s terminal-failed: %s", jid, exc)
        return driven

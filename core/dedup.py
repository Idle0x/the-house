"""F2 — Dedup-as-Revenue (specs/03-FEATURES.md F2).

Never re-serve what a caller already paid for. Fingerprints on the caller
WARM row (dedup_fp), answers cached on disk (cache/<fp>.json), and a hard
money counter in HOT state key="dedup_stats":
    {hits, usdc_saved, compute_avoided_usd}

Canonical fingerprinting strips volatile params (timestamps, defaults) so
"same question, different clock" is still a repeat.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from core.memory import HouseMemory

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"


def canonical(params: dict[str, Any], volatile_keys: set[str] | None = None) -> dict[str, Any]:
    """Stable, order-independent view of params minus volatile keys."""
    volatile = volatile_keys or {"ts", "timestamp", "limit", "_"}
    return {k: v for k, v in params.items() if k not in volatile}


def fingerprint(route: str, params: dict[str, Any]) -> str:
    """sha256(route|canonical-json) — the dedup identity of a request."""
    canon = json.dumps(canonical(params), sort_keys=True, default=str)
    return hashlib.sha256(f"{route}|{canon}".encode()).hexdigest()


class DedupEngine:
    """Server-side dedup store. Deletion harness: no cache reads/writes."""

    def __init__(self, m: HouseMemory, cache_dir: Path = CACHE_DIR) -> None:
        self.m = m
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _fp_path(self, fp: str) -> Path:
        return self.cache_dir / f"{fp}.json"

    def is_repeat(self, caller_row: dict, fp: str) -> bool:
        return fp in (caller_row.get("dedup_fp") or [])

    def load(self, fp: str) -> Optional[dict]:
        """Return the cached answer for fp (None in deletion mode)."""
        if self.m.disabled():
            return None
        p = self._fp_path(fp)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def store(self, fp: str, answer: dict) -> None:
        if self.m.disabled():
            return
        self._fp_path(fp).write_text(json.dumps(answer))

    # ------------------------------------------------------------------ #
    def mark_served(self, caller_row: dict, addr: str, fp: str,
                    answer: dict, price_usdc: float) -> dict:
        """Append fp + write cache. Returns the updated caller row.

        Re-reads the CURRENT entity before writing so concurrent updates
        (e.g. a trust bump from the same request) are not clobbered by a
        stale snapshot.
        """
        current = self.m.get_entity("caller", addr)
        row = dict(current) if current is not None else dict(caller_row)
        fps = list(row.get("dedup_fp") or [])
        if fp not in fps:
            fps.append(fp)
        row["dedup_fp"] = fps
        self.m.set_entity("caller", addr, row)
        self.store(fp, answer)
        return row

    def note_repeat(self, price_usdc: float, *, compute_avoided: bool = True) -> dict:
        """Increment the money counter: hits, usdc_saved, compute_avoided_usd.

        ``compute_avoided`` is TRUE only when the repeat was served from the
        cache WITHOUT re-running the work (audit SEV-1: the counter used to
        claim +$0.001 even when `_do_work` had run on every repeat). The
        ~$0.001 estimate is added only when compute was genuinely avoided.
        """
        stats = self.m.get_state("dedup_stats") or {
            "hits": 0, "usdc_saved": 0.0, "compute_avoided_usd": 0.0,
        }
        stats["hits"] = int(stats.get("hits", 0)) + 1
        stats["usdc_saved"] = round(float(stats.get("usdc_saved", 0.0)) + price_usdc, 6)
        # Compute estimate: ~$0.001 of LLM/compute per served answer.
        if compute_avoided:
            stats["compute_avoided_usd"] = round(
                float(stats.get("compute_avoided_usd", 0.0)) + 0.001, 6
            )
        self.m.set_state("dedup_stats", stats)
        return stats

    def stats(self) -> dict:
        return self.m.get_state("dedup_stats") or {
            "hits": 0, "usdc_saved": 0.0, "compute_avoided_usd": 0.0,
        }

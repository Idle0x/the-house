"""HouseMemory — THE single place all memory I/O goes.

This wrapper normalizes the 8 verified SDK realities (see
shared/specs/sdk-realities.md) into the clean API the features use:

    1. get_entity RAISES NotFoundError on a miss  -> we return None
    2. entities come back wrapped under "body"    -> we unwrap
    3. write_event has NO free-form fields        -> we journal via
       acted=[text], extra={"kind": kind}
    4. get_reference stores body as a JSON STRING -> we parse back to dict
    5. scar compilation uses list_entities, NOT search_entities
    6. set_state body must be a dict/list        -> validated here
    7. MemoryClient.local — no init, no network, free tier
    8. verified-working API surface (11/11 round-trip checks in
       scripts/verify_sibyl_sdk.py)

SIBYL_DISABLED=1 no-ops every read to empty and every write — the deletion
harness (tests/test_deletion_f1.py, deletion_test.py). Under it the house
remembers nothing: every caller is "new" at list price.

This module is the README's "where memory is load-bearing" pointer. Do not
call the raw client anywhere else.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from sibyl_memory_client import MemoryClient
from sibyl_memory_client.exceptions import NotFoundError

# Journal kinds — KEEP STABLE. E2 (calibrate) scores decisions off
# extra.kind, and the COLD journal is the audit trail.
# Taxonomy (audit finding 16): `refund` (trust outcome) and `refunded`
# (job phase) are both kept for backward compat with written events;
# `repeat`, `prepay` and `refuse` cover events that previously fell through
# as `paid`/untyped or never existed. `funding` is the funding-graph edge
# written by the watchtower (the `funded_by` writer, audit SEV-2).
KINDS = ("served", "caller_fault", "refund", "paid", "failure", "job",
         "audit", "refunded", "bond", "claim", "screen", "refuse",
         "repeat", "prepay", "funding")

DEFAULT_DB = Path("~/.sibyl-memory/memory.db").expanduser()


def memory_disabled() -> bool:
    """Deletion harness: SIBYL_DISABLED=1 → memory reads empty, writes no-op."""
    return os.environ.get("SIBYL_DISABLED", "").strip() in ("1", "true", "TRUE", "yes")


class _NullMemory:
    """Drop-in that answers like an empty memory (deletion mode)."""

    def get_entity(self, kind: str, name: str) -> Optional[dict]:
        return None

    def set_entity(self, kind: str, name: str, body: dict) -> None:
        return None

    def get_state(self, key: str) -> Optional[dict]:
        return None

    def set_state(self, key: str, body: dict) -> None:
        return None

    def write_event(self, *, evaluated=None, acted=None, forward=None,
                    extra=None, ts=None) -> None:
        return None

    def read_events(self, *args: Any, **kwargs: Any) -> list:
        return []

    def get_reference(self, key: str) -> Optional[dict]:
        return None

    def set_reference(self, key: str, body: dict) -> None:
        return None

    def list_entities(self, category: str, limit: int = 200) -> list:
        return []

    def search_entities(self, query: str) -> list:
        return []

    def archive_entity(self, kind: str, name: str) -> None:
        return None


class HouseMemory:
    """Thin, normalized wrapper over the Sibyl Memory client (free tier)."""

    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self._null: Any = _NullMemory()
        self._disabled = memory_disabled()
        if self._disabled:
            self._m: Any = self._null
            self._real_m: Any = self._null
        else:
            # Ensure the parent dir exists for local file mode.
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._real_m = MemoryClient.local(str(Path(db_path).expanduser()))
            self._m = self._real_m
        self.db_path = str(db_path)
        # Runtime mode: "live" | "disabled" (soft off, data kept) | "purged"
        # (true deletion). The env flag only governs the initial state.
        self._mode: str = "disabled" if self._disabled else "live"

    # ------------------------------------------------------------------ #
    # Runtime wipe — the public memory gate. Wipe is a TRUE, PERMANENT
    # deletion: the underlying store is closed and its file removed, so the
    # recalled state (entities, dedup, scars, trust, journal) is genuinely
    # gone — the house is blind, and remembers nothing, including its own
    # purge. There is no restore and no re-seed: purge is irreversible, which
    # is why the reversible soft-off (disable) exists. The env flag
    # SIBYL_DISABLED still governs the initial state; the runtime flag is an
    # additional override on top of it.
    # ------------------------------------------------------------------ #
    @property
    def purged(self) -> bool:
        """True when the runtime deletion gate (true deletion) is active."""
        return self._mode == "purged"

    @property
    def mode(self) -> str:
        """live | disabled (soft off, data kept) | purged (deleted)."""
        return self._mode

    def disable(self) -> None:
        """SOFT off: reads empty, writes no-op, but the underlying store
        persists untouched. Reversible instantly via enable() — no re-seed,
        all remembered state comes back intact. This is the 'unplug' mode:
        the house stops remembering but forgets nothing."""
        if self._mode != "live":
            return
        self._m = self._null
        self._mode = "disabled"

    def enable(self) -> None:
        """Reconnect after disable — data intact, no re-seed needed."""
        if self._mode != "disabled":
            return
        if self._real_m is self._null:
            return  # deletion harness: nothing real to reconnect to
        self._m = self._real_m
        self._mode = "live"

    def wipe(self) -> None:
        """TRUE, PERMANENT deletion: close the store, remove its file,
        recreate empty. The house is blind — every read returns empty, every
        write no-ops. There is no way back: purge is irreversible."""
        if self._real_m is not self._null:
            try:
                self._real_m.storage.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass
            try:
                p = Path(self.db_path).expanduser()
                if p.exists():
                    p.unlink()
            except Exception:  # noqa: BLE001 - best-effort unlink
                pass
            # recreate an empty store at the same path
            try:
                Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
                self._real_m = MemoryClient.local(str(Path(self.db_path).expanduser()))
            except Exception:  # noqa: BLE001 - if recreate fails, stay null
                self._real_m = self._null
        self._m = self._null
        self._mode = "purged"
        # Leave a marker beside the DB so a later restart can tell "purged
        # on purpose" apart from "fresh deploy, never had data". The boot
        # re-seed (seller lifespan) restores chain-proven callers ONLY when
        # this marker is absent — a purge stays blind across restarts.
        try:
            marker = Path(self.db_path).expanduser().parent / ".house-purged"
            marker.write_text(str(time.time()))
        except Exception:  # noqa: BLE001 - best-effort marker
            pass

    def restore(self) -> None:
        """Legacy reconnect helper — retained for the deletion harness. NOTE:
        purge is irreversible; nothing in the app calls restore anymore."""
        self._m = self._real_m
        self._mode = "live"

    # ------------------------------------------------------------------ #
    # WARM entities (caller, provider, scar)
    # ------------------------------------------------------------------ #
    def get_entity(self, kind: str, name: str) -> Optional[dict]:
        """Return the entity's body dict, or None if absent (quirk 1+2)."""
        try:
            row = self._m.get_entity(kind, name)
        except NotFoundError:
            return None
        if row is None:
            return None
        body = row.get("body") if isinstance(row, dict) else None
        return body if isinstance(body, dict) else None

    def set_entity(self, kind: str, name: str, body: dict) -> None:
        self._m.set_entity(kind, name, body)

    def upsert_entity(self, kind: str, name: str, body: dict) -> dict:
        """Merge into an existing entity (or create). Returns the stored body."""
        existing = self.get_entity(kind, name) or {}
        merged = {**existing, **body}
        self.set_entity(kind, name, merged)
        return merged

    def list_entities(self, category: str, limit: int = 200) -> list[dict]:
        """List wrapped rows → unwrapped bodies (quirk 5)."""
        rows = self._m.list_entities(category, limit=limit)
        out = []
        for r in rows or []:
            body = r.get("body") if isinstance(r, dict) else None
            if isinstance(body, dict):
                out.append(body)
        return out

    def archive_entity(self, kind: str, name: str) -> None:
        self._m.archive_entity(kind, name)

    def search_entities(self, query: str) -> list[dict]:
        rows = self._m.search_entities(query) or []
        out = []
        for r in rows:
            body = r.get("body") if isinstance(r, dict) else None
            if isinstance(body, dict):
                out.append(body)
        return out

    # ------------------------------------------------------------------ #
    # HOT state (jobs, dedup_stats, baseline, totals)
    # ------------------------------------------------------------------ #
    def get_state(self, key: str) -> Optional[dict]:
        """Return state body dict or None (state is always stored as a dict)."""
        try:
            row = self._m.get_state(key)
        except NotFoundError:
            return None
        if row is None:
            return None
        body = row.get("body") if isinstance(row, dict) else None
        return body if isinstance(body, dict) else None

    def set_state(self, key: str, body: dict) -> None:
        if not isinstance(body, dict):
            raise ValueError(f"set_state body must be a dict, got {type(body).__name__}")
        self._m.set_state(key, body)

    def update_state(self, key: str, delta: dict) -> dict:
        """Merge delta into a state dict. Returns the merged body."""
        current = self.get_state(key) or {}
        if not isinstance(current, dict):
            current = {}
        merged = {**current, **delta}
        self.set_state(key, merged)
        return merged

    # ------------------------------------------------------------------ #
    # COLD journal (events)
    # ------------------------------------------------------------------ #
    def write_event(self, text: str, kind: str = "job") -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown journal kind {kind!r}; keep KINDS stable")
        # Quirk 3: no free-form fields — journal via acted/extra.
        self._m.write_event(evaluated=None, acted=[text], extra={"kind": kind})

    def read_events(self, **kwargs: Any) -> list[dict]:
        return self._m.read_events(**kwargs) or []

    # ------------------------------------------------------------------ #
    # REFERENCE (pricing, policy, calibration, last_audit)
    # ------------------------------------------------------------------ #
    def get_reference(self, key: str) -> Optional[dict]:
        """Return parsed dict body, or None (quirk 4: body is a JSON string)."""
        try:
            row = self._m.get_reference(key)
        except NotFoundError:
            return None
        if row is None:
            return None
        raw = row.get("body") if isinstance(row, dict) else None
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {"value": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def set_reference(self, key: str, body: dict) -> None:
        if not isinstance(body, dict):
            raise ValueError(f"set_reference body must be a dict, got {type(body).__name__}")
        self._m.set_reference(key, json.dumps(body))

    # ------------------------------------------------------------------ #
    def disabled(self) -> bool:
        # True in both off-states: disabled (soft, data kept) and wiped
        # (true deletion). The runtime mode overrides the env flag.
        return self._mode != "live"

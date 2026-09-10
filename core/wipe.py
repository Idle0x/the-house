"""THE HOUSE — the public memory gate (WipeController).

Two real ways to take the house's memory off, with opposite semantics:

  DISABLE (recommended) — SOFT off. The house stops reading and writing, but
  the store persists untouched and everything comes back. It is reversible:
  after DISABLE_AUTO_REENABLE_SECONDS (15 min) the house re-enables itself in
  the background (the landing page shows a live countdown), or anyone can
  re-enable it instantly. Data is kept.

  PURGE (not recommended) — TRUE, PERMANENT deletion. The store is closed and
  its file removed; the learned state (trust, dedup, scars, journal) is gone
  with NO way back. There is NO countdown, NO auto-restore and NO restore
  endpoint — purge is irreversible. That is why disable exists: if you want
  memory off but recoverable, disable it; purge is only for when you want it
  gone.

Because purge is destructive and irreversible, it is guarded by two layers of
constraint. The confirmation message surfaces the irreversibility, but the
rejection messages are rate-limit flavored (they never say "you can only wipe
N times per day" — that reads as a game; they say "you've been deleting memory
too frequently, this affects the house's availability to everyone").

  1. PER-IP COOLDOWN — the same address cannot purge again for
     PER_IP_COOLDOWN_SECONDS (2 h) after its own purge. Stops one visitor
     hammering the gate.
  2. PER-IP DAILY CAP — at most DAILY_WIPE_LIMIT (3) purges per address per
     UTC day. Other addresses can still purge their own 3 — the cap is per
     user, not global — so the demo is never permanently dead for the next
     judge, but one visitor cannot exhaust the gate for everyone.

Disable carries a lighter rolling rate limit (3 disables per address in any
2-hour window) because it is non-destructive — it never takes the house down.

State is kept in-memory (process-local). On a multi-worker deploy this is a
best-effort guard, not a hard global lock — acceptable for a demo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

DISABLE_AUTO_REENABLE_SECONDS = 15 * 60    # disable self-heals after 15 min
PER_IP_COOLDOWN_SECONDS = 2 * 60 * 60     # 2 h per-address re-purge cooldown
DAILY_WIPE_LIMIT = 3                      # max purges per address per UTC day
# Soft-off (disable) rate limit: at most 3 disables per address in any rolling
# 2-hour window. No per-day cap — after the window drains, disabling is
# available again.
DISABLE_MAX = 3
DISABLE_WINDOW_SECONDS = 2 * 60 * 60


def _utc_day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


# Rate-limit flavored rejection copy. Never states the exact quota — reads as
# "you are being rate limited", not "this is a game with rules".
_RATE_LIMITED = (
    "you've been deleting memory too frequently — this affects the house's "
    "availability to everyone. please wait before trying again."
)


@dataclass
class WipeController:
    """Guard + executor for the public memory gate."""

    reenable_seconds: int = DISABLE_AUTO_REENABLE_SECONDS
    per_ip_cooldown_seconds: int = PER_IP_COOLDOWN_SECONDS
    daily_limit: int = DAILY_WIPE_LIMIT
    disable_max: int = DISABLE_MAX
    disable_window_seconds: int = DISABLE_WINDOW_SECONDS

    # process-local state
    _purged_at: Optional[float] = field(default=None, init=False)
    _disabled_at: Optional[float] = field(default=None, init=False)
    _reenable_at: Optional[float] = field(default=None, init=False)
    _last_purge_by_ip: dict[str, float] = field(default_factory=dict, init=False)
    # rolling disable timestamps per ip (pruned to the window)
    _disable_events_by_ip: dict[str, list[float]] = field(default_factory=dict, init=False)
    # per-address daily counts keyed by ip -> (day, count)
    _count_by_ip: dict[str, tuple[str, int]] = field(default_factory=dict, init=False)

    # ------------------------------------------------------------------ #
    def status(self, ip: Optional[str] = None) -> dict:
        """Current gate state, for the landing page / status endpoint."""
        now = time.time()
        purged = self._purged_at is not None
        disabled = self._disabled_at is not None
        remaining = 0
        # only a soft-off (disable) has a recovery window — purge is permanent
        if disabled and self._reenable_at is not None:
            remaining = max(0, int(self._reenable_at - now))
        mode = "purged" if purged else ("disabled" if disabled else "live")
        return {
            "mode": mode,
            "purged": purged,
            "disabled": disabled,
            "purged_at": self._purged_at,
            "disabled_at": self._disabled_at,
            "remaining_seconds": remaining,
            "reenable_seconds": self.reenable_seconds,
            "per_ip_cooldown_seconds": self.per_ip_cooldown_seconds,
            "daily_limit": self.daily_limit,
            "disable_max": self.disable_max,
            "disable_window_seconds": self.disable_window_seconds,
            "ip": ip,
            "ip_can_wipe": self._ip_can_wipe(ip) if ip else True,
            "ip_cooldown_remaining": self._ip_cooldown_remaining(ip) if ip else 0,
            "ip_wipes_today": self._ip_wipes_today(ip) if ip else 0,
            "ip_can_disable": self._ip_disable_remaining(ip) > 0 if ip else True,
            "ip_disable_remaining": self._ip_disable_remaining(ip) if ip else self.disable_max,
            "ip_disable_seconds_left": self._ip_disable_seconds_left(ip) if ip else 0,
        }

    # ------------------------------------------------------------------ #
    def _ip_wipes_today(self, ip: str) -> int:
        day, count = self._count_by_ip.get(ip, ("", 0))
        return count if day == _utc_day() else 0

    def _ip_can_wipe(self, ip: str) -> bool:
        # both the per-IP cooldown and the per-IP daily cap must pass
        if self._ip_wipes_today(ip) >= self.daily_limit:
            return False
        last = self._last_purge_by_ip.get(ip)
        if last is None:
            return True
        return (time.time() - last) >= self.per_ip_cooldown_seconds

    def _ip_cooldown_remaining(self, ip: str) -> int:
        last = self._last_purge_by_ip.get(ip)
        if last is None:
            return 0
        rem = int(self.per_ip_cooldown_seconds - (time.time() - last))
        return max(0, rem)

    def _ip_disable_recent(self, ip: str) -> list[float]:
        """Disable timestamps for this IP still inside the 2h window."""
        now = time.time()
        cutoff = now - self.disable_window_seconds
        events = [t for t in self._disable_events_by_ip.get(ip, []) if t > cutoff]
        self._disable_events_by_ip[ip] = events
        return events

    def _ip_disable_remaining(self, ip: str) -> int:
        """How many disables this IP may still make in the current window."""
        return max(0, self.disable_max - len(self._ip_disable_recent(ip)))

    def _ip_disable_seconds_left(self, ip: str) -> int:
        """Seconds until the oldest in-window disable event expires."""
        events = self._ip_disable_recent(ip)
        if len(events) < self.disable_max:
            return 0
        oldest = min(events)
        rem = int((oldest + self.disable_window_seconds) - time.time())
        return max(0, rem)

    # ------------------------------------------------------------------ #
    def try_purge(self, memory, *, ip: str) -> tuple[bool, str, dict]:
        """PERMANENT, irreversible deletion. The store is closed and its file
        removed — the learned state is gone with no way back. There is no
        countdown, no auto-restore and no restore endpoint. Guarded by the
        per-IP cooldown + per-IP daily cap."""
        now = time.time()

        # already purged — nothing to do, and it can't come back
        if self._purged_at is not None:
            return False, "memory is already purged — permanently.", self.status(ip)

        # per-IP cooldown + per-IP daily cap (rate-limit flavored)
        if not self._ip_can_wipe(ip):
            return False, _RATE_LIMITED, self.status(ip)

        # ---- apply the purge (a true deletion supersedes any soft-off) ----
        memory.wipe()
        self._purged_at = now
        self._disabled_at = None
        self._reenable_at = None
        self._last_purge_by_ip[ip] = now
        day, count = self._count_by_ip.get(ip, (_utc_day(), 0))
        self._count_by_ip[ip] = (_utc_day() if day != _utc_day() else day, count + 1)
        return True, "memory purged — permanently. the store is erased.", self.status(ip)

    # ------------------------------------------------------------------ #
    def try_disable(self, memory, *, ip: str) -> tuple[bool, str, dict]:
        """SOFT off: memory stops reading and writing, but the store persists
        untouched. Reversible — it self-heals after reenable_seconds (5 min)
        in the background, or anyone can re-enable instantly via enable().
        Non-destructive, so it carries a light rolling rate limit (3 disables
        per IP in any 2h window), not the heavy purge gate."""
        now = time.time()
        # a true deletion is already off and permanent — must purge-aware
        if self._purged_at is not None:
            return False, "memory is purged — permanently. it cannot be disabled.", self.status(ip)
        # rolling rate limit: 3 disables per IP per 2h window
        if self._ip_disable_remaining(ip) <= 0:
            left = self._ip_disable_seconds_left(ip)
            return (
                False,
                "you've disabled memory too often — it re-opens in "
                f"{left // 60}m {left % 60}s.",
                self.status(ip),
            )
        memory.disable()
        self._disabled_at = now
        self._reenable_at = now + self.reenable_seconds
        self._disable_events_by_ip.setdefault(ip, []).append(now)
        return True, "memory disabled — data kept, re-enables itself in 15 minutes.", self.status(ip)

    def enable(self, memory) -> dict:
        """Instant re-enable after a soft-off. Data was never destroyed, so
        no re-seed is needed — all remembered state returns intact."""
        was_disabled = self._disabled_at is not None
        if was_disabled:
            memory.enable()
        self._disabled_at = None
        self._reenable_at = None
        return self.status()

    def maybe_auto_reenable(self, memory) -> bool:
        """Background self-heal: if a soft-off's 15-minute window has elapsed,
        re-enable the house automatically. Returns True if it re-enabled."""
        if self._disabled_at is None or self._reenable_at is None:
            return False
        if time.time() >= self._reenable_at:
            self.enable(memory)
            return True
        return False
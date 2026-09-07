"""F3 — Failure Compilation (scars → policy), spec 03-FEATURES.md F3.

The agent learns from its OWN failures. WARM rows kind="scar" record each
failure; compile() groups same (route, failure_class) scars into REFERENCE
policy rules; the serve path applies matching rules and "cites the scar"
(scar_cited=<rule.source_scar>). Fresh sessions inherit hardened policy.

Deletion harness: SIBYL_DISABLED=1 → no scars recorded, no policy written,
no rules applied → the same mistake repeats. "Wipe the scars and it's back
to fresh eyes."
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from core.memory import HouseMemory

SCAR_COMPILE_N = 3  # same (route, failure_class) count to compile a rule

# Rule actions the serve path understands.
ACTIONS = ("prepay_required", "retry_budget=0", "refuse_until", "switch_upstream")


class ScarCompiler:
    def __init__(self, m: HouseMemory) -> None:
        self.m = m

    # ------------------------------------------------------------------ #
    def record(self, route: str, failure_class: str, root_cause: str) -> str:
        """Record a failure scar. Returns the scar id."""
        sid = f"S-{uuid.uuid4().hex[:10]}"
        scar = {
            "id": sid,
            "route": route,
            "failure_class": failure_class,
            "root_cause": root_cause,
            "occurred_at": time.time(),
            "policy_delta": {"rule_id": None, "action": None},
        }
        self.m.set_entity("scar", sid, scar)
        self.m.write_event(f"scar {sid} {failure_class} on {route}", kind="failure")
        return sid

    # ------------------------------------------------------------------ #
    def _group_scars(self) -> dict[tuple[str, str], list[dict]]:
        groups: dict[tuple[str, str], list[dict]] = {}
        for scar in self.m.list_entities("scar", limit=500):
            key = (scar.get("route", "?"), scar.get("failure_class", "?"))
            groups.setdefault(key, []).append(scar)
        return groups

    def compile(self) -> list[str]:
        """Group scars → create/refresh policy rules at threshold.

        Returns the list of rule_ids created/updated this pass.
        """
        rules = self.m.get_reference("policy") or {}
        changed: list[str] = []
        for (route, failure_class), scars in self._group_scars().items():
            if len(scars) < SCAR_COMPILE_N:
                continue
            # Pick the most recent scar as source.
            source = max(scars, key=lambda s: float(s.get("occurred_at", 0)))
            rule_id = f"R-{route}-{failure_class}".replace("/", "_")
            action = self._pick_action(failure_class)
            existing = rules.get(rule_id)
            if existing and existing.get("source_scar") == source.get("id"):
                continue  # already compiled from this scar
            rules[rule_id] = {
                "match": {"route": route, "failure_class": failure_class},
                "action": action,
                "until": time.time() + 24 * 3600,  # 24h policy sunset
                "source_scar": source.get("id"),
            }
            # Stamp the policy_delta onto every grouped scar.
            for s in scars:
                sid = s.get("id")
                if sid:
                    self.m.upsert_entity("scar", str(sid), {
                        "policy_delta": {"rule_id": rule_id, "action": action},
                    })
            changed.append(rule_id)
        if changed:
            self.m.set_reference("policy", rules)
        return changed

    @staticmethod
    def _pick_action(failure_class: str) -> str:
        """Defensible default hardening per failure class."""
        f = failure_class.lower()
        if "refund" in f or "chargeback" in f:
            return "prepay_required"
        if "timeout" in f or "upstream" in f or "5xx" in f:
            return "switch_upstream"
        if "banned" in f or "abuse" in f:
            return "refuse_until"
        return "retry_budget=0"

    # ------------------------------------------------------------------ #
    def apply_policy(self, route: str, failure_class: str,
                     now: float | None = None) -> Optional[dict]:
        """Consult REFERENCE policy for a matching, unexpired rule.

        Returns {action, rule_id, source_scar, until} or None.
        """
        rules = self.m.get_reference("policy") or {}
        now = now if now is not None else time.time()
        for rule in rules.values():
            match = rule.get("match") or {}
            if match.get("route") == route and match.get("failure_class") == failure_class:
                until = float(rule.get("until", 0))
                if until <= now:
                    continue  # lapsed
                return rule
        return None

    def active_rules(self) -> dict:
        return self.m.get_reference("policy") or {}

    def clear_policy(self) -> None:
        """Manual reset for tests/demo (rules auto-lapse anyway)."""
        self.m.set_reference("policy", {})

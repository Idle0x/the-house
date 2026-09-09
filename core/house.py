"""THE HOUSE — money engine (the paid-intel spoke).

This is where the memory actually decides what happens to a verified payer.
It owns the real money flow so it can be unit-tested without the x402
middleware, the CDP facilitator, or any network.

Money model (verified against the installed x402 2.x exact scheme, NOT
assumed):

* The buyer signs an EIP-3009 authorization for EXACTLY the 402 quote, which
  is BASE. ``ExactEvmScheme.settle`` re-verifies the amount, so the onchain
  settlement is ALWAYS base — the server cannot extract more from that
  payment, and cannot settle it for less (a ``$0`` ``Settlement-Overrides``
  is an *upto*-scheme feature; it rejects under *exact*).
* The handler runs BEFORE settlement (middleware ``call_next`` → then
  ``process_settlement``), and a >=400 response CANCELS settlement. So the
  payer is known from the verified payload, and a refusal (banned / risky
  prepay) is genuinely uncharged.
* Therefore the house's loyalty pricing is: settle base onchain, then send
  the DISCOUNT BACK as a real rebate tx (``HouseWallet.send_rebate``) via the
  house's own ACP wallet. VIP (×0.80) → rebates 0.002; regular (×0.95) →
  0.0005; repeat (net $0) → rebates the full base. Every rebate is journaled
  with its tx hash. Net = base × mult, and it reconciles to Basescan
  (settlement tx + rebate tx).
* risky (×1.30) cannot be charged from the buyer's fixed signature, so it is
  enforced as ``Decision.prepay``: the house refuses to serve a risky wallet
  until it carries a prepay credit covering the surcharge — a memory decision
  with a money consequence, exactly what ``Decision.prepay`` models.

Deletion harness: SIBYL_DISABLED=1 → recall None → every caller is "new" at
list price, no dedup, no refusal, no rebate, no prepay. The business model
collapses to a stateless price list (that is the gate).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

from core.audit import SelfAuditor
from core.calibrate import Calibrator
from core.dedup import DedupEngine, fingerprint
from core.executor import JobExecutor
from core.jobs import JobStateMachine
from core.memory import HouseMemory
from core.config import INTEL_ENTITY_PRICE
from core.scars import ScarCompiler
from core.settle_journal import SettlementJournal
from core.trust import TrustLedger
from core.wallet import DryRunWallet, HouseWallet, USDC_BASE
from core.watch import Watchtower

log = logging.getLogger("the-house.engine")


def _failure_class(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "5xx upstream timeout"
    if "connection" in msg or "refused" in msg:
        return "upstream connection refused"
    return f"exception:{name}"


class House:
    """The house: memory + trust + dedup + scars + jobs + money.

    ``wallet`` is injectable (tests stub the money-out); ``do_work`` is the
    real serve body (the ACP underwriting call in production).
    """

    def __init__(self, memory: HouseMemory, *,
                 base_price: float,
                 wallet: Optional[HouseWallet] = None,
                 do_work: Optional[Callable[[str], dict[str, Any]]] = None,
                 do_work_secondary: Optional[Callable[[str], dict[str, Any]]] = None,
                 wallet_check: Optional[Callable[[], dict]] = None,
                 service_name: str = "the-house",
                 watch: Optional[Watchtower] = None,
                 entity_price: Optional[float] = None) -> None:
        self.m = memory
        self.base_price = base_price
        self.service_name = service_name
        self.ledger = TrustLedger(memory)
        self.dedup = DedupEngine(memory)
        self.scars = ScarCompiler(memory)
        self.jobs = JobStateMachine(memory)
        self.auditor = SelfAuditor(memory)
        self.calibrator = Calibrator(memory, base_price=base_price)
        # Money-out is SAFE-BY-DEFAULT: DryRunWallet (no acp, no money) unless
        # the caller injects a real HouseWallet (build_app does so only when
        # HOUSE_LIVE_MONEY_OUT=1 + a real HOUSE_WALLET are set).
        self.wallet = wallet if wallet is not None else DryRunWallet(memory)
        self.journal = SettlementJournal(memory)
        # /intel/entity base price (default: the config's dossier price).
        self.entity_price = (INTEL_ENTITY_PRICE if entity_price is None
                             else entity_price)
        # The entity dossier (Room 5) — wired by build_app once desk/front/
        # watch exist. serve_entity() needs it; without it a live entity read
        # 404s (nothing to assemble). Kept as a plain attribute (no import
        # cycle: dossier is assembled in the boundary layer).
        self.dossier: Any = None
        # F3 upstream registry: the house can have a PRIMARY upstream (its own
        # memory-derived brief — always available, the product) and an optional
        # SECONDARY (the real ACP/external call in production). A compiled
        # ``switch_upstream`` scar policy rotates which one the serve path uses;
        # the choice is persisted in WARM state so a fresh session inherits it.
        self._work_primary = do_work if do_work is not None else self._default_work
        self._work_secondary = do_work_secondary
        # The serve path calls ``self._do_work`` for the primary upstream (the
        # memory brief / injected work fn — tests monkeypatch this attr) and
        # ``self._work_secondary`` for the secondary (the real external call in
        # production). rotate_upstream() toggles which one _run_work uses.
        self._do_work = self._work_primary
        self._wallet_check = wallet_check
        self.watch = watch
        self._executor: Optional[JobExecutor] = None

    # ------------------------------------------------------------------ #
    def _default_work(self, payer: str) -> dict[str, Any]:
        """The real serve body: a memory-derived brief about the caller.

        This is the product — "I remember who you are." The intel is not a
        canned line; it is the relationship the house has with THIS payer,
        read live from its own memory: who they are (segment + trust), how
        long the house has known them, what they've paid, and the watchtower's
        current verdict on them. Deletion → no standing → the brief collapses
        to "new wallet, list price" (the gate, inside the product).
        """
        row = self.ledger.recall(payer) or {}
        standing = {
            "segment": row.get("segment"),
            "trust_score": row.get("trust_score"),
            "tx_count": int(row.get("tx_count", 0)),
            "served": int(row.get("served_count", 0)),
            "dedup_hits": int(row.get("dedup_hits", 0)),
            "lifetime_usdc": round(float(row.get("total_paid_usdc", 0.0) or 0.0), 6),
            "first_seen": row.get("first_seen"),
            "last_seen": row.get("last_seen"),
        }
        # The watchtower's live verdict on this caller (read-only; no feed write).
        verdict = None
        evidence: list[str] = []
        if self.watch is not None:
            try:
                a = self.watch.assess(payer)
                verdict = a.get("verdict")
                evidence = [e.get("rule") for e in a.get("evidence", [])]
            except Exception:  # noqa: BLE001 - watch is best-effort in the brief
                verdict = None

        segment = standing["segment"]
        known = standing["tx_count"] > 0
        if not known:
            brief = ("New wallet. The house has no memory of you yet — you "
                     "are priced at list and every serve is billed in full. "
                     "Pay, and the house will start to remember.")
        else:
            tenure = ""
            first = standing.get("first_seen")
            if first:
                days = (time.time() - float(first)) / 86400.0
                tenure = (f" The house has known you {days:.0f} day"
                          + ("s" if abs(days - 1) >= 0.5 else "") +
                          f" ({standing['tx_count']} settlement"
                           + ("s" if standing['tx_count'] != 1 else "") + ").")
            brief = (f"You are a {segment} counterparty "
                     f"(trust {standing['trust_score']}). "
                     f"Net charged to you this lifetime: "
                     f"${standing['lifetime_usdc']:g}." + tenure)
            if standing["dedup_hits"]:
                brief += (f" {standing['dedup_hits']} repeat request"
                          + ("s" if standing['dedup_hits'] != 1 else "")
                          + " served from cache at no charge.")
        if verdict in ("HOLD", "ABORT"):
            brief += (f" Watchtower verdict on you right now: {verdict}"
                      + (f" ({', '.join(evidence)})." if evidence else "."))
        # NOTE: the envelope already carries the authoritative, POST-UPDATE
        # standing (and the repeat path replays the cached answer). So the
        # answer must NOT re-emit a top-level "standing" — it would clobber
        # the envelope's. The brief is self-contained in the intel string.
        return {"intel": brief, "watch_verdict": verdict, "brief_standing": standing}

    def _drive(self, job: dict[str, Any]) -> None:
        """Executor re-drive: finish a job killed mid-serve. Re-runs the work
        and settles idempotently (``jobs.settle`` is a no-op the 2nd time —
        the original onchain settlement already happened, so no double
        charge). Underwriting work is idempotent (same job id / fp)."""
        jid = job.get("id")
        if jid:
            self.jobs.settle(jid, job.get("caller", ""))

    # ------------------------------------------------------------------ #
    def startup(self) -> dict[str, Any]:
        """F4 boot: verify the money-out wallet, resume stalled jobs, re-drive.

        When live money-out is enabled, the ACP wallet address MUST
        match the configured HOUSE_WALLET (the x402 pay_to) — otherwise the
        house would receive on one wallet and send rebates from another.
        Fail-closed: on mismatch/error we mark wallet_ok=False (the engine
        still serves; rebates degrade to the dry-run path, logged).
        """
        wallet_check = {"ok": True, "mode": "dry-run"}
        if self._wallet_check is not None:
            try:
                wallet_check = self._wallet_check()
            except Exception as exc:  # noqa: BLE001
                wallet_check = {"ok": False, "reason": str(exc)}
        if not wallet_check.get("ok"):
            log.warning("startup: money-out wallet check FAILED %s — "
                        "rebates degrade to dry-run", wallet_check)
        # Bound the jobs state: terminal rows older than the newest `keep`
        # are pruned (the COLD journal keeps the full settle trail). A fresh
        # boot must not inherit an unbounded HOT dict.
        pruned = self.jobs.prune() if not self.m.disabled() else 0
        resumed = self.jobs.resume_all()
        self._executor = JobExecutor(self.jobs, self._drive)
        driven = self._executor.drive() if resumed else []
        # E1: establish/refresh the self-audit baseline at boot (memory live
        # only). The baseline is what a later /house/audit/run diffs against.
        audit_status = None
        if not self.m.disabled():
            try:
                audit_status = self.auditor.audit().get("status")
            except Exception:  # noqa: BLE001 - self-audit is best-effort
                audit_status = None
        return {"wallet_ok": bool(wallet_check.get("ok")),
                "wallet_check": wallet_check,
                "resumed": len(resumed), "driven": driven,
                "pruned": pruned, "audit": audit_status}

    # ------------------------------------------------------------------ #
    # F3 — real upstream switching + retry budget (audit: the actions were
    # cosmetic — applied as plain "serve"). Now they ACT: a compiled
    # switch_upstream rotates the active upstream; a compiled retry_budget=0
    # refuses a fingerprint that has already failed this session.
    # ------------------------------------------------------------------ #
    def _active_upstream_name(self) -> str:
        """Which upstream the serve path currently uses (persisted, so a fresh
        session inherits the rotation — F3 "the policy is remembered")."""
        if self.m.disabled():
            return "primary"
        stored = self.m.get_state("active_upstream") or {}
        name = stored.get("name")
        if name in self._upstream_names():
            return name
        return "primary"

    def _set_active_upstream(self, name: str) -> None:
        if name in self._upstream_names() and not self.m.disabled():
            self.m.set_state("active_upstream", {"name": name, "since": time.time()})

    def rotate_upstream(self) -> tuple[str, str]:
        """Switch to a DIFFERENT upstream than the active one (wrap around).
        Returns (from_name, to_name). With only one upstream, this is an
        honest no-op (from == to) — the house cannot switch to nothing.

        ``secondary`` is the production ACP/external call (``do_work_secondary``);
        ``primary`` is the always-available memory brief (``do_work``). When a
        secondary is registered the registry is ["primary", "secondary"].
        """
        cur = self._active_upstream_name()
        names = self._upstream_names()
        if len(names) <= 1:
            return cur, cur
        nxt = names[(names.index(cur) + 1) % len(names)]
        self._set_active_upstream(nxt)
        return cur, nxt

    def _upstream_names(self) -> list[str]:
        names = ["primary"]
        if self._work_secondary is not None:
            names.append("secondary")
        return names

    def _run_work(self, payer: str,
                  work_fn: Optional[Callable[[str], dict[str, Any]]] = None) -> tuple[str, dict[str, Any]]:
        """Run the work on the ACTIVE upstream. Returns (upstream_name, answer).

        ``work_fn`` (default ``self._do_work``) is the primary serve body — the
        memory brief / injected work fn / the entity dossier. ``secondary`` →
        the injected ``do_work_secondary`` (the real external call in prod); a
        per-route work_fn only applies to the primary (the secondary is a
        drop-in for the primary's role).
        """
        name = self._active_upstream_name()
        fn = work_fn if work_fn is not None else self._do_work
        if name == "secondary":
            if self._work_secondary is None:  # defensive: secondary unregistered
                return "primary", fn(payer)
            return name, self._work_secondary(payer)
        return "primary", fn(payer)

    def _work_with_failover(self, payer: str,
                            work_fn: Optional[Callable[[str], dict[str, Any]]] = None) -> tuple[str, dict[str, Any]]:
        """Run the work, with real F3 failover: try the ACTIVE upstream; on
        failure, if a DIFFERENT upstream is registered, rotate to it and retry
        ONCE. Returns (upstream_name, answer). If the retried upstream also
        fails (or there is no second upstream), the exception propagates to the
        serve path, which books a scar + 502.

        This is what makes ``switch_upstream`` a genuine fix rather than a
        persisted flip: the house actively leaves a source that is failing and
        lands on one that isn't — the fresh session does not re-make the
        mistake, it escapes it.
        """
        try:
            return self._run_work(payer, work_fn)
        except Exception:
            if len(self._upstream_names()) > 1:
                _from, to = self.rotate_upstream()
                # Only retry if we actually moved to a different source.
                if to != self._active_upstream_name() or _from != to:
                    return self._run_work(payer, work_fn)
            raise

    # ---- retry budget (retry_budget=0): per-fingerprint failure memory ---- #
    def note_failed_fp(self, fp: str) -> None:
        """Record that a fingerprint just failed (retry budget spends it)."""
        if self.m.disabled():
            return
        ts = self.m.get_state("failed_fps") or {}
        ts[fp] = time.time()
        self.m.set_state("failed_fps", ts)

    def fp_has_failed(self, fp: str) -> bool:
        if self.m.disabled():
            return False
        ts = self.m.get_state("failed_fps") or {}
        return fp in ts

    def heal_fp(self, fp: str) -> None:
        """Remove a fingerprint from the failed set after a SUCCESSFUL serve —
        the route the house remembered as broken is now healthy, so
        ``retry_budget=0`` must not keep refusing it."""
        if self.m.disabled():
            return
        ts = self.m.get_state("failed_fps") or {}
        if fp in ts:
            del ts[fp]
            self.m.set_state("failed_fps", ts)

    # ------------------------------------------------------------------ #
    def _route_rule(self, route: str) -> Optional[dict]:
        """FIX-2: first active (unexpired) compiled policy rule for `route`."""
        now = time.time()
        for rule in self.scars.active_rules().values():
            match = rule.get("match") or {}
            if match.get("route") == route and float(rule.get("until", 0)) > now:
                return rule
        return None

    def _apply_scar_action(self, payer: str, row: dict, action: str,
                           fp: str) -> str:
        """FIX-2: apply a compiled rule's single action to this serve.
        Returns "refuse" (hardening blocks the serve) or "serve".

        F3 (audit: the non-refusal actions were COSMETIC — they returned plain
        "serve" and changed nothing). Now they act:
          * ``switch_upstream`` → rotate to a different upstream BEFORE the work
            (a real handoff; persisted, so the fresh session inherits it). With
            only one upstream it is an honest no-op (no second source exists).
          * ``retry_budget=0`` → if THIS fingerprint already failed this
            session, refuse (no retry) instead of burning the buyer's payment
            again on a route the house remembers as broken.
        Both still "cite the scar" via the serve path's ``scar_cited``.
        """
        if action == "prepay_required":
            # The route has a known money-failure mode: demand full prepay.
            prepay = float(row.get("prepay_usdc", 0.0) or 0.0)
            if prepay >= self.base_price:
                self._debit_prepay(payer, self.base_price,
                                   memo=f"prepay (policy {action})")
                return "serve"
            return "refuse"
        if action == "refuse_until":
            return "refuse"   # active window already checked in _route_rule
        if action == "switch_upstream":
            # A real handoff: move the work to the other upstream, then serve
            # there. The house does NOT naively re-hit the source that failed.
            self.rotate_upstream()
            return "serve"
        if action == "retry_budget=0":
            # The route has a known failure mode and this fingerprint already
            # failed once: no retry — refuse before doing the work again.
            if self.fp_has_failed(fp):
                return "refuse"
            return "serve"
        # Unknown action → fail open (serve) rather than fail closed on a
        # policy the house does not understand.
        return "serve"

    # ================================================================== #
    # The shared paid-serve pipeline (both paid intel routes must
    # run the SAME engine — trust pricing, refusals, watchtower, scar policy,
    # job state, upstream/failover, money, envelope — not one thin wrapper
    # and one dossier-only shortcut).
    # ================================================================== #
    def serve_intel(self, payer: str, params: Optional[dict] = None) -> tuple[int, dict]:
        """The paid ``/intel/quote`` serve. Returns (http_status, body).

        Thin wrapper over :meth:`_paid_serve` with the quote's defaults:
        dedup ON (a repeat is served from cache at net $0 — the F2 promise)
        and the memory brief as the work.

        Order is load-bearing (see ``_paid_serve``):
          1. refusals (banned / watchtower / risky-prepay / scar policy) all
             happen BEFORE ``jobs.start`` — a refusal is a pure read and must
             never leave a job row the executor later "settles";
          2. a repeat (already-paid fp) is served from cache BEFORE any work,
             so the F2 promise "never re-compute, never re-fail" is true in
             code — a down upstream can no longer 502 a cached answer;
          3. the job is persisted only once we are committed to NEW work, with
             a unique attempt number, so a repeat-repair never reuses (and
             resets) the original serve's settled job id.
        """
        return self._paid_serve(payer, "/intel/quote", params, self.base_price,
                                dedup=True, work=self._do_work)

    def serve_entity(self, payer: str, entity: str) -> tuple[int, dict]:
        """The paid ``/intel/entity/{name}`` serve.

        The dossier is a LIVE cross-room read: it runs the FULL engine (trust
        pricing by the payer's segment, banned/watchtower/scar-policy refusals,
        a job row for F4 kill-resume, the scar_cited envelope) but with
        **dedup OFF** — a live read is always re-read (the dossier changes as
        the house's memory changes; caching a "dated snapshot" is a lie). The
        house sells what it has: an entity it has never observed is a 404
        BEFORE any work/job (uncharged).
        """
        if self.dossier is None:
            # No cross-room assembler wired (test House): a bare room probe
            # still answers "does the house remember this at all?"
            found = (self.ledger.recall(entity) is not None
                     or self.m.get_entity("provider", entity) is not None
                     or self.m.get_entity("bond", entity) is not None
                     or any(b.get("provider") == entity or b.get("buyer") == entity
                            for b in self.m.list_entities("bond", limit=50)))
        else:
            found = self.dossier.build(entity)["found"]
        if not found:
            return 404, {"entity": entity, "found": False,
                         "note": ("no record: the house has never seen this "
                                  "wallet as a caller, provider, insurer, or "
                                  "payer."), "uncharged": True}

        def work(p: str) -> dict:
            brief = self._default_work(p)
            result = (self.dossier.build(entity)
                      if self.dossier is not None else {"entity": entity,
                                                        "found": True})
            return {**result, **brief}

        return self._paid_serve(payer, "/intel/entity", {"entity": entity},
                                self.entity_price, dedup=False, work=work)

    def _paid_serve(self, payer: str, route: str,
                    params: Optional[dict], price: float,
                    *, dedup: bool = True,
                    work: Optional[Callable[[str], dict[str, Any]]] = None,
                    ) -> tuple[int, dict]:
        """The shared paid-serve pipeline (every paid intel route runs this).

        ``price`` is the onchain base for THIS route (the settlement amount);
        the trust-segment rebate is computed against it. ``dedup`` gates the
        F2 repeat short-circuit (ON for /intel/quote, OFF for the live entity
        read). ``work`` is the serve body (default: the memory brief).
        """
        assert payer, "payer must be known (verified payload)"
        live = not self.m.disabled()
        params = params or {}
        fp = fingerprint(route, params)

        row = self.ledger.recall(payer)
        if row is None:
            row = self.ledger.on_first(payer)
        # Segment RE-DERIVED from the live counters — never the stored label,
        # which can be stale. decision()/update()/serve
        # now all read the same pure function.
        segment, mult = self.ledger.segment(row)

        # ---- banned: refuse, journaled (settlement cancelled → uncharged) --
        if segment == "banned":
            reason = self.ledger.refuse_reason(payer) or "banned wallet"
            self._journal_refusal(payer, f"banned — {reason}")
            return 403, {"error": "the house declines this wallet",
                         "house_refused": reason, "segment": "banned",
                         "house_declined": True,
                         "house": {"segment": "banned"}}

        # ---- Room 4: the watchtower — the house refuses to launder -------
        # A caller the tower calls ABORT (self-pay, funding-cluster sybil,
        # factory) is refused BEFORE settlement → genuinely uncharged, and
        # the refusal + ring are published on the verdict feed.
        #
        # The refusal is also a CALLER-ATTRIBUTABLE failure (spec
        # trust-model.md: D_CALLER_FAULT = "failure attributable to caller"):
        # the caller's own behavior is why the house declined them. Booking
        # it in the trust ledger is what lets a bad actor become risky/banned
        # through REAL request behavior — trust could only
        # ever move UP (+3/serve) from the product surface; a burner that
        # tries to launder now burns trust with every refused attempt.
        if self.watch is not None:
            refusal = self.watch.consult(payer)
            if refusal is not None:
                if live:
                    try:
                        self.ledger.update(payer, "caller_fault")
                    except Exception:  # noqa: BLE001 - trust never breaks a refusal
                        log.exception("caller_fault booking failed")
                return 403, refusal   # consult already journals + publishes

        # ---- F2: is this a repeat (fp the caller already paid for)? ------
        # Served from cache at net $0 BEFORE any work — no re-compute, no
        # re-fail, no new job row, no trust/tx bump. The scar policy does not
        # govern repeats: the buyer owns this answer; hardening protects NEW
        # work, not replay of purchased memory. DEDUP-OFF routes (the entity
        # read) skip this: a live read is always re-read.
        if dedup and live and self.dedup.is_repeat(row, fp):
            return self._serve_repeat(payer, fp)

        # ---- FIX-2: scar policy cite (NEW work only; consult compiled
        #      policy on read) ---------------------------------------------
        scar_cited = None
        switched_upstream = None  # set when a switch_upstream policy fires
        if live:
            try:
                rule = self._route_rule(route)
                if rule:
                    scar_cited = rule.get("source_scar") or rule.get("rule_id")
                    action = rule.get("action", "")
                    before = self._active_upstream_name()
                    decision = self._apply_scar_action(payer, row, action, fp)
                    after = self._active_upstream_name()
                    if action == "switch_upstream" and after != before:
                        switched_upstream = {"from": before, "to": after}
                    if decision == "refuse":
                        self._journal_refusal(payer, f"policy {action}")
                        return 403, {"error": "the house declines this wallet",
                                     "house_refused": f"policy {action}",
                                     "segment": segment,
                                     "scar_cited": scar_cited,
                                     "house_declined": True,
                                     "house": {"segment": segment}}
            except Exception:  # noqa: BLE001 - policy hardening, not a blocker
                log.exception("scar policy consult failed (continuing serve)")

        # ---- risky ×1.30: enforce as Decision.prepay ----------------------
        # BEFORE any job is started — a prepay refusal is a pure read and must
        # not leave an accepted job the executor later settles as "paid" for
        # an uncharged request. The onchain settlement is fixed
        # at base; the +30% cannot be extracted from the buyer's signature, so
        # a risky wallet must carry a prepay credit covering the surcharge, or
        # the house refuses (settlement cancelled → uncharged).
        if segment == "risky":
            surcharge = round(price * (mult - 1.0), 6)
            prepay = float(row.get("prepay_usdc", 0.0) or 0.0)
            if prepay < surcharge:
                self._journal_refusal(payer, f"prepay required ${surcharge:g}")
                return 403, {"error": "prepay required before serving",
                             "prepay_required": surcharge,
                             "prepay_on_file": prepay,
                             "segment": "risky", "decision": "prepay",
                             "house_declined": True,
                             "house": {"segment": "risky"}}
            # prepay covers it: consume the credit, serve at the surcharge price
            self._debit_prepay(payer, surcharge, "risky surcharge covered")

        # ---- F4: persist the job BEFORE the work (kill → resume, no
        #      double-serve). Unique attempt number per request key so a
        #      later repair/retry never overwrites a settled row. ----------
        jid: Optional[str] = None
        if live:
            try:
                attempt = self._next_attempt(payer, fp)
                jid = self.jobs.start(payer, route, fp,
                                      attempt=attempt, params=params)["id"]
            except Exception:  # noqa: BLE001
                log.exception("job start failed (continuing serve)")
                jid = None

        # ---- net price the house actually charges this request ------------
        net = round(price * mult, 6)

        # ---- the work (on the ACTIVE upstream; real F3 failover) ----------
        work_fn = work if work is not None else self._default_work
        work_started_on = self._active_upstream_name()
        work_upstream = work_started_on
        try:
            if jid:
                self.jobs.advance(jid, "serving", step="serve",
                                  payment_state="verified")
            work_upstream, answer = self._work_with_failover(payer, work_fn)
        except Exception as exc:  # noqa: BLE001 - F3: serve failure → scar
            failure_class = _failure_class(exc)
            scar_id: Optional[str] = None
            if live:
                try:
                    scar_id = self.scars.record(route, failure_class, str(exc))
                    self.note_failed_fp(fp)  # retry_budget spends this fingerprint
                    if jid:
                        self.jobs.advance(jid, "failed",
                                          step=f"serve failed: {failure_class}")
                except Exception:  # noqa: BLE001
                    log.exception("scar recording failed")
            return 502, {"error": "serve failed", "failure_class": failure_class,
                         "scar_id": scar_id, "upstream": work_upstream}

        # The work succeeded on the active upstream → heal the fingerprint so a
        # later retry_budget=0 consult does not refuse a now-healthy request.
        self.heal_fp(fp)

        # ---- book it ------------------------------------------------------
        standing = self.ledger.update(payer, "served", paid_usdc=net)

        # rebate owed = base (onchain settlement) − net (what we keep)
        rebate = round(price - net, 6)
        rebate_tx = None
        if rebate > 0:
            try:
                memo = f"loyalty rebate seg×{mult:g}"
                rebate_tx = self.wallet.send_usdc(payer, rebate, memo)
            except Exception:  # noqa: BLE001 - never fail a paid serve on a rebate
                log.exception("rebate send failed payer=%s amount=%s", payer, rebate)
                rebate_tx = None

        if dedup:
            self.dedup.mark_served(row, payer, fp, answer, price_usdc=price)
        # (dedup-off routes — the entity live read — write NO dedup state: no
        # cache, no fp on the caller row, no hit counters. A live read is
        # re-read, never replayed.)

        # re-read so standing reflects EVERY write in this request
        standing = self.ledger.recall(payer) or standing

        if jid:
            self.jobs.settle(jid, payer)  # idempotent — the double-charge killer

        # ---- envelope: shows what was actually charged ---------------------
        body: dict[str, Any] = {
            "cached": False,
            "caller": payer,
            "standing": standing,
            "segment_price": net,
            "mult_applied": mult,
            "paid_usdc": price,  # the onchain settlement (base)
            "rebate_usdc": rebate,
            "rebate_tx": rebate_tx,
            "upstream": work_upstream,
            "house": {"segment": standing.get("segment"),
                      "trust_score": standing.get("trust_score"),
                      "repeat_of": None},
        }
        body.update(answer)
        if scar_cited:
            body["scar_cited"] = scar_cited
        if switched_upstream is None and work_upstream != work_started_on:
            # The work started on one upstream and finished on another — an
            # in-flight failover (the active source failed mid-serve and the
            # house escaped it). Surface it the same way as a policy switch.
            switched_upstream = {"from": work_started_on, "to": work_upstream}
        if switched_upstream:
            body["switched_upstream"] = switched_upstream
        return 200, body

    def _next_attempt(self, payer: str, fp: str) -> int:
        """Next attempt number for (caller, route, fp).

        Scans the live job rows for the same request key and returns
        max(attempt)+1 (or 1 when none exist). Because ``job_id`` embeds the
        attempt, every request against the same fp gets its own job row —
        the original serve keeps its settled history and a repair/retry
        (e.g. a repeat whose cache file was wiped) can never reset it.
        """
        best = 0
        for job in self.jobs.snapshot(limit=500):
            if job.get("caller") == payer and job.get("fp") == fp:
                try:
                    best = max(best, int(job.get("attempt", 1)))
                except (TypeError, ValueError):
                    continue
        return best + 1

    def _serve_repeat(self, payer: str, fp: str) -> tuple[int, dict]:
        """F2 repeat: the caller already bought this answer — serve it from
        cache at net $0, charge 0 work, and honor the promise in code.

        * cache HIT  → served with NO ``_do_work`` invocation (compute really
          avoided; the money counter only claims what it saved);
        * cache MISS (file wiped but the fp is still on the caller row — the
          row is the promise, the disk file is an optimization) → the work is
          re-run once under a NEW job attempt (never reusing the original
          settled row's id), re-stored, still net $0, and no trust/tx bump.

        A repeat settles base onchain (the middleware settles every 200) and
        the house rebates the FULL base back — net $0 for the caller, exactly
        one settlement tx on the original serve's job history.
        """
        cached = self.dedup.load(fp)
        served_from_cache = cached is not None
        answer = cached

        jid: Optional[str] = None
        if not served_from_cache:
            # Rare repair: re-run the work once, under a fresh attempt id.
            live = not self.m.disabled()
            if live:
                try:
                    attempt = self._next_attempt(payer, fp)
                    jid = self.jobs.start(payer, "/intel/quote", fp,
                                          attempt=attempt,
                                          params={"repeat_repair": True})["id"]
                except Exception:  # noqa: BLE001
                    log.exception("job start failed (repeat repair)")
                    jid = None
            try:
                if jid:
                    self.jobs.advance(jid, "serving", step="serve",
                                      payment_state="verified")
                answer = self._do_work(payer)
            except Exception as exc:  # noqa: BLE001
                # No cached copy AND the work is down: nothing to serve. The
                # buyer is uncharged (>=400 cancels settlement); this books a
                # scar so the route hardens instead of failing forever.
                failure_class = _failure_class(exc)
                scar_id: Optional[str] = None
                if not self.m.disabled():
                    try:
                        scar_id = self.scars.record(
                            "/intel/quote", failure_class, str(exc))
                        if jid:
                            self.jobs.advance(jid, "failed",
                                              step=f"repeat repair failed: {failure_class}")
                    except Exception:  # noqa: BLE001
                        log.exception("scar recording failed")
                return 502, {"error": "serve failed (repeat repair)",
                             "failure_class": failure_class,
                             "scar_id": scar_id}

        # ---- book it: dedup only — no trust / tx_count / served bump ------
        standing = self.ledger.note_dedup(payer)

        # Full base rebate: net $0 to a caller who already bought this.
        rebate = round(self.base_price, 6)
        rebate_tx = None
        try:
            rebate_tx = self.wallet.send_usdc(payer, rebate, "repeat refund")
        except Exception:  # noqa: BLE001 - never fail a paid serve on a rebate
            log.exception("repeat rebate send failed payer=%s amount=%s",
                          payer, rebate)
            rebate_tx = None

        # compute_avoided is TRUE only when no work ran — the counter is not
        # a lie.
        self.dedup.note_repeat(price_usdc=self.base_price,
                               compute_avoided=served_from_cache)

        if answer is not None and not served_from_cache:
            # Re-store the repaired answer under the same fp.
            self.dedup.store(fp, answer)

        if jid:
            self.jobs.settle(jid, payer)

        # re-read so standing reflects the dedup hit in this request
        standing = self.ledger.recall(payer) or standing

        self.m.write_event(
            f"repeat {payer} served from cache net $0 "
            f"(compute {'avoided' if served_from_cache else 're-ran'})",
            kind="repeat")

        body: dict[str, Any] = {
            "cached": True,
            "caller": payer,
            "standing": standing,
            "segment_price": 0.0,       # net charged: $0
            "mult_applied": 0.0,
            "paid_usdc": self.base_price,  # the onchain settlement (base)
            "rebate_usdc": rebate,
            "rebate_tx": rebate_tx,
            "repeat_of": fp,
            "house": {"segment": standing.get("segment"),
                      "trust_score": standing.get("trust_score"),
                      "repeat_of": fp},
        }
        if answer is not None:
            body.update(answer)
        return 200, body

    def _journal_refusal(self, payer: str, why: str) -> None:
        """COLD-journal every refusal (kind=refuse). Banned /
        risky / policy refusals returned 403 but never wrote the event the
        spec requires ("Journal it") — only the watchtower did."""
        if self.m.disabled():
            return
        try:
            self.m.write_event(f"refused {payer}: {why}", kind="refuse")
        except Exception:  # noqa: BLE001 - journaling never breaks a refusal
            log.exception("refusal journal failed")

    # ------------------------------------------------------------------ #
    def _debit_prepay(self, payer: str, usdc: float, memo: str) -> None:
        row = self.m.get_entity("caller", payer) or {}
        new_prepay = round(float(row.get("prepay_usdc", 0.0) or 0.0) - usdc, 6)
        row["prepay_usdc"] = max(new_prepay, 0.0)
        self.m.set_entity("caller", payer, row)
        self.m.write_event(f"prepay debit {payer} {usdc:g}USDC ({memo})",
                           kind="prepay")

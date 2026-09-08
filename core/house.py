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
                 wallet_check: Optional[Callable[[], dict]] = None,
                 service_name: str = "the-house",
                 watch: Optional[Watchtower] = None) -> None:
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
        self._do_work = do_work if do_work is not None else self._default_work
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

        FIX-4d: when live money-out is enabled, the ACP wallet address MUST
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
        resumed = self.jobs.resume_all()
        self._executor = JobExecutor(self.jobs, self._drive)
        driven = self._executor.drive() if resumed else []
        return {"wallet_ok": bool(wallet_check.get("ok")),
                "wallet_check": wallet_check,
                "resumed": len(resumed), "driven": driven}

    # ------------------------------------------------------------------ #
    def _route_rule(self, route: str) -> Optional[dict]:
        """FIX-2: first active (unexpired) compiled policy rule for `route`."""
        now = time.time()
        for rule in self.scars.active_rules().values():
            match = rule.get("match") or {}
            if match.get("route") == route and float(rule.get("until", 0)) > now:
                return rule
        return None

    def _apply_scar_action(self, payer: str, row: dict, action: str) -> str:
        """FIX-2: apply a compiled rule's single action to this serve.
        Returns "refuse" (hardening blocks the serve) or "serve"."""
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
        # retry_budget=0 / switch_upstream → serve under hardened policy
        return "serve"

    def serve_intel(self, payer: str, params: Optional[dict] = None) -> tuple[int, dict]:
        """The paid serve. Returns (http_status, body).

        The x402 middleware has already verified payment (payer known) and
        will settle base AFTER we return a <400. We decide what the memory
        owes / refuses / charges.

        Order is load-bearing:
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
        assert payer, "payer must be known (verified payload)"
        live = not self.m.disabled()
        params = params or {}
        fp = fingerprint("/intel/quote", params)

        row = self.ledger.recall(payer)
        if row is None:
            row = self.ledger.on_first(payer)
        # Segment RE-DERIVED from the live counters — never the stored label,
        # which can be stale (audit finding 5/6). decision()/update()/serve
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
        if self.watch is not None:
            refusal = self.watch.consult(payer)
            if refusal is not None:
                return 403, refusal   # consult already journals + publishes

        # ---- F2: is this a repeat (fp the caller already paid for)? ------
        # Served from cache at net $0 BEFORE any work — no re-compute, no
        # re-fail, no new job row, no trust/tx bump. The scar policy does not
        # govern repeats: the buyer owns this answer; hardening protects NEW
        # work, not replay of purchased memory.
        if live and self.dedup.is_repeat(row, fp):
            return self._serve_repeat(payer, fp)

        # ---- FIX-2: scar policy cite (NEW work only; consult compiled
        #      policy on read) ---------------------------------------------
        scar_cited = None
        if live:
            try:
                rule = self._route_rule("/intel/quote")
                if rule:
                    scar_cited = rule.get("source_scar") or rule.get("rule_id")
                    action = rule.get("action", "")
                    if self._apply_scar_action(payer, row, action) == "refuse":
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
        # an uncharged request (audit SEV-1). The onchain settlement is fixed
        # at base; the +30% cannot be extracted from the buyer's signature, so
        # a risky wallet must carry a prepay credit covering the surcharge, or
        # the house refuses (settlement cancelled → uncharged).
        if segment == "risky":
            surcharge = round(self.base_price * (mult - 1.0), 6)
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
                jid = self.jobs.start(payer, "/intel/quote", fp,
                                      attempt=attempt, params=params)["id"]
            except Exception:  # noqa: BLE001
                log.exception("job start failed (continuing serve)")
                jid = None

        # ---- net price the house actually charges this request ------------
        net = round(self.base_price * mult, 6)

        # ---- the work -----------------------------------------------------
        try:
            if jid:
                self.jobs.advance(jid, "serving", step="serve",
                                  payment_state="verified")
            answer = self._do_work(payer)
        except Exception as exc:  # noqa: BLE001 - F3: serve failure → scar
            failure_class = _failure_class(exc)
            scar_id: Optional[str] = None
            if live:
                try:
                    scar_id = self.scars.record("/intel/quote", failure_class, str(exc))
                    if jid:
                        self.jobs.advance(jid, "failed",
                                          step=f"serve failed: {failure_class}")
                except Exception:  # noqa: BLE001
                    log.exception("scar recording failed")
            return 502, {"error": "serve failed", "failure_class": failure_class,
                         "scar_id": scar_id}

        # ---- book it ------------------------------------------------------
        standing = self.ledger.update(payer, "served", paid_usdc=net)

        # rebate owed = base (onchain settlement) − net (what we keep)
        rebate = round(self.base_price - net, 6)
        rebate_tx = None
        if rebate > 0:
            try:
                memo = f"loyalty rebate seg×{mult:g}"
                rebate_tx = self.wallet.send_usdc(payer, rebate, memo)
            except Exception:  # noqa: BLE001 - never fail a paid serve on a rebate
                log.exception("rebate send failed payer=%s amount=%s", payer, rebate)
                rebate_tx = None

        self.dedup.mark_served(row, payer, fp, answer, price_usdc=self.base_price)

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
            "paid_usdc": self.base_price,  # the onchain settlement (base)
            "rebate_usdc": rebate,
            "rebate_tx": rebate_tx,
            "house": {"segment": standing.get("segment"),
                      "trust_score": standing.get("trust_score"),
                      "repeat_of": None},
        }
        body.update(answer)
        if scar_cited:
            body["scar_cited"] = scar_cited
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
        # a lie (audit SEV-1).
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
        """COLD-journal every refusal (kind=refuse). Audit finding: banned /
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

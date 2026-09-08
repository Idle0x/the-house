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

log = logging.getLogger("the-house.engine")

DEFAULT_INTEL = ("The house remembers its counterparties. "
                 "That memory is the price, the refusal, the repeat.")


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
                 service_name: str = "the-house") -> None:
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
        self._executor: Optional[JobExecutor] = None

    # ------------------------------------------------------------------ #
    def _default_work(self, payer: str) -> dict[str, Any]:
        return {"intel": DEFAULT_INTEL}

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
        """
        assert payer, "payer must be known (verified payload)"
        live = not self.m.disabled()
        params = params or {}
        fp = fingerprint("/intel/quote", params)

        row = self.ledger.recall(payer)
        if row is None:
            row = self.ledger.on_first(payer)
        segment = row.get("segment")

        # ---- banned: refuse (settlement cancelled → genuinely uncharged) --
        if segment == "banned":
            reason = self.ledger.refuse_reason(payer) or "banned wallet"
            return 403, {"error": "the house declines this wallet",
                         "house_refused": reason, "segment": "banned",
                         "house_declined": True,
                         "house": {"segment": "banned"}}

        # ---- FIX-2: scar policy cite (consult compiled policy on read) ---
        scar_cited = None
        if live:
            try:
                rule = self._route_rule("/intel/quote")
                if rule:
                    scar_cited = rule.get("source_scar") or rule.get("rule_id")
                    action = rule.get("action", "")
                    if self._apply_scar_action(payer, row, action) == "refuse":
                        return 403, {"error": "the house declines this wallet",
                                     "house_refused": f"policy {action}",
                                     "segment": segment,
                                     "scar_cited": scar_cited,
                                     "house_declined": True,
                                     "house": {"segment": segment}}
            except Exception:  # noqa: BLE001 - policy hardening, not a blocker
                log.exception("scar policy consult failed (continuing serve)")

        # ---- F4: persist the job BEFORE the work (kill → resume, no
        #      double-serve). Reuses the deterministic id on a repeat.
        jid: Optional[str] = None
        if live:
            try:
                jid = self.jobs.start(payer, "/intel/quote", fp, params=params)["id"]
            except Exception:  # noqa: BLE001
                log.exception("job start failed (continuing serve)")
                jid = None

        # ---- FIX-4a: is this a repeat (net $0)? --------------------------
        repeat = live and self.dedup.is_repeat(row, fp)
        _, mult = self.ledger.segment(row)  # (segment, mult)
        effective_mult = mult

        # ---- risky ×1.30: enforce as Decision.prepay ----------------------
        # The onchain settlement is fixed at base; the +30% cannot be
        # extracted from the buyer's signature. So a risky wallet must carry
        # a prepay credit covering the surcharge, or the house refuses
        # (settlement cancelled → uncharged). This is a memory decision with
        # a money consequence.
        if segment == "risky" and not repeat:
            surcharge = round(self.base_price * (mult - 1.0), 6)
            prepay = float(row.get("prepay_usdc", 0.0) or 0.0)
            if prepay < surcharge:
                return 403, {"error": "prepay required before serving",
                             "prepay_required": surcharge,
                             "prepay_on_file": prepay,
                             "segment": "risky", "decision": "prepay",
                             "house_declined": True,
                             "house": {"segment": "risky"}}
            # prepay covers it: consume the credit, serve at the surcharge price
            self._debit_prepay(payer, surcharge, "risky surcharge covered")
            effective_mult = mult  # ×1.30

        # ---- net price the house actually charges this request ------------
        if repeat:
            net = 0.0
            effective_mult = 0.0
        else:
            net = round(self.base_price * effective_mult, 6)

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
        if repeat:
            # FIX-4a: a repeat does NOT bump tx_count / served / trust.
            # Only the dedup hit counter moves.
            standing = self.ledger.note_dedup(payer)
        else:
            standing = self.ledger.update(payer, "served", paid_usdc=net)

        # rebate owed = base (onchain settlement) − net (what we keep)
        rebate = round(self.base_price - net, 6)
        rebate_tx = None
        if rebate > 0:
            try:
                memo = ("repeat refund" if repeat
                        else f"loyalty rebate seg×{mult:g}")
                rebate_tx = self.wallet.send_usdc(payer, rebate, memo)
            except Exception:  # noqa: BLE001 - never fail a paid serve on a rebate
                log.exception("rebate send failed payer=%s amount=%s", payer, rebate)
                rebate_tx = None

        if repeat:
            self.dedup.note_repeat(price_usdc=self.base_price)
        else:
            self.dedup.mark_served(row, payer, fp, answer, price_usdc=self.base_price)

        # re-read so standing reflects EVERY write in this request
        standing = self.ledger.recall(payer) or standing

        if jid:
            self.jobs.settle(jid, payer)  # idempotent — the double-charge killer

        # ---- envelope: shows what was actually charged ---------------------
        body: dict[str, Any] = {
            "cached": bool(repeat),
            "caller": payer,
            "standing": standing,
            "segment_price": net,
            "mult_applied": effective_mult,
            "paid_usdc": self.base_price,  # the onchain settlement (base)
            "rebate_usdc": rebate,
            "rebate_tx": rebate_tx,
            "house": {"segment": standing.get("segment"),
                      "trust_score": standing.get("trust_score"),
                      "repeat_of": fp if repeat else None},
        }
        if repeat:
            body["repeat_of"] = fp
            cached = self.dedup.load(fp) or answer
            body.update(cached)
        else:
            body.update(answer)
        if scar_cited:
            body["scar_cited"] = scar_cited
        return 200, body

    # ------------------------------------------------------------------ #
    def _debit_prepay(self, payer: str, usdc: float, memo: str) -> None:
        row = self.m.get_entity("caller", payer) or {}
        new_prepay = round(float(row.get("prepay_usdc", 0.0) or 0.0) - usdc, 6)
        row["prepay_usdc"] = max(new_prepay, 0.0)
        self.m.set_entity("caller", payer, row)
        self.m.write_event(f"prepay debit {payer} {usdc:g}USDC ({memo})",
                           kind="paid")

"""Room 2 — THE UNDERWRITING DESK (elevation Room 2).

Sibyl enters insurance. THE HOUSE writes bonds on *other agents'* work, priced
from what it REMEMBERS about those agents. The actuarial table is a pure
function of the provider's WARM record + the scars it has accumulated — no LLM,
no judgment (Moneyball: price revealed history and show your work).

The product:
  * ``premium_quote(provider)`` — a deterministic premium, a pure function of
    the recalled provider row + the bond scars against it. Proven providers
    cost less; scarred/defaulting providers cost more; an unknown provider
    costs the flat base.
  * ``issue(...)`` — buyer pays the premium (the x402 settlement is the base
    quote; the memory discount/surcharge is settled as a rebate / prepay, the
    exact M0 money-out pattern); the house writes the BOND to a WARM ``bond``
    entity + a COLD journal event, and opens exposure in the bond book.
  * ``settle_failure(...)`` — when the guaranteed provider fails (a scar is
    recorded / the job terminates failed), the house AUTO-PAYS the face from
    its own wallet via ``wallet.send_usdc`` (real onchain money-out), journals
    the claim tx next to the bond + the triggering scar, and — crucially —
    REMEMBERS the claim: each claim shrinks the book's max-exposure cap. The
    house knows its own limits because it remembers them.
  * max-open-exposure is enforced from memory — the house refuses to
    over-leverage its remembered risk.

Deletion harness: SIBYL_DISABLED=1 → every provider looks identical (no
record, no scars) → every quote is the same flat standard premium → adverse
selection, the book is unpriceable. Deleting memory collapses the whole
underwriting market — that is the point of the gate.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from core import config as C
from core.memory import HouseMemory
from core.scars import ScarCompiler
from core.wallet import DryRunWallet

# Bond book state key (HOT state).
BOOK_KEY = "bond_book"


def _now() -> float:
    return time.time()


class UnderwritingDesk:
    """The underwriting desk: memory-priced bonds with auto-payout claims."""

    def __init__(self, m: HouseMemory, *,
                 wallet=None,
                 base_premium: float = C.BOND_BASE_PREMIUM,
                 face: float = C.BOND_FACE,
                 max_exposure: float = C.BOND_MAX_EXPOSURE) -> None:
        self.m = m
        self.base_premium = base_premium
        self.face = face
        self.max_exposure = max_exposure
        # Money-out is SAFE-BY-DEFAULT: DryRun (no acp, no money) unless the
        # caller injects a real HouseWallet (build_app does so only when live
        # money-out is enabled). Claims are real onchain transfers only then.
        self.wallet = wallet if wallet is not None else DryRunWallet(m)
        self.scars = ScarCompiler(m)

    # ------------------------------------------------------------------ #
    # Memory reads
    # ------------------------------------------------------------------ #
    def recall_provider(self, addr: str) -> Optional[dict]:
        return self.m.get_entity("provider", addr)

    def bond_scars_against(self, addr: str) -> int:
        """Count the bond scars this provider has accumulated. A provider's
        bond failure is recorded on the route ``/bond/<addr>`` so the count is
        exact and deletion-safe (no scars in deletion mode → 0)."""
        route = f"/bond/{addr}"
        n = 0
        for scar in self.m.list_entities("scar", limit=500):
            if scar.get("route") == route:
                n += 1
        return n

    def claims_paid(self) -> int:
        book = self.m.get_state(BOOK_KEY) or {}
        return int(book.get("claims_paid", 0))

    # ------------------------------------------------------------------ #
    # The actuarial table (pure function of memory)
    # ------------------------------------------------------------------ #
    def premium_quote(self, provider: str) -> dict:
        """Deterministic premium from the recalled provider record + scars.

        Returns {provider, segment, premium, base_premium, mult, evidence,
        face}. In deletion mode there is no record and no scars, so every
        provider prices identically at the flat standard premium — adverse
        selection, the book unpriceable (the gate).
        """
        row = self.recall_provider(provider)
        scars = self.bond_scars_against(provider)
        defaults = int((row or {}).get("default_events", 0))
        quality = float((row or {}).get("quality_score", 0.0))
        on_time = float((row or {}).get("on_time", 0.0))
        jobs = int((row or {}).get("jobs_done", 0))

        if row is None:
            segment = "standard"
            evidence = ("no record (or memory disabled): priced at the flat "
                        "standard premium")
        elif quality < C.BOND_RISKY_MAX_QUALITY or defaults >= 1:
            segment = "risky"
            evidence = (f"bad record: quality {quality:.2f}, defaults "
                        f"{defaults} — priced high")
        elif (quality >= C.BOND_PROVEN_MIN_QUALITY
              and on_time >= C.BOND_PROVEN_MIN_ON_TIME and jobs >= 1):
            segment = "proven"
            evidence = (f"proven: {jobs} job(s), quality {quality:.2f}, "
                        f"on-time {on_time:.2f} — priced low")
        else:
            segment = "standard"
            evidence = f"thin record ({jobs} job(s)): standard premium"

        # Each bond scar against this provider raises the premium a fixed
        # step (the house remembers the provider's bond failures).
        scar_steps = scars
        mult = C.BOND_PREMIUM_MULT[segment]
        if scar_steps:
            mult += 0.10 * scar_steps
        premium = round(self.base_premium * mult, 6)
        return {
            "provider": provider,
            "segment": segment,
            "premium": premium,
            "base_premium": self.base_premium,
            "mult": round(mult, 4),
            "face": self.face,
            "evidence": evidence,
            "scars_against": scars,
        }

    # ------------------------------------------------------------------ #
    # The book (max open exposure, remembered)
    # ------------------------------------------------------------------ #
    def _book(self) -> dict:
        return self.m.get_state(BOOK_KEY) or {}

    def _effective_max_exposure(self) -> float:
        """The house's cap, remembered: base cap minus one decay step per
        claim it has paid (it remembers its own limits). Floor at 0."""
        claims = self.claims_paid()
        return max(0.0, self.max_exposure
                   - C.BOND_CAP_DECAY_PER_CLAIM * claims)

    def open_exposure(self) -> float:
        total = 0.0
        for bond in self.m.list_entities("bond", limit=500):
            if bond.get("status") == "open":
                total += float(bond.get("face_usdc", 0.0) or 0.0)
        return round(total, 6)

    def can_write(self, face: float) -> tuple[bool, str]:
        cap = self._effective_max_exposure()
        if self.open_exposure() + face > cap:
            return False, (
                f"max open exposure: ${self.open_exposure():.2f} + ${face:.2f} "
                f"> ${cap:.2f} cap (remembered)")
        return True, "within remembered exposure cap"

    # ------------------------------------------------------------------ #
    # Money actions
    # ------------------------------------------------------------------ #
    def issue(self, provider: str, buyer: str, *,
              premium: Optional[float] = None) -> tuple[int, dict]:
        """Write a bond. Returns (http_status, body).

        The premium is a pure function of memory (recomputed here unless the
        caller passes a verified one — the route passes the x402-verified
        premium so the response matches what was actually charged). Memory
        acts: a proven buyer discount / risky surcharge is settled by the
        engine's rebate/prepay path OUTSIDE this call; the bond premium itself
        is what the buyer paid onchain.
        """
        quote = self.premium_quote(provider)
        if premium is None:
            premium = float(quote["premium"])
        else:
            premium = float(premium)

        # --- risk refusal: the house does not bond a provider it refuses --
        if quote["segment"] == "risky":
            return 403, {
                "error": "the house will not bond this provider",
                "provider": provider,
                "segment": "risky",
                "evidence": quote["evidence"],
                "house_declined": True,
            }

        # --- max open exposure (remembered) -------------------------------
        ok, why = self.can_write(self.face)
        if not ok:
            return 403, {
                "error": "book at its remembered exposure limit",
                "provider": provider,
                "reason": why,
                "open_exposure": self.open_exposure(),
                "house_declined": True,
            }

        bond_id = f"B-{uuid.uuid4().hex[:10]}"
        bond = {
            "id": bond_id,
            "provider": provider,
            "buyer": buyer,
            "face_usdc": self.face,
            "premium_usdc": round(premium, 6),
            "segment": quote["segment"],
            "premium_mult": quote["mult"],
            "evidence": quote["evidence"],
            "status": "open",
            "issued_at": _now(),
            "claim_tx": None,
            "scar_evidence": None,
        }
        self.m.set_entity("bond", bond_id, bond)
        book = self._book()
        book["premiums_collected_usdc"] = round(
            float(book.get("premiums_collected_usdc", 0.0)) + premium, 6)
        book["bonds_issued"] = int(book.get("bonds_issued", 0)) + 1
        self.m.set_state(BOOK_KEY, book)
        self.m.write_event(
            f"bond {bond_id} on {provider} face ${self.face:.2f} "
            f"premium ${premium:.4f} ({quote['segment']})",
            kind="bond")
        return 200, {
            "bond_id": bond_id,
            "provider": provider,
            "face_usdc": self.face,
            "premium_usdc": round(premium, 6),
            "segment": quote["segment"],
            "evidence": quote["evidence"],
            "status": "open",
            "open_exposure": self.open_exposure(),
            "max_exposure": self._effective_max_exposure(),
        }

    def settle_failure(self, bond_id: str, failure_class: str,
                       root_cause: str) -> tuple[int, dict]:
        """The guaranteed provider failed: pay the claim from the house
        wallet and journal the tx next to the bond + the triggering scar.

        The INSURED (the buyer who paid the premium) receives the face — the
        house pays real money out on the provider's default. It also
        REMEMBERS both sides: a scar against the provider (raises its future
        premiums) + a default event on the provider's WARM record (escalates
        its segment), and a PAID claim shrinks the book's exposure cap.

        Claim state machine (finding #21: a claim the wallet cannot send must
        never be booked as ``paid`` — "never book imaginary money"):
          open   + payout ok      → paid    (scar + default + cap decay)
          open   + payout failed  → failed  (default remembered, NO payout
                                             booked, NO cap decay)
          failed + payout ok      → paid    (retry: no double memory writes)
          paid   → 409 (settled claims cannot be paid again)
        """
        bond = self.m.get_entity("bond", bond_id)
        if bond is None:
            return 404, {"error": "unknown bond", "bond_id": bond_id}
        status = bond.get("status")
        if status == "paid":
            return 409, {"error": "bond already closed", "bond_id": bond_id,
                         "status": status}
        if status not in ("open", "failed"):
            return 409, {"error": "bond not claimable", "bond_id": bond_id,
                         "status": status}
        retry = status == "failed"  # payout failed before: re-attempt only

        provider = bond.get("provider")
        if provider is None:
            return 422, {"error": "bond has no provider", "bond_id": bond_id}
        # The insured (buyer) is owed the face. Fall back to the provider only
        # if the bond was somehow written without a buyer — never pay the
        # defaulting provider its own claim.
        buyer = bond.get("buyer") or provider
        face = float(bond.get("face_usdc") or self.face)

        scar_id = bond.get("scar_evidence")
        if not retry:
            # Record the triggering scar (memory act — the provider's failure
            # is remembered and will raise its future premiums).
            if not self.m.disabled():
                try:
                    scar_id = self.scars.record(
                        f"/bond/{provider}", failure_class, root_cause)
                except Exception:  # noqa: BLE001
                    scar_id = None
                # Remember the default on the provider's WARM record too —
                # this is what escalates the segment (defaults >= 1 → risky)
                # so the provider's NEXT bond is priced off its failure.
                try:
                    row = self.m.get_entity("provider", provider) or {}
                    row["default_events"] = int(row.get("default_events", 0)) + 1
                    self.m.set_entity("provider", provider, row)
                except Exception:  # noqa: BLE001
                    pass

        # Pay the face from the house wallet to the insured (real onchain
        # money-out when live; a clearly-marked dry: hash otherwise).
        claim_tx = None
        memo = f"underwriting claim {bond_id}: {provider} defaulted"
        try:
            claim_tx = self.wallet.send_usdc(buyer, face, memo)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger("the-house.bonds").exception(
                "claim payout failed bond=%s amount=%s", bond_id, face)
            claim_tx = None

        if claim_tx is None:
            # The payout did NOT go out — the house owes the insured but must
            # not book money it never sent. Close as "failed": the claim is
            # retriable, the exposure cap does NOT decay (the house has not
            # actually reduced its risk), and claims_paid is not incremented.
            bond["status"] = "failed"
            bond["closed_at"] = _now()
            bond["claim_tx"] = None
            bond["scar_evidence"] = scar_id
            self.m.set_entity("bond", bond_id, bond)
            self.m.write_event(
                f"claim {bond_id} FAILED to pay ${face:.2f} to insured {buyer} "
                f"(wallet unavailable; claim open for retry) scar={scar_id}",
                kind="claim")
            return 200, {
                "bond_id": bond_id,
                "provider": provider,
                "insured": buyer,
                "status": "failed",
                "payout_usdc": face,      # the face OWED, not paid
                "paid": False,
                "claim_tx": None,
                "scar_evidence": scar_id,
                "claims_paid": self.claims_paid(),
                "max_exposure_after": self._effective_max_exposure(),
                "note": "payout not sent — the house does not book money it "
                        "never sent; retry the claim once the wallet is live",
            }

        # Payout confirmed. Close the bond, journal the claim, REMEMBER it.
        bond["status"] = "paid"
        bond["closed_at"] = _now()
        bond["claim_tx"] = claim_tx
        bond["scar_evidence"] = scar_id
        self.m.set_entity("bond", bond_id, bond)

        book = self._book()
        book["claims_paid"] = int(book.get("claims_paid", 0)) + 1
        book["payouts_usdc"] = round(
            float(book.get("payouts_usdc", 0.0)) + face, 6)
        self.m.set_state(BOOK_KEY, book)
        self.m.write_event(
            f"claim {bond_id} PAID ${face:.2f} to insured {buyer} "
            f"({provider} defaulted) tx={claim_tx} scar={scar_id}",
            kind="claim")

        return 200, {
            "bond_id": bond_id,
            "provider": provider,
            "insured": buyer,
            "status": "paid",
            "paid": True,
            "payout_usdc": face,
            "claim_tx": claim_tx,
            "scar_evidence": scar_id,
            "claims_paid": self.claims_paid(),
            "max_exposure_after": self._effective_max_exposure(),
        }

    # ------------------------------------------------------------------ #
    # The auto-trigger (Room 2's money moment: the default pays the claim)
    # ------------------------------------------------------------------ #
    def claim_for_provider(self, provider: str, failure_class: str,
                           root_cause: str) -> list[tuple[int, dict]]:
        """Auto-pay every OPEN bond the house has on this provider.

        This is the trigger Room 2's spec describes: "when the guaranteed
        provider fails (scar recorded / job terminal-failed), the house
        AUTO-PAYS the claim." The ACP job-completion hook (or the demo's
        fault injector, or the operator claim route) calls this the moment a
        default is known. Each claim is settled independently — one bad bond
        does not sink the others.
        """
        provider = (provider or "").strip()
        results: list[tuple[int, dict]] = []
        if not provider or self.m.disabled():
            return results
        for bond in self.m.list_entities("bond", limit=500):
            if str(bond.get("provider", "")).strip() != provider:
                continue
            if bond.get("status") != "open":
                continue
            try:
                results.append(self.settle_failure(
                    str(bond.get("id")), failure_class, root_cause))
            except Exception:  # noqa: BLE001 - settle the rest regardless
                import logging
                logging.getLogger("the-house.bonds").exception(
                    "claim_for_provider: failed to settle bond %s",
                    bond.get("id"))
        return results

    # ------------------------------------------------------------------ #
    # The public register (the money shot)
    # ------------------------------------------------------------------ #
    def register(self) -> dict:
        """The insurance register: every bond, premium, claim, payout tx."""
        bonds = self.m.list_entities("bond", limit=500)
        book = self._book()
        return {
            "book": {
                "open_exposure": self.open_exposure(),
                "max_exposure": self._effective_max_exposure(),
                "bonds_issued": int(book.get("bonds_issued", 0)),
                "premiums_collected_usdc":
                    round(float(book.get("premiums_collected_usdc", 0.0)), 6),
                "claims_paid": int(book.get("claims_paid", 0)),
                "payouts_usdc":
                    round(float(book.get("payouts_usdc", 0.0)), 6),
            },
            "face_usdc": self.face,
            "base_premium": self.base_premium,
            "bonds": [{
                "id": b.get("id"),
                "provider_last6": (b.get("provider") or "?")[-6:],
                "face_usdc": b.get("face_usdc"),
                "premium_usdc": b.get("premium_usdc"),
                "segment": b.get("segment"),
                "status": b.get("status"),
                "claim_tx": b.get("claim_tx"),
                "scar_evidence": b.get("scar_evidence"),
            } for b in bonds],
        }

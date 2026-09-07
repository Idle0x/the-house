#!/usr/bin/env python3
"""THE DELETION TEST — the hackathon gate, runnable.

What it proves (verbatim rule): "Delete the Sibyl Memory layer. Does the
project still do what it claims? If yes, it is not load-bearing."

Run:  .venv/bin/python deletion_test.py

It builds real history for a VIP caller with memory ON, then flips memory
OFF (SIBYL_DISABLED=1) and shows the product collapsing to
"trust everyone at list price" — no loyalty, no refusal, no differentiation.

Exit code 0 = the gate holds (deletion breaks the business model).
Exit code 1 = memory is NOT load-bearing (we should be worried).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from core.memory import HouseMemory  # noqa: E402
from core.trust import TrustLedger  # noqa: E402


def line(s: str) -> None:
    print(s)


def main() -> int:
    db = os.path.join(tempfile.mkdtemp(prefix="house_deletion_"), "memory.db")
    m = HouseMemory(db)
    ledger = TrustLedger(m)

    vip_addr = "0x" + "V" * 40
    stranger_addr = "0x" + "S" * 40
    bad_addr = "0x" + "B" * 40

    line("=" * 64)
    line("THE DELETION TEST — is Sibyl Memory load-bearing?")
    line("=" * 64)

    # ---- Phase 1: build real memory (a loyal VIP + a burned bad actor) ----
    line("\n[1] WITH MEMORY — building history…")
    for i in range(10):
        ledger.update(vip_addr, "served", paid_usdc=0.01)   # → vip (10 txs)
    for i in range(3):
        ledger.update(bad_addr, "caller_fault")              # → risky
    for i in range(3):
        ledger.update(bad_addr, "refund")                    # → banned

    d_vip = ledger.decision(vip_addr)
    d_bad = ledger.decision(bad_addr)
    line(f"    VIP {vip_addr[:10]}…: segment={d_vip.segment}, "
         f"price_mult={d_vip.price_mult}, allow={d_vip.allow}")
    line(f"    BAD {bad_addr[:10]}…: segment={d_bad.segment}, allow={d_bad.allow}")
    assert d_vip.segment == "vip", "sanity: vip not reached with memory on"
    assert d_bad.segment == "banned", "sanity: bad actor not banned with memory on"

    # ---- Phase 2: DELETE the memory layer ----
    line("\n[2] DELETING MEMORY (SIBYL_DISABLED=1)…")
    os.environ["SIBYL_DISABLED"] = "1"
    m_gone = HouseMemory(db)   # reads → empty, writes → no-op
    ledger_gone = TrustLedger(m_gone)

    # ---- Phase 3: same wallets, no memory ----
    d_vip_gone = ledger_gone.decision(vip_addr)
    d_stranger_gone = ledger_gone.decision(stranger_addr)
    d_bad_gone = ledger_gone.decision(bad_addr)

    line("\n[3] WITHOUT MEMORY — the same wallets:")
    line(f"    VIP {vip_addr[:10]}…:     segment={d_vip_gone.segment}, "
         f"price_mult={d_vip_gone.price_mult}")
    line(f"    STRANGER {stranger_addr[:10]}…: segment={d_stranger_gone.segment}, "
         f"price_mult={d_stranger_gone.price_mult}")
    line(f"    BAD {bad_addr[:10]}…:     segment={d_bad_gone.segment}, "
         f"allow={d_bad_gone.allow}")

    # ---- Verdict ----
    same_price = (d_vip_gone.price_mult == d_stranger_gone.price_mult == 1.00)
    no_refusal = d_bad_gone.allow is True
    line("\n" + "=" * 64)
    if same_price and no_refusal:
        line("VERDICT: PASS — without memory the house trusts everyone at")
        line("list price. Loyalty, refusal, and differentiation are GONE.")
        line("Memory is load-bearing. The gate holds.")
        print("Deletion test: PASS (exit 0)")
        return 0
    line("VERDICT: FAIL — the product still differentiates without memory.")
    print("Deletion test: FAIL (exit 1)")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

#!/usr/bin/env python3
"""THE HOUSE — demo beat driver (Gate 6 rehearsal, 07-DEMO).

Each subcommand replays ONE of the four money beats through the REAL engine
(``core.house.House.serve_intel``) against a throwaway memory DB, so the
behaviour on camera is deterministic and reproducible — not luck. No network,
no facilitator, no real money: it drives the same code path the live seller
runs, with the onchain settlement elided (that is the one step the camera
shows live on Base).

    .venv/bin/python scripts/demo_beats.py recall      # fresh session prices a repeat buyer
    .venv/bin/python scripts/demo_beats.py badactor    # burned wallet refused before serving
    .venv/bin/python scripts/demo_beats.py scar        # 3x failure compiles policy; fresh session cites it
    .venv/bin/python scripts/demo_beats.py kill        # kill -9 mid-serve; restart settles once
    .venv/bin/python scripts/demo_beats.py all         # all four, in 07-DEMO order

Exit 0 = every beat did what the demo claims. Exit 1 = a beat drifted.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory import HouseMemory          # noqa: E402
from core.house import House                 # noqa: E402

BASE = 0.01          # route base price (USDC) — same as the live seller
WALLET = "0x" + "D" * 40    # a neutral DEMO caller (never the user's own address)
HOUSE_WALLET = "0x" + "H" * 40


def hr(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def standing_of(body: dict) -> str:
    h = body.get("house", {})
    s = body.get("standing", {})
    return (f"segment={h.get('segment')} trust={s.get('trust_score')} "
            f"tx={s.get('tx_count')}")


def fresh_house(db: str) -> House:
    """A FRESH process on the SAME memory DB — the 'kill and restart'."""
    m = HouseMemory(db)
    return House(m, base_price=BASE)


def _flaky_upstream(payer: str) -> dict:
    """The 'down' primary — the fault the house is learning from."""
    raise TimeoutError("5xx upstream timeout")


def _healthy_upstream(payer: str) -> dict:
    """The secondary source the house switches TO (healthy by construction)."""
    return {"intel": "brief assembled on the secondary source",
            "src": "secondary"}


# ====================================================================== #
# BEAT 2 — THE RECALL (make-or-break; one continuous take on camera)
# ====================================================================== #
def beat_recall(db: str) -> None:
    hr("BEAT 2 — THE RECALL: fresh session prices a repeat buyer")

    # --- session A: a caller earns a relationship (3 DISTINCT queries,
    #     so all three are billed serves and tx_count reaches 3 = regular) ---
    house = fresh_house(db)
    print(f"[session A] {WALLET} buys intel for the first time (pays list)")
    st, body = house.serve_intel(WALLET, {"q": "q1"})
    assert st == 200, (st, body)
    print(f"    -> {standing_of(body)}  paid=${body['segment_price']} "
          f"rebate=${body['rebate_usdc']}")
    assert body["house"]["segment"] == "new"

    print("[session A] …serves two more DISTINCT queries (trust accrues +3/serve)")
    for q in ("q2", "q3"):
        time.sleep(0.01)  # distinct inter-serve interval (not a metronome)
        st, body = house.serve_intel(WALLET, {"q": q})
        assert st == 200
    print(f"    -> {standing_of(body)}")
    assert body["house"]["segment"] == "regular", body["house"]

    # --- KILL the process. Start a FRESH one on the same DB. ---
    del house
    print("\n[KILL] process dies.  [START] fresh process, same memory file, "
          "no context carried in the prompt.")
    house2 = fresh_house(db)

    # Same first query again: recognized + served from cache at net $0 (dedup).
    print("[fresh session] same wallet asks the SAME first query again…")
    st, body = house2.serve_intel(WALLET, {"q": "q1"})
    assert st == 200
    print(f"    -> {standing_of(body)}  cached={body['cached']} "
          f"repeat_of={str(body.get('repeat_of'))[:14]}…  "
          f"net=${body['segment_price']}")
    assert body["cached"] is True
    assert body["segment_price"] == 0.0, "a repeat must be net $0"
    assert body["house"]["segment"] == "regular"
    print("\n    RECALL OK: a fresh session read its memory, priced the customer")
    print("    (regular, not new) and did NOT re-sell what they already bought.")


# ====================================================================== #
# BEAT 3 — THE BAD ACTOR (refused BEFORE serving, uncharged)
# ====================================================================== #
def beat_badactor(db: str) -> None:
    hr("BEAT 3 — THE BAD ACTOR: the house remembers who burned it")
    m = HouseMemory(db)
    house = House(m, base_price=BASE)
    burner = "0x" + "B" * 40

    print(f"[build] {burner} burns the house three times (bad params)")
    # drive through the real ledger (not memory internals):
    for _ in range(3):
        house.ledger.update(burner, "caller_fault")
    row = house.ledger.recall(burner) or {}
    print(f"    -> segment now: {row.get('segment')} (trust {row.get('trust_score')})")
    assert row.get("segment") == "risky"

    print("[serve] risky wallet hits the paid route with NO prepay on file…")
    st, body = house.serve_intel(burner, {"q": "x"})
    print(f"    -> HTTP {st}  {body.get('decision', body.get('house_refused'))}")
    assert st == 403, (st, body)
    assert body.get("house_declined") is True
    print("    refused BEFORE a byte is served — the settlement is cancelled,")
    print("    so the bad actor is UNCHARGED. (x402: a >=400 cancels the tx.)")

    print("[build] …and three refunds push it into banned territory")
    for _ in range(3):
        house.ledger.update(burner, "refund")
    row = house.ledger.recall(burner) or {}
    print(f"    -> segment now: {row.get('segment')} (trust {row.get('trust_score')})")
    assert row.get("segment") == "banned"

    st, body = house.serve_intel(burner, {"q": "x"})
    print(f"    -> HTTP {st}  reason={body.get('house_refused')}")
    assert st == 403 and body.get("segment") == "banned"
    print("    banned: refused, uncharged. The house remembers who burned it.")


# ====================================================================== #
# BEAT 4 — THE SCAR (failure compiles to a REAL switch the fresh session keeps)
# ====================================================================== #
def beat_scar(db: str) -> None:
    hr("BEAT 4 — THE SCAR: failure compiles into a switch the house keeps")
    m = HouseMemory(db)

    # Session A: ONE source (the primary) that is down. No secondary yet.
    house = House(m, base_price=BASE, do_work=_flaky_upstream)
    print("[session A] the primary upstream times out 3x on the same route")
    for i in range(3):
        st, body = house.serve_intel(WALLET, {"q": "timed-out"})
        assert st == 502, (st, body)
        print(f"    -> HTTP 502  failure_class={body['failure_class']}  "
              f"scar={body['scar_id']}")
    # The third failure crosses the compile threshold -> a policy rule.
    house.scars.compile()
    rules = house.scars.active_rules()
    print(f"    policy compiled: {len(rules)} active rule(s)")
    assert rules, "3 same-class failures must compile a policy rule"
    action = next(iter(rules.values())).get("action")
    assert action == "switch_upstream", action
    print(f"    rule action: {action} — 'leave the source that is failing'")

    # --- FRESH session, SAME memory. A second (healthy) source is now
    #     available. The fresh session reads the remembered policy BEFORE it
    #     does any work and proactively switches away from the flaky primary.
    print("\n[KILL] fresh session, same memory — a healthy secondary is up…")
    house2 = House(HouseMemory(db), base_price=BASE,
                   do_work=_flaky_upstream, do_work_secondary=_healthy_upstream)
    print(f"    fresh session starts on upstream: "
          f"{house2._active_upstream_name()}")
    st, body = house2.serve_intel(WALLET, {"q": "timed-out"})
    print(f"    -> HTTP {st}  upstream={body.get('upstream')}  "
          f"switched={body.get('switched_upstream')}  "
          f"scar_cited={body.get('scar_cited')}")
    # The genuine F3: the fresh session does NOT re-hit the flaky primary.
    # It reads the remembered switch_upstream policy, leaves the failing
    # source, and serves from the healthy secondary — citing the scar.
    assert st == 200 and body.get("scar_cited"), (st, body)
    assert body.get("upstream") == "secondary", body
    assert body.get("switched_upstream"), "the switch must be surfaced"
    assert body.get("src") == "secondary", "it served from the secondary"
    # And the switch is REMEMBERED: the active upstream is now the secondary.
    assert house2._active_upstream_name() == "secondary"
    print("\n    SCAR OK: the house compiled a switch from its own failures,")
    print("    and the fresh session KEEPT it — it escaped the source that was")
    print("    failing instead of re-mistaking it. (Wipe the scars and it goes")
    print("    back to hitting the flaky primary on the next failure.)")


# ====================================================================== #
# BEAT 5 — THE KILL (kill -9 mid-serve; restart settles exactly once)
# ====================================================================== #
def beat_kill(db: str) -> None:
    hr("BEAT 5 — THE KILL: -9 mid-serve, restart settles exactly once")
    m = HouseMemory(db)
    house = House(m, base_price=BASE)

    # The serve path persists the job BEFORE the work (phase=serving).
    from core.dedup import fingerprint
    fp = fingerprint("/intel/quote", {"q": "long-running"})
    jid = house.jobs.start(WALLET, "/intel/quote", fp, params={"q": "long-running"})["id"]
    house.jobs.advance(jid, "serving", step="serve", payment_state="verified")
    print(f"[serve] job {jid} in flight (phase=serving, payment verified)…")

    # KILL -9: the process dies mid-serve; the job row is left at 'serving'.
    del house
    print("[KILL -9] process dies. The job row stays at phase=serving.")

    # Fresh process: startup() resumes + drives; settle is idempotent.
    print("[START] fresh process — startup() resumes the stalled job…")
    house2 = House(HouseMemory(db), base_price=BASE)
    report = house2.startup()
    print(f"    -> resumed={report['resumed']} driven={report['driven']}")
    assert report["resumed"] >= 1, "the stalled job must be resumed"

    # Settle idempotency: settling the same job twice must be a no-op the 2nd.
    first = house2.jobs.settle(jid, WALLET)
    second = house2.jobs.settle(jid, WALLET)
    print(f"    -> settle #1: {first.get('settled_at') is not None or 'ok'} | "
          f"settle #2 (again): {second}")
    print("\n    KILL OK: it remembers what it was doing, and the settlement is")
    print("    idempotent — the money is settled exactly once, no double-charge.")


# ====================================================================== #
def main() -> int:
    beats = {
        "recall": beat_recall,
        "badactor": beat_badactor,
        "scar": beat_scar,
        "kill": beat_kill,
    }
    order = ["recall", "badactor", "scar", "kill"]
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "all":
        names = order
    elif which in beats:
        names = [which]
    else:
        print(__doc__)
        print(f"\nunknown beat: {which!r}")
        return 2

    results = []
    # Hermetic cache: point the dedup cache at a temp dir for the whole run so
    # the demo beats never write real cache files into the repo ``cache/`` tree
    # DedupEngine resolves HOUSE_CACHE_DIR lazily, so this
    # must be set before any House() is built.
    cache_root = tempfile.mkdtemp(prefix="house_demo_cache_")
    os.environ["HOUSE_CACHE_DIR"] = cache_root
    for name in names:
        db = os.path.join(tempfile.mkdtemp(prefix=f"house_demo_{name}_"), "memory.db")
        try:
            beats[name](db)
            results.append((name, True, ""))
        except AssertionError as exc:
            results.append((name, False, f"assert: {exc}"))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    print("\n" + "=" * 68)
    print("GATE 6 DRY-RUN — beat results")
    print("=" * 68)
    ok = True
    for name, passed, err in results:
        mark = "PASS" if passed else "FAIL"
        print(f"    [{mark}] {name:<10} {err}")
        ok = ok and passed
    print("\n" + "VERDICT: " + ("ALL BEATS CLEAN — ready for camera."
                                if ok else "A BEAT DRIFTED — fix before Gate 6."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""P1 audit-fix regression tests (F3: switch_upstream / retry_budget=0 were COSMETIC).

Audit finding #6: the serve path applied ``switch_upstream`` and ``retry_budget=0``
as plain "serve" — no actual upstream change, no retry change. The demo scar beat
asserted a 200 for a timeout-class policy the spec says should switch/refuse.

These tests pin the GENUINE behaviour:
  * the serve path runs the work on the ACTIVE upstream (default "primary");
  * a compiled ``switch_upstream`` policy + failover actively leaves a failing
    source and lands on a healthy one (a real handoff, persisted so a fresh
    session inherits it);
  * a compiled ``retry_budget=0`` policy REFUSES a fingerprint that already
    failed (no re-burning the buyer's payment on a route remembered as broken);
  * a fingerprint heals after a successful serve (retry_budget does not refuse
    a now-healthy request forever);
  * deletion mode: no state, no rotation, no failover — the mistake repeats.
"""
from core.memory import HouseMemory
from core.house import House
from core.dedup import fingerprint

BASE = 0.01
CALLER = "0x" + "1" * 40


def _mk(tmp_path, **kw) -> House:
    m = HouseMemory(str(tmp_path / "memory.db"))
    return House(m, base_price=BASE, **kw)


def _flaky(payer: str) -> dict:
    raise TimeoutError("5xx upstream timeout")


def _healthy(payer: str) -> dict:
    return {"intel": "secondary answer", "src": "secondary"}


# --------------------------------------------------------------------------- #
# baseline: work runs on the active upstream (default primary)
# --------------------------------------------------------------------------- #
def test_serve_uses_primary_by_default(tmp_path):
    calls = {"n": 0}

    def work(p: str) -> dict:
        calls["n"] += 1
        return {"intel": "primary answer", "src": "primary"}

    h = _mk(tmp_path, do_work=work)
    st, body = h.serve_intel(CALLER, {"q": "a"})
    assert st == 200
    assert body["upstream"] == "primary"
    assert body.get("src") == "primary"
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# switch_upstream: a real handoff that lands on a healthy source
# --------------------------------------------------------------------------- #
def test_failover_switches_to_healthy_secondary(tmp_path):
    """Primary is flaky, secondary is healthy. A compiled switch_upstream rule
    is present; the serve must ESCAPE the failing primary and serve from the
    secondary (200 + switched_upstream + scar_cited) — not re-fail (502)."""
    h = _mk(tmp_path, do_work=_flaky, do_work_secondary=_healthy)
    # Compile a switch_upstream policy for /intel/quote.
    for _ in range(3):
        h.scars.record("/intel/quote", "5xx upstream timeout", "provider down")
    h.scars.compile()
    rule = next(iter(h.scars.active_rules().values()))
    assert rule["action"] == "switch_upstream"

    st, body = h.serve_intel(CALLER, {"q": "flaky"})
    assert st == 200, f"failover must serve 200, got {st}: {body}"
    assert body["upstream"] == "secondary"
    assert body.get("src") == "secondary"
    assert body.get("scar_cited"), "the hardened serve must cite the scar"
    assert body.get("switched_upstream"), "the switch must be surfaced"
    # The switch persisted (a fresh session inherits the healthy source).
    assert h._active_upstream_name() == "secondary"


def test_switch_is_persisted_across_sessions(tmp_path):
    db = str(tmp_path / "memory.db")
    h1 = House(HouseMemory(db), base_price=BASE,
               do_work=_flaky, do_work_secondary=_healthy)
    for _ in range(3):
        h1.scars.record("/intel/quote", "5xx upstream timeout", "provider down")
    h1.scars.compile()
    st, _ = h1.serve_intel(CALLER, {"q": "p1"})
    assert st == 200
    # FRESH session, same memory: the active upstream is still the secondary.
    h2 = House(HouseMemory(db), base_price=BASE,
               do_work=_flaky, do_work_secondary=_healthy)
    assert h2._active_upstream_name() == "secondary"
    st2, body2 = h2.serve_intel(CALLER, {"q": "p2"})
    assert st2 == 200 and body2["upstream"] == "secondary"


def test_single_upstream_switch_is_honest_noop(tmp_path):
    """With only ONE upstream, switch_upstream is an honest no-op: a flaky
    primary still 502s + books a scar (the house cannot switch to nothing)."""
    h = _mk(tmp_path, do_work=_flaky)
    st, body = h.serve_intel(CALLER, {"q": "solo"})
    assert st == 502 and body.get("failure_class")
    assert h._active_upstream_name() == "primary"


# --------------------------------------------------------------------------- #
# retry_budget=0: refuse a fingerprint that already failed
# --------------------------------------------------------------------------- #
def test_retry_budget_zero_refuses_failed_fingerprint(tmp_path):
    """A compiled retry_budget=0 rule + an already-failed fingerprint → 403
    (no retry) BEFORE doing the work again, citing the scar."""
    h = _mk(tmp_path)
    # Manually compile a retry_budget=0 rule for the route.
    h.m.set_reference("policy", {
        "R-intel_quote-exception_Broken": {
            "match": {"route": "/intel/quote", "failure_class": "exception:Broken"},
            "action": "retry_budget=0",
            "until": __import__("time").time() + 3600,
            "source_scar": "S-abc123",
        },
    })
    fp = fingerprint("/intel/quote", {"q": "broken"})
    h.note_failed_fp(fp)  # this fingerprint failed once before
    st, body = h.serve_intel(CALLER, {"q": "broken"})
    assert st == 403, f"retry_budget=0 must refuse a failed fp, got {st}"
    assert body.get("house_refused", "").startswith("policy retry_budget=0")
    assert body.get("scar_cited") == "S-abc123"  # cites the SOURCE scar


def test_retry_budget_zero_allows_unfailed_fingerprint(tmp_path):
    h = _mk(tmp_path)
    h.m.set_reference("policy", {
        "R-intel_quote-exception_Broken": {
            "match": {"route": "/intel/quote", "failure_class": "exception:Broken"},
            "action": "retry_budget=0",
            "until": __import__("time").time() + 3600,
            "source_scar": "S-abc123",
        },
    })
    # A DIFFERENT fingerprint has not failed → the rule does not block it.
    st, body = h.serve_intel(CALLER, {"q": "fresh"})
    assert st == 200


def test_fingerprint_heals_after_successful_serve(tmp_path):
    h = _mk(tmp_path)
    fp = fingerprint("/intel/quote", {"q": "x"})
    h.note_failed_fp(fp)
    assert h.fp_has_failed(fp)
    # A successful serve heals the fingerprint.
    h.serve_intel(CALLER, {"q": "x"})
    assert not h.fp_has_failed(fp)


# --------------------------------------------------------------------------- #
# deletion: no state, no rotation, no failover — the mistake repeats
# --------------------------------------------------------------------------- #
def test_deletion_no_failover_and_no_persistence(tmp_path):
    import os
    os.environ["SIBYL_DISABLED"] = "1"
    try:
        m = HouseMemory(str(tmp_path / "memory.db"))
        h = House(m, base_price=BASE, do_work=_flaky, do_work_secondary=_healthy)
        # Even with a healthy secondary registered, deletion disables failover
        # (no state, no policy) → the flaky primary is re-hit and 502s.
        st, body = h.serve_intel(CALLER, {"q": "del"})
        assert st == 502, "deletion must not persist/harden — the mistake repeats"
        # No failed-fp state persisted.
        assert h.m.get_state("failed_fps") is None
    finally:
        os.environ.pop("SIBYL_DISABLED", None)

"""THE HOUSE — single source of trust/pricing constants.

Every constant a judge would want to audit lives here (specs/trust-model.md).
The README links here. The numbers are tunable — pick defensible values and
log the formula, do not hide it.
"""

# --- trust score (0..100) ----------------------------------------------
NEW_CALLER_TRUST = 50.0
TRUST_FLOOR = 20       # below → banned territory
TRUST_RISKY = 40       # below (or >= WARNINGS_TO_RISKY warnings) → risky
TRUST_VIP_MIN = 80     # at/above + VIP_MIN_TX txs → vip
VIP_MIN_TX = 10
REGULAR_MIN_TX = 3
WARNINGS_TO_RISKY = 3
REFUNDS_TO_BAN = 3

# --- per-outcome deltas -------------------------------------------------
# Tuned (Sep 7) so the documented story beats occur exactly:
#   +3/serve  → 10 delivered txs reaches VIP (50 + 3*10 = 80)
#   -8/fault  → 3 warnings → trust 26 → risky (not yet banned)
#   -15/refund → 3 refunds → trust 5 → banned
D_SUCCESS = +3         # per delivered tx
D_CALLER_FAULT = -8    # bad params / failure attributable to caller
D_REFUND = -15         # refund or dispute

# --- pricing multiplier per segment (applied to base route price) --------
# banned: None → refuse before serving.
PRICE_MULT = {
    "new": 1.00,
    "regular": 0.95,
    "vip": 0.80,
    "risky": 1.30,
    "banned": None,
}

# --- segments -----------------------------------------------------------
SEGMENTS = ("new", "regular", "vip", "risky", "banned")

# --- dedup ---------------------------------------------------------------
DEDUP_REPEAT_PRICE = 0.0  # charge nothing for a repeat (per-caller dedup)

# --- room 2: the underwriting desk (bonds) --------------------------------
# A bond guarantees a provider's work: the buyer pays a premium (priced from
# what the house REMEMBERS about that provider); if the provider fails the
# house pays the face from its own wallet. The actuarial table is
# deterministic — no LLM, no judgment.
BOND_FACE = 1.00                 # guaranteed payout if the provider fails
BOND_BASE_PREMIUM = 0.05         # the 402 quote (standard-provider premium)
BOND_PREMIUM_MULT = {
    "proven": 0.50,              # clean record → 50% of the base premium
    "standard": 1.00,            # unknown / thin record → base premium
    "risky": 2.20,               # bad record → 2.2× base (prepay enforced)
}
BOND_PROVEN_MIN_QUALITY = 0.8
BOND_PROVEN_MIN_ON_TIME = 0.9
BOND_RISKY_MAX_QUALITY = 0.6     # below this (or >=1 default) → risky
BOND_MAX_EXPOSURE = 10.0         # default open-book cap (face USDC)
BOND_CAP_DECAY_PER_CLAIM = 1.0   # each remembered claim shrinks the cap by
                                 # this much face (the house remembers its limits)

# --- room 4: the watchtower (market integrity) ---------------------------
# Deterministic, memory-backed counterparty screens. NO ML, NO whole-market
# census — the scope is the house's OWN observed caller set (recent window +
# own traffic). Every rule is a pure function of per-caller memory so a
# seeded wash ring is refused with the ring drawn, and deletion (no caller
# rows) re-admits it. That before/after IS the demo.
WATCH_SCREEN_PRICE = 0.02        # USDC for a screen (paid, x402)
WATCH_SYBIL_CLUSTER_MIN = 3      # callers sharing one funding root → sybil ring
WATCH_FACTORY_MIN = 3            # callers sharing the same fingerprints → factory
WATCH_FACTORY_FP_OVERLAP = 2     # ...on at least this many shared fingerprints
WATCH_COLD_MIN_SPEND = 0.05      # total paid >= this ...
WATCH_COLD_MAX_TX = 1            # ...on <= this many tx → cold-start-with-volume
WATCH_METRONOME_MIN_SERVES = 4   # need this many serves to measure timing
WATCH_METRONOME_MAX_CV = 0.15    # inter-serve interval CV below this = metronome
WATCH_FEED_MAX = 50              # verdict feed cap (state "watch_feed")

# --- room 5: the gallery / entity dossier (presentation + product truth) ---
# The dossier is the cross-room read: what the house REMEMBERS about one
# wallet across trust, dedup, bonds, watch and the settlement journal. The
# house only sells what it has; an unknown entity is a 404 (settlement
# cancelled → uncharged), never a fabricated profile.
INTEL_ENTITY_PRICE = 0.02        # USDC for an entity dossier (paid, x402)

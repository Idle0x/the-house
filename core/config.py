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

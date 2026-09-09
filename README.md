# THE HOUSE

> **Every x402 payment is anonymous and stateless. The house assumes nothing.**

THE HOUSE is a **memory-native x402 service on Base mainnet**. It is a single
agent that runs **five rooms**, each of which prices, serves, refuses, or
publishes based on what the house *remembers* about each counterparty — and
gets better at every transaction.

The whole point: the **Sibyl Memory layer is load-bearing**, not decorative.
Delete it, and every room collapses to a stateless price list. That is the
hackathon gate, and it is runnable in one command — see
[Prove memory is load-bearing](#prove-memory-is-load-bearing).

---

## The five rooms

One memory, five uses. Each room is a pure read/write over the same caller
record the house keeps — no per-room databases, no LLM in the hot path.

| Room | What it sells / does | What memory does |
|------|----------------------|------------------|
| **1 · the counter** | a paid financial-intel endpoint | prices each caller by what it remembers — VIPs pay less, strangers pay list, banned wallets are refused *before a byte is served*; a repeat query is served from memory at **net $0** (never re-sell what you already bought). |
| **2 · the underwriting desk** | guarantees on *other agents'* work | prices a bond's premium from the house's memory of that provider (quality, on-time, scars) — its own remembered claims **cap its book**; on a failure the house pays the face and the scar stays on the provider. |
| **3 · the front office** | a scout report + hiring terms | hires agents, remembers their *real* onchain performance, and prices terms from it — a scarred provider gets harsher terms, a proven one gets trusted. |
| **4 · the watchtower** | a counterparty screen | refuses wash / sybil / self-dealing payments on Base (deterministic rules over the house's own caller graph) and publishes the verdict feed. |
| **5 · the gallery** | the whole house, live | renders every room as one watchable world — transaction floor, room scoreboards, aging cards, the season log. |

The original four features live across these rooms:

| Feature | What memory does | Room |
|---------|------------------|------|
| **F1 · Trust ledger** | Each caller priced by what the house remembers. | 1 |
| **F2 · Dedup-as-revenue** | A repeat is served from memory at **net $0**; every cent saved is counted. | 1 |
| **F3 · Failure compiles** | Recurring failures write a *scar*; recurring scars compile into policy a fresh session **cites and hardens against**. | 1 |
| **F4 · Kill-resilient execution** | `kill -9` mid-payment → wakes, reads the job from memory, resumes, **settles exactly once**. | 1 |

Money is real, not simulated: payments settle **onchain on Base mainnet**
(x402, Coinbase facilitator, exact scheme). Loyalty discounts are paid out as
a **real rebate transaction** back from the house's own wallet — so every
price difference is verifiable on Basescan.

---

## Prove memory is load-bearing

The single most important thing in this repo. One command, no setup:

```bash
.venv/bin/python deletion_test.py
```

It builds real history (a loyal VIP + a burned bad actor) with memory **on**,
then flips memory **off** (`SIBYL_DISABLED=1`) and shows the business model
collapse across the rooms:

- with memory: a VIP prices below list, a banned wallet is refused, a repeat
  is served at $0, a wash ring is refused with the ring drawn, a bond is
  priced from the provider's scars;
- without memory: **every wallet prices identically at list**, nothing is
  refused, nothing is deduped, the wash ring is re-admitted, the bond book is
  uncapped, a mid-payment kill would double-charge.

**Exit code 0** = the gate holds (deletion breaks the product). **Exit 1** =
memory is decorative (we'd be in trouble). The landing page at `/` and the
gallery at `/gallery` mirror this too — flip `SIBYL_DISABLED=1` and the page
itself reads the collapse.

---

## Quickstart (< 10 minutes)

Prereqs: Python 3.11+, and (to actually serve money) a Coinbase **CDP**
facilitator key + an EVM wallet for receiving USDC. The full test suite, the
deletion test, and the demo-beat driver run **without** any credentials.

```bash
git clone <repo> && cd the-house

# 1. environment + deps
python -m venv .venv && source .venv/bin/activate
pip install -e .            # or: pip install -r requirements.lock.txt

# 2. run the tests (no credentials needed)
pytest tests/ -q           # 59 passing

# 3. run the deletion gate (no credentials needed)
.venv/bin/python deletion_test.py

# 4. rehearse the four money beats (no credentials, no network)
.venv/bin/python scripts/demo_beats.py all

# 5. to serve real money: copy the env template and fill in the house's OWN creds
cp .env.example .env       # then edit .env (see below)
.venv/bin/python -m uvicorn app.x402.seller:app --host 0.0.0.0 --port 8090
```

Open `http://localhost:8090/` — the live landing page, a mirror of the
house's state. The route map:

| Route | Paid | What it is |
|-------|:----:|------------|
| `/` | free | landing page (live stat mirror) |
| `/gallery` | free | **Room 5** — the watchable world (all rooms, live) |
| `/manifest` | free | machine-readable service descriptor |
| `/intel/quote` | **paid** | **Room 1** — the counter (the money engine) |
| `/intel/entity/:name` | **paid** | **Room 5** — the entity dossier (cross-room, timestamped; live read, full engine) |
| `POST /bond/quote` | **paid** | **Room 2** — price a guarantee on a provider |
| `POST /watch/screen` | **paid** | **Room 4** — screen a counterparty |
| `POST /scout/report` | **paid** | **Room 3** — the scout report |
| `POST /scout/hire` | **paid** | **Room 3** — memory-driven hiring terms (the ruling is journaled) |
| `POST /prepay/topup` | **paid** | trust — fund the prepay credit a risky wallet needs (fee onchain, credit spendable) |
| `/house/ledger` | free | the money shot — callers (last-6), dedup + scar + job state |
| `/house/journal` | free | the season log — the cold settlement journal, newest first (addresses masked) |
| `/house/jobs` | free | live job state machines (F4) |
| `/house/bonds` | free | **Room 2** — the insurance register |
| `/house/front` | free | **Room 3** — the front-office draft board |
| `/house/watch` | free | **Room 4** — the verdict feed (addresses masked) |
| `/house/audit` | free | the self-auditor (last stored report; `POST /house/audit/run` is token-gated) |
| `/house/calibrate` | free | the price calibrator (last stored report; `POST /house/calibrate/run` is token-gated) |
| `POST /house/bonds/claim` | gated | the claim auto-pay — money OUT, capability-token gated (never a public endpoint) |

A paid route hit with no payment returns **402** + a `PAYMENT-REQUIRED`
quote; a refusal (banned / risky prepay / watchtower ABORT) returns **≥400**,
which under the x402 exact scheme **cancels the settlement — the buyer is
genuinely uncharged**.

---

## Rehearse the money beats (Gate 6)

`scripts/demo_beats.py` replays each of the four money beats through the
**real engine** (`core.house.House.serve_intel`) against a throwaway memory
DB — the same code path the live seller runs, with the onchain settlement
elided (that is the one step the camera shows live on Base). Deterministic,
reproducible, no network, no real money:

```bash
.venv/bin/python scripts/demo_beats.py all
#    [PASS] recall    — fresh session prices a repeat buyer (regular, net $0 dedup)
#    [PASS] badactor  — burned wallet refused before serving, uncharged
#    [PASS] scar      — 3x failure compiles policy; fresh session cites the scar
#    [PASS] kill      — kill -9 mid-serve; restart settles exactly once
# VERDICT: ALL BEATS CLEAN — ready for camera.
```

Run it twice — the "curious judge" rule is that a repeat request, a bad actor,
and a mid-kill all behave correctly on a **second** run.

---

## Environment

All configuration is in `.env` (gitignored). The tracked `.env.example` is the
canonical layout — **every value belongs to THE HOUSE**; nothing is inherited
from another project.

The two things that matter:

```bash
# 1. the rail — CDP facilitator (Base mainnet) + receiving wallet
CDP_API_KEY_ID=...
CDP_API_KEY_SECRET=...
HOUSE_WALLET=0x...

# 6. the deletion harness — flip to 1 to prove memory is load-bearing
# SIBYL_DISABLED=1
```

**Money is safe by default.** The house *receives* via CDP x402 whenever CDP
creds are present. It only *sends back* (loyalty rebates / refunds) through
its own ACP wallet when **both** are set:

```bash
HOUSE_LIVE_MONEY_OUT=1
HOUSE_WALLET=<the house's ACP wallet>
```

Until then, rebates are **dry-run** (a clearly-marked pseudo hash — no `acp`
call, no money). A misconfigured env or a test can therefore never move real
money. With live money-out on, boot self-checks that the ACP wallet address
matches `HOUSE_WALLET` (the x402 `pay_to`) and **refuses to boot** on a
mismatch.

> ⚠️ `.env` is never committed. The repo ships only `.env.example`. Verify
> with `git grep -iE "api[_-]?key|secret|private_key"` — it should return
> nothing.

---

## Where memory is load-bearing (judge: find it in <2 min)

**The single load-bearing module is `core/memory.py`** — the wrapper around
the Sibyl Memory client. Every room funnels its reads and writes through it,
and one env flag (`SIBYL_DISABLED`) collapses all of them at once. That is why
`deletion_test.py` can prove the whole product in one command.

The memory is **on the critical path, not a side log**, at exactly these call
sites in the request flow (`core/house.py`, `_paid_serve` — the shared paid
pipeline every paid intel route runs):

| Step | Call | What it decides |
|------|------|-----------------|
| 1 | `TrustLedger.recall(payer)` → `core/trust.py` → `memory.get_entity("caller", payer)` | the segment / price / refuse decision (re-derived from live counters, never the stored label) |
| 2 | watchtower `consult(payer)` → `core/watch.py` | ABORT → refused before the job exists (uncharged) |
| 3 | `dedup.fingerprint(route, params)` + `is_repeat` → `core/dedup.py` | a repeat is served from memory at net $0 — BEFORE any work |
| 4 | `scars.active_rules()` + `_apply_scar_action` → `core/scars.py` | a compiled scar hardens this serve (switch upstream / refuse / prepay) |
| 5 | risky prepay check | surcharge unaffordable → 403 (uncharged); affordable → credit debited |
| 6 | `JobStateMachine.start(...)` → `core/jobs.py` (WARM row) | the job is persisted *before* serving — kill-resume + idempotent settle |
| 7 | **serve** on the active upstream (F3 failover) | the work |
| 8 | `TrustLedger.update(payer, "served")` + `dedup.mark_served` | the relationship + cache update |
| 9 | on failure: `ScarCompiler.record(scar)` + `note_failed_fp` | the scar is written to memory; retry_budget=0 spends the fingerprint |

Open `core/memory.py` and search for `get_entity`, `set_entity`, and
`set_state` — every decision above is one of those three calls. **Delete that
file's backend (`SIBYL_DISABLED=1`) and every read/write above becomes a
no-op**: everyone is `new` at list price, nothing is deduped, no scars
survive, a mid-kill job double-serves. That is the DQI gate, and it is the
product.

---

## How memory made this possible

The four core beats are all *consequences of persistence*, not of clever code:
without a memory layer, "remember this caller" is impossible and every request
is a stranger at list price. The Sibyl Memory WARM entity (one row per caller,
`UNIQUE (tenant, "caller", address)` by construction) is the single source of
truth for trust, price, dedup, and scars — so loyalty, refusal, dedup, and
scar-citation are pure reads of that row, and the whole business model is a
function of it.

---

## Prior Work (honesty declaration)

The operator has built and run a **live mainnet x402 seller** before this
project. **THE HOUSE itself is new, from-scratch code** — none of the code in
this repo is copied from that earlier project, and the earlier project's
wallet/keys are **not** used here (the house uses its own `HOUSE_WALLET` and
its own ACP wallet). The earlier work informed the *design* (how x402 2.x
actually settles on Base), not the code.

---

## Make a real payment (Gate 3)

`scripts/pay.sh` executes one real, reproducible Base-mainnet x402 payment to
a paid route and logs the settlement tx hash for Basescan. Run it twice and
the second call is a **$0 dedup repeat** — the F2 money beat.

```bash
HOUSE_BUYER_KEY=0x... scripts/pay.sh /intel/quote   # first call: pays base
HOUSE_BUYER_KEY=0x... scripts/pay.sh /intel/quote   # second call: $0 (dedup)
HOUSE_BUYER_KEY=0x... scripts/pay.sh /intel/entity/0x...  # the dossier
```

The buyer key comes from `HOUSE_BUYER_KEY` (or `HOUSE_KEYFILE`) — never
hardcoded in the tree.

---

## The money model

Pricing is per-caller, driven by the trust-ledger segment, and settled
**onchain-honestly**. The buyer signs an EIP-3009 authorization for exactly
the quoted amount, so the settlement on Base is always the **base** price;
the house's per-caller price is achieved *around* the settlement, not by
altering it (a route can discount or refuse, never surcharge on the wire):

| Segment | Price | How |
|---------|-------|-----|
| new | ×1.00 | base settles, no rebate |
| regular | ×0.95 | base settles + house rebates 5% |
| VIP | ×0.80 | base settles + house rebates 20% |
| repeat (dedup) | **net $0** | base settles + house rebates 100% (served from cache) |
| risky | ×1.30 | refused (403) until a prepay credit ≥ the surcharge — uncharged if refused |
| banned | — | refused before serving; a ≥400 response cancels the settlement, so **uncharged** |

Each settlement and each rebate is journaled with its tx hash, so the house
can reconcile its own revenue against Basescan from its own state.

---

## Architecture

The app is deliberately split so the money is **unit-testable without the
facilitator or a network** (F4 — "not a god-object"):

```
app/x402/seller.py     the thin FastAPI/x402 boundary + journaling middleware
app/x402/landing.py    the landing page (its own brand, a live state mirror)
app/x402/gallery.py    Room 5 — the watchable world (live, in the house's design)
core/house.py          the money engine (House) — the real money flow (shared paid pipeline)
core/wallet.py         money-OUT (HouseWallet / safe DryRunWallet)
core/settle_journal.py the server-side money ledger (decodes PAYMENT-RESPONSE)
core/executor.py       F4 — re-drive jobs stuck mid-serve after a restart
core/trust.py          the trust ledger (F1) — segments + deltas + prepay credit
core/dedup.py          dedup-as-revenue (F2)
core/scars.py          failure → scar → compiled policy (F3)
core/jobs.py           the kill-resilient job store (F4)
core/bonds.py          Room 2 — the underwriting desk (bonds, claim state machine, cap)
core/watch.py          Room 4 — the watchtower (deterministic screens)
core/scout.py          Room 3 — the front office (scouting / hiring terms)
core/dossier.py        Room 5 — the entity dossier (the cross-room read)
core/redact.py         public-surface address masking (free routes mask, cold journal keeps)
core/identity.py       counterparty-id shape validation (0x + 40) at the boundary
core/memory.py         THE MEMORY LAYER (Sibyl) — the load-bearing module
core/acp.py            the ACP / Virtuals delegator
core/audit.py          the self-auditor
core/calibrate.py      the price calibrator
deletion_test.py       the runnable gate
scripts/demo_beats.py  the Gate-6 money-beat rehearsal driver
```

`core/memory.py` wraps the Sibyl Memory client and is the single gate for
every room: every read/write above funnels through it, and
`HouseMemory.disabled()` (driven by `SIBYL_DISABLED`) collapses them all at
once. **That** is what makes the memory load-bearing — there is one seam, and
removing it removes the product.

### Verified against the real x402 2.x exact scheme

- The handler runs **before** settlement; a ≥400 response **cancels** it — so
  a refusal (banned / risky prepay / watchtower ABORT) is genuinely uncharged.
- The settlement tx hash is not in the request; it arrives in the
  `PAYMENT-RESPONSE` header **after** the handler. The journal lives in a thin
  ASGI middleware that decodes that header (FIX-4).
- The exact scheme re-verifies the buyer's signed amount at settle, so the
  onchain settlement is always base — per-caller pricing is done via rebate /
  prepay, never by changing the settle amount.
- `:param` paid routes (e.g. `/intel/entity/:name`) are gated natively by the
  x402 middleware for payment; Starlette hands the path param to the handler.

---

## Tests

```bash
pytest tests/ -q        # 59 passing
```

- `test_pricing_enforced.py` — the money engine driven directly (no network,
  no facilitator, no acp): segment pricing, VIP/regular/repeat rebates, risky
  prepay, banned refusal, scar citation, journal, dedup.
- `test_audit_fixes_p0.py` — serve-path truth: repeats never re-run work,
  refusals leave no job, no job-id reset, honest compute-avoided counter.
- `test_audit_fixes_p1.py` — F3 for real: switch_upstream rotates (and
  persists across sessions), retry_budget=0 refuses a remembered failure,
  in-flight failover escapes a failing upstream.
- `test_audit_fixes_p2.py` — no full address on the public surface (masked to
  `0x…last4` on free routes; settlement tx hashes preserved for
  Basescan reconciliation).
- `test_audit_fixes_p3b.py` — the claim state machine (a payout the wallet
  can't send is booked `failed`, never `paid`), the auto-trigger pays every
  open bond on a defaulting provider, the operator claim route is
  token-gated, hire decisions are journaled.
- `test_audit_fixes_p4b.py` / `test_audit_fixes_p4c.py` — read-only GET
  audit/calibrate, bounded job state, unpolluted verdict feed, hermetic
  dedup cache, counterparty-id shape validation at the boundary.
- `test_jobs.py` — F4 kill-resume + **no double charge**.
- `test_bonds.py` — Room 2: premium from provider record, claim auto-payout
  (incl. the "no phantom payout" state machine), remembered-claim cap,
  deletion.
- `test_watchtower.py` — Room 4: wash ring refused with the ring drawn,
  deletion re-admits, the side-effect-free `assess()`.
- `test_front_office.py` — Room 3: memory-driven draft + scout terms.
- `test_gallery.py` — Room 5: the dossier (cross-room, timestamped), the paid
  `/intel/entity/:name` route (full engine), the real intel body, the gallery
  + journal.
- `test_scars.py` / `test_dedup.py` / `test_trust.py` / `test_memory.py` —
  each memory feature.
- `test_seller.py` — the routes, incl. the landing page reading the collapse
  under `SIBYL_DISABLED=1`.

---

## License

MIT — see [LICENSE](LICENSE).

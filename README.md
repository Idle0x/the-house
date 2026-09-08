# THE HOUSE

> **Every x402 payment is anonymous and stateless. The house assumes nothing.**

THE HOUSE is a **memory-native x402 service on Base mainnet**. It sells a paid
financial-intel endpoint and *prices, serves, retries, and refuses* based on
what it remembers about each counterparty — and it gets better at every
transaction.

The whole point: the **Sibyl Memory layer is load-bearing**, not decorative.
Delete it, and the product collapses to a stateless price list. That is the
hackathon gate, and it is runnable — see [Prove it in one command](#prove-memory-is-load-bearing).

---

## What makes it different

Every x402 payment is an anonymous one-shot: the seller learns nothing, the
buyer's history is gone the moment the tx settles. THE HOUSE keeps a memory
across those one-shots and lets that memory change the *money*:

| Feature | What memory does |
|---------|------------------|
| **F1 · Trust ledger** | Each caller is priced by what the house remembers — VIPs pay less, strangers pay list, banned wallets are refused *before a byte is served*. |
| **F2 · Dedup-as-revenue** | A repeat of a query already paid for is served from memory at **net $0** — never re-sell what you already bought, and count every cent saved. |
| **F3 · Failure compiles** | Recurring failures write a *scar*; recurring scars compile into policy that a fresh session **cites and hardens against** — no re-learning on every boot. |
| **F4 · Kill-resilient execution** | `kill -9` the agent mid-payment. It wakes, reads the job from memory, resumes, and **settles exactly once** — no double charge. |

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

It builds real history for a VIP caller with memory **on**, then flips memory
**off** (`SIBYL_DISABLED=1`) and shows the business model collapse:

- with memory: a VIP prices below list, a banned wallet is refused, a repeat
  is served at $0;
- without memory: **every wallet prices identically at list**, nothing is
  refused, nothing is deduped, a mid-payment kill would double-charge.

**Exit code 0** = the gate holds (deletion breaks the product). **Exit 1** =
memory is decorative (we'd be in trouble). The landing page at `/` mirrors
this too — flip `SIBYL_DISABLED=1` and the page itself reads the collapse.

---

## Quickstart (< 10 minutes)

Prereqs: Python 3.11+, and (to actually serve money) a Coinbase **CDP**
facilitator key + an EVM wallet for receiving USDC. The full test suite and
the deletion test run **without** any credentials.

```bash
git clone <repo> && cd the-house

# 1. environment + deps
python -m venv .venv && source .venv/bin/activate
pip install -e .            # or: pip install -r requirements.lock.txt

# 2. run the tests (no credentials needed)
pytest tests/ -q           # 78 passing

# 3. run the deletion gate (no credentials needed)
.venv/bin/python deletion_test.py

# 4. to serve real money: copy the env template and fill in the house's OWN creds
cp .env.example .env       # then edit .env (see below)
.venv/bin/python -m uvicorn app.x402.seller:app --host 0.0.0.0 --port 8090
```

Open `http://localhost:8090/` — the live landing page, a mirror of the house's
state. The free observability surface:

| Route | What it is |
|-------|------------|
| `/` | landing page (live stat mirror) |
| `/manifest` | machine-readable service descriptor |
| `/house/ledger` | the money shot — callers (anonymized to last-6), dedup + scar + job state |
| `/house/jobs` | live job state machines (F4) |
| `/house/audit` | the self-auditor (failure rate, trust drift) |
| `/house/calibrate` | the price calibrator |
| `/intel/quote` | **the paid route** (x402-gated) |

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

## Make a real payment (Gate 3)

`scripts/pay.sh` executes one real, reproducible Base-mainnet x402 payment to
the paid route and logs the settlement tx hash for Basescan. Run it twice and
the second call is a **$0 dedup repeat** — the F2 money beat.

```bash
HOUSE_BUYER_KEY=0x... scripts/pay.sh        # first call: pays base
HOUSE_BUYER_KEY=0x... scripts/pay.sh        # second call: $0 (dedup hit)
```

The buyer key comes from `HOUSE_BUYER_KEY` (or `HOUSE_KEYFILE`) — never
hardcoded in the tree.

---

## The money model

Pricing is per-caller, driven by the trust ledger segment, and settled
**onchain-honestly**. The buyer signs an EIP-3009 authorization for exactly
the quoted amount, so the settlement on Base is always the **base** price;
the house's per-caller price is achieved *around* the settlement, not by
altering it:

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
core/house.py          the money engine (House) — the real money flow
core/wallet.py         money-OUT (HouseWallet / safe DryRunWallet)
core/settle_journal.py the server-side money ledger (decodes PAYMENT-RESPONSE)
core/executor.py       F4 — re-drive jobs stuck mid-serve after a restart
core/trust.py          the trust ledger (F1) — segments + deltas
core/dedup.py          dedup-as-revenue (F2)
core/scars.py          failure → scar → compiled policy (F3)
core/jobs.py           the kill-resilient job store (F4)
core/memory.py         THE MEMORY LAYER (Sibyl) — the load-bearing module
core/acp.py            the ACP / Virtuals delegator
core/audit.py          the self-auditor
core/calibrate.py      the price calibrator
deletion_test.py       the runnable gate
```

`core/memory.py` wraps the Sibyl Memory client and is the single gate for
every feature: every read/write above funnels through it, and
`HouseMemory.disabled()` (driven by `SIBYL_DISABLED`) collapses them all at
once. **That** is what makes the memory load-bearing — there is one seam, and
removing it removes the product.

### Verified against the real x402 2.x exact scheme

- The handler runs **before** settlement; a ≥400 response **cancels** it — so
  a refusal (banned / risky prepay) is genuinely uncharged.
- The settlement tx hash is not in the request; it arrives in the
  `PAYMENT-RESPONSE` header **after** the handler. The journal lives in a thin
  ASGI middleware that decodes that header (FIX-4).
- The exact scheme re-verifies the buyer's signed amount at settle, so the
  onchain settlement is always base — per-caller pricing is done via rebate /
  prepay, never by changing the settle amount.

---

## Tests

```bash
pytest tests/ -q
```

- `test_pricing_enforced.py` — the money engine driven directly (no network,
  no facilitator, no acp): segment pricing, VIP/regular/repeat rebates, risky
  prepay, banned refusal, scar citation, journal, dedup.
- `test_jobs.py` — F4 kill-resume + **no double charge**.
- `test_scars.py` / `test_dedup.py` / `test_trust.py` / `test_memory.py` —
  each memory feature.
- `test_seller.py` — the routes, incl. the landing page reading the collapse
  under `SIBYL_DISABLED=1`.

---

## License

MIT — see [LICENSE](LICENSE).

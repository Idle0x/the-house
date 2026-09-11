# THE HOUSE

> **On Base, every x402 payment is anonymous and stateless. A seller can't tell a 20-transaction VIP from a first-time scammer.**
> 
> **THE HOUSE is a memory-native x402 service that fixes this.** Loyal wallets pay less, cheaters are refused before a byte is served, and repeat questions are answered free. **Delete the memory, and the entire business model collapses.**

**Live Demo:** [the-house-production-10ea.up.railway.app](https://the-house-production-10ea.up.railway.app/)  
**Demo Video:** [Watch on YouTube](https://youtu.be/1gWCZYmMKRA)  
**Full Manual:** [DOCUMENTATION.md](DOCUMENTATION.md) · [live /docs](https://the-house-production-10ea.up.railway.app/docs)

---

## How This Scores (The Judge's Checklist)

| Criteria | Proof in this Repo / Demo |
| :--- | :--- |
| **Memory is Load-Bearing** (Gate) | Run `.venv/bin/python deletion_test.py`. Flip `SIBYL_DISABLED=1` and watch pricing, refusals, and dedup instantly collapse to stateless defaults. |
| **Base Multiplier (×1.15)** | Real x402 USDC settlements on Base mainnet. Loyalty discounts are executed as verifiable cashback rebates on Basescan. |
| **Virtuals Multiplier (×1.25)** | Real ACP delegation exercised. Memory flips a provider from `unknown` to `proven`, programmatically altering on-chain hiring terms. |
| **Innovation** | Memory is not a side-log; it is the active pricing, refusal, and contract-term engine. |
| **Credible Execution** | 60 genuine passing tests, deterministic `demo_beats.py`, fully audited codebase. |

---

## Built With

* **Core:** Python 3.11, FastAPI, SQLite
* **Memory:** [Sibyl Memory](https://sibyllabs.org) (The load-bearing layer)
* **Payments:** Base Mainnet, x402 Protocol (Coinbase Facilitator), USDC
* **Agents:** Virtuals Protocol ACP (ERC-8183)

---

## Where Memory is Load-Bearing (< 2 Minute Proof)

The single load-bearing module is **[`core/memory.py`](core/memory.py)**. Every room funnels its reads and writes through it. One environment flag (`SIBYL_DISABLED=1`) collapses all of them at once. 

Memory is on the critical path, not a side log, at these exact call sites in the shared paid pipeline ([`core/house.py`](core/house.py)):
1. **Pricing/Refusal:** `TrustLedger.recall(payer)` → [`core/trust.py`](core/trust.py) decides the segment (VIP, regular, risky, banned) *before* any work begins.
2. **Dedup-as-Revenue:** `dedup.is_repeat()` → [`core/dedup.py`](core/dedup.py) serves cached answers at **net $0**.
3. **Policy Compilation:** `scars.active_rules()` → [`core/scars.py`](core/scars.py) hardens the serve against repeated failure patterns.
4. **On-Chain Terms:** `acp.terms_from_row()` → [`core/acp.py`](core/acp.py) uses the provider's remembered record to set real ACP delegation terms.

**The Ultimate Proof:** Run the deletion gate. No setup required.
```bash
.venv/bin/python deletion_test.py
```
*Exit code 0 = the gate holds (deletion breaks the product). Exit 1 = memory is decorative.*

---

## Architecture: One Memory, Five Rooms

```text
                    ┌───────────────────────────────────┐
                    │       THE HOUSE MEMORY            │
                    │       (Sibyl SQLite DB)           │
                    │                                   │
                    │  • Trust scores & segments        │
                    │  • Dedup cache (repeat queries)   │
                    │  • Scar policies (compiled rules) │
                    │  • Provider performance records   │
                    └─────────────────┬─────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
    ┌───────────────┐         ┌───────────────┐         ┌───────────────┐
    │ 1. COUNTER    │         │ 2. UNDERWRIT. │         │ 3. FRONT OFF. │
    │               │         │               │         │               │
    │ READ → PRICE  │         │ READ → PREMIUM│         │ READ → HIRE   │
    │ WRITE → TRUST │         │ WRITE → CLAIM │         │ WRITE → PERF  │
    └───────┬───────┘         └───────┬───────┘         └───────┬───────┘
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
    ┌───────────────┐         ┌───────────────┐         ┌───────────────┐
    │ 4. WATCHTOWER │         │ 5. GALLERY    │         │               │
    │               │         │               │         │               │
    │ READ → REFUSE │         │ READ → RENDER │         │               │
    │ WRITE → VERDICT│        │ WRITE → LOG   │         │               │
    └───────────────┘         └───────────────┘         └───────────────┘

═══════════════════════════════════════════════════════════════════════════
        SIBYL_DISABLED=1  (MEMORY DELETED / DISABLED)
        ↓
        ALL ROOMS COLLAPSE TO STATELESS PRICE LIST
        No pricing tiers • No refusals • No dedup • No scars • No trust
═══════════════════════════════════════════════════════════════════════════
```

---

## Try It Live & Run Locally

**3 Commands to verify the core claims (no API keys needed):**

```bash
git clone https://github.com/Idle0x/the-house && cd the-house
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 1. Prove the gate (no credentials needed)
.venv/bin/python deletion_test.py

# 2. Rehearse the 4 money beats deterministically (no network, no real money)
.venv/bin/python scripts/demo_beats.py all

# 3. Run the full test suite
pytest tests/ -q  # 60 passing
```

### Environment Variables
To serve real money or enable outbound rebates, copy the template and configure:
```bash
cp .env.example .env
```
| Variable | Purpose |
| :--- | :--- |
| `CDP_API_KEY_ID` / `SECRET` | Coinbase CDP facilitator for x402 settlements. |
| `HOUSE_WALLET` | The receiving EVM wallet address (Base). |
| `HOUSE_LIVE_MONEY_OUT` | Set to `1` to enable real cashback rebates (Default: `0` / Dry-run). |
| `SIBYL_DISABLED` | Set to `1` to prove the deletion gate (Default: `0`). |

---

## The Five Rooms

One memory, five uses. Each room is a pure read/write over the same caller record the house keeps.

| Room | What it does | What memory decides |
| :--- | :--- | :--- |
| **1 · The Counter** ([`core/house.py`](core/house.py)) | Paid financial-intel endpoint | Prices by history. VIPs pay less, strangers pay list, banned wallets are refused *before a byte is served*. Repeats are net $0. |
| **2 · Underwriting Desk** ([`core/bonds.py`](core/bonds.py)) | Guarantees on *other agents'* work | Prices bond premiums from the provider's remembered quality/scar history. Past claims cap the book. |
| **3 · Front Office** ([`core/scout.py`](core/scout.py)) | Scout reports + hiring terms | Hires agents and prices terms from their *real* on-chain performance. Proven = trusted; scarred = harsh terms. |
| **4 · The Watchtower** ([`core/watch.py`](core/watch.py)) | Counterparty screening | Refuses wash/sybil/self-dealing payments using deterministic rules over the house's own caller graph. |
| **5 · The Gallery** ([`app/x402/gallery.py`](app/x402/gallery.py)) | The live workbench | Configure a subject + function on the left, watch the run/quote/memory-trace/artifact unfold in the console, with the journals dock below. |

---

## The Money Model (Real, Not Simulated)

Payments settle **on-chain on Base mainnet** via the x402 exact scheme. The wire *always* settles the full list price. Per-caller pricing is achieved *around* the settlement via the memory interceptor:

```text
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   WALLET    │─────▶│  x402 QUOTE │─────▶│   SIGN TX   │
│  (User)     │      │  ($0.01)    │      │  (EIP-3009) │
└─────────────┘      └─────────────┘      └──────┬──────┘
                                                  │
                                                  ▼
                                         ┌───────────────┐
                                         │   SETTLE ON   │
                                         │   BASE (USDC) │
                                         │   Full price  │
                                         └───────┬───────┘
                                                 │
                                                 ▼
                               ┌─────────────────────────────────┐
                               │      MEMORY INTERCEPTOR           │
                               │  (core/house.py + core/memory.py)│
                               │                                   │
                               │  1. Recall wallet → trust score   │
                               │  2. Check dedup → repeat?         │
                               │  3. Check scars → hardened?       │
                               │  4. Check watchtower → banned?    │
                               │                                   │
                               │  DECISION:                        │
                               │  • VIP → 20% cashback             │
                               │  • Regular → 5% cashback          │
                               │  • Repeat → 100% cashback ($0)    │
                               │  • Banned → REFUSE (uncharged)    │
                               └────────────────┬──────────────────┘
                                                │
                                                ▼
                                       ┌────────────────┐
                                       │  SERVE ANSWER  │
                                       │  + JOURNAL     │
                                       └────────┬───────┘
                                                │
                                                ▼
                                       ┌────────────────┐
                                       │  CASHBACK TX   │
                                       │  (if eligible) │
                                       │  Verifiable on │
                                       │  Basescan      │
                                       └────────────────┘
```
* **New:** Pays base price.
* **Regular/VIP:** Pays base price, house sends a **real cashback rebate** (5% or 20%) from its own wallet. Verifiable on Basescan.
* **Repeat (Dedup):** Pays base price, house rebates 100% (served from cache at net $0).
* **Risky:** Refused (403) until a prepay credit covers the surcharge.
* **Banned:** Refused *before* the job is created. Under the x402 exact scheme, a ≥400 response **cancels the settlement**, meaning the buyer is genuinely uncharged.

---

## Rehearse the Money Beats (Gate 6)

`scripts/demo_beats.py` replays each of the four core money beats through the **real engine** against a throwaway memory DB. Deterministic, reproducible, no network:

```bash
.venv/bin/python scripts/demo_beats.py all
#    [PASS] recall    — fresh session prices a repeat buyer (regular, net $0 dedup)
#    [PASS] badactor  — burned wallet refused before serving, uncharged
#    [PASS] scar      — 3x failure compiles policy; fresh session cites the scar
#    [PASS] kill      — kill -9 mid-serve; restart settles exactly once
# VERDICT: ALL BEATS CLEAN — ready for camera.
```

---

## Codebase Map

The app is split so the money logic is **unit-testable without the network**:
- **[`app/x402/seller.py`](app/x402/seller.py)**: The thin FastAPI/x402 boundary — paid routes, free ledgers, memory gate, operator triggers.
- **[`app/x402/landing.py`](app/x402/landing.py)** / **[`app/x402/gallery.py`](app/x402/gallery.py)**: The homepage (live mirror of house state) and the workbench (configure + console + journals dock). Shared pop-up in [`app/x402/_tryit.py`](app/x402/_tryit.py).
- **[`core/house.py`](core/house.py)**: The money engine and shared paid pipeline.
- **[`core/memory.py`](core/memory.py)**: **THE MEMORY LAYER** (Sibyl) — the load-bearing module. Gate logic lives in [`core/wipe.py`](core/wipe.py), chain re-learning in [`core/reseed.py`](core/reseed.py).
- **[`core/trust.py`](core/trust.py) / [`core/dedup.py`](core/dedup.py) / [`core/scars.py`](core/scars.py)**: The pure-function decision engines. Pricing constants audited in [`core/config.py`](core/config.py).
- **[`core/watch.py`](core/watch.py)** / **[`core/scout.py`](core/scout.py)** / **[`core/bonds.py`](core/bonds.py)**: Watchtower screens, front-office hiring, underwriting desk.
- **[`core/dossier.py`](core/dossier.py)**: The cross-room entity file (Room 5's read side).
- **[`core/acp.py`](core/acp.py)**: The Virtuals ACP delegator (reads memory to set on-chain terms).
- **[`core/wallet.py`](core/wallet.py)**: Money-OUT (DryRun-safe by default). Receipts in [`core/settle_journal.py`](core/settle_journal.py).
- **[`core/jobs.py`](core/jobs.py)** / **[`core/executor.py`](core/executor.py)**: Crash-proof work orders (resume exactly once, never double-charge).
- **[`core/audit.py`](core/audit.py)** / **[`core/calibrate.py`](core/calibrate.py)**: The house auditing and grading itself.
- **[`core/identity.py`](core/identity.py)** / **[`core/redact.py`](core/redact.py)**: Wallet validation at the door, address masking on every public output.
- **[`scripts/`](scripts/)**: [`buyer.py`](scripts/buyer.py) (scripted $0.01 purchase), [`demo_beats.py`](scripts/demo_beats.py) (deterministic demo rehearsal), [`verify_sibyl_sdk.py`](scripts/verify_sibyl_sdk.py) (memory SDK checks).
- **[`tests/`](tests/)**: 60 tests, one per real contract. Deletion gate: [`deletion_test.py`](deletion_test.py).

---

## Reproducing the Project

Everything below runs on a fresh clone. No API keys, no network, no money — except where marked.

**1. Install and prove the gate (2 minutes).** The headline claim — *delete the memory and the business collapses* — reproduces in one command:
```bash
git clone https://github.com/Idle0x/the-house && cd the-house
python -m venv .venv && source .venv/bin/activate
pip install -e .
.venv/bin/python deletion_test.py   # exit 0 = gate holds
```
**2. Rehearse the money beats (deterministic).** [`scripts/demo_beats.py`](scripts/demo_beats.py) drives the real engine ([`core/house.py`](core/house.py)) against a throwaway database — same code path as production, on-chain settlement elided:
```bash
.venv/bin/python scripts/demo_beats.py all
# recall (repeat served net $0) · badactor (refused, uncharged) ·
# scar (failures compile to policy) · kill (crash resumes, settles once)
```
**3. Run the suite.** [`tests/`](tests/) holds 60 tests, one per real contract: pricing, discounts, free repeats, uncharged refusals, crash recovery, scars, screens, bonds, hiring, dossier, and the memory gate itself.
```bash
pytest tests/ -q  # 60 passing
```
**4. Reproduce the trust ladder.** Serve one fresh wallet twice through the engine: first serve moves trust 50 → 53, the identical repeat serves at net $0 with trust frozen (anti-farming). Nine more *distinct* serves reach 80 + 10 visits = VIP (20% back). The [`#scoring` docs on the landing page](https://the-house-production-10ea.up.railway.app/#scoring) state every rule.
**5. Reproduce live (small real money).** Fund any wallet with ~$0.50 USDC on Base, open `/gallery` on the [live deploy](https://the-house-production-10ea.up.railway.app/gallery), ask a question ($0.01), ask it again ($0 net), then flip *disable memory* and watch the same question cost full price with no history. Every receipt links to Basescan.

---

## Contributing to the Project

**Setup:** clone, `pip install -e .`, copy `.env.example` to `.env` only if you need live money (CDP keys, house wallet). Never commit `.env`, databases, or anything under `data/` — all git-ignored.

**The one gate every change must pass:**
```bash
pytest tests/ -q
.venv/bin/python deletion_test.py
```
A red suite or a broken deletion gate is a veto, no exceptions.

**Where to touch what:** money logic belongs in [`core/`](core/) (unit-testable, no network imports); [`app/x402/seller.py`](app/x402/seller.py) stays a thin boundary (routes + middleware only); pages live in [`app/x402/landing.py`](app/x402/landing.py) / [`app/x402/gallery.py`](app/x402/gallery.py) with shared pieces in [`app/x402/_tryit.py`](app/x402/_tryit.py). Pricing constants live in [`core/config.py`](core/config.py) — tune values, never hide formulas. New paid behavior needs a test in the owning room's suite (`tests/test_<room>.py`), following the one-test-per-contract convention.

**Money-out safety:** rebates and payouts stay DryRun unless `HOUSE_LIVE_MONEY_OUT=1` *and* a real `HOUSE_WALLET` are set. Tests and demos must never move real money — [`scripts/demo_beats.py`](scripts/demo_beats.py) and the suite elide settlement by design.

---

## License

MIT — see [LICENSE](LICENSE).
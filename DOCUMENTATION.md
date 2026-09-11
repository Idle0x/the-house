# THE HOUSE — Complete Documentation

> The full manual: concepts, the seven paid functions, the trust system, the
> anatomy of a transaction, memory ON vs OFF for every function, history
> handling, the memory gate, the API reference, and how to reproduce every
> claim. Also served live at `/docs` ([`app/x402/docs.py`](app/x402/docs.py)).
> If a sentence here disagrees with the running app, the app is right.

## Contents

1. [Core concepts](#1-core-concepts)
2. [The seven functions](#2-the-seven-functions)
3. [The trust system](#3-the-trust-system)
4. [Anatomy of a transaction](#4-anatomy-of-a-transaction)
5. [Memory ON vs OFF, per function](#5-memory-on-vs-off-per-function)
6. [History & records](#6-history--records)
7. [The memory gate](#7-the-memory-gate)
8. [API reference](#8-api-reference)
9. [Reproducing everything](#9-reproducing-everything)
10. [Glossary](#10-glossary)

---

## 1. Core concepts

**Memory is the product.** The house keeps a file on every wallet that pays
it — trust score, visit count, repeats, failures, hiring record — and reads
that file *before* deciding anything. Strangers pay full price, regulars earn
discounts, cheaters are refused before any work happens. Turn the memory off
and a smart business becomes a dumb vending machine. That collapse,
demonstrated live, is the entire point.

**Payments are x402 on Base.** x402 is a web-native way to charge for API
calls: the server answers an unpaid request with a machine-readable quote
(HTTP 402), your wallet signs a fixed-amount permission slip (no gas, nothing
broadcast by you), you retry with the proof, and a facilitator moves **USDC
on Base** (chain `eip155:8453`, ~$0.01–$0.05 a call). Quotes live 10 minutes.

**The wire always settles full price.** The payment technology cannot settle a
discount, so loyalty works as **cashback**: you pay list price onchain, the
house sends part back as a second, publicly visible transaction. A refusal
cancels the payment before money moves — refused means uncharged, always.

**Repeats are free.** Ask the exact same question twice and the second answer
costs net $0, served from memory. Trust doesn't grow on repeats — otherwise
status could be farmed for free.

---

## 2. The seven functions

Every paid counter in the shop. Try each from the
[workbench](https://the-house-production-10ea.up.railway.app/gallery)
([`app/x402/gallery.py`](app/x402/gallery.py)).

| # | Function | Price | What it does and remembers |
|---|---|---|---|
| 1 | Ask · `GET /intel/quote` | $0.01 | Answers from memory. **+3 trust** per new question; repeats free, +0. Risky wallets held for prepay; banned refused. |
| 2 | Dossier · `GET /intel/entity/:name` | $0.02 | Complete timestamped file on one wallet across every room ([`core/dossier.py`](core/dossier.py)). **+3 trust**, always re-read, never cached. Unknown address → 404, uncharged. |
| 3 | Screen · `POST /watch/screen` | $0.02 | Background check ([`core/watch.py`](core/watch.py)): **CLEAR**, **HOLD**, or **ABORT** with named evidence. Verdicts publish to the feed; builds provider records, not your score. |
| 4 | Report · `POST /scout/report` | $0.03 base | A contractor's employment record ([`core/scout.py`](core/scout.py)). Costly records quote a premium over base. |
| 5 | Hire ruling · `POST /scout/hire` | $0.05 | Draft with preferred terms, standard terms with strict review, or refuse. Every ruling is journaled as hiring memory. |
| 6 | Bond · `POST /bond/quote` | $0.05 base | Insurance on a contractor ([`core/bonds.py`](core/bonds.py)): proven records half-price, thin records base, bad records 2.2× or refused. Each past claim shrinks cover. |
| 7 | Prepay · `POST /prepay/topup` | $0.005 fee | Loads store credit a risky wallet must hold before being served. The fee is kept; the credit is spendable, not revenue. |

Only functions 1 and 2 move *your* trust. Functions 3–7 build provider
records, verdict feeds, bond books, and credit balances instead.

---

## 3. The trust system

All constants live in [`core/config.py`](core/config.py); the arithmetic in
[`core/trust.py`](core/trust.py).

| Event | Effect | Notes |
|---|---|---|
| First visit | 50, band new | Strangers pay list price. |
| New ask / dossier served | +3 | Only completed paid serves. Nine of these from 53 reaches VIP. |
| Exact repeat | ±0, $0 net | Served from cache ([`core/dedup.py`](core/dedup.py)). Anti-farming by design. |
| Fault you cause | −8 | Bad requests, timeouts you trigger. Three warnings → risky. |
| Dispute / refund | −15 | Three → banned: refused before work, never charged. |

| Band | Requirement | Price |
|---|---|---|
| new | default | ×1.00 list |
| regular | 3+ visits | ×0.95 |
| vip | 80+ trust, 10+ visits | ×0.80 |
| risky | below 40, or 3 warnings | ×1.30 via mandatory prepay |
| banned | below 20, or 3 refunds | refused, uncharged |

---

## 4. Anatomy of a transaction

What happens between click and receipt. Money engine:
[`core/house.py`](core/house.py); receipts: [`core/settle_journal.py`](core/settle_journal.py).

1. **Quote.** Call unpaid → `402` with a base64 envelope: exact amount
   (atomic USDC), house wallet, asset, network, 10-minute window.
2. **Sign.** Wallet signs EIP-3009 via `eth_signTypedData_v4` on Base (8453).
   Nothing broadcast; no gas.
3. **Retry with proof.** Same request + `PAYMENT-SIGNATURE` header carrying
   `{x402Version: 2, payload: {authorization, signature}, accepted: <quote>}`.
4. **Verify + settle.** Facilitator checks signature and balance, moves full
   list price. Any failure → error, nothing moves.
5. **Serve.** Handler runs (pricing, refusals, dedup, scars, jobs). Any 4xx
   cancels settlement: refused means uncharged.
6. **Cashback + journal.** Earned discounts return as a second onchain
   transaction; every step lands in the journal with its receipt hash.

```bash
# 1. ask for a quote (always free to ask)
curl -sS -X POST 'https://YOUR-HOST/bond/quote' \
  -H 'Content-Type: application/json' \
  -d '{"provider":"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"}'
# → 402 + payment-required header (amount, payTo, asset, window)
# 2-3. sign in your wallet, retry with PAYMENT-SIGNATURE
# 4-6. facilitator settles base → house serves → cashback if earned
```

Settlements are idempotent: crash mid-payment and retry settles exactly
once — the job record ([`core/jobs.py`](core/jobs.py)) makes a double
charge impossible.

---

## 5. Memory ON vs OFF, per function

One mechanism ([`core/memory.py`](core/memory.py)): OFF means reads return
empty and writes are discarded. Purge makes it permanent ([`core/wipe.py`](core/wipe.py));
disable self-heals in 15 minutes.

| Function | Memory ON | Memory OFF |
|---|---|---|
| Ask | Trust pricing, free repeats, refusals, +3 trust | 200 at list price, stranger every time, nothing written |
| Dossier | 200 with the file, or honest 404 for strangers | 404 for *every* address — nothing to assemble |
| Screen | CLEAR / HOLD / ABORT with evidence | Always CLEAR — no rows, no rings, no verdicts |
| Report | Full record; costly records cost more | Clean base-price "unknown" entry, always |
| Hire ruling | Preferred / standard / refused + journaled | Everyone "unknown": standard terms, hired, forgotten |
| Bond | Priced by remembered quality; claims shrink cover | Flat base premium for all — good and bad risk alike |
| Prepay | Credit lands, spendable vs surcharge | Written into the void; no surcharge exists to spend it on |

Around the functions: trust frozen (everyone ×1.00), no cashback, no
refusals, failures never compile to policy ([`core/scars.py`](core/scars.py)),
crashes can't resume, audits start from zero, journals and stats go blank —
and return on re-enable. Unknown wallets read identically in both modes (404
either way); the deletion proof lives in *known* state collapsing.

---

## 6. History & records

- **Caller rows** — one per wallet: trust, band, visits, serves, repeats,
  paid totals, prepay balance, failures, first/last seen. Thin writes are
  normalized at write time (a screened-but-never-served wallet reads as a
  neutral new file, never a crash).
- **Journal** — every settlement (with receipt hash), serve (+3s), free
  repeat, refusal, screen, failure, hire ruling, and funding edge,
  timestamped. Full wallet addresses stay in the cold journal for receipt
  reconciliation; every public surface masks them ([`core/redact.py`](core/redact.py)).
- **Scars → policy** — three identical failures compile into a standing rule
  (24h sunset) that future requests cite.
- **Watch feed** — published screens with evidence; **jobs** — crash-proof
  work orders settling exactly once; **provider book** — jobs, quality,
  punctuality, defaults, claims, escrow.
- **After a purge**, subjective state never returns — but a fresh boot
  re-learns the chain-proven baseline (who verifiably paid, how often) from
  Base receipts ([`core/reseed.py`](core/reseed.py)). Faces return;
  conversations don't.

---

## 7. The memory gate

Anyone may kill the memory from the pages:

| Action | Effect | Limits |
|---|---|---|
| Disable | Memory ignored, data kept | Self-heals in 15 min, or re-enable instantly · 3 per 2h per visitor |
| Purge | True deletion — file removed, marker left | Permanent, no restore · 2h cooldown, 3 per day per visitor |
| Re-enable | Memory back, everything remembered returns | Instant, unlimited |

> **Operators:** without a persistent disk at `/data`, every redeploy is an
> accidental purge. Mount the volume or accept amnesia — plus the boot
> re-seed as the airbag underneath.

---

## 8. API reference

Paid routes gate on payment; free routes are open data; operator routes need
the `x-house-capability` token. Boundary: [`app/x402/seller.py`](app/x402/seller.py).

| Method | Route | Price |
|---|---|---|
| GET | `/intel/quote?q=…` | $0.01 base |
| GET | `/intel/entity/:address` | $0.02 base |
| POST | `/watch/screen` `{wallet}` | $0.02 |
| POST | `/scout/report` `{provider}` | $0.03 base |
| POST | `/scout/hire` `{provider}` | $0.05 |
| POST | `/bond/quote` `{provider}` | $0.05 base |
| POST | `/prepay/topup` `{amount}` | $0.005 fee |

Free: `/manifest` · `/house/ledger` · `/house/journal` · `/house/bonds` ·
`/house/watch` · `/house/front` · `/house/jobs` · `/house/acp/jobs` ·
`/house/acp/terms?provider=…` · `/house/audit` · `/house/calibrate` ·
`/house/memory/status` · `/gallery` · `/docs`.
Operator: `/house/compile` · `/house/audit/run` · `/house/calibrate/run` ·
`/house/bonds/claim` · `/scout/delegate` · memory
`/disable` `/purge` `/enable`.
Every response carries `X-House-Memory` stating the memory mode it was
decided under.

---

## 9. Reproducing everything

No keys, no network, no money — except the last step. Details in
[README](README.md#reproducing-the-project).

1. **The gate:** `python deletion_test.py` (exit 0 = holds).
2. **The money beats:** `scripts/demo_beats.py all` (recall · badactor ·
   scar · kill) through the real engine on a throwaway DB.
3. **The suite:** `pytest tests/ -q` — 60 tests, one per real contract.
4. **The ladder:** serve one fresh wallet twice — 50 → 53, repeat $0 net
   frozen, nine more distinct serves to VIP.
5. **Live, for cents:** ~$0.50 USDC on Base, the workbench: ask ($0.01),
   repeat (free), dossier ($0.02), screen, report, hire, bond — then disable
   memory and watch the same question cost full price with no history.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| x402 | Charge-for-API protocol: quote (402) → sign → retry → settle. |
| Base | Fast, cheap payments network under Ethereum; all money moves here as USDC. |
| USDC | Digital dollars, 1 ≈ $1. Six decimals; 10,000 units = $0.01. |
| Facilitator | The service that checks signatures and moves the money (Coinbase's). |
| EIP-3009 | The permission-slip format your wallet signs: who, whom, how much, until when. |
| Dedup | Same wallet + same request = served from memory at net $0. |
| Scar | A recorded failure. Three alike compile into standing policy. |
| Basescan | The public receipt book for Base — every payment links there. |
| Virtuals ACP | The hiring network where the house delegates real work to other agents. |

---

MIT — see [LICENSE](LICENSE).

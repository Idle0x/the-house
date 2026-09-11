"""THE HOUSE — formal documentation page (/docs).

A single, complete manual: concepts, the seven paid functions, the trust
system, the transaction flow, memory ON vs OFF for every function, history
handling, the memory gate, the full API reference, and how to reproduce
every claim. Static HTML (no JS, no polling) in the house's own design
language: near-black, single glacier accent, Space Grotesk + Inter +
Space Mono.

Rendering: plain ``.replace()`` for the commit token (kept consistent with
landing.py / gallery.py so no template engine is ever involved).
"""
from __future__ import annotations

import html


def render_docs(*, commit: str = "") -> str:
    """Render the docs page. Only the commit token is dynamic."""
    return _DOCS_HTML.replace("__COMMIT__", html.escape(commit))


_DOCS_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>the-house · documentation — Sibyl Labs Hackathon 2026</title>
<meta name="description" content="The complete manual for THE HOUSE: concepts, functions, trust, transactions, memory on vs off, API reference, reproduction.">
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E%3Crect%20width='32'%20height='32'%20fill='%230A0A0A'/%3E%3Cpath%20d='M11%208v16M21%208v16M11%2016h10'%20stroke='%238FC7FF'%20stroke-width='3'%20stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#07090B; --surface:#0D1013; --surface2:#12161A;
    --border:rgba(255,255,255,.07); --border2:rgba(255,255,255,.11);
    --text:#F2F5F7; --muted:#79808A; --dim:#A9B2BC;
    --glacier:#8FC7FF; --glacier-deep:#4E8FE0; --glacier-dim:rgba(143,199,255,.10);
    --green:#27AE60; --red:#C0392B; --amber:#E8C547;
    --grotesk:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;
    --sans:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    --mono:"Space Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  html{scroll-behavior:smooth;}
  html,body{background:var(--bg);color:var(--text);
    font-family:var(--sans);-webkit-font-smoothing:antialiased;}
  body{line-height:1.65;overflow-x:hidden;font-size:15px;}
  a{color:var(--glacier);text-decoration:none;border-bottom:1px solid rgba(143,199,255,.3);}
  a:hover{border-bottom-color:var(--glacier);}
  ::selection{background:var(--glacier);color:#0A0A0A;}

  .ambient{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
  .grid-bg{position:absolute;inset:0;
    background-image:linear-gradient(rgba(143,199,255,.035) 1px,transparent 1px),
      linear-gradient(90deg,rgba(143,199,255,.035) 1px,transparent 1px);
    background-size:56px 56px;
    -webkit-mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 30%,transparent 75%);
            mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 30%,transparent 75%);}
  .glow{position:absolute;border-radius:50%;filter:blur(90px);opacity:.4;}
  .glow.a{width:520px;height:520px;top:-160px;left:8%;background:radial-gradient(circle,rgba(143,199,255,.22),transparent 70%);}

  .bar{width:100%;border-bottom:1px solid var(--border);
    background:rgba(10,10,10,.82);backdrop-filter:blur(14px);position:sticky;top:0;z-index:50;}
  .bar-inner{max-width:960px;margin:0 auto;padding:16px 32px 12px;
    display:flex;flex-direction:column;gap:12px;}
  .bar-row{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
  .bar-row.bottom{border-top:1px solid rgba(255,255,255,.05);padding-top:10px;flex-wrap:nowrap;}
  .bar-row.bottom .nav{flex:0 0 auto;min-width:0;flex-wrap:nowrap;}
  .bar-row.bottom .nav a{flex-shrink:0;}
  .bar-row.bottom .hash{flex:1 1 auto;min-width:0;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;text-align:right;}
  .wordmark{font-family:var(--grotesk);font-weight:700;letter-spacing:.16em;font-size:19px;
    display:flex;align-items:center;gap:10px;}
  .wordmark .tick{color:var(--glacier);}
  .wordmark .home-link{color:inherit;border:none;display:inline-flex;align-items:center;gap:10px;}
  .wordmark .home-link:hover{color:var(--glacier);}
  .wordmark .tag-stack{display:inline-flex;flex-direction:column;gap:1px;line-height:1.4;}
  .wordmark .sub{color:var(--muted);font-weight:400;font-size:11px;letter-spacing:.1em;font-family:var(--grotesk);}
  .hash{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.03em;opacity:.85;}
  .nav{display:flex;gap:20px;font-family:var(--mono);font-size:12px;color:var(--muted);align-items:center;}
  .nav a{color:var(--muted);border:none;transition:color .15s;}
  .nav a:hover{color:var(--glacier);}
  .nav a.active{color:var(--glacier);}
  .nav a.try-live{color:var(--glacier);border:1px solid rgba(143,199,255,.5);
    padding:6px 14px;border-radius:20px;background:rgba(143,199,255,.07);
    box-shadow:0 0 14px rgba(143,199,255,.28),inset 0 0 8px rgba(143,199,255,.08);
    white-space:nowrap;}
  .nav a.try-live:hover{color:#d6e9ff;border-color:var(--glacier);}

  .wrap{max-width:960px;margin:0 auto;padding:48px 32px 64px;position:relative;z-index:2;}
  .kicker{font-family:var(--mono);font-size:12px;letter-spacing:.22em;
    color:var(--glacier);text-transform:uppercase;margin-bottom:18px;display:flex;align-items:center;gap:10px;}
  .kicker::before{content:"";width:26px;height:1px;background:var(--glacier);}
  h1{font-family:var(--grotesk);font-size:clamp(30px,4vw,44px);line-height:1.1;
    font-weight:700;letter-spacing:-.02em;max-width:24ch;}
  h1 em{font-style:normal;color:var(--glacier);}
  .lede{color:var(--dim);font-size:17px;max-width:64ch;margin:20px 0 0;line-height:1.7;}
  .toc{border:1px solid var(--border);border-radius:12px;background:var(--surface);
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    padding:22px 24px;margin:36px 0 8px;box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .toc .t-head{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;
    color:var(--muted);margin-bottom:12px;}
  .toc ol{list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:6px 20px;}
  .toc li a{border:none;color:var(--dim);font-size:14px;}
  .toc li a:hover{color:var(--glacier);}
  .toc li a span.n{font-family:var(--mono);color:var(--glacier);margin-right:8px;font-size:12px;}
  @media(max-width:640px){.toc ol{grid-template-columns:1fr;}}

  section.doc{padding:44px 0 8px;border-bottom:1px solid var(--border);}
  section.doc:last-of-type{border-bottom:none;}
  section.doc h2{font-family:var(--grotesk);font-size:clamp(21px,2.6vw,28px);font-weight:700;
    letter-spacing:-.01em;margin-bottom:6px;display:flex;align-items:center;gap:12px;}
  section.doc h2 .n{font-family:var(--mono);font-size:13px;color:var(--glacier);font-weight:400;}
  section.doc h2::before{content:"";width:22px;height:1px;background:var(--glacier);opacity:.7;flex-shrink:0;}
  section.doc .sub{color:var(--muted);font-size:14px;margin-bottom:18px;max-width:66ch;}
  section.doc p{color:var(--dim);margin-bottom:14px;max-width:72ch;}
  section.doc p b,section.doc li b{color:var(--text);font-weight:600;}
  section.doc ul{margin:0 0 14px 20px;color:var(--dim);max-width:70ch;}
  section.doc li{margin-bottom:8px;}
  section.doc .hl{color:var(--glacier);font-weight:600;}

  table{width:100%;border-collapse:collapse;margin:18px 0 20px;font-size:13.5px;
    border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--surface);}
  th{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
    color:var(--muted);text-align:left;padding:11px 14px;border-bottom:1px solid var(--border);
    background:rgba(255,255,255,.015);font-weight:400;}
  td{padding:11px 14px;border-bottom:1px solid rgba(255,255,255,.04);color:var(--dim);
    vertical-align:top;line-height:1.6;}
  tr:last-child td{border-bottom:none;}
  td:first-child{font-family:var(--mono);font-size:12.5px;color:var(--text);white-space:nowrap;}
  td .pos{color:var(--green);font-weight:700;} td .neg{color:#e0a49c;font-weight:700;}
  td .neu{color:var(--glacier);font-weight:700;}
  code{font-family:var(--mono);font-size:12.5px;color:#c9dcff;background:rgba(143,199,255,.07);
    border:1px solid rgba(143,199,255,.18);border-radius:6px;padding:1px 6px;}
  pre{background:#0b0d10;border:1px solid var(--border);border-radius:12px;padding:16px 18px;
    overflow-x:auto;margin:16px 0 20px;}
  pre code{background:none;border:none;padding:0;display:block;line-height:1.7;white-space:pre;}
  pre .cm{color:var(--muted);}
  .note{border-left:3px solid var(--glacier);background:var(--glacier-dim);
    padding:12px 16px;border-radius:0 8px 8px 0;font-size:14px;color:#c9dcff;margin:16px 0;max-width:72ch;}
  .note.warn{border-left-color:var(--red);background:rgba(192,57,43,.08);color:#e0a49c;}
  .note b{color:var(--text);}

  footer{margin-top:48px;padding-top:24px;border-top:1px solid var(--border);
    display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
    font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--muted);}
  footer .foot-links{display:flex;gap:18px;flex-wrap:wrap;}
  footer .foot-links a{color:var(--muted);border-bottom:1px solid transparent;}
  footer .foot-links a:hover{color:var(--glacier);border-color:var(--glacier);}
  @media(max-width:560px){.wrap{padding:32px 16px 40px;}table{font-size:12.5px;}}
  @media (prefers-reduced-motion:reduce){html{scroll-behavior:auto;}}
</style>
</head>
<body>
<div class="ambient" aria-hidden="true"><div class="grid-bg"></div><div class="glow a"></div></div>

<header class="bar">
  <div class="bar-inner">
    <div class="bar-row top">
      <div class="wordmark"><a href="/" class="home-link">THE<span class="tick">·</span>HOUSE</a><span class="tag-stack"><span class="sub">memory-native x402</span></span></div>
      <div class="nav">
        <a href="/gallery" class="try-live">try it live</a>
        <a href="/docs" class="active">docs</a>
        <a href="/house/ledger">ledger</a>
        <a href="/manifest">manifest</a>
      </div>
    </div>
    <div class="bar-row bottom">
      <div class="nav"><span style="color:var(--muted)">documentation</span></div>
      <div class="hash">commit __COMMIT__</div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="kicker">the manual</div>
  <h1>Everything the house knows, <em>written down.</em></h1>
  <p class="lede">Concepts, the seven paid functions, the trust system, the anatomy of a payment, what changes when memory goes off, the records it keeps, the kill-switch, the full API reference, and how to reproduce every claim. If a sentence here disagrees with the running app, the app is right and this page has a bug — tell us.</p>

  <nav class="toc">
    <div class="t-head">contents</div>
    <ol>
      <li><a href="#concepts"><span class="n">01</span>Core concepts</a></li>
      <li><a href="#functions"><span class="n">02</span>The seven functions</a></li>
      <li><a href="#trust"><span class="n">03</span>The trust system</a></li>
      <li><a href="#transactions"><span class="n">04</span>Anatomy of a transaction</a></li>
      <li><a href="#modes"><span class="n">05</span>Memory on vs off, per function</a></li>
      <li><a href="#history"><span class="n">06</span>History &amp; records</a></li>
      <li><a href="#gate"><span class="n">07</span>The memory gate</a></li>
      <li><a href="#api"><span class="n">08</span>API reference</a></li>
      <li><a href="#reproducing"><span class="n">09</span>Reproducing everything</a></li>
      <li><a href="#glossary"><span class="n">10</span>Glossary</a></li>
    </ol>
  </nav>

  <section class="doc" id="concepts">
    <h2><span class="n">01</span>Core concepts</h2>
    <div class="sub">Four ideas; everything else is detail.</div>
    <p><b>Memory is the product.</b> The house keeps a file on every wallet that pays it — trust score, visit count, repeats, failures, hiring record — and reads that file <em>before</em> deciding anything. Strangers pay full price; regulars earn discounts; cheaters are refused before any work happens. Turn the memory off and a smart business becomes a dumb vending machine. That collapse, demonstrated live, is the entire point.</p>
    <p><b>Payments are x402 on Base.</b> x402 is a web-native way to charge for API calls: the server answers an unpaid request with a machine-readable quote (HTTP 402), your wallet signs a fixed-amount permission slip (no gas, nothing broadcast by you), you retry with the proof, and a facilitator moves <b>USDC on Base</b> (chain <code>eip155:8453</code>, ~$0.01–$0.05 a call). Quotes live 10 minutes.</p>
    <p><b>The wire always settles full price.</b> The payment technology cannot settle a discount, so loyalty works as <b>cashback</b>: you pay list price onchain, the house sends part back as a second, publicly visible transaction. A refusal cancels the payment before money moves — refused means uncharged, always.</p>
    <p><b>Repeats are free.</b> Ask the exact same question twice and the second answer costs net $0, served from memory. Trust doesn't grow on repeats — otherwise status could be farmed for free.</p>
  </section>

  <section class="doc" id="functions">
    <h2><span class="n">02</span>The seven functions</h2>
    <div class="sub">Every paid counter in the shop. Try each from the <a href="/gallery">workbench</a>.</div>
    <table>
      <tr><th>#</th><th>Function</th><th>Price</th><th>What it does and remembers</th></tr>
      <tr><td>1</td><td>Ask · <code>GET /intel/quote</code></td><td>$0.01</td><td>Answers from memory. <b>+3 trust</b> per new question; repeats free, +0. Risky wallets are held for prepay; banned wallets refused.</td></tr>
      <tr><td>2</td><td>Dossier · <code>GET /intel/entity/:name</code></td><td>$0.02</td><td>The complete timestamped file on one wallet across every room. <b>+3 trust</b>, always re-read (never cached). Unknown address → 404, uncharged.</td></tr>
      <tr><td>3</td><td>Screen · <code>POST /watch/screen</code></td><td>$0.02</td><td>Background check: <b>CLEAR</b>, <b>HOLD</b>, or <b>ABORT</b> with named evidence. Verdicts publish to the feed; builds provider records, not your score.</td></tr>
      <tr><td>4</td><td>Report · <code>POST /scout/report</code></td><td>$0.03 base</td><td>A contractor's employment record (jobs, quality, punctuality, defaults, claims). Costly records quote a premium over base.</td></tr>
      <tr><td>5</td><td>Hire ruling · <code>POST /scout/hire</code></td><td>$0.05</td><td>Draft with preferred terms, standard terms with strict review, or refuse. Every ruling is journaled as hiring memory.</td></tr>
      <tr><td>6</td><td>Bond · <code>POST /bond/quote</code></td><td>$0.05 base</td><td>Insurance on a contractor: proven records half-price, thin records base, bad records 2.2× or refused. Each past claim shrinks what the house will cover.</td></tr>
      <tr><td>7</td><td>Prepay · <code>POST /prepay/topup</code></td><td>$0.005 fee</td><td>Loads store credit a risky wallet must hold before being served. A $0.005 handling fee; the credit itself is spendable, not revenue.</td></tr>
    </table>
    <p>Only functions 1 and 2 move <em>your</em> trust. Functions 3–7 build provider records, verdict feeds, bond books, and credit balances instead.</p>
  </section>

  <section class="doc" id="trust">
    <h2><span class="n">03</span>The trust system</h2>
    <div class="sub">Exact rules. <a href="/#scoring">Short version on the homepage</a>.</div>
    <table>
      <tr><th>Event</th><th>Effect</th><th>Notes</th></tr>
      <tr><td>First visit</td><td><span class="neu">50, band new</span></td><td>Strangers pay list price.</td></tr>
      <tr><td>New ask / dossier served</td><td><span class="pos">+3</span></td><td>Only completed paid serves. Nine of these from 53 reaches VIP.</td></tr>
      <tr><td>Exact repeat</td><td><span class="neu">±0, $0 net</span></td><td>Served from cache. Anti-farming by design.</td></tr>
      <tr><td>Fault you cause</td><td><span class="neg">−8</span></td><td>Bad requests, timeouts you trigger. Three warnings → risky.</td></tr>
      <tr><td>Dispute / refund</td><td><span class="neg">−15</span></td><td>Three → banned: refused before work, never charged.</td></tr>
    </table>
    <table>
      <tr><th>Band</th><th>Requirement</th><th>Price</th></tr>
      <tr><td>new</td><td>default</td><td>×1.00 list</td></tr>
      <tr><td>regular</td><td>3+ visits</td><td>×0.95</td></tr>
      <tr><td>vip</td><td>80+ trust, 10+ visits</td><td>×0.80</td></tr>
      <tr><td>risky</td><td>below 40, or 3 warnings</td><td>×1.30 via mandatory prepay</td></tr>
      <tr><td>banned</td><td>below 20, or 3 refunds</td><td>refused, uncharged</td></tr>
    </table>
  </section>

  <section class="doc" id="transactions">
    <h2><span class="n">04</span>Anatomy of a transaction</h2>
    <div class="sub">What happens between your click and the receipt, verbatim.</div>
    <p><b>1. Quote.</b> You call the endpoint with no payment. It answers <code>402</code> with a signed envelope: exact amount (atomic USDC), the house wallet, asset, network, and a 10-minute window.</p>
    <p><b>2. Sign.</b> Your wallet signs an EIP-3009 authorization for <em>exactly</em> the quoted amount via <code>eth_signTypedData_v4</code> on Base (chain 8453). Nothing is broadcast; no gas is spent.</p>
    <p><b>3. Retry with proof.</b> The same request goes again carrying a <code>PAYMENT-SIGNATURE</code> header: the signed authorization plus the exact quote it answers.</p>
    <p><b>4. Verify + settle.</b> The facilitator checks the signature and your balance, then moves full list price to the house wallet. Any failure here returns an error and nothing moves.</p>
    <p><b>5. Serve.</b> The handler runs — pricing, refusals, dedup, scars, jobs. Any 4xx cancels the settlement: <b>refused means uncharged</b>.</p>
    <p><b>6. Cashback + journal.</b> Earned discounts return as a second onchain transaction; every step lands in the journal with its receipt hash.</p>
<pre><code><span class="cm"># 1. ask for a quote (always free to ask)</span>
curl -sS -X POST 'https://YOUR-HOST/bond/quote' \
  -H 'Content-Type: application/json' \
  -d '{"provider":"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"}'
<span class="cm"># → 402 + payment-required header (amount, payTo, asset, window)</span>
<span class="cm"># 2-3. sign in your wallet, retry with PAYMENT-SIGNATURE</span>
<span class="cm"># 4-6. facilitator settles base → house serves → cashback if earned</span></code></pre>
    <div class="note"><b>Settlements are idempotent:</b> crashing mid-payment and retrying settles exactly once — the job record makes a second charge impossible. Verified by the kill-resume rehearsal.</div>
  </section>

  <section class="doc" id="modes">
    <h2><span class="n">05</span>Memory on vs off, per function</h2>
    <div class="sub">One mechanism: off means reads return empty and writes are discarded. Purge makes it permanent; disable self-heals in 15 minutes.</div>
    <table>
      <tr><th>Function</th><th>Memory ON</th><th>Memory OFF</th></tr>
      <tr><td>Ask</td><td>Trust pricing, free repeats, refusals, +3 trust</td><td>200 at list price, stranger every time, nothing written</td></tr>
      <tr><td>Dossier</td><td>200 with the file, or honest 404 for strangers</td><td>404 for <em>every</em> address — nothing to assemble</td></tr>
      <tr><td>Screen</td><td>CLEAR / HOLD / ABORT with evidence</td><td>Always CLEAR — no rows, no rings, no verdicts</td></tr>
      <tr><td>Report</td><td>Full record; costly records cost more</td><td>Clean base-price "unknown" entry, always</td></tr>
      <tr><td>Hire ruling</td><td>Preferred / standard / refused + journaled</td><td>Everyone "unknown": standard terms, hired, forgotten</td></tr>
      <tr><td>Bond</td><td>Priced by remembered quality; claims shrink cover</td><td>Flat base premium for all — good and bad risk alike</td></tr>
      <tr><td>Prepay</td><td>Credit lands, spendable vs surcharge</td><td>Written into the void; no surcharge exists to spend it on</td></tr>
    </table>
    <p>Around the functions: trust frozen (everyone ×1.00), no cashback, no refusals, failures never compile to policy, crashes can't resume, audits start from zero, journals and stats go blank — and return on re-enable. Unknown wallets read identically in both modes (404 either way); the deletion proof lives in <em>known</em> state collapsing.</p>
  </section>

  <section class="doc" id="history">
    <h2><span class="n">06</span>History &amp; records</h2>
    <div class="sub">What is kept, where, and what survives a wipe.</div>
    <p><b>Caller rows</b> — one per wallet: trust, band, visits, serves, repeats, paid totals, prepay balance, failures, first/last seen. Thin writes are normalized at write time (a screened-but-never-served wallet reads as a neutral new file, never a crash).</p>
    <p><b>Journal</b> — every settlement (with receipt hash), serve (+3s), free repeat, refusal, screen, failure, hire ruling, and funding edge, timestamped. Full wallet addresses stay in the cold journal for receipt reconciliation; every public surface masks them.</p>
    <p><b>Scars → policy</b> — three identical failures compile into a standing rule (e.g. switch upstream, refuse-until, prepay-required) that future requests cite; rules sunset after 24 hours.</p>
    <p><b>Watch feed</b> — published screens with evidence; <b>jobs</b> — crash-proof work orders settling exactly once; <b>provider book</b> — jobs, quality, punctuality, defaults, claims, escrow.</p>
    <p><b>After a purge</b>, subjective state never returns — but a fresh boot re-learns the chain-proven baseline (who verifiably paid, how often) from Base receipts. Faces return; conversations don't.</p>
  </section>

  <section class="doc" id="gate">
    <h2><span class="n">07</span>The memory gate</h2>
    <div class="sub">Anyone may kill the memory from the pages. The rules:</div>
    <table>
      <tr><th>Action</th><th>Effect</th><th>Limits</th></tr>
      <tr><td>Disable</td><td>Memory ignored, data kept</td><td>Self-heals in 15 min, or re-enable instantly · 3 per 2h per visitor</td></tr>
      <tr><td>Purge</td><td>True deletion — file removed, marker left</td><td>Permanent, no restore · 2h cooldown, 3 per day per visitor</td></tr>
      <tr><td>Re-enable</td><td>Memory back, everything remembered returns</td><td>Instant, unlimited</td></tr>
    </table>
    <div class="note warn"><b>Operators:</b> without a persistent disk at <code>/data</code>, every redeploy is an accidental purge. Mount the volume or accept amnesia — plus the boot re-seed as the airbag underneath.</div>
  </section>

  <section class="doc" id="api">
    <h2><span class="n">08</span>API reference</h2>
    <div class="sub">Paid routes gate on payment; free routes are open data; operator routes need a capability token.</div>
    <table>
      <tr><th>Method</th><th>Route</th><th>Price</th></tr>
      <tr><td>GET</td><td><code>/intel/quote?q=…</code></td><td>$0.01 base</td></tr>
      <tr><td>GET</td><td><code>/intel/entity/:address</code></td><td>$0.02 base</td></tr>
      <tr><td>POST</td><td><code>/watch/screen</code> <code>{wallet}</code></td><td>$0.02</td></tr>
      <tr><td>POST</td><td><code>/scout/report</code> <code>{provider}</code></td><td>$0.03 base</td></tr>
      <tr><td>POST</td><td><code>/scout/hire</code> <code>{provider}</code></td><td>$0.05</td></tr>
      <tr><td>POST</td><td><code>/bond/quote</code> <code>{provider}</code></td><td>$0.05 base</td></tr>
      <tr><td>POST</td><td><code>/prepay/topup</code> <code>{amount}</code></td><td>$0.005 fee</td></tr>
    </table>
    <table>
      <tr><th>Method</th><th>Route</th><th>Reads</th></tr>
      <tr><td>GET</td><td><code>/manifest</code></td><td>Service menu, prices, live totals</td></tr>
      <tr><td>GET</td><td><code>/house/ledger</code></td><td>Callers, trust, dedup, recent money</td></tr>
      <tr><td>GET</td><td><code>/house/journal</code></td><td>Season log, newest first</td></tr>
      <tr><td>GET</td><td><code>/house/bonds</code> · <code>/house/watch</code> · <code>/house/front</code> · <code>/house/jobs</code></td><td>Bond book · verdict feed · draft board · job states</td></tr>
      <tr><td>GET</td><td><code>/house/acp/jobs</code> · <code>/house/acp/terms?provider=…</code></td><td>Live delegation status · free terms preview</td></tr>
      <tr><td>GET</td><td><code>/house/audit</code> · <code>/house/calibrate</code></td><td>Last self-audit · last self-grade</td></tr>
      <tr><td>GET/POST</td><td><code>/house/memory/status</code> · <code>/disable</code> · <code>/purge</code> · <code>/enable</code></td><td>The gate (limits above)</td></tr>
    </table>
    <p>Operator routes (<code>/house/compile</code>, <code>/house/audit/run</code>, <code>/house/calibrate/run</code>, <code>/house/bonds/claim</code>, <code>/scout/delegate</code>) require the <code>x-house-capability</code> token. Every response carries <code>X-House-Memory</code> stating the memory mode it was decided under.</p>
  </section>

  <section class="doc" id="reproducing">
    <h2><span class="n">09</span>Reproducing everything</h2>
    <div class="sub">No keys, no network, no money — except the last step.</div>
    <p><b>1. The gate:</b> <code>python deletion_test.py</code> flips memory off and asserts the collapse (exit 0 = holds).</p>
    <p><b>2. The money beats:</b> <code>scripts/demo_beats.py all</code> replays recall, bad-actor refusal, scar compilation, and kill-resume through the real engine on a throwaway database.</p>
    <p><b>3. The suite:</b> <code>pytest tests/ -q</code> — 60 tests, one per real contract.</p>
    <p><b>4. The ladder:</b> serve one fresh wallet twice — first serve 50 → 53, identical repeat $0 net with trust frozen, nine more distinct serves to VIP.</p>
    <p><b>5. Live, for cents:</b> ~$0.50 USDC on Base, the <a href="/gallery">workbench</a>: ask ($0.01), repeat (free), dossier ($0.02), screen, report, hire, bond — then disable memory and watch the same question cost full price with no history.</p>
  </section>

  <section class="doc" id="glossary">
    <h2><span class="n">10</span>Glossary</h2>
    <div class="sub">Plain words for the few terms this manual can't avoid.</div>
    <table>
      <tr><th>Term</th><th>Meaning</th></tr>
      <tr><td>x402</td><td>Charge-for-API protocol: quote (402) → sign → retry → settle.</td></tr>
      <tr><td>Base</td><td>Fast, cheap payments network under Ethereum; all money moves here as USDC.</td></tr>
      <tr><td>USDC</td><td>Digital dollars, 1 ≈ $1. Six decimals; 10,000 units = $0.01.</td></tr>
      <tr><td>Facilitator</td><td>The service that checks signatures and moves the money. Ours is Coinbase's.</td></tr>
      <tr><td>EIP-3009</td><td>The permission-slip format your wallet signs: who, whom, how much, until when.</td></tr>
      <tr><td>Dedup</td><td>Same wallet + same request = served from memory at net $0.</td></tr>
      <tr><td>Scar</td><td>A recorded failure. Three alike compile into standing policy.</td></tr>
      <tr><td>Basescan</td><td>The public receipt book for Base — every payment links there.</td></tr>
      <tr><td>Virtuals ACP</td><td>The hiring network where the house delegates real work to other agents.</td></tr>
    </table>
  </section>

  <footer>
    <div class="foot-main" style="display:flex;gap:22px;flex-wrap:wrap;align-items:center;min-width:0;">
      <span>the-house · base mainnet · x402 exact scheme</span>
      <span class="foot-links">
        <a href="/gallery">workbench</a>
        <a href="/docs">docs</a>
        <a href="/manifest">manifest</a>
      </span>
    </div>
    <span>commit __COMMIT__</span>
  </footer>
</div>
</body>
</html>
"""

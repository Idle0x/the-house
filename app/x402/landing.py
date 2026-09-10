"""THE HOUSE — landing page (the house's own design language).

Forensic / investigative, near-black + a single glacier (ice-blue) accent, Space Grotesk
+ Space Mono. The page is a LIVE mirror of the house's real state — every
number is rendered from the actual memory entities, dedup stats, onchain
history and ACP wallet, never canned. When memory is off (disabled or
purged — the public memory gate) the aggregates collapse and the page reads
the collapse: the graph empties, every stat drops, the pulse goes red. That
is the gate, visible.

Architecture: the server injects a JSON state blob (``window.__HOUSE__``)
built from the real aggregates; the page renders it for first paint, then
keeps itself fresh by polling the free /house/* ledgers + /manifest +
/house/memory/status. No framework, no build step, no external JS. All
animations are gated by ``prefers-reduced-motion`` and a no-JS guard.

Kept in its own module so ``app/x402/seller.py`` stays a thin FastAPI/x402
boundary (F4 — the app is not a god-object).
"""
from __future__ import annotations

import json

from app.x402._tryit import TRYIT_CSS, TRYIT_HTML, TRYIT_JS

# The real, Basescan-verifiable onchain history of the house's live Gate 1
# run (Sep 8, Base mainnet) — see shared/BUILD-STATE.md. These are REAL txs,
# Genuine house settlements on Base mainnet — every row verified onchain:
# the house wallet actually RECEIVED the USDC (not a payment to a different
# wallet). Block timestamps are the real onchain times. Each links to Basescan.
REAL_SETTLEMENT_TXS = [
    {
        "hash": "0xd31364dcd77ce5888d0408a005fbc220db1bd5cc42210b69a72a5c3b0631c69e",
        "label": "settlement · buyer → house wallet",
        "usdc": 0.01,
        "ts": "2026-09-08 05:42 UTC",
        "note": "caller 890fae · trust 50→53",
    },
]

# The real ACP (Virtuals) delegation proof — 3 jobs completed on Base mainnet
# Sep 7 (see shared/specs/acp-plan.md). Real escrow funded + released. Each
# escrow_tx is the actual USDC transfer from the house wallet
# (0x9fd05b6ff42f2ece0e1ef418cbca00b716ee6753) to the ACP Core contract
# (0x238e541bfefd82238730d00a2208e5497f1832e0), Basescan-verifiable.
ACP_AGENT = {
    "name": "the-house",
    "agent_id": "01a07d2a-5d23-7d59-af53-c53d0146e2b5",
    "wallet": "0x9fd05b6ff42f2ece0e1ef418cbca00b716ee6753",
    "acp_core": "0x238e541bfefd82238730d00a2208e5497f1832e0",
    "chain_id": 8453,
}
ACP_JOBS = [
    {"id": "77330", "offering": "prompt_optimization", "usdc": 0.02,
     "provider": "0x436f324eff0b32a405c5b9102e1a6ef85451cec1",
     "provider_name": "BitsAndBytesBack", "status": "completed",
     "ts": "2026-09-07 20:57 UTC",
     "escrow_tx": "0x939a1fc8ab94d5aeed5725aaca6e6c96122a5d95c624e835a045855b5492a277"},
    {"id": "77332", "offering": "page_markdown", "usdc": 0.02,
     "provider": "0xec4bc04310925326ff80daf419a3861173865689",
     "provider_name": "aiworker-data", "status": "completed",
     "ts": "2026-09-07 21:07 UTC",
     "escrow_tx": "0xebcf9d0c137b5216df45fe49a6187ae4a3e3c76bc378cdcece9003d283ec756a"},
    {"id": "77338", "offering": "agentRiskCheck", "usdc": 0.05,
     "provider": "0xecf9773b50f01f3a97b087a6ecdf12a71afc558c",
     "provider_name": "TheMetaBot", "status": "completed",
     "ts": "2026-09-07 21:14 UTC",
     "escrow_tx": "0xfce202ce19be3d9359e4ba4a5181342b1bd6f02153b0c05ee65a8c38a7206d30"},
]

# The house's real journal (the "season log"), newest first, from onchain
# timestamps. Only genuine house transactions appear here — 1 settlement +
# 3 ACP delegations. (The live SettlementJournal appends new live serves on
# top of this.)
REAL_JOURNAL = [
    {"ts": "2026-09-08 05:42 UTC", "kind": "settle",
     "text": "settlement · $0.01 received by house wallet · caller 890fae · trust 50→53 · tx 0xd31364dc…"},
    {"ts": "2026-09-07 21:14 UTC", "kind": "job",
     "text": "ACP job 77338 · agentRiskCheck · $0.05 escrow funded for TheMetaBot · tx 0xfce202ce…"},
    {"ts": "2026-09-07 21:07 UTC", "kind": "job",
     "text": "ACP job 77332 · page_markdown · $0.02 escrow funded for aiworker-data · tx 0xebcf9d0c…"},
    {"ts": "2026-09-07 20:57 UTC", "kind": "job",
     "text": "ACP job 77330 · prompt_optimization · $0.02 escrow funded for BitsAndBytesBack · tx 0x939a1fc8…"},
]


def build_landing_state(*, memory_mode: str, callers: list, providers: list,
                        dedup: dict, scars_total: int, scars_rules: int,
                        commit: str, base_price: float, repo_url: str,
                        ts: str, wipe_status: dict, public_url: str = "") -> dict:
    """Assemble the JSON state blob the landing page renders + polls.

    All values come from the real aggregates passed in (memory entities,
    dedup stats, front office, wipe controller). The onchain tx + ACP job
    lists are the house's real, documented, Basescan-verifiable history.
    ``public_url`` is the externally reachable origin (Railway domain) used
    for the try-it commands — NEVER the internal host/IP.
    """
    return {
        "memory": memory_mode,  # "live" | "disabled" | "purged"
        "commit": commit,
        "base_price": round(float(base_price), 2),
        "repo_url": repo_url,
        "public_url": public_url,
        "ts": ts,
        "callers": callers,
        "providers": providers,
        "dedup": {
            "hits": int(dedup.get("hits", 0)),
            "usdc_saved": round(float(dedup.get("usdc_saved", 0.0)), 4),
        },
        "scars": {"total": scars_total, "rules": scars_rules},
        # headline aggregates (no zeros when real data exists)
        "stats": {
            "callers": len(callers),
            "providers": len(providers),
            "dedup_hits": int(dedup.get("hits", 0)),
            "usdc_saved": round(float(dedup.get("usdc_saved", 0.0)), 4),
            "trust": round(sum(c.get("trust_score", 0) for c in callers) / len(callers), 1) if callers else 0,
            "quality": round(sum(p.get("quality_score", 0) for p in providers) / len(providers), 2) if providers else 0,
            "jobs": sum(p.get("jobs_done", 0) for p in providers),
            "scars": scars_total,
            "rules": scars_rules,
        },
        "txs": REAL_SETTLEMENT_TXS,
        "acp": {
            "agent": ACP_AGENT,
            "jobs": ACP_JOBS,
            "total_jobs": len(ACP_JOBS),
            "total_usdc": round(sum(j["usdc"] for j in ACP_JOBS), 4),
        },
        "wipe": wipe_status,
    }


def render_landing(state: dict) -> str:
    """Render the landing page from the state blob. The JSON is embedded raw
    (not HTML-escaped) because it lives inside a <script> block where entities
    are not decoded; the payload is our own controlled data (no </script>)."""
    payload = json.dumps(state)
    tryit_js = ("window.__TRYIT__ = {public_url: "
                + json.dumps(state.get("public_url", ""))
                + "};\n" + TRYIT_JS)
    return (_LANDING_HTML
            .replace("__TRYIT_CSS__", TRYIT_CSS)
            .replace("__TRYIT_HTML__", TRYIT_HTML)
            .replace("__TRYIT_JS__", tryit_js)
            .replace("__STATE__", payload))


_LANDING_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>the-house — memory-native x402 · Sibyl Labs Hackathon 2026</title>
<meta name="description" content="A memory-native x402 service on Base mainnet. Built on Sibyl Memory for the Sibyl Labs Hackathon 2026.">
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E%3Crect%20width='32'%20height='32'%20fill='%230A0A0A'/%3E%3Cpath%20d='M11%208v16M21%208v16M11%2016h10'%20stroke='%238FC7FF'%20stroke-width='3'%20stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#07090B; --surface:#0D1013; --border:rgba(255,255,255,.07); --surface2:#12161A;
    --text:#F2F5F7; --muted:#79808A; --dim:#A9B2BC;
    --glacier:#8FC7FF; --glacier-deep:#4E8FE0; --glacier-dim:rgba(143,199,255,.10);
    --green:#27AE60; --red:#C0392B; --cyan:#00D9FF;
    --grotesk:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;
    --mono:"Space Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  html{scroll-behavior:smooth;}
  html,body{background:var(--bg);color:var(--text);
    font-family:var(--grotesk);-webkit-font-smoothing:antialiased;}
  body{line-height:1.55;overflow-x:hidden;}
  a{color:inherit;text-decoration:none;}
  .wrap{max-width:1180px;margin:0 auto;padding:0 32px 64px;position:relative;z-index:2;}
  ::selection{background:var(--glacier);color:#0A0A0A;}

  /* ---------- tooltips: JS-managed floating box (see initTooltips) ---------- */

  /* ---------- hackathon badge ---------- */
  .hack-badge{display:inline-flex;align-items:center;gap:10px;margin-bottom:26px;
    font-family:var(--mono);font-size:11px;letter-spacing:.18em;color:var(--glacier);
    border:1px solid rgba(143,199,255,.4);background:rgba(143,199,255,.06);
    padding:8px 16px;border-radius:30px;cursor:default;}
  .hack-badge::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--glacier);
    animation:breath 2.6s ease-in-out infinite;}

  /* ---------- ambient background ---------- */
  .ambient{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
  .grid-bg{position:absolute;inset:0;
    background-image:linear-gradient(rgba(143,199,255,.035) 1px,transparent 1px),
      linear-gradient(90deg,rgba(143,199,255,.035) 1px,transparent 1px);
    background-size:56px 56px;
    -webkit-mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 30%,transparent 75%);
            mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 30%,transparent 75%);}
  .glow{position:absolute;border-radius:50%;filter:blur(90px);opacity:.4;
    will-change:transform;}
  .glow.a{width:520px;height:520px;top:-160px;left:8%;background:radial-gradient(circle,rgba(143,199,255,.22),transparent 70%);}
  .glow.b{width:420px;height:420px;top:20%;right:-120px;background:radial-gradient(circle,rgba(0,217,255,.12),transparent 70%);}
  .glow.c{width:380px;height:380px;bottom:-120px;left:30%;background:radial-gradient(circle,rgba(143,199,255,.10),transparent 70%);}

  /* ---------- top bar ---------- */
  .bar{width:100%;border-bottom:1px solid var(--border);
    background:rgba(10,10,10,.82);backdrop-filter:blur(14px);position:sticky;top:0;z-index:50;}
  .bar-inner{max-width:1180px;margin:0 auto;padding:20px 32px 16px;
    display:flex;flex-direction:column;gap:14px;}
  .bar-row{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
  .bar-row.bottom{border-top:1px solid rgba(255,255,255,.05);padding-top:12px;flex-wrap:nowrap;}
  .bar-row.bottom .nav{flex:0 0 auto;min-width:0;flex-wrap:nowrap;}
  .bar-row.bottom .nav a{flex-shrink:0;}
  .bar-row.bottom .hash{flex:1 1 auto;min-width:0;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;text-align:right;}
  .wordmark{font-weight:700;letter-spacing:.16em;font-size:19px;display:flex;align-items:center;gap:10px;}
  .wordmark .tick{color:var(--glacier);}
  .wordmark .home-link{color:inherit;display:inline-flex;align-items:center;gap:10px;transition:color .15s;}
  .wordmark .home-link:hover{color:var(--glacier);}
  .wordmark .tag-stack{display:inline-flex;flex-direction:column;gap:1px;line-height:1.4;}
  .wordmark .sub{color:var(--muted);font-weight:400;font-size:11px;letter-spacing:.1em;}
  .status{display:flex;align-items:center;gap:9px;font-family:var(--mono);
    font-size:12px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--green);
    animation:breath 3s ease-in-out infinite;}
  .dot.off{background:var(--red);animation:none;box-shadow:0 0 0 0 transparent;}
  .hash{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.03em;opacity:.85;}
  .nav{display:flex;gap:20px;font-family:var(--mono);font-size:12px;color:var(--muted);}
  .nav a:hover{color:var(--glacier);}
  .nav a.gate-link{color:#ff8a7a;border:1px solid rgba(192,57,43,.5);padding:5px 12px;border-radius:20px;transition:all .18s ease;}
  .nav a.gate-link:hover{color:#ffb3a8;border-color:var(--red);background:rgba(192,57,43,.16);}
  /* header memory button — red, opens the disable modal */
  .status-group .gate-link{color:#ff8a7a;border:1px solid rgba(192,57,43,.55);padding:5px 12px;border-radius:20px;
    transition:all .18s ease;font-family:var(--mono);font-size:12px;letter-spacing:.08em;
    background:transparent;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;}
  .status-group .gate-link:hover{color:#ffb3a8;border-color:var(--red);background:rgba(192,57,43,.16);}
  .status .recover{color:var(--red);font-size:11px;letter-spacing:.08em;}
  .status-group{display:flex;align-items:center;gap:14px;}
  .hash a{color:var(--muted);text-decoration:none;border-bottom:1px dashed rgba(255,255,255,.2);}
  .hash a:hover{color:var(--glacier);border-bottom-color:var(--glacier);}
  @keyframes breath{0%,100%{opacity:.55;box-shadow:0 0 0 0 rgba(39,174,96,.4)}
    50%{opacity:1;box-shadow:0 0 12px 2px rgba(39,174,96,.45)}}

  /* ---------- hero ---------- */
  .hero{padding:72px 0 20px;position:relative;}
  .hero .kicker{font-family:var(--mono);font-size:12px;letter-spacing:.22em;
    color:var(--glacier);text-transform:uppercase;margin-bottom:22px;display:flex;align-items:center;gap:10px;}
  .hero .kicker::before{content:"";width:26px;height:1px;background:var(--glacier);}
  .hero h1{font-size:clamp(28px,3.4vw,46px);line-height:1.1;font-weight:700;
    letter-spacing:-.02em;max-width:22ch;}
  .hero h1 .line{display:block;overflow:hidden;}
  .hero h1 .line span{display:block;transform:translateY(110%);animation:rise .8s cubic-bezier(.16,1,.3,1) forwards;}
  .hero h1 .line:nth-child(1) span{animation-delay:.05s;}
  .hero h1 .line:nth-child(2) span{animation-delay:.18s;}
  .hero h1 .line:nth-child(3) span{animation-delay:.31s;}
  .hero h1 em{font-style:normal;color:var(--glacier);}
  @keyframes rise{to{transform:translateY(0)}}
  @keyframes shine{0%{background-position:200% 0}100%{background-position:-200% 0}}
  .hero .sub{font-size:clamp(15px,1.8vw,19px);color:var(--dim);max-width:62ch;
    margin:26px 0 0;opacity:0;animation:fade .8s ease .5s forwards;}
  @keyframes fade{to{opacity:1}}
  .hero .cta{display:flex;gap:14px;margin-top:34px;flex-wrap:wrap;
    opacity:0;animation:fade .8s ease .7s forwards;}
  .btn{display:inline-flex;align-items:center;gap:9px;padding:12px 20px;border-radius:10px;
    font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:13.5px;font-weight:600;letter-spacing:-.01em;
    cursor:pointer;transition:transform .18s ease,box-shadow .18s ease,background .18s ease,border-color .18s ease;
    border:1px solid transparent;}
  .btn.primary{background:var(--glacier);color:#0A0A0A;}
  .btn.primary:hover{transform:translateY(-2px);box-shadow:0 8px 24px -8px rgba(143,199,255,.45);}
  .btn.primary:active{transform:translateY(0);}
  .btn.ghost{background:rgba(255,255,255,.03);border-color:var(--border);color:var(--text);}
  .btn.ghost:hover{border-color:rgba(143,199,255,.4);color:var(--glacier);transform:translateY(-2px);}
  .btn.danger{background:rgba(192,57,43,.1);border-color:rgba(192,57,43,.4);color:#e0a49c;}
  .btn.danger:hover{border-color:var(--red);color:#ffb3a8;transform:translateY(-2px);}
  .btn.soft{background:rgba(143,199,255,.06);border-color:rgba(143,199,255,.35);color:var(--glacier);}
  .btn.soft:hover{border-color:var(--glacier);color:#bcdcff;transform:translateY(-2px);}
  /* recommendation annotations on the memory-gate buttons */
  .btn .rec,.btn .nrec{font-size:10px;letter-spacing:.04em;opacity:.75;font-weight:500;}
  .btn .rec{color:var(--glacier);}
  .btn .nrec{color:#e0a49c;}
  .trust-strip{display:flex;flex-wrap:wrap;gap:8px 26px;margin-top:40px;
    font-family:var(--mono);font-size:11px;letter-spacing:.1em;color:var(--muted);
    text-transform:uppercase;opacity:0;animation:fade .8s ease .9s forwards;}
  .trust-strip b{color:var(--dim);font-weight:400;}

  /* ---------- hero memory graph ---------- */
  .graph-wrap{margin-top:48px;border:1px solid var(--border);border-radius:12px;
    background:linear-gradient(180deg,rgba(255,255,255,.02),rgba(255,255,255,.004));
    padding:22px;position:relative;overflow:hidden;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .graph-wrap .ghead{display:flex;justify-content:space-between;align-items:center;
    font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:12px;font-weight:600;
    letter-spacing:.06em;color:var(--muted);
    text-transform:uppercase;margin-bottom:16px;flex-wrap:wrap;gap:10px;}
  .graph-wrap .ghead .live{display:flex;align-items:center;gap:7px;color:var(--green);}
  .graph-wrap .ghead .live .dot{width:7px;height:7px;}
  .graph-wrap .ghead .live.off{color:var(--red);}
  .graph-wrap .ghead .live.off .dot,.rp-live.off .dot{background:var(--red);animation:none;box-shadow:0 0 0 0 transparent;}
  svg.graph{width:100%;height:auto;display:block;}
  .node{transition:opacity .4s ease;}
  .node circle{transition:r .4s ease;}
  .node .lbl{font-family:var(--mono);font-size:10px;fill:var(--dim);letter-spacing:.05em;}
  .edge{stroke:var(--border);stroke-width:1.5;}
  .edge.mem{stroke:var(--glacier);stroke-dasharray:6 5;animation:dash 3s linear infinite;}
  .edge.live{stroke:var(--green);stroke-width:2;stroke-dasharray:4 4;animation:dash 2.4s linear infinite;}
  @keyframes dash{to{stroke-dashoffset:-22}}
  .pulse-dot{animation:nodePulse 2.4s ease-in-out infinite;transform-origin:center;}
  @keyframes nodePulse{0%,100%{opacity:.35}50%{opacity:1}}

  /* ---------- live ledger ---------- */
  .section{padding:64px 0 12px;}
  .section h2{font-size:12px;font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-weight:600;letter-spacing:.12em;
    text-transform:uppercase;color:var(--glacier);margin-bottom:8px;}
  .section .lead{font-size:clamp(20px,2.8vw,28px);font-weight:700;letter-spacing:-.015em;
    max-width:26ch;line-height:1.15;margin-bottom:20px;}
  .section .lead em{font-style:normal;color:var(--glacier);}
  .section .section-note{color:var(--muted);font-size:14px;line-height:1.6;max-width:62ch;margin-bottom:24px;}
  .ledger{border:1px solid var(--border);border-radius:12px;overflow:hidden;
    background:var(--surface);
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);}
  .ledger .row{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr .8fr;
    gap:12px;padding:13px 18px;border-bottom:1px solid var(--border);
    align-items:center;font-family:var(--mono);font-size:12px;
    font-variant-numeric:tabular-nums;
    transition:background .18s ease;}
  .ledger .row:last-child{border-bottom:none;}
  .ledger .row:hover{background:var(--surface2);}
  .ledger .row.head{color:var(--muted);font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:11px;font-weight:600;letter-spacing:.08em;
    text-transform:uppercase;background:rgba(255,255,255,.015);}
  .ledger .tx{color:var(--glacier);word-break:break-all;}
  .ledger .tx:hover{text-decoration:underline;}
  .ledger .amt{font-weight:700;color:var(--text);}
  .ledger .amt.zero{color:var(--muted);}
  .ledger .age{color:var(--muted);}
  .ledger .delta{color:var(--green);}
  .ledger .delta.neg{color:var(--red);}
  .ledger .note{color:var(--dim);}

  /* ---------- stats ---------- */
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:32px;}
  .cell{background:linear-gradient(180deg,rgba(255,255,255,.045),rgba(255,255,255,.008));
    border:1px solid var(--border);border-radius:12px;padding:18px 18px 16px;
    position:relative;overflow:hidden;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease;
    display:block;color:inherit;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  a.cell:hover{transform:translateY(-2px);border-color:rgba(143,199,255,.4);color:inherit;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 12px 32px -16px rgba(0,0,0,.6);}
  .cell:active{transform:translateY(0);}
  .cell .sub{opacity:0;transform:translateY(2px);transition:opacity .18s ease,transform .18s ease;}
  a.cell:hover .sub{opacity:1;transform:none;}
  .cell .num{font-family:var(--mono);font-weight:700;font-size:clamp(26px,3vw,34px);
    line-height:1;color:var(--text);font-variant-numeric:tabular-nums;letter-spacing:-.01em;}
  .cell .num.amber{color:var(--glacier);}
  .cell .num.green{color:var(--green);}
  .cell .lbl{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:12.5px;font-weight:550;
    letter-spacing:-.01em;color:var(--muted);margin-top:10px;}
  .cell .sub{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:11.5px;color:var(--dim);margin-top:3px;}

  /* ---------- live-state: single stacked card on mobile ----------
     Desktop/wide keeps the four separate cells above. On small screens the
     four cells collapse into ONE bordered card with four stacked rows
     (label left, number right) — same ids, no duplicated markup. */
  @media (max-width:760px){
    .stats{grid-template-columns:1fr;gap:0;border:1px solid var(--border);border-radius:14px;
      background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.01));
      padding:4px 18px;margin-top:26px;}
    .stats .cell{box-shadow:none;border:none;border-radius:0;background:none;padding:13px 0;
      display:flex;justify-content:space-between;align-items:center;gap:14px;
      border-bottom:1px solid rgba(255,255,255,.05);}
    .stats .cell:last-child{border-bottom:none;}
    .stats .cell:hover{transform:none;}
    .stats .cell .num{font-size:20px;order:2;}
    .stats .cell .lbl{order:1;margin-top:0;font-size:10px;}
    .stats .cell .sub{display:none;}
  }

  /* ---------- live-state explanation + replay ---------- */
  .mem-explain{color:var(--dim);font-size:15px;line-height:1.7;max-width:78ch;margin:28px 0 6px;}
  .mem-explain b{color:var(--text);font-weight:600;}
  .mem-explain .hl{color:var(--glacier);font-weight:600;}

  /* ---------- memory flow diagram ---------- */
  .flow{border:1px solid var(--border);border-radius:12px;background:var(--surface);
    padding:24px;margin-top:10px;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .flow svg{width:100%;height:auto;display:block;}
  .flow .fstep{font-family:var(--mono);font-size:10px;fill:var(--dim);letter-spacing:.04em;text-anchor:middle;}
  .flow .fstep.mem{fill:var(--glacier);font-weight:700;}
  .flow .fnode rect{fill:var(--surface2);stroke:var(--border);rx:9;}
  .flow .fnode .t{font-family:var(--grotesk);font-size:12px;fill:var(--text);font-weight:600;text-anchor:middle;}
  .flow .fnode.mem rect{stroke:var(--glacier);fill:rgba(143,199,255,.07);}
  .flow .fnode.mem .t{fill:var(--glacier);}
  .flow .arrow{stroke:var(--dim);stroke-width:1.6;}
  .flow .arrow.feed{stroke:var(--glacier);stroke-width:2;stroke-dasharray:6 5;animation:dash 2.6s linear infinite;}
  .flow .dot{animation:flowDot 3s linear infinite;}
  @keyframes flowDot{0%{offset-distance:0%}100%{offset-distance:100%}}

  /* ---------- rooms (tabs) ---------- */
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:26px 0 18px;}
  .tab{padding:9px 16px;border-radius:10px;border:1px solid var(--border);
    font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:13px;font-weight:550;
    letter-spacing:-.01em;color:var(--muted);cursor:pointer;
    transition:all .18s ease;background:rgba(255,255,255,.015);}
  .tab:hover{border-color:var(--border);color:var(--text);background:rgba(255,255,255,.035);}
  .tab.active{background:rgba(143,199,255,.12);border-color:rgba(143,199,255,.45);color:var(--glacier);font-weight:600;
    box-shadow:inset 0 1px 0 rgba(143,199,255,.15);}
  .tab:active{transform:translateY(1px);}
  .room-panel{display:none;border:1px solid var(--border);border-radius:12px;
    background:var(--surface);padding:24px;animation:panelIn .25s ease;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .room-panel.active{display:block;}
  @keyframes panelIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  .room-panel h3{font-size:20px;font-weight:700;margin-bottom:8px;}
  .room-panel h3 .rn{color:var(--glacier);font-family:var(--mono);margin-right:8px;}
  .room-panel .desc{color:var(--dim);font-size:15px;max-width:66ch;margin-bottom:20px;}
  .room-panel .mem-note{border-left:3px solid var(--glacier);background:var(--glacier-dim);
    padding:12px 16px;border-radius:0 8px 8px 0;font-size:14px;color:#c9dcff;margin-bottom:20px;}
  .room-panel .mem-note b{color:var(--glacier);}
  .room-actions{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 16px;}
  .btn.sm{font-size:12px;padding:8px 14px;}

  /* ---------- try-the-house CTA ---------- */
  .try-cta{border:1px solid var(--border);border-radius:16px;
    background:linear-gradient(180deg,rgba(255,255,255,.03),rgba(255,255,255,.005) 40%,transparent);
    padding:36px 32px;margin:48px 0;position:relative;overflow:hidden;}
  .try-cta::before{content:"";position:absolute;top:0;left:0;right:0;height:1px;
    background:linear-gradient(90deg,transparent,rgba(143,199,255,.5),transparent);}
  .try-cta .tc-kicker{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:12px;font-weight:600;
    letter-spacing:.1em;text-transform:uppercase;
    color:var(--green);margin-bottom:10px;cursor:default;}
  .try-cta .tc-head h2{font-size:clamp(24px,3.4vw,36px);font-weight:700;letter-spacing:-.015em;margin-bottom:10px;}
  .try-cta .tc-head p{color:var(--muted);font-size:14.5px;line-height:1.65;max-width:64ch;margin-bottom:26px;}
  .try-cta .tc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;}
  .try-cta .tc-card{background:linear-gradient(180deg,var(--surface2),#0d0d0d);
    border:1px solid var(--border);border-radius:12px;
    padding:18px;text-align:left;cursor:pointer;transition:all .18s ease;position:relative;
    display:flex;flex-direction:column;gap:6px;color:var(--text);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .try-cta .tc-card::after{content:"";position:absolute;inset:0;border-radius:12px;
    background:radial-gradient(340px circle at var(--mx,50%) var(--my,0%),rgba(143,199,255,.12),transparent 65%);
    opacity:0;transition:opacity .25s ease;pointer-events:none;}
  .try-cta .tc-card:hover{border-color:rgba(143,199,255,.45);transform:translateY(-2px);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 14px 36px -16px rgba(0,0,0,.6);}
  .try-cta .tc-card:hover::after{opacity:1;}
  .try-cta .tc-card:active{transform:translateY(0);}
  .try-cta .tc-card .tc-ico{font-size:18px;color:var(--glacier);line-height:1;margin-bottom:2px;}
  .try-cta .tc-card .tc-room{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:11px;font-weight:600;
    color:var(--muted);letter-spacing:.08em;text-transform:uppercase;}
  .try-cta .tc-card .tc-name{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:15px;font-weight:600;letter-spacing:-.01em;}
  .try-cta .tc-card .tc-arrow{position:absolute;top:16px;right:16px;color:var(--muted);font-size:14px;transition:all .18s ease;}
  .try-cta .tc-card:hover .tc-arrow{color:var(--glacier);transform:translate(2px,-2px);}
  .room-table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px;}
  .room-table th{text-align:left;color:var(--muted);font-weight:400;letter-spacing:.08em;
    text-transform:uppercase;font-size:10px;padding:8px 10px;border-bottom:1px solid var(--border);}
  .room-table td{padding:10px;border-bottom:1px solid var(--border);color:#cfcfcf;vertical-align:top;}
  .room-table td a{color:var(--glacier);}
  .room-table .seg.proven{color:var(--green);}
  .room-table .seg.regular{color:var(--glacier);}
  .room-table .seg.new{color:var(--dim);}
  .room-table .seg.banned,.room-table .seg.risky{color:var(--red);}
  .empty{font-family:var(--mono);font-size:12px;color:var(--muted);padding:14px 2px;}

  /* ---------- ACP / Virtuals ---------- */
  .acp{border:1px solid var(--border);border-radius:12px;background:var(--surface);
    padding:24px;margin-top:10px;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .acp .head{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:18px;}
  .acp .head .title{font-size:17px;font-weight:700;letter-spacing:-.01em;}
  .acp .head .title span{color:var(--glacier);}
  .acp .head .badge{font-family:var(--mono);font-size:11px;color:var(--green);
    border:1px solid rgba(39,174,96,.4);padding:4px 10px;border-radius:20px;letter-spacing:.08em;}
  .acp .jobs{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;}
  .acp .job{border:1px solid var(--border);border-radius:12px;padding:16px;background:var(--surface2);
    min-width:0;overflow:hidden;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 32%);
    transition:border-color .18s ease,transform .18s ease;}
  .acp .job:hover{border-color:rgba(143,199,255,.3);transform:translateY(-2px);}
  .acp .job .jid{font-family:var(--mono);font-size:11px;color:var(--glacier);margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .acp .job .off{font-size:14px;font-weight:600;margin-bottom:6px;word-break:break-word;overflow-wrap:anywhere;}
  .acp .job .meta{font-family:var(--mono);font-size:11px;color:var(--muted);word-break:break-word;overflow-wrap:anywhere;}
  .acp .job .meta b{color:var(--green);}
  .acp .job .off .prov{margin-left:8px;font-family:var(--mono);font-size:11px;font-weight:400;color:var(--muted);}
  .acp .job .meta.proof{margin-top:8px;}
  .acp .job .meta.proof a{color:var(--glacier);text-decoration:none;border-bottom:1px dotted rgba(143,199,255,.4);}
  .acp .job .meta.proof a:hover{color:#bcdcff;}
  .acp .acp-live{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:10px;min-height:14px;}
  /* agent identity strip */
  .acp .agent-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px;}
  .acp .a-cell{border:1px solid var(--border);border-radius:10px;padding:11px 13px;background:rgba(255,255,255,.015);
    min-width:0;overflow:hidden;}
  .acp .a-cell .k{display:block;font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:var(--dim);margin-bottom:5px;}
  .acp .a-cell .v{font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .acp .a-cell .v.hash{font-family:var(--mono);font-size:11.5px;color:var(--glacier);font-weight:400;}
  .acp .a-cell .v.hash a{color:var(--glacier);text-decoration:none;border-bottom:1px dotted rgba(143,199,255,.4);}
  .acp .a-cell .v.hash a:hover{color:#bcdcff;}
  .badge .live-dot,.badge .rec-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin:0 3px;vertical-align:middle;}
  .badge .live-dot{background:var(--green);box-shadow:0 0 7px rgba(39,174,96,.6);}
  .badge .rec-dot{background:var(--muted);}
  /* interactive terms checker */
  .acp .checker{margin-top:22px;border-top:1px solid var(--border);padding-top:20px;}
  .acp .checker .fhead{font-family:var(--mono);font-size:11px;letter-spacing:.12em;color:var(--muted);
    text-transform:uppercase;margin-bottom:14px;}
  .acp .check-row{display:flex;gap:10px;flex-wrap:wrap;}
  .acp .acp-input{flex:1;min-width:220px;background:var(--surface2);border:1px solid var(--border);border-radius:9px;
    padding:10px 12px;font-family:var(--mono);font-size:12px;color:var(--text);outline:none;min-width:0;overflow:hidden;}
  .acp .acp-input:focus{border-color:var(--glacier);}
  .acp .check-hint{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.5;}
  .acp .check-hint b{color:var(--glacier);font-weight:600;}
  .acp .check-out{margin-top:14px;}
  .acp .check-out .fhead{font-size:10px;margin-bottom:8px;}
  .acp .check-out .on-tag{color:var(--green);letter-spacing:.08em;}
  .acp .check-out .off-tag{color:var(--muted);letter-spacing:.08em;}
  .flip-cards{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
  .flip-card{border:1px solid var(--border);border-radius:12px;padding:18px;background:var(--surface2);min-width:0;overflow:hidden;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 32%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .flip-card .seg{font-family:var(--mono);font-size:12px;font-weight:700;margin-bottom:10px;}
  .flip-card .seg.proven{color:var(--green);}
  .flip-card .seg.unknown{color:var(--muted);}
  .flip-card .term{display:flex;justify-content:space-between;gap:12px;padding:7px 0;
    border-bottom:1px solid var(--border);font-family:var(--mono);font-size:12px;}
  .flip-card .term:last-child{border-bottom:none;}
  .flip-card .term .k{color:var(--muted);flex-shrink:0;}
  .flip-card .term .v{color:var(--text);text-align:right;min-width:0;overflow:hidden;text-overflow:ellipsis;word-break:break-word;}
  .flip-card .term .v.reason{font-size:10.5px;line-height:1.45;color:var(--dim);white-space:normal;}
  .flip-card .term .v.strict{color:var(--red);}
  .flip-card .term .v.ok{color:var(--green);}

  /* ---------- wipe / deletion gate ---------- */
  .gate{border:1px solid rgba(192,57,43,.35);border-radius:12px;
    background:linear-gradient(180deg,rgba(192,57,43,.06),rgba(192,57,43,.015));
    padding:24px;margin-top:10px;position:relative;overflow:hidden;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .gate .ghead{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:14px;}
  .gate .gtitle{font-size:19px;font-weight:700;letter-spacing:-.01em;}
  .gate .gtitle span{color:var(--red);}
  .gate .status-line{font-family:var(--mono);font-size:12px;color:var(--muted);margin-bottom:18px;}
  .gate .status-line b{color:var(--text);}
  .gate .status-line .red{color:var(--red);}
  .gate .status-line .green{color:var(--green);}
  .gate .status-line .gl{color:var(--glacier);}
  .gate .countdown{font-family:var(--mono);font-size:26px;font-weight:700;color:var(--red);
    margin-bottom:6px;}
  .gate .constraints{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0;}
  .gate .constraint{border:1px solid var(--border);border-radius:10px;padding:14px;background:rgba(0,0,0,.25);}
  .gate .constraint .cnum{font-family:var(--mono);font-size:22px;font-weight:700;color:var(--text);}
  .gate .constraint .cnum.amber{color:var(--glacier);}
  .gate .constraint .clbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;
    text-transform:uppercase;color:var(--muted);margin-top:8px;}
  .gate .actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;}

  /* modal */
  .modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);
    z-index:100;display:none;align-items:center;justify-content:center;padding:20px;}
  .modal-bg.show{display:flex;}
  .modal{background:var(--surface);border:1px solid rgba(192,57,43,.4);border-radius:12px;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);
    max-width:520px;width:100%;padding:28px;animation:panelIn .25s ease;}
  .modal h3{font-size:20px;font-weight:700;color:#e0a49c;margin-bottom:14px;}
  .modal p{color:var(--dim);font-size:14px;margin-bottom:16px;line-height:1.6;}
  .modal .warn{font-family:var(--mono);font-size:12px;color:var(--red);border:1px solid rgba(192,57,43,.4);
    padding:12px 14px;border-radius:8px;background:rgba(192,57,43,.08);margin-bottom:20px;}
  .modal .mbtns{display:flex;gap:12px;justify-content:flex-end;flex-wrap:wrap;}
  .modal .mbtns .btn.cancel{background:transparent;border-color:var(--border);color:var(--muted);}
  .modal .mbtns .btn.cancel:hover{color:var(--text);border-color:var(--dim);}
  /* in-progress state on the confirm button (disable / purge) */
  .btn.working{pointer-events:none;opacity:.85;position:relative;padding-right:34px;}
  .btn.working::after{content:"";position:absolute;right:12px;top:50%;width:14px;height:14px;
    margin-top:-7px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;
    border-radius:50%;animation:spin .7s linear infinite;}
  @keyframes spin{to{transform:rotate(360deg)}}
  .modal .progress{font-family:var(--mono);font-size:12px;color:var(--glacier);
    border:1px solid rgba(143,199,255,.35);padding:12px 14px;border-radius:8px;
    background:rgba(143,199,255,.07);margin-bottom:20px;display:flex;align-items:center;gap:10px;}
  .modal .progress .pdot{width:9px;height:9px;border-radius:50%;background:var(--glacier);
    animation:breath 1s ease-in-out infinite;flex:none;}
  .toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(120%);
    background:var(--surface2);border:1px solid var(--border);border-radius:10px;
    padding:14px 22px;font-family:var(--mono);font-size:13px;z-index:120;
    transition:transform .3s ease;max-width:90vw;text-align:center;}
  .toast.show{transform:translateX(-50%) translateY(0);}
  .toast.err{border-color:var(--red);color:#e0a49c;}
  .toast.ok{border-color:var(--green);color:#8fd9ac;}

  __TRYIT_CSS__
  /* ---------- discovery ---------- */
  .discovery{border:1px solid var(--border);border-radius:12px;background:var(--surface);
    padding:24px;margin-top:10px;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .discovery .q{font-size:clamp(18px,2.4vw,24px);font-weight:700;letter-spacing:-.01em;line-height:1.2;margin-bottom:14px;}
  .discovery .q em{font-style:normal;color:var(--glacier);}
  .discovery p{color:var(--dim);font-size:15px;max-width:70ch;margin-bottom:14px;line-height:1.65;}
  .discovery .partner{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);
    font-size:12px;color:var(--glacier);border:1px solid rgba(143,199,255,.35);
    padding:7px 14px;border-radius:20px;margin:4px 6px 4px 0;}

  /* ---------- proof / footer ---------- */
  .proof{margin-top:56px;padding-top:28px;border-top:1px solid var(--border);}
  .proof p{color:var(--dim);font-size:15px;max-width:66ch;margin-bottom:16px;}
  .links{display:flex;flex-wrap:wrap;gap:10px 22px;font-family:var(--mono);font-size:13px;}
  .links a{color:var(--text);border-bottom:1px solid var(--border);padding-bottom:2px;transition:color .15s;}
  .links a:hover{color:var(--glacier);border-color:var(--glacier);}
  .repo{font-family:var(--mono);font-size:13px;color:var(--muted);margin-top:20px;}
  .repo a{color:var(--text);border-bottom:1px solid var(--border);}
  footer{margin-top:56px;padding-top:24px;border-top:1px solid var(--border);
    display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
    font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--muted);}
  footer .foot-main{display:flex;gap:22px;flex-wrap:wrap;align-items:center;min-width:0;}
  footer .foot-links{display:flex;gap:18px;flex-wrap:wrap;}
  footer .foot-links a{color:var(--muted);border-bottom:1px solid transparent;transition:color .15s,border-color .15s;}
  footer .foot-links a:hover{color:var(--glacier);border-color:var(--glacier);}
  .wordmark .sibyl-credit{color:var(--muted);font-weight:400;font-size:10px;letter-spacing:.08em;
    border-bottom:1px solid transparent;transition:color .15s,border-color .15s;}
  .wordmark .sibyl-credit:hover{color:var(--glacier);border-color:var(--glacier);}

  /* ---------- scroll choreography: in on entry, ghost after leaving ---------- */
  .reveal{opacity:0;transform:translateY(18px);transition:opacity .5s cubic-bezier(.16,1,.3,1),transform .5s cubic-bezier(.16,1,.3,1);}
  .reveal.in{opacity:1;transform:none;}
  .reveal[data-d="1"]{transition-delay:.06s;}
  .reveal[data-d="2"]{transition-delay:.12s;}
  .reveal[data-d="3"]{transition-delay:.18s;}
  .reveal[data-d="4"]{transition-delay:.24s;}
  /* once a section has been shown and scrolled past, it fades to ghost state */
  .section, .graph-wrap, .try-cta{transition:opacity .5s ease;}
  .ghosted{opacity:.45;}
  .hero.ghosted{opacity:1;}

  /* ---------- 3D hero stage ---------- */
  .hero-grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);
    gap:48px;align-items:center;}
  .hero-copy{min-width:0;}
  .hero-stage{position:relative;height:400px;perspective:820px;perspective-origin:50% 40%;}
  .hero-stack{position:absolute;inset:0;transform-style:preserve-3d;
    transform:rotateX(var(--tilt-x,9deg)) rotateY(var(--tilt-y,-14deg));
    transition:transform .5s cubic-bezier(.16,1,.3,1);will-change:transform;}
  .hcard{position:absolute;border:1px solid rgba(255,255,255,.10);border-radius:14px;
    background:linear-gradient(160deg,rgba(18,22,26,.96),rgba(10,13,15,.98));
    box-shadow:0 30px 60px -20px rgba(0,0,0,.7),0 0 0 1px rgba(255,255,255,.02) inset;
    padding:16px 18px;font-family:var(--mono);min-width:0;
    animation:floaty var(--fd,7s) ease-in-out var(--hd,.5s) infinite;
    transition:border-color .3s ease,box-shadow .3s ease;will-change:transform;}
  .hcard::before{content:"";position:absolute;top:0;left:14px;right:14px;height:1px;
    background:linear-gradient(90deg,transparent,rgba(143,199,255,.5),transparent);}
  .hcard .hc-k{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin-bottom:8px;
    display:flex;align-items:center;gap:7px;overflow-wrap:anywhere;}
  .hcard .hc-row{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;
    padding:5px 0;border-top:1px solid rgba(255,255,255,.05);min-width:0;}
  .hcard .hc-row .k{color:var(--dim);overflow-wrap:anywhere;min-width:0;}
  .hcard .hc-row .v{color:var(--text);text-align:right;font-weight:500;overflow-wrap:anywhere;
    word-break:break-word;min-width:0;text-align:right;}
  .hcard .hc-row .v.gl{color:var(--glacier);font-weight:600;}
  .hcard .hc-row .v.gr{color:var(--green);}
  .hcard.main{width:276px;left:16%;top:2%;transform:translateZ(150px) rotateY(-12deg) rotateX(3deg);--fd:8s;--hd:.45s;z-index:3;
    box-shadow:0 44px 90px -18px rgba(0,0,0,.85),0 0 0 1px rgba(143,199,255,.22);}
  .hcard.a2{width:198px;right:0;top:0;transform:translateZ(-90px) rotateY(10deg);--fd:9.5s;--hd:.6s;--ho:.9;z-index:1;opacity:.9;}
  .hcard.a3{width:204px;left:2%;bottom:6%;transform:translateZ(-140px) rotateY(-9deg);--fd:11s;--hd:.75s;--ho:.88;z-index:0;opacity:.88;}
  .hcard.a4{width:226px;right:1%;bottom:1%;transform:translateZ(60px) rotateY(10deg);--fd:10s;--hd:.9s;z-index:2;opacity:.96;}
  .js .hcard{animation:hcIn .8s cubic-bezier(.16,1,.3,1) var(--hd,.5s) forwards,
    floaty var(--fd,7s) ease-in-out var(--hd,.5s) infinite;}
  @keyframes hcIn{from{opacity:0}to{opacity:var(--ho,1)}}
  .hcard:hover{transform:translateZ(170px) rotateY(-4deg) rotateX(2deg);
    box-shadow:0 40px 80px -20px rgba(0,0,0,.8),0 0 0 1px rgba(143,199,255,.30);}
  .hcard.a2:hover{transform:translateZ(0) rotateY(5deg);}
  .hcard.a3:hover{transform:translateZ(-80px) rotateX(3deg);}
  .hcard.a4:hover{transform:translateZ(90px) rotateX(2.5deg);}
  @media (prefers-reduced-motion:reduce){.js .hcard{animation:none;opacity:var(--ho,1);}}
  @keyframes floaty{0%,100%{margin-top:0}50%{margin-top:-14px}}
  .stage-glow{position:absolute;left:50%;top:50%;width:420px;height:420px;transform:translate(-50%,-50%);
    background:radial-gradient(circle,rgba(143,199,255,.14),transparent 65%);filter:blur(30px);
    pointer-events:none;z-index:0;opacity:.85;}
  @media (max-width:960px){
    .hero-grid{grid-template-columns:1fr;gap:28px;}
    .hero-stage{height:340px;order:-1;perspective:900px;}
    .hcard.main{width:230px;}
    .hcard.a2{width:180px;}
    .hcard.a3{width:180px;}
    .hcard.a4{width:196px;}
  }
  @media (max-width:600px){
    .hero-stage{height:250px;}
    .hcard{padding:12px 13px;}
    .hcard .hc-row{font-size:11.5px;padding:4px 0;}
    .hcard .hc-k{font-size:9px;}
    .hcard.main{width:190px;top:4%;}
    .hcard.a2{width:150px;}
    .hcard.a3{width:152px;bottom:6%;}
    .hcard.a4{width:164px;bottom:2%;}
  }

  /* ---------- live memory decision replay (stats section) ---------- */
  .replay{border:1px solid rgba(255,255,255,.10);border-radius:16px;
    background:linear-gradient(160deg,rgba(18,22,26,.97),rgba(10,13,15,.99));
    box-shadow:0 30px 60px -20px rgba(0,0,0,.7),0 0 0 1px rgba(143,199,255,.14) inset;
    padding:22px;font-family:var(--mono);display:flex;flex-direction:column;
    min-height:300px;position:relative;margin-top:8px;}
  .replay::before{content:"";position:absolute;top:0;left:14px;right:14px;height:1px;
    background:linear-gradient(90deg,transparent,rgba(143,199,255,.5),transparent);}
  .rp-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
    font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);
    border-bottom:1px solid var(--border);padding-bottom:12px;margin-bottom:16px;}
  .rp-live{display:flex;align-items:center;gap:7px;color:var(--green);}
  .rp-live .dot{width:7px;height:7px;}
  .rp-live.off{color:var(--red);}
  .rp-body{flex:1;font-size:12.5px;line-height:1.75;overflow:hidden;position:relative;
    display:flex;flex-direction:column;justify-content:center;}
  .rp-line{opacity:0;transform:translateY(4px);transition:opacity .25s ease,transform .25s ease;}
  .rp-line.show{opacity:1;transform:none;}
  .rp-line .tag{display:inline-block;min-width:96px;color:var(--muted);letter-spacing:.06em;}
  .rp-line.mem .tag{color:var(--glacier);font-weight:700;}
  .rp-line .val{color:var(--text);}
  .rp-line.mem .val{color:#c9dcff;}
  .rp-line .val a{color:var(--glacier);border-bottom:1px dashed rgba(143,199,255,.4);}
  .rp-line .val a:hover{border-bottom-color:var(--glacier);}
  .rp-line.recall .val{color:var(--glacier);font-weight:700;}
  .rp-foot{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:16px;
    padding-top:14px;border-top:1px solid var(--border);font-size:10px;letter-spacing:.1em;
    color:var(--muted);text-transform:uppercase;}
  .rp-proof{display:flex;align-items:center;gap:6px;}
  .rp-proof::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--green);}
  .rp-progress{display:flex;gap:5px;align-items:center;}
  .rp-progress .seg{width:20px;height:3px;border-radius:2px;background:var(--border);transition:background .2s;}
  .rp-progress .seg.on{background:var(--glacier);}
  @media (max-width:600px){
    .replay{padding:16px;min-height:270px;}
    .rp-body{font-size:11.5px;}
    .rp-line .tag{min-width:84px;}
  }

  /* ---------- the house remembers (per-wallet) ---------- */
  .remember{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));gap:12px;margin:20px 0 6px;}
  .rw-card{border:1px solid var(--border);border-radius:12px;
    background:linear-gradient(160deg,rgba(18,22,26,.9),rgba(10,13,15,.96));
    padding:14px 15px;font-family:var(--mono);position:relative;overflow:hidden;
    transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease;}
  .rw-card::before{content:"";position:absolute;top:0;left:12px;right:12px;height:1px;
    background:linear-gradient(90deg,transparent,rgba(143,199,255,.45),transparent);}
  .rw-card:hover{border-color:rgba(143,199,255,.35);box-shadow:0 0 0 1px rgba(143,199,255,.18) inset;transform:translateY(-2px);}
  .rw-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;}
  .rw-addr{color:var(--glacier);font-size:12px;border-bottom:1px dashed rgba(143,199,255,.4);text-decoration:none;overflow-wrap:anywhere;}
  .rw-addr:hover{border-bottom-color:var(--glacier);}
  .rw-seg{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:10.5px;font-weight:600;
    letter-spacing:.06em;text-transform:uppercase;padding:3px 8px;border-radius:8px;
    border:1px solid var(--border);color:var(--muted);white-space:nowrap;}
  .rw-seg.proven{color:var(--glacier);border-color:rgba(143,199,255,.4);}
  .rw-seg.risky{color:var(--red);border-color:rgba(192,57,43,.5);}
  .rw-row{display:flex;justify-content:space-between;gap:10px;font-size:11.5px;padding:3px 0;color:var(--dim);}
  .rw-row .v{color:var(--text);font-weight:500;overflow-wrap:anywhere;text-align:right;}
  .rw-row .v.gl{color:var(--glacier);}
  .rw-trajectory{margin:16px 0 6px;border:1px solid var(--border);border-radius:12px;padding:16px 18px;background:rgba(255,255,255,.015);
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);}
  .rw-t-label{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:12px;}
  .rw-t-steps{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-family:var(--mono);}
  .rw-t-step{display:flex;flex-direction:column;gap:2px;align-items:center;padding:8px 12px;border:1px solid var(--border);
    border-radius:10px;background:rgba(18,22,26,.8);}
  .rw-t-step b{font-size:18px;color:var(--glacier);line-height:1;}
  .rw-t-step span{font-size:9.5px;color:var(--muted);letter-spacing:.04em;text-align:center;}
  .rw-t-arrow{color:var(--dim);font-size:16px;}
  .rw-t-events{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;}
  .rw-t-ev{font-family:var(--mono);font-size:10.5px;padding:4px 10px;border-radius:20px;border:1px solid var(--border);color:var(--muted);}
  .rw-t-ev.dedup{color:var(--green);border-color:rgba(74,222,128,.35);}
  .rw-t-ev.gate{color:var(--red);border-color:rgba(192,57,43,.45);}

  /* collapsible section toggle bar + wrapper (used by "house remembers" and
     the ACP delegation rail; the ACP variant is green to read as distinct). */
  .collap-bar{display:flex;align-items:center;justify-content:space-between;gap:14px;width:100%;
    margin:18px 0 0;padding:14px 18px;background:linear-gradient(180deg,rgba(143,199,255,.06),rgba(143,199,255,.02));
    border:1px solid rgba(143,199,255,.30);border-radius:12px;cursor:pointer;color:var(--text);
    font-family:var(--mono);font-size:12px;letter-spacing:.05em;text-align:left;
    transition:border-color .18s ease,background .18s ease;}
  .collap-bar:hover{border-color:rgba(143,199,255,.55);}
  .collap-bar .cb-title{display:flex;align-items:center;gap:10px;font-size:12.5px;letter-spacing:.04em;}
  .collap-bar .cb-count{color:var(--glacier);font-weight:700;}
  .collap-bar .cb-caret{transition:transform .22s ease;color:var(--muted);font-size:11px;flex:0 0 auto;}
  .collap-bar.open .cb-caret{transform:rotate(180deg);}
  .collap-wrap{display:none;margin-top:14px;}
  .collap-wrap.open{display:block;}
  /* the ACP rail's bar is green + a different accent so it never reads
     templated against the glacier "remembers" toggle. */
  .collap-bar.green{background:linear-gradient(180deg,rgba(39,174,96,.10),rgba(39,174,96,.025));
    border-color:rgba(39,174,96,.42);border-radius:12px 12px 12px 4px;}
  .collap-bar.green:hover{border-color:rgba(39,174,96,.7);}
  .collap-bar.green .cb-count{color:var(--green);}
  .collap-bar.green .cb-caret{color:var(--green);}

  /* per-card "how derived" — an expandable, data-derived explanation inside
     each remember card. Collapsed by default; opens when the card is tapped. */
  .rw-card{cursor:pointer;}
  .rw-derive{max-height:0;overflow:hidden;opacity:0;transition:max-height .32s ease,opacity .28s ease,margin .28s ease;}
  .rw-card.open .rw-derive{max-height:360px;opacity:1;margin-top:12px;}
  .rw-derive .d-inner{border-top:1px solid var(--border);padding-top:11px;}
  .rw-derive .d-k{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--glacier);
    margin-bottom:9px;font-family:var(--mono);}
  .rw-derive p{font-size:11px;line-height:1.65;color:var(--dim);margin-bottom:8px;font-family:var(--mono);}
  .rw-derive p:last-child{margin-bottom:0;}
  .rw-derive b{color:var(--text);font-weight:600;}
  .rw-derive .gl{color:var(--glacier);} .rw-derive .gr{color:var(--green);} .rw-derive .rd{color:var(--red);}
  .rw-more{margin-top:10px;font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.05em;
    transition:color .18s ease;}
  .rw-card:hover .rw-more{color:var(--glacier);}
  .rw-card.open .rw-more{color:var(--glacier);}

  @media (max-width:560px){
    .rw-t-steps{gap:4px;}
    .rw-t-step{padding:6px 8px;}
    .rw-t-step b{font-size:15px;}
    .rw-t-arrow{font-size:13px;}
  }

  /* ---------- 3D tilt cards (hover) ---------- */
  .tilt{transform-style:preserve-3d;transition:transform .35s cubic-bezier(.16,1,.3,1),border-color .25s ease,box-shadow .35s ease;
    will-change:transform;}
  .tilt:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-4px);
    box-shadow:0 24px 60px -18px rgba(0,0,0,.65),0 0 0 1px rgba(143,199,255,.16);}
  .cell.tilt:hover{border-color:rgba(143,199,255,.35);}

  /* ---------- endpoints strip ---------- */
  .eps-head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;flex-wrap:wrap;
    margin:0 0 20px;}
  .eps-head .lead{margin:8px 0 0;max-width:640px;}
  .eps-toggle{display:inline-flex;align-items:center;gap:10px;cursor:pointer;user-select:none;
    font-family:var(--mono);font-size:12px;letter-spacing:.08em;color:var(--dim);
    border:1px solid var(--border);background:var(--surface);border-radius:22px;padding:7px 12px;
    transition:border-color .18s ease,background .18s ease;}
  .eps-toggle:hover{border-color:rgba(143,199,255,.4);background:rgba(143,199,255,.04);}
  .eps-toggle .lbl{color:var(--muted);}
  .eps-toggle .st{color:var(--glacier);font-weight:600;}
  .eps-toggle .sw{position:relative;width:34px;height:18px;border-radius:10px;background:rgba(143,199,255,.25);
    border:1px solid rgba(143,199,255,.5);transition:background .2s ease,border-color .2s ease;flex:0 0 auto;}
  .eps-toggle .knob{position:absolute;top:1px;left:1px;width:14px;height:14px;border-radius:50%;
    background:var(--glacier);transition:left .2s cubic-bezier(.16,1,.3,1),background .2s ease;}
  .eps-toggle.off .st{color:var(--muted);}
  .eps-toggle.off .sw{background:rgba(255,255,255,.06);border-color:var(--border);}
  .eps-toggle.off .knob{left:17px;background:var(--muted);}
  .eps-group{margin-bottom:14px;}
  .eps-group:last-child{margin-bottom:0;}
  .eps-group > .glabel{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
    color:var(--muted);margin:0 0 10px 2px;display:flex;align-items:center;gap:10px;}
  .eps-group > .glabel::after{content:"";flex:1;height:1px;background:var(--border);}
  .eps-strip{display:flex;gap:12px;overflow-x:auto;padding:4px 2px 12px;scroll-snap-type:x proximity;
    -webkit-overflow-scrolling:touch;scrollbar-width:thin;scrollbar-color:rgba(143,199,255,.3) transparent;}
  .eps-strip::-webkit-scrollbar{height:6px;}
  .eps-strip::-webkit-scrollbar-thumb{background:rgba(143,199,255,.25);border-radius:3px;}
  .eps-strip::-webkit-scrollbar-track{background:transparent;}
  .ep-card{position:relative;flex:0 0 292px;scroll-snap-align:start;border:1px solid var(--border);
    border-radius:12px;background:linear-gradient(160deg,rgba(18,22,26,.92),rgba(10,13,15,.96));
    padding:16px;cursor:pointer;overflow:hidden;transition:border-color .18s ease,transform .18s ease,box-shadow .18s ease;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .ep-card:hover{border-color:rgba(143,199,255,.4);transform:translateY(-2px);box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 16px 36px -18px rgba(0,0,0,.7);}
  .ep-card.open{border-color:rgba(143,199,255,.5);transform:translateY(-2px);}
  .ep-top{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
  .ep-verb{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.08em;padding:3px 7px;
    border-radius:6px;border:1px solid rgba(143,199,255,.4);color:var(--glacier);background:rgba(143,199,255,.08);}
  .ep-price{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--dim);white-space:nowrap;}
  .ep-price.free{color:var(--muted);letter-spacing:.06em;}
  .ep-card.danger .ep-verb{border-color:rgba(255,138,122,.5);color:#ff8a7a;background:rgba(192,57,43,.1);}
  .ep-card.danger:hover,.ep-card.danger.open{border-color:rgba(255,138,122,.5);}
  .ep-path{display:block;font-family:var(--mono);font-size:14px;color:var(--text);font-weight:600;
    overflow-wrap:anywhere;word-break:break-word;line-height:1.4;margin-bottom:6px;}
  .ep-room{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
    color:var(--muted);display:block;margin-bottom:8px;}
  .ep-brief{color:var(--dim);font-size:12.5px;line-height:1.55;margin:0;overflow-wrap:anywhere;}
  .ep-more{display:block;margin-top:10px;font-family:var(--mono);font-size:11px;letter-spacing:.06em;
    color:var(--muted);transition:color .15s ease;}
  .ep-card:hover .ep-more,.ep-card.open .ep-more{color:var(--glacier);}
  .ep-more .arr{display:inline-block;transition:transform .2s ease;margin-left:4px;}
  .ep-card.open .ep-more .arr{transform:rotate(90deg);}
  .ep-card.danger.open .ep-more,.ep-card.danger:hover .ep-more{color:#ff8a7a;}
  .ep-detail{display:grid;grid-template-rows:0fr;transition:grid-template-rows .28s ease;}
  .ep-detail > div{overflow:hidden;}
  .ep-card.open .ep-detail{grid-template-rows:1fr;}
  .ep-dbody{margin-top:12px;padding-top:12px;border-top:1px solid var(--border);}
  .ep-drow{display:flex;gap:10px;font-size:12px;line-height:1.6;color:var(--dim);margin-bottom:10px;overflow-wrap:anywhere;}
  .ep-drow .k{font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--muted);
    min-width:78px;flex:0 0 78px;padding-top:2px;text-transform:uppercase;}
  .ep-drow .v{flex:1;min-width:0;transition:opacity .2s ease;}
  .ep-drow .v b{color:var(--text);font-weight:600;}
  .ep-drow .v .on{color:var(--glacier);}
  .ep-drow .v .off{color:var(--muted);}
  .ep-tryit{display:inline-block;margin-top:2px;font-family:var(--mono);font-size:11px;color:var(--glacier);
    border:1px solid rgba(143,199,255,.4);padding:5px 10px;border-radius:8px;background:none;cursor:pointer;
    transition:background .15s ease;}
  .ep-tryit:hover{background:rgba(143,199,255,.1);}
  .eps-hint{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.06em;margin-top:4px;
    display:flex;align-items:center;gap:8px;}
  @media (max-width:640px){
    .eps-head{flex-direction:column;align-items:flex-start;gap:14px;}
    .ep-card{flex:0 0 258px;}
  }

  /* ---------- ? tooltips ---------- */
  .qmark{display:inline-flex;align-items:center;justify-content:center;
    width:15px;height:15px;flex:0 0 auto;margin-left:6px;border-radius:50%;
    border:1px solid rgba(143,199,255,.45);color:var(--glacier);
    font-family:var(--mono);font-size:10px;font-weight:600;line-height:1;
    cursor:help;user-select:none;-webkit-user-select:none;
    transition:background .15s ease,color .15s ease,box-shadow .15s ease;}
  .qmark:hover,.qmark:focus-visible{background:var(--glacier);color:#08131f;outline:none;
    box-shadow:0 0 0 3px rgba(143,199,255,.18);}
  h2 .qmark{margin-left:10px;vertical-align:middle;}
  .tc-card .qmark{position:absolute;top:14px;right:40px;margin-left:0;}
  .status .qmark{margin-left:8px;}
  .hack-badge .qmark{margin-left:9px;}
  .cell .qmark{margin-left:8px;}
  .tip-float{position:fixed;z-index:300;max-width:300px;padding:10px 13px;border-radius:10px;
    background:rgba(16,20,24,.97);border:1px solid rgba(143,199,255,.28);
    box-shadow:0 18px 50px rgba(0,0,0,.65),0 0 0 1px rgba(0,0,0,.4);
    color:var(--dim);font-family:var(--mono);font-size:11.5px;line-height:1.6;letter-spacing:0;
    text-transform:none;font-weight:400;white-space:normal;text-align:left;
    opacity:0;pointer-events:none;transform:translate(-50%,-100%) translateY(6px);
    transition:opacity .16s ease,transform .16s ease;}
  .tip-float.below{transform:translate(-50%,0) translateY(-6px);}
  .tip-float.show{opacity:1;transform:translate(-50%,-100%) translateY(0);}
  .tip-float.below.show{transform:translate(-50%,0) translateY(0);}
  .tip-float::after{content:"";position:absolute;left:50%;bottom:-5px;transform:translateX(-50%) rotate(45deg);
    width:8px;height:8px;background:rgba(16,20,24,.97);border-right:1px solid rgba(143,199,255,.28);
    border-bottom:1px solid rgba(143,199,255,.28);}
  .tip-float.below::after{bottom:auto;top:-5px;border-right:none;border-bottom:none;
    border-left:1px solid rgba(143,199,255,.28);border-top:1px solid rgba(143,199,255,.28);}

  /* ---------- premium surface polish ---------- */
  .ledger, .flow, .acp, .discovery, .gate, .room-panel, .stats .cell, .tc-card, .try-cta{
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);}
  .ledger .row .tx{font-variant-numeric:tabular-nums;}
  .cell .num{font-variant-numeric:tabular-nums;}
  h1,h2,h3,.lead,.tc-head h2{font-feature-settings:"ss01";}
  .section h2{display:flex;align-items:center;gap:12px;}
  .section h2::before{content:"";width:22px;height:1px;background:var(--glacier);opacity:.7;flex-shrink:0;}
  .hero .kicker::before{width:30px;background:linear-gradient(90deg,var(--glacier),transparent);}

  /* ---------- responsive ---------- */
  @media (max-width:860px){
    .section{padding:48px 0 8px;}
    .bar-inner{padding:16px 20px 12px;}
    /* bottom bar-row stays one row: shrink gaps, never wrap */
    .bar-row.bottom{gap:10px;}
    .bar-row.bottom .nav{gap:12px;}
    .graph-wrap{margin-top:40px;}
    .stats{grid-template-columns:repeat(2,1fr);gap:10px;}
    .acp .jobs{grid-template-columns:1fr;}
    .flip-cards{grid-template-columns:1fr;}
    .gate .constraints{grid-template-columns:1fr;}
    .ledger .row{grid-template-columns:1fr 1fr;gap:6px 12px;font-size:11px;}
    .ledger .row.head{display:none;}
    .try-cta .tc-grid{grid-template-columns:1fr;}
    .try-cta .tc-card{padding:13px 14px;flex-direction:row;align-items:center;gap:11px;min-height:0;}
    .try-cta .tc-card .tc-ico{font-size:19px;margin-bottom:0;flex:0 0 auto;}
    .try-cta .tc-card .tc-room{display:none;}
    .try-cta .tc-card .tc-name{font-size:14.5px;flex:1 1 auto;}
    .try-cta .tc-card .tc-arrow{position:static;flex:0 0 auto;margin-left:auto;}
    .try-cta .tc-card .qmark{position:static;order:3;flex:0 0 auto;margin-left:2px;}
  }
  @media (max-width:560px){
    .wrap{padding:0 16px 40px;}
    .hero{padding-top:38px;}
    .hero h1{font-size:clamp(26px,8vw,32px);}
    .hero .sub{font-size:14.5px;}
    .stats{grid-template-columns:1fr 1fr;gap:9px;}
    .section .section-note{font-size:13.5px;}
    .room-table{font-size:11px;}
    .room-table td{padding:8px 6px;}
    .try-cta .tc-head h2{font-size:26px;}
  }

  /* ---------- reduced motion + no-JS ---------- */
  @media (prefers-reduced-motion:reduce){
    *,*::before,*::after{animation-duration:.001s !important;animation-iteration-count:1 !important;
      transition-duration:.001s !important;scroll-behavior:auto !important;}
    .hero h1 .line span{transform:none;animation:none;}
    .hero .sub,.hero .cta,.trust-strip{opacity:1;animation:none;}
    .reveal{opacity:1;transform:none;}
  }
  .js .hero h1 .line span{transform:translateY(110%);}
  .no-js .hero h1 .line span{transform:none;}
  .no-js .hero .sub,.no-js .hero .cta,.no-js .trust-strip{opacity:1;}
  .no-js .reveal{opacity:1;transform:none;}

  /* ---- memory off: memory-derived views blank + shrink ----
     The value of the house IS the memory. When memory is off (disabled or
     purged), the memory-DERIVED views — the live graph, the aggregate stats,
     and "the house remembers" (per-wallet cards + trust ladder) — collapse to
     a slim "no record" band. The onchain proof table is an immutable record
     (the chain does not care about memory), so it STAYS, with only its
     memory-delta column blanked. The collapse is visible the moment the gate
     flips — not just the header dot. */
  .mem-off .graph-wrap, .mem-off #stats-band, .mem-off #remember-band{
    transition:max-height .7s ease, opacity .5s ease, margin .7s ease, padding .5s ease;
    max-height:0 !important; opacity:0; overflow:hidden;
    margin:0 !important; padding:0 !important; border-width:0 !important;
  }
  .mem-off .no-record-band{display:flex !important;}
  .no-record-band{
    display:none; align-items:center; gap:10px;
    margin:34px 0; padding:15px 20px;
    border:1px dashed var(--border); border-radius:14px;
    background:rgba(255,255,255,.015);
    color:var(--dim); font-family:"Space Mono",monospace; font-size:13px;
    letter-spacing:.03em;
  }
  .no-record-band .nr-dot{width:8px;height:8px;border-radius:50%;background:var(--dim);flex:0 0 auto;}
  .no-record-band b{color:var(--text);font-weight:600;}
</style>
</head>
<body class="no-js">
<div class="ambient" aria-hidden="true">
  <div class="grid-bg"></div>
  <div class="glow a"></div>
  <div class="glow b"></div>
  <div class="glow c"></div>
</div>

<header class="bar">
    <div class="bar-inner">
      <div class="bar-row top">
        <div class="wordmark"><a href="/" class="home-link">THE<span class="tick">·</span>HOUSE</a><span class="tag-stack"><span class="sub">memory-native x402</span><a class="sibyl-credit" href="https://sibyllabs.org/" target="_blank" rel="noopener">by Sibyl Labs</a></span></div>
        <div class="status-group">
          <div class="status" data-tip="The house's memory is live: pricing, dedup and refusals all run on remembered state." data-tip-pos="below"><span class="dot" id="mem-dot"></span><span id="mem-status">MEMORY</span><span class="recover" id="mem-recover" style="display:none"></span></div>
          <button type="button" id="header-gate" class="gate-link" data-tip="Memory control — disable it (data kept, self-heals in 15 min) or purge it (permanent, irreversible)." data-tip-pos="below">disable memory</button>
        </div>
      </div>
      <div class="bar-row bottom">
        <div class="nav">
          <a href="/gallery" data-tip="The workbench: pick a counterparty, run a function, watch memory decide — then it hands you the next step." data-tip-pos="below">try it live</a>
          <a href="/house/ledger" data-tip="Raw JSON: every caller, trust score, dedup state." data-tip-pos="below">ledger</a>
          <a href="/manifest" data-tip="The house's machine-readable service manifest: every endpoint and its price." data-tip-pos="below">manifest</a>
        </div>
        <div class="hash" id="hash"></div>
      </div>
    </div>
  </header>

<div class="wrap">

  <main>
    <!-- HERO -->
    <section class="hero">
      <div class="hero-grid">
        <div class="hero-copy">
          <div class="hack-badge" data-tip="Sibyl Labs 2026 hackathon — the memory track. THE HOUSE is built on the memory substrate Sibyl Labs made.">SIBYL LABS HACKATHON 2026 · MEMORY TRACK</div>
          <div class="kicker">the house · a memory business on base mainnet</div>
          <h1>
            <span class="line"><span>Every price, refusal and settlement</span></span>
            <span class="line"><span>is decided by what the house</span></span>
            <span class="line"><span><em>remembers about each wallet.</em></span></span>
          </h1>
          <p class="sub">A live business on Base where memory is the product, not a log. The house reads what it
            remembers about a wallet before it sets a price, serves a repeat for free, or refuses a bad actor.
            Below, it replays its settlements — each one settled on Base. Pay it once, and it starts
            remembering you.</p>
          <div class="cta">
            <a href="/gallery" class="btn primary">Try it live →</a>
          </div>
          <div class="trust-strip">
            <span>built on <b>Sibyl Memory</b></span>
            <span>settled on <b>Base</b></span>
            <span>rail <b>eip155:8453</b></span>
            <span>asset <b>USDC</b></span>
            <span>auditable <b>Basescan</b></span>
            <span>agent rail <b>Virtuals ACP</b></span>
          </div>
        </div>
        <div class="hero-stage" aria-hidden="true">
          <div class="stage-glow"></div>
          <div class="hero-stack" id="hero-stack">
            <div class="hcard main" id="hc-main">
              <div class="hc-k">memory · live</div>
              <div id="hc-main-body"><div class="hc-row"><span class="k">counterparties</span><span class="v">—</span></div></div>
            </div>
            <div class="hcard a2" id="hc-caller"><div class="hc-k">caller</div><div id="hc-caller-body"><div class="hc-row"><span class="k">trust</span><span class="v">—</span></div></div></div>
            <div class="hcard a3" id="hc-provider"><div class="hc-k">provider</div><div id="hc-provider-body"><div class="hc-row"><span class="k">quality</span><span class="v">—</span></div></div></div>
            <div class="hcard a4" id="hc-settle"><div class="hc-k">settled · onchain</div><div id="hc-settle-body"><div class="hc-row"><span class="k">txs</span><span class="v">—</span></div></div></div>
          </div>
        </div>
      </div>
    </section>

    <!-- TRY THE HOUSE -->
    <section class="try-cta reveal" id="try">
      <div class="tc-head">
        <div class="tc-kicker" data-tip="Every function here is a live endpoint on Base mainnet.">live · settled on base mainnet</div>
        <h2>Pay it. Watch it remember you.</h2>
        <p>Seven live functions, all priced in USDC on Base. Pick one in the workbench — pay from your own wallet, or have
          your agent do it. The first payment costs cents; the second one may cost nothing at all,
          because the house will know you.</p>
      </div>
      <a class="btn primary" href="/gallery">Open the workbench →</a>
    </section>

    <!-- LIVE MEMORY GRAPH -->
    <section class="graph-wrap reveal">
      <div class="ghead">
        <span data-tip="The house's working memory, rendered live: who it knows, how much it trusts them, and what it has learned.">the house's memory — live</span>
        <span class="live" id="graph-live"><span class="dot" id="graph-dot"></span><span id="graph-status">connected</span></span>
      </div>
      <svg id="mem-graph" class="graph" viewBox="0 0 520 240" role="img" aria-label="live memory graph">
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#6B6B6B"/>
          </marker>
          <marker id="arrAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="#8FC7FF"/>
          </marker>
        </defs>
        <!-- edges (rebuilt by paintMemoryGraph) -->
        <g id="graph-edges"></g>
        <!-- memory core -->
        <g class="node mem" data-wipe="core">
          <circle cx="350" cy="120" r="88" fill="rgba(143,199,255,.08)" stroke="#8FC7FF" stroke-width="2.5"/>
          <circle class="pulse-dot" cx="350" cy="120" r="108" fill="none" stroke="rgba(143,199,255,.35)" stroke-width="1.5"/>
          <text x="350" y="116" text-anchor="middle" fill="#8FC7FF" font-family="Space Mono,monospace" font-size="16" font-weight="700" letter-spacing=".12em">MEMORY</text>
          <text x="350" y="136" text-anchor="middle" fill="#c9dcff" font-family="Space Mono,monospace" font-size="12">the business</text>
        </g>
        <!-- counterparty nodes: rebuilt live from the ledger (paintMemoryGraph) -->
        <g id="graph-cps"></g>
      </svg>
    </section>

    <!-- HEADLINE STATS -->
    <section class="section">
      <div id="stats-band">
      <h2 data-tip="Aggregate read live from the memory store. These are what the house has actually learned — not configured numbers.">live state</h2>
      <div class="lead">Read live from the house's memory.</div>
      <div class="stats">
        <a href="/house/ledger" class="cell tilt reveal" data-tip="Distinct wallets the house has served, remembered with a trust score."><div class="num" id="st-callers">0</div><div class="lbl">counterparties remembered</div><div class="sub">live ledger →</div></a>
        <a href="/house/ledger" class="cell tilt reveal" data-tip="Average trust across remembered callers. Trust drives the price each wallet is quoted."><div class="num amber" id="st-trust">0</div><div class="lbl">mean trust</div><div class="sub">live ledger →</div></a>
        <a href="/house/front" class="cell tilt reveal" data-tip="Average provider quality, from completed work. Drives bond premiums and hiring terms."><div class="num" id="st-quality">0</div><div class="lbl">provider quality</div><div class="sub">front office →</div></a>
        <a href="/house/ledger" class="cell tilt reveal" data-tip="USDC the house has not spent re-computing a repeat request — served from memory at net $0 instead."><div class="num green" id="st-dedup">0</div><div class="lbl">usdc saved · repeat serves</div><div class="sub">live ledger →</div></a>
      </div>
      <p class="mem-explain reveal">These four numbers are aggregates read live from the memory store — not configured figures.
        Each is derived from the same rows the request path reads before it prices a wallet: the counterparty
        ledger, the dedup counter, and the provider book.
        <br><br>
        Watch the panel replay the house's real settlement on Base, step by step: <b>recall</b> the
        wallet, <b class="hl">read memory</b> to see what the house knows about it, <b>price</b> it,
        <b>serve</b> it, then <b class="hl">write memory</b> with what it learned. The two memory steps
        are highlighted — they are the difference between a vending machine and a business.
        <br><br>
        Right now the house has served one wallet: a stranger at list price, now remembered at trust 53.
        The next payment from that wallet is a repeat — recognized from memory, served at <b>net $0</b>,
        and the usdc-saved number above moves. More serves, more trust. <b>The business model is the memory.</b></p>
      <div class="replay reveal" id="replay">
        <div class="rp-head">
          <span class="rp-title">memory · deciding live</span>
          <span class="rp-live" id="rp-live"><span class="dot" id="rp-dot"></span><span id="rp-status">connected</span></span>
        </div>
        <div class="rp-body" id="replay-body" aria-live="polite"></div>
        <div class="rp-foot">
          <span class="rp-proof">settled on base</span>
          <span class="rp-progress" id="rp-progress"></span>
        </div>
      </div>
      </div>
      <div class="no-record-band"><span class="nr-dot"></span><span id="nr-stats">memory is off.</span></div>
    </section>

    <!-- THE HOUSE REMEMBERS -->
    <section class="section reveal">
      <div id="remember-band">
      <h2 data-tip="Every wallet the house has met, remembered with what it did and what the house now trusts it with. Trusted and new are shown as they are; a banned wallet would be refused, not charged.">the house remembers</h2>
      <div class="lead">Every wallet that has paid the house is remembered — what it used, how often, and what the house now trusts it with. Open a card to see exactly how its numbers were derived.</div>
      <button class="collap-bar" id="remember-toggle" type="button" aria-expanded="false">
        <span class="cb-title"><span class="cb-caret">▾</span>counterparties &amp; providers the house holds</span>
        <span class="cb-count" id="remember-count">0 remembered</span>
      </button>
      <div class="collap-wrap" id="remember-wrap">
      <div class="remember" id="remember-grid"></div>
      <div class="rw-trajectory reveal" id="ladder-band">
        <div class="rw-t-label">how trust is built — real serves on base</div>
        <div class="rw-t-steps" id="trust-ladder"></div>
        <div class="rw-t-events">
          <span class="rw-t-ev dedup">a repeat request is served from memory at net $0</span>
          <span class="rw-t-ev gate">memory off → every wallet is a stranger again</span>
        </div>
      </div>
      <p class="mem-explain reveal">
        Trust is not a slider — it is <b class="hl">built, serve by serve</b>. Every wallet in the grid above paid
        the house a real USDC settlement on Base, and the ladder is its trust as it exists in the live ledger
        right now: one serve, <b>50→53</b>. Each further serve raises that wallet's trust; a repeat request is
        recognized and served from memory at <b>net $0</b>; a serve that fails is recorded as a
        <b class="hl">scar</b>; a risky wallet is <b class="hl">refused</b> with a 403 and not charged.
        <b>None of that survives memory going off</b>: a trusted wallet becomes a stranger again at list price —
        flip the gate below and watch this section blank out.
      </p>
      </div>
      </div>
      <div class="no-record-band"><span class="nr-dot"></span><span id="nr-remember">memory is off.</span></div>
    </section>

    <!-- LIVE LEDGER -->
    <section class="section">
      <h2 data-tip="Every settlement the house wallet received, each with its Basescan tx hash.">proof · onchain</h2>
      <div class="lead">Settlements the house wallet <em>received</em> on Base mainnet. Every row links to its Basescan transaction.</div>
      <div class="ledger reveal" id="ledger">
        <div class="row head">
          <span>transaction</span><span>what happened</span><span>usdc</span><span>memory delta</span><span>age</span>
        </div>
        <div id="ledger-rows"></div>
      </div>
    </section>

    <!-- MEMORY FLOW -->
    <section class="section">
      <h2 data-tip="The actual request pipeline, in order. Memory is read before pricing and written after serving — the two memory steps are what make this a memory business, not a vending machine.">why memory is load-bearing</h2>
      <div class="lead">The request path reads memory before it prices: pay → read memory → price → serve → write memory.</div>
      <div class="flow reveal">
        <svg viewBox="0 0 900 240" role="img" aria-label="memory flow diagram">
          <defs>
            <marker id="farr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#6B6B6B"/>
            </marker>
            <marker id="farrAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#8FC7FF"/>
            </marker>
          </defs>
          <!-- nodes -->
          <g class="fnode"><rect x="20" y="80" width="120" height="52"/><text class="t" x="80" y="112">caller</text></g>
          <g class="fnode"><rect x="200" y="80" width="120" height="52"/><text class="t" x="260" y="112">pay</text></g>
          <g class="fnode mem"><rect x="380" y="80" width="120" height="52"/><text class="t" x="440" y="112">read memory</text></g>
          <g class="fnode"><rect x="560" y="80" width="120" height="52"/><text class="t" x="620" y="112">price</text></g>
          <g class="fnode"><rect x="740" y="80" width="120" height="52"/><text class="t" x="800" y="112">serve</text></g>
          <!-- arrows -->
          <line class="arrow" x1="140" y1="106" x2="198" y2="106" marker-end="url(#farr)"/>
          <line class="arrow" x1="320" y1="106" x2="378" y2="106" marker-end="url(#farr)"/>
          <line class="arrow" x1="500" y1="106" x2="558" y2="106" marker-end="url(#farr)"/>
          <line class="arrow" x1="680" y1="106" x2="738" y2="106" marker-end="url(#farr)"/>
          <!-- feedback: serve -> write memory -> read -->
          <path class="arrow feed" d="M800 132 L800 190 L440 190 L440 134" fill="none" marker-end="url(#farrAmber)"/>
          <text class="fstep mem" x="620" y="206">write memory ← what it learned</text>
          <text class="fstep" x="80" y="152">who are you?</text>
          <text class="fstep" x="260" y="152">x402 exact</text>
          <text class="fstep" x="440" y="152">priced by trust</text>
          <text class="fstep" x="620" y="152">dedup · refusal</text>
          <text class="fstep" x="800" y="152">then remember</text>
        </svg>
      </div>
    </section>

    <!-- ROOMS -->
    <section class="section reveal">
      <h2 data-tip="The house's five business functions. Each one is a live endpoint you can open — and each one reads the same shared memory.">the rooms</h2>
      <div class="lead">Five operational surfaces, one shared memory. Each is a live endpoint.</div>
      <p class="section-note">The house runs five functions — taking payment, pricing by trust, underwriting,
        hiring providers, and screening risk. Every one of them reads the same memory, so a wallet's history
        changes how the house treats it everywhere at once. Click a room to see its live table.</p>
      <div class="tabs" id="room-tabs">
        <button class="tab active" data-room="0">0 · money floor</button>
        <button class="tab" data-room="1">1 · trust desk</button>
        <button class="tab" data-room="2">2 · underwriting</button>
        <button class="tab" data-room="3">3 · front office</button>
        <button class="tab" data-room="4">4 · watchtower</button>
      </div>
      <div class="room-panel active" data-room="0">
        <h3><span class="rn">0</span>The money floor</h3>
        <p class="desc">Every payment the house has received and served, in one ledger. Each row is a real
          transaction you can open on Basescan — this is the reconciliation a payment receipt alone cannot give.</p>
        <div class="mem-note"><b>Memory does:</b> the house journals each serve and writes what it learned about the payer.</div>
        <div class="room-actions"><a class="btn ghost sm" href="/house/ledger">open ledger</a></div>
        <div id="room0"></div>
      </div>
      <div class="room-panel" data-room="1">
        <h3><span class="rn">1</span>The trust desk</h3>
        <p class="desc">Every wallet that has paid the house before, with the trust score built up from its history.
          That score is what changes the price the wallet is quoted next time. Addresses are anonymized to their last six characters.</p>
        <div class="mem-note"><b>Memory does:</b> known callers pay less, strangers pay list price, banned wallets are refused.</div>
        <div class="room-actions">
          <a class="btn primary sm" href="/gallery?fn=intel_quote">try it — ask the house</a>
          <a class="btn ghost sm" href="/gallery?fn=prepay">try it — fund credit</a>
        </div>
        <div id="room1"></div>
      </div>
      <div class="room-panel" data-room="2">
        <h3><span class="rn">2</span>Underwriting</h3>
        <p class="desc">Bonds issued, premiums collected, claims paid. The house underwrites insurance for the agents
          it works with, and the premium it offers depends on what it remembers about each provider.</p>
        <div class="mem-note"><b>Memory does:</b> a proven provider receives the discounted premium; a risky one is refused before settlement.</div>
        <div class="room-actions">
          <a class="btn primary sm" href="/gallery?fn=bond_quote">try it — underwrite a provider</a>
        </div>
        <div id="room2"></div>
      </div>
      <div class="room-panel" data-room="3">
        <h3><span class="rn">3</span>The front office</h3>
        <p class="desc">Every provider the house can delegate work to, with the terms it would offer each one.
          Memory drafts the proven and refuses the scarred — the remembered provider is chosen, not the cheapest.</p>
        <div class="mem-note"><b>Memory does:</b> provider quality, defaults and bond claims are read from memory.</div>
        <div class="room-actions">
          <a class="btn primary sm" href="/gallery?fn=scout_report">try it — provider report</a>
          <a class="btn ghost sm" href="/gallery?fn=scout_hire">try it — hire decision</a>
        </div>
        <div id="room3"></div>
      </div>
      <div class="room-panel" data-room="4">
        <h3><span class="rn">4</span>The watchtower</h3>
        <p class="desc">A risk screen run on every counterparty before money moves. Each wallet is marked CLEAR, HOLD or
          ABORT with the rule that fired — the house refuses to launder, and the refusals are published.</p>
        <div class="mem-note"><b>Memory does:</b> the screen is a deterministic memory read with a monetary consequence.</div>
        <div class="room-actions">
          <a class="btn primary sm" href="/gallery?fn=watch_screen">try it — screen a wallet</a>
          <a class="btn ghost sm" href="/gallery?fn=intel_entity">try it — entity dossier</a>
        </div>
        <div id="room4"></div>
      </div>
    </section>

    <!-- ACP / VIRTUALS -->
    <section class="section reveal">
      <h2 data-tip="The house doesn't only take money — it also hires other AI agents through Virtuals' Agent Commerce Protocol, paying them on Base. Its memory of each provider changes the terms it offers. Each job below is a real delegation settled on Base.">the agent rail · Virtuals ACP</h2>
      <div class="lead">The house delegates real work to other agents over Virtuals ACP and pays them on Base. What it remembers about each provider changes the terms it offers — and it can check any provider, live.</div>
      <p class="section-note">the-house holds its own ACP identity
        and wallet on Base; each row below is a real job it funded and completed, with every escrow settled
        onchain. Ask the checker for any provider and it returns the terms it
        would offer right now — then the same terms with memory off, so you can see exactly what memory is worth.</p>
      <div class="acp tilt reveal">
        <div class="head">
          <div class="title">ACP delegations on <span>Base</span></div>
          <div class="badge" id="acp-badge">×1.25 · exercised</div>
        </div>
        <div class="agent-strip">
          <div class="a-cell"><span class="k">agent</span><span class="v" id="acp-agent-name">the-house</span></div>
          <div class="a-cell"><span class="k">agent id</span><span class="v hash" id="acp-agent-id"></span></div>
          <div class="a-cell"><span class="k">wallet</span><span class="v hash" id="acp-agent-wallet"></span></div>
          <div class="a-cell"><span class="k">acp core</span><span class="v hash" id="acp-core"></span></div>
        </div>
        <button class="collap-bar green" id="acp-toggle" type="button" aria-expanded="false">
          <span class="cb-title"><span class="cb-caret">▾</span>delegations on Base — funded + released escrow</span>
          <span class="cb-count" id="acp-count">3 jobs</span>
        </button>
        <div class="collap-wrap" id="acp-wrap">
        <div class="jobs" id="acp-jobs"></div>
        <div class="acp-live" id="acp-live"></div>
        </div>

        <div class="checker">
          <div class="fhead">ask the house its terms for a provider</div>
          <div class="check-row">
            <input id="acp-provider" class="acp-input" spellcheck="false"
                   placeholder="0x… provider address"
                   value="0x436f324eff0b32a405c5b9102e1a6ef85451cec1" />
            <button class="btn primary sm" id="acp-check">check terms</button>
          </div>
          <div class="check-hint" id="acp-check-hint">the default is BitsAndBytesBack — the proven provider behind job #77330.</div>
          <div class="check-out" id="acp-check-out" style="display:none">
            <div class="flip-cards">
              <div class="flip-card" id="acp-on">
                <div class="fhead">with memory <span class="on-tag">live read</span></div>
                <div class="term"><span class="k">segment</span><span class="v" id="acp-on-seg">—</span></div>
                <div class="term"><span class="k">hired</span><span class="v" id="acp-on-hired">—</span></div>
                <div class="term"><span class="k">evaluator</span><span class="v" id="acp-on-eval">—</span></div>
                <div class="term"><span class="k">reason</span><span class="v reason" id="acp-on-reason">—</span></div>
              </div>
              <div class="flip-card" id="acp-off">
                <div class="fhead">with memory off <span class="off-tag">what deletion does</span></div>
                <div class="term"><span class="k">segment</span><span class="v" id="acp-off-seg">—</span></div>
                <div class="term"><span class="k">hired</span><span class="v" id="acp-off-hired">—</span></div>
                <div class="term"><span class="k">evaluator</span><span class="v" id="acp-off-eval">—</span></div>
                <div class="term"><span class="k">reason</span><span class="v reason" id="acp-off-reason">—</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- MEMORY CONTROL (two modes) -->
    <section class="section reveal" id="gate">
      <h2 data-tip="Two real ways to take the house's memory off. Disable is soft — the house stops reading and writing, but the data is kept and it re-enables itself in 15 minutes. Purge is permanent — the store is erased, irreversibly; there is no countdown and no way back.">memory control</h2>
      <div class="lead">Two ways to take the house's memory off. <b>Disable</b> is reversible — the data is kept and it self-heals in 15 minutes. <b>Purge</b> is permanent — the store is erased, irreversibly.</div>
      <div class="gate reveal">
        <div class="ghead">
          <div class="gtitle">Memory <span>control</span></div>
          <div class="status-line"><span id="gate-status">memory is <b class="green">live</b></span></div>
        </div>
        <div class="countdown" id="gate-countdown" style="display:none"></div>
        <div class="status-line" id="gate-detail"></div>
        <div class="actions">
          <button class="btn soft" id="disable-btn">Disable memory <span class="rec">(recommended)</span></button>
          <button class="btn danger" id="wipe-btn">Purge memory <span class="nrec">(not recommended)</span></button>
          <button class="btn ghost" id="enable-btn" style="display:none">Re-enable now</button>
        </div>
      </div>
    </section>

    <!-- DISCOVERY -->
    <section class="section">
      <h2 data-tip="The bet this project makes — and what memory becomes when it is the product instead of a log.">the thesis</h2>
      <div class="lead">Memory is the load-bearing layer under payments.</div>
      <div class="discovery reveal">
        <div class="q">The agent economy treats every counterparty as a stranger. The house is the counter-example:
          pricing, dedup, refusal, underwriting, hiring and screening all read the same remembered truth.
          Remove it and the business returns to a stateless price list.</div>
        <p>This is the thesis the sponsors' own memory tech makes possible — what memory becomes when it is the
          product, not a sidecar.</p>
        <div>
          <span class="partner">Base · mem</span>
          <span class="partner">Virtuals · ACP</span>
          <span class="partner">x402 · exact</span>
          <span class="partner">Sibyl · memory</span>
        </div>
      </div>
    </section>

    <!-- ENDPOINTS -->
    <section class="section" id="endpoints">
      <div class="eps-head">
        <div>
          <h2 data-tip="Every route the house exposes — what it returns, and how each one changes when memory is turned off. Toggle memory below to see the collapse live.">the surface</h2>
          <div class="lead" style="margin-top:8px">Everything the house exposes, and what each does — with the difference memory makes. Flip memory off to watch the paid functions lose it.</div>
        </div>
        <div class="eps-toggle" id="eps-toggle" role="switch" aria-checked="true" tabindex="0">
          <span class="lbl">memory</span>
          <span class="st" id="eps-st">on</span>
          <span class="sw"><span class="knob"></span></span>
        </div>
      </div>
      <div class="eps-group" data-ep-group>
        <div class="glabel">paid · x402 on base</div>
        <div class="eps-strip">
          <div class="ep-card" data-ep="intel/quote" data-on="Serves your question from the house's memory. Repeats from the same wallet are served from cache at net $0 (dedup); trust and tx count move with every serve." data-off="Recall returns nothing, so the answer is always 'new wallet — list price'. No dedup, no trust pricing, no repeat refund. The function still answers; it just never remembers."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price">$0.01 · intel</span></div><span class="ep-path">/intel/quote</span><span class="ep-room">trust desk</span><p class="ep-brief">Ask the house a question from its memory. Repeats are served at net $0.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="intel_quote">try it ↗</button></div></div></div></div>
          <div class="ep-card" data-ep="intel/entity" data-on="A live cross-room dossier of one wallet — trust, dedup, bonds, watch, journal. Unknown wallet → 404 (uncharged). Always re-read, never cached." data-off="No caller/provider/bond rows exist, so every wallet is a 404. The house sells what it has — and it has nothing."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price">$0.02 · intel</span></div><span class="ep-path">/intel/entity/:name</span><span class="ep-room">dossier</span><p class="ep-brief">The house's full remembered picture of one wallet. Only sells what it has.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="intel_entity">try it ↗</button></div></div></div></div>
          <div class="ep-card" data-ep="bond/quote" data-on="Issues a bond on a provider. Premium is priced from its remembered quality: proven → discounted (rebated as a real tx); unknown → base; risky → refused 403, uncharged." data-off="Every provider is 'unknown' at the base premium. No discount, no refusal — the house underwrites blind."><div class="ep-top"><span class="ep-verb">POST</span><span class="ep-price">$0.05 · bond</span></div><span class="ep-path">/bond/quote</span><span class="ep-room">underwriting</span><p class="ep-brief">The house bonds a provider with its own money. Premium from remembered quality.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="bond_quote">try it ↗</button></div></div></div></div>
          <div class="ep-card" data-ep="watch/screen" data-on="Deterministic counterparty screen: CLEAR / HOLD / ABORT + the fired evidence (self-pay, sybil cluster, factory, metronome). A wash caller is refused with the ring drawn." data-off="No caller rows → no clusters, no rings, no verdicts. Every wallet screens CLEAR. The house cannot see the wash ring it was built to catch."><div class="ep-top"><span class="ep-verb">POST</span><span class="ep-price">$0.02 · screen</span></div><span class="ep-path">/watch/screen</span><span class="ep-room">watchtower</span><p class="ep-brief">A deterministic risk screen — CLEAR, HOLD or ABORT — with the evidence that fired.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="watch_screen">try it ↗</button></div></div></div></div>
          <div class="ep-card" data-ep="scout/report" data-on="The house's record on a provider — jobs, quality, on-time, defaults, claims — priced by its remembered quality (a costly record quotes a premium)." data-off="No record exists, so every report is a clean base-price 'unknown' entry. The house rates nobody."><div class="ep-top"><span class="ep-verb">POST</span><span class="ep-price">$0.03 · report</span></div><span class="ep-path">/scout/report</span><span class="ep-room">front office</span><p class="ep-brief">The house's experience with a provider, priced by its remembered quality.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="scout_report">try it ↗</button></div></div></div></div>
          <div class="ep-card" data-ep="scout/hire" data-on="A hiring ruling on a provider: proven → preferred terms; unknown → standard + stricter evaluator; risky → refused 403 before any work. Journaled as hiring memory." data-off="Every provider is 'unknown' at standard terms. The house hires blind — exactly the disease the room cures."><div class="ep-top"><span class="ep-verb">POST</span><span class="ep-price">$0.05 · hire</span></div><span class="ep-path">/scout/hire</span><span class="ep-room">front office</span><p class="ep-brief">The house's hiring ruling: preferred, standard, or refused — from its record.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="scout_hire">try it ↗</button></div></div></div></div>
          <div class="ep-card" data-ep="prepay/topup" data-on="Funds a prepay credit on your wallet, spendable against a risky serve's surcharge. The house keeps only a small handling fee onchain." data-off="The credit can still be added, but with no trust model there is no surcharge to spend it against — it sits unused."><div class="ep-top"><span class="ep-verb">POST</span><span class="ep-price">$0.005 · fee</span></div><span class="ep-path">/prepay/topup</span><span class="ep-room">trust desk</span><p class="ep-brief">Add USDC credit a risky wallet needs before the house will serve it.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><button class="ep-tryit" data-try="prepay">try it ↗</button></div></div></div></div>
        </div>
      </div>
      <div class="eps-group" data-ep-group>
        <div class="glabel">free · live read</div>
        <div class="eps-strip">
          <div class="ep-card" data-ep="house/ledger" data-on="Every caller, trust score, segment, dedup state and lifetime USDC — the money shot. Anonymous to the last six chars." data-off="An empty ledger: no callers, no trust, no USDC. The business model, made visible, then gone."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/ledger</span><span class="ep-room">the desk</span><p class="ep-brief">The raw caller ledger: trust, segment, dedup, lifetime USDC.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/ledger" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/journal" data-on="The COLD journal — every settlement, refusal, failure and screen, timestamped. The audit trail is the pitch." data-off="No events written since the wipe. The journal is blank."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/journal</span><span class="ep-room">the trail</span><p class="ep-brief">Every settlement, refusal and screen — the full audit trail.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/journal" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/jobs" data-on="Live job state machines (F4) — kill the process mid-serve and it resumes, settling idempotently with no double charge." data-off="No job rows are persisted, so there is nothing to resume. Kill-resume requires memory."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/jobs</span><span class="ep-room">the state</span><p class="ep-brief">Live job state machines — kill-safe, idempotent settlement.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/jobs" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/front" data-on="The front-office draft board: every provider the house has hired, with terms + segment." data-off="An empty board — nothing remembered, nothing drafted."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/front</span><span class="ep-room">front office</span><p class="ep-brief">The draft board: every provider the house has hired or considered.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/front" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/watch" data-on="The verdict feed: every screen the tower has published, with the evidence." data-off="No screens land, so the feed stays empty."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/watch</span><span class="ep-room">watchtower</span><p class="ep-brief">The verdict feed: every screen, with the evidence that fired.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/watch" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/bonds" data-on="The bond book: every provider bond, face, premium and any claim the house paid." data-off="No bonds, no claims. The underwriting desk has no book."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/bonds</span><span class="ep-room">underwriting</span><p class="ep-brief">The bond book: every bond, premium and paid claim.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/bonds" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/audit" data-on="E1 self-audit: current health diffed against the baseline — degradation report in markdown/JSON." data-off="No baseline is recorded, so there is nothing to diff."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/audit</span><span class="ep-room">self-audit</span><p class="ep-brief">Current health diffed against the baseline — the degradation report.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/audit" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
          <div class="ep-card" data-ep="house/calibrate" data-on="E2 calibration: trust-decision precision/recall, realized-vs-base pricing, dedup hit-rate, scar hit-rate." data-off="No journal to read, so no calibration metrics can be computed."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/calibrate</span><span class="ep-room">calibration</span><p class="ep-brief">Decision precision, realized pricing, dedup and scar hit-rates.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/calibrate" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
        </div>
      </div>
      <div class="eps-group" data-ep-group>
        <div class="glabel">memory · the switch</div>
        <div class="eps-strip">
          <div class="ep-card danger" data-ep="memory/purge" data-on="Purges the memory store — a true, PERMANENT deletion: the file is closed and removed. Irreversible: no countdown, no restore, no re-seed. The house is blind for good." data-off="The active state. Every read returns empty and every write no-ops. Every counterparty is a stranger at list price."><div class="ep-top"><span class="ep-verb">POST</span><span class="ep-price free">operator</span></div><span class="ep-path">/house/memory/purge</span><span class="ep-room">memory gate</span><p class="ep-brief">Purge the memory store — permanent and irreversible. No countdown, no way back.</p><span class="ep-more">what it does <span class="arr">→</span></span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div></div></div></div></div>
          <div class="ep-card" data-ep="memory/status" data-on="Reports whether the memory is live, disabled (soft off, data kept) or purged (permanently deleted), plus the disable countdown." data-off="Reports purged."><div class="ep-top"><span class="ep-verb">GET</span><span class="ep-price free">free</span></div><span class="ep-path">/house/memory/status</span><span class="ep-room">memory gate</span><p class="ep-brief">Reports whether memory is live, disabled or purged, and the disable countdown.</p><span class="ep-more">open in a tab ↗</span><div class="ep-detail"><div><div class="ep-dbody"><div class="ep-drow"><span class="k">on</span><span class="v" data-ep-on></span></div><div class="ep-drow"><span class="k">off</span><span class="v" data-ep-off></span></div><a class="ep-tryit" href="/house/memory/status" target="_blank" rel="noopener">open ↗</a></div></div></div></div>
        </div>
      </div>
      <div class="eps-hint">drag to scroll · tap a card to expand · flip the switch to compare</div>
    </section>

    <!-- PROOF -->
    <section class="section proof">
      <p>The desk is free and live, with caller addresses anonymized to their last six characters.</p>
      <div class="links">
        <a href="/house/ledger">/house/ledger</a>
        <a href="/house/jobs">/house/jobs</a>
        <a href="/house/audit">/house/audit</a>
        <a href="/house/calibrate">/house/calibrate</a>
        <a href="/house/front">/house/front</a>
        <a href="/house/bonds">/house/bonds</a>
        <a href="/house/watch">/house/watch</a>
        <a href="/house/journal">/house/journal</a>
        <a href="/manifest">manifest</a>
      </div>
      <p class="repo" id="repo"></p>
    </section>
  </main>

  <footer>
    <div class="foot-main">
      <span>the-house · base mainnet · x402 exact scheme</span>
      <span class="foot-links">
        <a href="https://sibyllabs.org/" target="_blank" rel="noopener">Sibyl Labs</a>
        <a href="https://hack.sibyllabs.org/" target="_blank" rel="noopener">Hackathon</a>
        <a href="https://x.com/sibyl_labs_" target="_blank" rel="noopener">X</a>
        <a href="https://discord.gg/csya975jMa" target="_blank" rel="noopener">Discord</a>
      </span>
    </div>
    <span id="ts"></span>
  </footer>
</div>

  __TRYIT_HTML__

<!-- memory action confirmation modal -->
<div class="modal-bg" id="modal-bg">
  <div class="modal">
    <h3 id="modal-title">Memory control</h3>
    <p id="modal-body"></p>
    <div class="warn" id="modal-warn"></div>
    <div class="progress" id="modal-progress" style="display:none"><span class="pdot"></span><span id="modal-progress-label">disabling memory…</span></div>
    <div class="mbtns">
      <button class="btn cancel" id="modal-cancel">Cancel</button>
      <button class="btn danger" id="modal-confirm">I understand</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
__TRYIT_JS__
</script>

<script>
  window.__HOUSE__ = __STATE__;
(function(){
  var S = window.__HOUSE__ || {stats:{},callers:[],providers:[],txs:[],acp:{jobs:[]},wipe:{}};
  document.documentElement.classList.add('js');
  document.body.classList.remove('no-js');
  document.body.classList.add('js');

  function $(id){return document.getElementById(id);}
  function esc(s){return (s==null?"":String(s)).replace(/[&<>"]/g,function(c){
    return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]);});}
  function money(v){return (v==null?0:Number(v)).toFixed(2);}
  function money4(v){return (v==null?0:Number(v)).toFixed(4);}
  function age(s){
    if(s==null||s<0){return "—";}
    if(s<90){return Math.round(s)+"s";}
    if(s<5400){return Math.round(s/60)+"m";}
    if(s<172800){return Math.round(s/3600)+"h";}
    return Math.round(s/86400)+"d";}
  function shortHash(h){return h?h.slice(0,10)+"…"+h.slice(-6):"—";}

  // Shared derivation constants — the documented trust/segment formulas from
  // core/config.py. Used by the replay engine and the per-card "how derived"
  // panels below, so every surface cites the same math.
  var SEG_MULT = {new:1.0, regular:0.95, vip:0.80, risky:1.30, banned:0};
  var SEG_THRESH = {
    new:"trust ≥40 and fewer than 3 serves",
    regular:"3 or more delivered serves",
    vip:"trust ≥80 and 10 or more serves",
    risky:"trust <40, or 3 or more warnings",
    banned:"trust <20, or 3 or more refunds → refused, uncharged"
  };

  // ---- first paint from state ----
  function paint(){
    var st=S.stats||{};
    setNum("st-callers", st.callers!=null?st.callers:0);
    setNum("st-trust", st.trust!=null?st.trust:0, 1);
    setNum("st-quality", st.quality!=null?st.quality:0, 2);
    var d=st.dedup_hits!=null?st.dedup_hits:0;
    setNum("st-dedup", d);
    if(S.commit){
      var h=$("hash");
      if(S.repo_url){h.innerHTML = "<a href='"+esc(S.repo_url)+"/commit/"+esc(S.commit)+"' target='_blank' rel='noopener'>commit "+esc(S.commit)+"</a>";}
      else{h.textContent = "commit "+S.commit;}
    }
    $("ts").textContent = S.ts||"";
    if(S.repo_url){$("repo").innerHTML = "repository: <a href='"+esc(S.repo_url)+"' target='_blank' rel='noopener'>"+esc(S.repo_url)+"</a>";}
    else{$("repo").textContent = "repository: private build page (public repo at submission)";}
    paintMemory(S.memory);
    paintLedger();
    paintRooms();
    paintAcpAgent();
    paintAcp();
    paintGate();
    rpStart();
    paintHeroCards();
    paintRemember();
  }
  function setNum(id,v,dec){
    var el=$(id); if(!el)return;
    var n=Number(v||0);
    el.textContent = (dec!=null ? n.toFixed(dec) : String(Math.round(n)));
  }
  function paintMemory(mem){
    var dot=$("mem-dot"), st=$("mem-status");
    var live = mem==="live";
    var purged = mem==="purged";
    if(dot){dot.className="dot"+(live?"":" off");}
    if(st){st.textContent="MEMORY "+(live?"LIVE":(purged?"PURGED":"OFF"));}
    var rec=$("mem-recover");
    if(rec){rec.style.display=(live||purged)?"none":"inline";}
    // header button language: disable memory when live, restore memory when off
    var hg=$("header-gate");
    if(hg){
      if(live){ hg.textContent="disable memory"; hg.style.borderColor="rgba(192,57,43,.5)"; hg.style.color="#ff8a7a"; }
      else { hg.textContent="restore memory"; hg.style.borderColor="rgba(39,174,96,.5)"; hg.style.color="#8fd9ac"; }
    }
    if($("graph-status")){$("graph-status").textContent = live?"connected":(purged?"memory purged":"memory disabled");}
    var gLive=$("graph-live"), gDot=$("graph-dot");
    if(gLive){gLive.classList.toggle("off",!live);}
    if(gDot){gDot.className="dot"+(live?"":" off");}
    // the memory-off collapse: blank + shrink every memory-derived view
    if(document.body){
      document.body.classList.toggle("mem-off", !live);
      document.body.setAttribute("data-memory", mem);
    }
    // wipe the graph nodes
    var nodes=document.querySelectorAll(".graph .node");
    for(var i=0;i<nodes.length;i++){nodes[i].style.opacity = live?"1":"0.15";}
    // rebuild the live graph + trust ladder from the current ledger
    paintMemoryGraph();
    paintTrustLadder();
    // hero replay: pause + show blind state when memory is off
    if(rpPaused!==undefined){
      rpPaused=!live;
      var rpLive=$("rp-live"), rpStatus=$("rp-status"), rpDot=$("rp-dot");
      if(rpLive){rpLive.classList.toggle("off",!live);}
      if(rpDot){rpDot.className="dot"+(live?"":" off");}
      if(rpStatus){rpStatus.textContent=live?"connected":"memory off";}
      if(!live){if(rpTimer){clearTimeout(rpTimer);}rpRender();}
      else{rpRender();}
    }
    // header recovery timer only for a soft-off (disabled) — it self-heals in
    // 15 min. A purge is permanent: no countdown, no recovery.
    var rec2=$("mem-recover");
    if(!live && !purged && rec2){
      rec2.style.display="inline";
      if(!recoverEndAt){recoverEndAt=Date.now()+(gateState.remaining_seconds||0)*1000;}
      updateRecover();
    }else if(rec2){
      rec2.style.display="none";
      recoverEndAt=null;
    }
  }
  function updateRecover(){
    var rec=$("mem-recover");
    if(!rec||rec.style.display==="none")return;
    var rem;
    if(recoverEndAt){rem=Math.max(0,Math.round((recoverEndAt-Date.now())/1000));}
    else{rem=gateState.remaining_seconds||0;}
    rec.textContent=" · re-enables in "+fmtCountdown(rem);
  }

  // ---- live memory graph: rendered from the real ledger, never hardcoded ----
  var SVGNS="http://www.w3.org/2000/svg";
  function svgEl(tag,attrs){
    var el=document.createElementNS(SVGNS,tag);
    for(var k in attrs){el.setAttribute(k,attrs[k]);}
    return el;
  }
  // callers appear with a full address in the initial state blob but only a
  // last-6 after the live ledger poll — normalize.
  function cLast6(c){
    if(c.address_last6)return c.address_last6;
    if(c.addr_last6)return c.addr_last6;
    if(c.address)return c.address.slice(-6);
    return "—";
  }
  function paintMemoryGraph(){
    var cp=$("graph-cps"), ed=$("graph-edges");
    if(!cp||!ed)return;
    cp.innerHTML=""; ed.innerHTML="";
    if((S.memory||"live")!=="live")return; // blank while memory is off
    var items=[];
    var callers=S.callers||[], provs=S.providers||[];
    if(callers.length){
      var c=callers[0];
      items.push({x:85, label:"0x…"+cLast6(c),
        sub:(c.segment||"new")+" · trust "+(c.trust_score!=null?c.trust_score:"—"), href:c.address||""});
    }
    if(provs.length){
      var p=provs[0], paddr=p.provider||"";
      items.push({x:85, label:"0x…"+(p.provider_last6||(paddr?paddr.slice(-6):"—")),
        sub:"provider · q "+(p.quality_score!=null?Number(p.quality_score).toFixed(2):"—"), href:paddr});
    }
    if(!items.length)return; // nothing remembered → nothing drawn
    var ys = items.length===1 ? [120] : [66,174];
    for(var i=0;i<items.length;i++){
      var it=items[i], y=ys[i];
      // edge core → node
      ed.appendChild(svgEl("line",{x1:350,y1:120,x2:it.x,y2:y,"marker-end":"url(#arrAmber)","class":"edge mem"}));
      var g=svgEl("g",{"class":"node"});
      var a=svgEl("a",{href:"https://basescan.org/address/"+(it.href||""),target:"_blank","rel":"noopener"});
      g.appendChild(svgEl("circle",{cx:it.x,cy:y,r:52,fill:"#161616",stroke:"#1E1E1E","stroke-width":"2"}));
      var t1=svgEl("text",{x:it.x,y:y-6,"text-anchor":"middle",fill:"#E8E8E8","font-family":"Space Mono,monospace","font-size":"13"});
      t1.textContent=it.label;
      var t2=svgEl("text",{x:it.x,y:y+12,"text-anchor":"middle",fill:"#6B6B6B","font-family":"Space Mono,monospace","font-size":"10"});
      t2.textContent=it.sub;
      g.appendChild(t1); g.appendChild(t2); a.appendChild(g); cp.appendChild(a);
    }
  }

  // ---- trust ladder: rendered from the real ledger (trust per served wallet) ----
  function paintTrustLadder(){
    var el=$("trust-ladder"); if(!el)return;
    if((S.memory||"live")!=="live"){el.innerHTML="";return;}
    var steps=[];
    var callers=S.callers||[];
    for(var i=0;i<callers.length;i++){
      var c=callers[i], t=c.trust_score;
      if(t==null)continue;
      var n=c.tx_count!=null?c.tx_count:(c.served!=null?c.served:1);
      steps.push({v:t, label:"0x…"+cLast6(c)+" · "+n+" serve"+(n>1?"s":"")});
    }
    if(!steps.length){el.innerHTML="";return;}
    var h="";
    h+="<div class='rw-t-step'><b>50</b><span>stranger · list price</span></div><div class='rw-t-arrow'>→</div>";
    for(var j=0;j<steps.length;j++){
      h+="<div class='rw-t-step'><b>"+steps[j].v+"</b><span>"+esc(steps[j].label)+"</span></div>";
      if(j<steps.length-1){h+="<div class='rw-t-arrow'>→</div>";}
    }
    el.innerHTML=h;
  }

  // ---- ledger ----
  function paintLedger(){
    var txs=S.txs||[];
    var memLive=(S.memory||"live")==="live";
    var h="";
    for(var i=0;i<txs.length;i++){
      var t=txs[i];
      var zero = Number(t.usdc||0)<=0;
      // the memory delta only exists while memory is on — the chain record
      // (tx, amount) is immutable, but the memory note it produced is not.
      var delta = memLive ? esc(t.note||"") : "<span style='color:#3a3a3a'>— (memory off)</span>";
      h+="<div class='row'>"
        +"<a class='tx' href='https://basescan.org/tx/"+esc(t.hash)+"' target='_blank' rel='noopener'>"+esc(shortHash(t.hash))+"</a>"
        +"<span class='note'>"+esc(t.label||"")+"</span>"
        +"<span class='amt"+(zero?" zero":"")+"'>"+(zero?"net $0":money(t.usdc)+" USDC")+"</span>"
        +"<span class='delta'>"+delta+"</span>"
        +"<span class='age'>"+esc(t.ts||"onchain")+"</span>"
        +"</div>";
    }
    $("ledger-rows").innerHTML = h || "<div class='empty'>no settlements yet</div>";
  }

  // ---- rooms ----
  function paintRooms(){
    // room 0: money floor = the txs
    var txs=S.txs||[];
    var h="<table class='room-table'><tr><th>tx</th><th>what</th><th>usdc</th></tr>";
    for(var i=0;i<txs.length;i++){
      h+="<tr><td><a href='https://basescan.org/tx/"+esc(txs[i].hash)+"' target='_blank' rel='noopener'>"+esc(shortHash(txs[i].hash))+"</a></td>"
        +"<td>"+esc(txs[i].label||"")+"</td><td>"+money(txs[i].usdc)+"</td></tr>";
    }
    $("room0").innerHTML = h+"</table>";
    // room 1: trust desk (callers)
    var callers=S.callers||[];
    h="<table class='room-table'><tr><th>addr</th><th>segment</th><th>trust</th><th>tx</th><th>net $</th></tr>";
    for(var i=0;i<callers.length;i++){
      var c=callers[i];
      var addr=c.address||"";
      var disp=c.address_last6||"";
      h+="<tr><td>"+(addr?"<a href='https://basescan.org/address/"+esc(addr)+"' target='_blank' rel='noopener'>"+esc(disp)+"</a>":esc(disp))+"</td>"
        +"<td class='seg "+(c.segment||"")+"'>"+esc(c.segment||"—")+"</td>"
        +"<td>"+(c.trust_score!=null?c.trust_score:"—")+"</td>"
        +"<td>"+(c.tx_count!=null?c.tx_count:0)+"</td>"
        +"<td>"+money(c.net_charged_usdc||0)+"</td></tr>";
    }
    $("room1").innerHTML = h+"</table>";
    // room 3: front office (providers)
    var provs=S.providers||[];
    h="<table class='room-table'><tr><th>provider</th><th>segment</th><th>jobs</th><th>quality</th><th>terms</th></tr>";
    for(var i=0;i<provs.length;i++){
      var p=provs[i];
      var paddr=p.provider||"";
      var pdisp=p.provider_last6||"";
      h+="<tr><td>"+(paddr?"<a href='https://basescan.org/address/"+esc(paddr)+"' target='_blank' rel='noopener'>"+esc(pdisp)+"</a>":esc(pdisp))+"</td>"
        +"<td class='seg "+(p.segment||"")+"'>"+esc(p.segment||"—")+"</td>"
        +"<td>"+(p.jobs_done!=null?p.jobs_done:0)+"</td>"
        +"<td>"+(p.quality_score!=null?Number(p.quality_score).toFixed(2):"—")+"</td>"
        +"<td>"+(p.hired?"drafted":"refused")+"</td></tr>";
    }
    $("room3").innerHTML = h+"</table>";
    // room 2 + 4: fetch live
    fetchJson("/house/bonds").then(function(j){
      if(!j){return;}
      var b=j.book||{};
      var rows=j.bonds||[];
      var h="<div class='kv' style='font-family:mono;font-size:12px;color:var(--muted);margin-bottom:12px'>"
        +"bonds "+(b.bonds_issued!=null?b.bonds_issued:0)+" · premiums $"+money(b.premiums_collected_usdc||0)
        +" · claims "+(b.claims_paid!=null?b.claims_paid:0)+" · payouts $"+money(b.payouts_usdc||0)+"</div>";
      h+="<table class='room-table'><tr><th>bond</th><th>prov</th><th>face $</th><th>prem $</th><th>status</th></tr>";
      for(var i=0;i<rows.length;i++){
        h+="<tr><td>"+esc(rows[i].id||"—")+"</td><td>"+esc(rows[i].provider_last6||"—")+"</td>"
          +"<td>"+money(rows[i].face_usdc)+"</td><td>"+money(rows[i].premium_usdc)+"</td>"
          +"<td>"+esc(rows[i].status||"—")+"</td></tr>";
      }
      $("room2").innerHTML = h+"</table>";
    });
    fetchJson("/house/watch").then(function(j){
      if(!j){return;}
      var s=j.stats||{};
      var feed=j.feed||[];
      var h="<div class='kv' style='font-family:mono;font-size:12px;color:var(--muted);margin-bottom:12px'>"
        +"screens "+(s.screens!=null?s.screens:0)+" · organic "+(s.organic!=null?s.organic:0)
        +" · refusals "+(s.refusals!=null?s.refusals:0)+"</div>";
      h+="<table class='room-table'><tr><th>verdict</th><th>rule</th><th>ring</th></tr>";
      for(var i=0;i<feed.length;i++){
        h+="<tr><td>"+esc(feed[i].verdict||"—")+"</td><td>"+esc((feed[i].rules||[]).join(", ")||"clean")+"</td>"
          +"<td>"+esc((feed[i].ring||[]).map(function(x){return String(x).slice(-6);}).join(" ")||"—")+"</td></tr>";
      }
      $("room4").innerHTML = h+"</table>";
    });
  }

  // ---- ACP agent rail ----
  function acpCard(j, i){
    var tx = j.escrow_tx||"";
    var name = j.provider_name||"";
    var jid = j.id||j.job_id||"";
    var usdc = j.usdc!=null?j.usdc:(j.escrow_usdc!=null?j.escrow_usdc:0);
    var h = "<div class='job'>"
      +"<div class='jid'>job #"+esc(jid)+"</div>"
      +"<div class='off'>"+esc(j.offering||"")
      +(name?"<span class='prov'>"+esc(name)+"</span>":"")
      +"</div>"
      +"<div class='meta'>"+money(usdc)+" USDC escrow · <b>"+esc(j.status||"")+"</b></div>"
      +(tx?"<div class='meta proof'><a href='https://basescan.org/tx/"+esc(tx)+"' target='_blank' rel='noopener'>escrow tx "+esc(shortHash(tx))+" → Basescan</a></div>":"")
      +"</div>";
    return h;
  }
  function paintAcpAgent(){
    var a=(S.acp&&S.acp.agent)||{};
    $("acp-agent-name").textContent=a.name||"the-house";
    $("acp-agent-id").textContent=a.agent_id?shortHash(a.agent_id):"—";
    var w=$("acp-agent-wallet");
    if(a.wallet){
      w.innerHTML="";
      var wl=document.createElement("a");
      wl.href="https://basescan.org/address/"+esc(a.wallet);
      wl.target="_blank"; wl.rel="noopener"; wl.textContent="0x…"+a.wallet.slice(-6);
      w.appendChild(wl);
    } else { w.textContent="—"; }
    var c=$("acp-core");
    c.textContent=a.acp_core?shortHash(a.acp_core):"—";
    if(a.acp_core){
      var a2=document.createElement("a");
      c.innerHTML=""; c.textContent="";
      a2.href="https://basescan.org/address/"+esc(a.acp_core);
      a2.target="_blank"; a2.rel="noopener"; a2.textContent=shortHash(a.acp_core);
      c.appendChild(a2);
    }
  }
  function setAcpCount(n){var c=$("acp-count");if(c){c.textContent=(n||0)+" "+((n===1)?"job":"jobs");}}
  function paintAcp(){
    var jobs=(S.acp&&S.acp.jobs)||[];
    var h="";
    for(var i=0;i<jobs.length;i++){h+=acpCard(jobs[i],i);}
    $("acp-jobs").innerHTML = h || "<div class='empty'>no ACP jobs yet</div>";
    setAcpCount(jobs.length);
    // live status: refresh from the onchain index (server reads the ACP CLI)
    fetchJson("/house/acp/jobs").then(function(j){
      if(!j||!j.jobs){return;}
      var live=j.live;
      $("acp-badge").innerHTML = live
        ? "×1.25 · exercised <span class='live-dot'></span> live from the chain"
        : "×1.25 · exercised <span class='rec-dot'></span> recorded (live index offline)";
      var hh="";
      for(var i=0;i<j.jobs.length;i++){hh+=acpCard(j.jobs[i],i);}
      $("acp-jobs").innerHTML = hh;
      setAcpCount(j.jobs.length);
    });
  }

  // ---- deletion gate ----
  var gateState = S.wipe||{};
  var recoverEndAt = null;
  function paintGate(){
    var mode = gateState.mode || (gateState.purged?"purged":(gateState.disabled?"disabled":"live"));
    var st=$("gate-status");
    if(mode==="purged"){
      st.innerHTML = "memory is <b class='red'>purged — permanent</b>";
      $("gate-countdown").style.display="none";
      $("gate-detail").textContent = "the store is erased. this is irreversible — there is no countdown and no way back. the only reversible way to take memory off is disable.";
      $("disable-btn").style.display="none";
      $("wipe-btn").style.display="none";
      $("enable-btn").style.display="none";
    }else if(mode==="disabled"){
      st.innerHTML = "memory is <b class='gl'>disabled — data kept</b>";
      var rem=gateState.remaining_seconds||0;
      $("gate-countdown").style.display="block";
      $("gate-countdown").textContent = fmtCountdown(rem);
      $("gate-detail").textContent = "the house can't remember anyone: every request is a stranger at list price — no dedup, no trust pricing, no refusals. the data is kept; it re-enables itself in the background in 15 minutes, or re-enable now.";
      $("disable-btn").style.display="none";
      $("wipe-btn").style.display="inline-flex";
      $("enable-btn").style.display="inline-flex";
    }else{
      st.innerHTML = "memory is <b class='green'>live</b>";
      $("gate-countdown").style.display="none";
      $("gate-detail").textContent = "disable it and the house stops remembering — every request is a stranger at list price. purge it and the store is erased, permanently.";
      $("disable-btn").style.display="inline-flex";
      $("wipe-btn").style.display="inline-flex";
      $("enable-btn").style.display="none";
    }
  }
  function fmtCountdown(s){
    var m=Math.floor(s/60), sec=s%60;
    return m+"m "+String(sec).padStart(2,"0")+"s";
  }
  function refreshGate(){
    fetchJson("/house/memory/status").then(function(j){
      if(j&&j.memory){gateState=j.memory; paintGate();}
    });
  }

  // ---- memory actions (disable / purge / enable) ----
  var pendingAction=null;
  function openModal(title,body,warn,confirm,cls){
    $("modal-title").textContent=title;
    $("modal-body").textContent=body;
    $("modal-warn").textContent=warn;
    $("modal-progress").style.display="none";
    $("modal-confirm").textContent=confirm;
    $("modal-confirm").className="btn "+cls;
    $("modal-confirm").disabled=false;
    $("modal-cancel").disabled=false;
    $("modal-bg").classList.add("show");
  }
  function openDisableModal(){
    pendingAction="disable";
    openModal("Disable the memory? (recommended)",
      "The house stops reading and writing memory. Every request becomes a stranger at list price — no dedup, no trust pricing, no refusals.",
      "Data is kept — the house re-enables itself in the background in 15 minutes, or you can re-enable now. Nothing is lost.",
      "I understand — disable","soft");
  }
  $("header-gate").addEventListener("click",function(){
    if(gateState.mode==="disabled"||gateState.disabled||S.memory==="disabled"){
      // memory is off — the header button is now "restore memory"
      $("enable-btn").click();
    }else{
      openDisableModal();
    }
  });
  $("disable-btn").addEventListener("click",openDisableModal);
  $("wipe-btn").addEventListener("click",function(){
    pendingAction="purge";
    openModal("Purge the memory? (not recommended)",
      "Purging permanently erases the store: dedup savings, scars, refined trust and the journal are all gone. The house will have no recall of any counterparty.",
      "This is permanent and irreversible — the store is erased. There is no countdown and no way back. If you want memory off but recoverable, disable it instead.",
      "I understand — purge","danger");
  });
  $("modal-cancel").addEventListener("click",function(){$("modal-bg").classList.remove("show");});
  $("modal-bg").addEventListener("click",function(e){if(e.target===this){this.classList.remove("show");}});
  $("modal-confirm").addEventListener("click",function(){
    var act=pendingAction; pendingAction=null;
    var url = act==="disable" ? "/house/memory/disable" : "/house/memory/purge";
    var offMode = act==="disable" ? "disabled" : "purged";
    var emptyMsg = act==="disable"
      ? "<div class='empty'>memory disabled — the ledger is hidden (data kept)</div>"
      : "<div class='empty'>memory purged — permanently. the ledger is gone.</div>";
    var working = act==="disable" ? "disabling memory…" : "purging memory…";
    // live in-progress feedback: lock the modal, spin the confirm button,
    // pulse the progress line — the collapse plays on completion + toast.
    $("modal-confirm").disabled=true;
    $("modal-cancel").disabled=true;
    $("modal-confirm").classList.add("working");
    $("modal-progress-label").textContent=working;
    $("modal-progress").style.display="flex";
    fetch(url,{method:"POST",headers:{"Content-Type":"application/json"}})
      .then(function(r){return r.json();})
      .then(function(j){
        $("modal-confirm").classList.remove("working");
        if(j.ok){
          $("modal-bg").classList.remove("show");
          toast(j.reason,"ok");
          gateState=j.memory; paintGate();
          // collapse the live stats + graph + memory-derived sections
          S.memory=offMode; paintMemory(offMode);
          S.callers=[]; S.providers=[];
          setNum("st-callers",0); setNum("st-trust",0,1); setNum("st-quality",0,2); setNum("st-dedup",0);
          $("ledger-rows").innerHTML=emptyMsg;
          paintRemember(); paintHeroCards();
        }else{
          toast(j.reason,"err");
          refreshGate();
        }
      });
  });
  $("enable-btn").addEventListener("click",function(){
    fetch("/house/memory/enable",{method:"POST",headers:{"Content-Type":"application/json"}})
      .then(function(r){return r.json();})
      .then(function(j){
        if(j.ok){
          toast("memory back on — everything remembered returns","ok");
          gateState=j.memory; paintGate();
          S.memory="live"; paintMemory("live");
          refreshAll();
        }
      });
  });

  // ---- ACP terms checker (live read + what deletion does) ----
  function acpEval(strict){return strict?"stricter review":"trusted";}
  function acpHired(h){return h?"yes":"refused";}
  function setSeg(id,seg){
    var el=$(id); el.textContent=seg||"—";
    el.className="v"+(seg==="proven"?" ok":(seg==="risky"?" strict":""));
  }
  function runAcpCheck(){
    var p=$("acp-provider").value.trim();
    var hint=$("acp-check-hint");
    if(!/^0x[0-9a-fA-F]{40}$/.test(p)){
      hint.textContent="enter a 0x-prefixed 40-char provider address";
      return;
    }
    hint.textContent="reading the house's memory…";
    $("acp-check-out").style.display="none";
    fetchJson("/house/acp/terms?provider="+encodeURIComponent(p)).then(function(j){
      if(!j||j.error){
        hint.textContent=j?(j.error||"could not read terms"):"could not read terms (is the server up?)";
        return;
      }
      var on=j, off=j.no_memory_terms||{};
      setSeg("acp-on-seg",on.segment);
      $("acp-on-hired").textContent=acpHired(on.hired);
      $("acp-on-hired").className="v"+(on.refused?" strict":"");
      $("acp-on-eval").textContent=acpEval(on.strict_review);
      $("acp-on-reason").textContent=on.reason||"—";
      setSeg("acp-off-seg",off.segment);
      $("acp-off-hired").textContent=acpHired(off.hired);
      $("acp-off-hired").className="v"+(off.refused?" strict":"");
      $("acp-off-eval").textContent=acpEval(off.strict_review);
      $("acp-off-reason").textContent=off.reason||"—";
      var memState=j.memory_live
        ? "live read · memory "+(j.memory||"live")
        : "memory is "+(j.memory||"off")+" right now — every provider reads as unknown";
      var delta="";
      if((on.segment||"")!==(off.segment||"")){
        delta=" memory moves this provider from <b>"+esc(off.segment||"unknown")+"</b> to <b>"+esc(on.segment||"—")+"</b>.";
      }
      hint.innerHTML=memState+". the right-hand card is what the house offers the same provider once memory is off (a simulation of that state, computed from the same terms rule)."+delta;
      $("acp-check-out").style.display="block";
    });
  }
  $("acp-check").addEventListener("click",runAcpCheck);
  $("acp-provider").addEventListener("keydown",function(e){if(e.key==="Enter"){runAcpCheck();}});

  // ---- tabs ----
  var tabs=document.querySelectorAll(".tab");
  for(var i=0;i<tabs.length;i++){
    tabs[i].addEventListener("click",function(){
      var room=this.getAttribute("data-room");
      for(var j=0;j<tabs.length;j++){tabs[j].classList.toggle("active",tabs[j]===this);}
      var panels=document.querySelectorAll(".room-panel");
      for(var k=0;k<panels.length;k++){panels[k].classList.toggle("active",panels[k].getAttribute("data-room")===room);}
    });
  }

  // ---- collapsible sections: "house remembers" + ACP delegation rail ----
  // Both default to collapsed (reduces vertical length); the bar shows a live
  // count and the caret flips. The remember bar is glacier, the ACP bar green.
  function wireCollap(toggleId, wrapId){
    var bar=$(toggleId), wrap=$(wrapId);
    if(!bar||!wrap){return;}
    function flip(){
      var open=wrap.classList.toggle("open");
      bar.classList.toggle("open",open);
      bar.setAttribute("aria-expanded",open?"true":"false");
    }
    bar.addEventListener("click",flip);
  }
  wireCollap("remember-toggle","remember-wrap");
  wireCollap("acp-toggle","acp-wrap");

  // per-card "how derived": tap a card to expand its data-derived explanation.
  // Delegation (not per-card listeners) because the grid is re-rendered every
  // poll; clicking the address link still navigates (we let it win).
  (function(){
    var grid=$("remember-grid"); if(!grid)return;
    grid.addEventListener("click",function(e){
      var card=e.target.closest(".rw-card");
      if(!card||card!==e.target.closest(".rw-card"))return;
      if(e.target.closest(".rw-addr")){return;} // don't fight the link
      card.classList.toggle("open");
      var more=card.querySelector(".rw-more");
      if(more){more.textContent=card.classList.contains("open")?"collapse ▴":"how is this derived? ▾";}
    });
  })();

  // ---- endpoints strip: expand + memory on/off compare ----
  (function(){
    var cards=document.querySelectorAll(".ep-card");
    function setEpsState(on){
      for(var i=0;i<cards.length;i++){
        var c=cards[i];
        var onEl=c.querySelector("[data-ep-on]"), offEl=c.querySelector("[data-ep-off]");
        if(onEl) onEl.style.opacity = on?"1":".35";
        if(offEl) offEl.style.opacity = on?".35":"1";
      }
    }
    var tog=$("eps-toggle");
    // S.memory is the string "live" | "disabled" (the real house state at render).
    var epOn = !(S && S.memory === "disabled");
    function paintToggle(){
      if(!tog) return;
      tog.classList.toggle("off", !epOn);
      tog.setAttribute("aria-checked", epOn?"true":"false");
      var st=$("eps-st"); if(st) st.textContent = epOn?"on":"off";
      setEpsState(epOn);
    }
    if(tog){
      function flip(){ epOn=!epOn; paintToggle(); }
      tog.addEventListener("click",flip);
      tog.addEventListener("keydown",function(e){ if(e.key==="Enter"||e.key===" "){e.preventDefault();flip();} });
    }
    for(var i=0;i<cards.length;i++){
      (function(c){
        // fill the on/off text from data attrs (initial)
        var onEl=c.querySelector("[data-ep-on]"), offEl=c.querySelector("[data-ep-off]");
        if(onEl) onEl.textContent=c.getAttribute("data-on");
        if(offEl) offEl.textContent=c.getAttribute("data-off");
        c.addEventListener("click",function(e){
          if(e.target.closest(".ep-tryit")) return;   // let try/links do their thing
          c.classList.toggle("open");
        });
        var tryBtn=c.querySelector(".ep-tryit[data-try]");
        if(tryBtn){
          tryBtn.addEventListener("click",function(e){
            e.stopPropagation();
            var k=tryBtn.getAttribute("data-try");
            window.location.href = "/gallery?fn=" + encodeURIComponent(k);
          });
        }
      })(cards[i]);
    }
    paintToggle();
  })();

  // ---- reveal on scroll + ghost-out after leaving ----
  if("IntersectionObserver" in window){
    var io=new IntersectionObserver(function(entries){
      for(var i=0;i<entries.length;i++){
        if(entries[i].isIntersecting){entries[i].target.classList.add("in");io.unobserve(entries[i].target);}
      }
    },{threshold:.12});
    var reveals=document.querySelectorAll(".reveal");
    for(var r=0;r<reveals.length;r++){io.observe(reveals[r]);}
    // sections that have been revealed fade to ghost state once scrolled past
    var gobs=document.querySelectorAll(".section, .graph-wrap, .try-cta");
    for(var g=0;g<gobs.length;g++){
      var el=gobs[g], shown=false;
      (function(node){
        var o=new IntersectionObserver(function(entries){
          for(var i=0;i<entries.length;i++){
            if(entries[i].isIntersecting){shown=true;node.classList.remove("ghosted");}
            else if(shown){node.classList.add("ghosted");}
          }
        },{threshold:.18});
        o.observe(node);
      })(el);
    }
  }else{
    var rr=document.querySelectorAll(".reveal");
    for(var x=0;x<rr.length;x++){rr[x].classList.add("in");}
  }
  // safety net: anything not yet revealed (e.g. full-page capture without
  // scrolling, or a jump via anchor) is revealed after a short delay
  setTimeout(function(){
    var late=document.querySelectorAll(".reveal:not(.in)");
    for(var l=0;l<late.length;l++){late[l].classList.add("in");}
  },3500);

  // ---- card cursor glow ----
  var tcards=document.querySelectorAll(".tc-card");
  for(var c=0;c<tcards.length;c++){
    tcards[c].addEventListener("mousemove",function(e){
      var rect=this.getBoundingClientRect();
      this.style.setProperty("--mx",((e.clientX-rect.left)/rect.width*100)+"%");
      this.style.setProperty("--my",((e.clientY-rect.top)/rect.height*100)+"%");
    });
  }

  // ---- tooltips: a ? icon on each explainer; hover (desktop) or tap (touch) it ----
  var tipEl=document.createElement("div");
  tipEl.className="tip-float";
  document.body.appendChild(tipEl);
  var tipCur=null;
  function showTip(el){
    if(!el || !el.getAttribute("data-tip")){hideTip();return;}
    if(tipCur===el){return;}
    hideTip();
    tipCur=el;
    tipEl.textContent=el.getAttribute("data-tip");
    var q=el.querySelector(".qmark");
    var r=(q||el).getBoundingClientRect();
    tipEl.style.visibility="hidden";
    tipEl.classList.add("show");
    var tw=tipEl.offsetWidth;
    var left=Math.max(tw/2+8,Math.min(window.innerWidth-tw/2-8,r.left+r.width/2));
    var below=r.top<70;
    tipEl.classList.toggle("below",below);
    tipEl.style.left=left+"px";
    tipEl.style.top=(below?r.bottom+10:r.top-10)+"px";
    tipEl.style.visibility="";
  }
  function hideTip(){
    tipCur=null;
    tipEl.classList.remove("show");
  }
  // build the ? icons
  var tipHosts=document.querySelectorAll("[data-tip]");
  for(var hq=0;hq<tipHosts.length;hq++){
    (function(el){
      var q=document.createElement("span");
      q.className="qmark";
      q.setAttribute("role","button");
      q.setAttribute("tabindex","0");
      q.setAttribute("aria-label","More information");
      q.textContent="?";
      if(el.classList.contains("tc-card")){
        var room=el.querySelector(".tc-room");
        if(room&&room.parentNode){room.parentNode.insertBefore(q,room.nextSibling);}
        else{el.appendChild(q);}
      }else{
        el.appendChild(q);
      }
      q.addEventListener("mouseenter",function(){showTip(el);});
      q.addEventListener("mouseleave",hideTip);
      q.addEventListener("focus",function(){showTip(el);});
      q.addEventListener("blur",hideTip);
      q.addEventListener("click",function(e){
        e.preventDefault();e.stopPropagation();
        if(tipCur===el){hideTip();}else{showTip(el);}
      });
      q.addEventListener("keydown",function(e){
        if(e.key==="Enter"||e.key===" "){
          e.preventDefault();e.stopPropagation();
          if(tipCur===el){hideTip();}else{showTip(el);}
        }
      });
    })(tipHosts[hq]);
  }
  document.addEventListener("click",function(e){
    if(!e.target.closest||!e.target.closest(".qmark")){hideTip();}
  });
  document.addEventListener("touchstart",function(e){
    if(!e.target.closest||!e.target.closest(".qmark")){hideTip();}
  },{passive:true});
  window.addEventListener("scroll",hideTip,{passive:true});
  window.addEventListener("resize",hideTip);

  // ---- 3D tilt on hover (stat cells, panels) ----
  var tilts=document.querySelectorAll(".tilt");
  for(var t2=0;t2<tilts.length;t2++){
    (function(el){
      el.addEventListener("mousemove",function(e){
        if(window.matchMedia("(prefers-reduced-motion: reduce)").matches){return;}
        var r=el.getBoundingClientRect();
        var px=(e.clientX-r.left)/r.width - .5;
        var py=(e.clientY-r.top)/r.height - .5;
        el.style.setProperty("--ry",(px*7).toFixed(2)+"deg");
        el.style.setProperty("--rx",(-py*7).toFixed(2)+"deg");
      });
      el.addEventListener("mouseleave",function(){
        el.style.setProperty("--ry","0deg");
        el.style.setProperty("--rx","0deg");
      });
    })(tilts[t2]);
  }

  // ---- hero 3D stage: parallax tilt ----
  var heroStack=$("hero-stack"), heroStage=document.querySelector(".hero-stage");
  if(heroStack && heroStage){
    heroStage.addEventListener("mousemove",function(e){
      if(window.matchMedia("(prefers-reduced-motion: reduce)").matches){return;}
      var r=heroStage.getBoundingClientRect();
      var px=(e.clientX-r.left)/r.width - .5;
      var py=(e.clientY-r.top)/r.height - .5;
      heroStack.style.setProperty("--tilt-y",(-12 + px*10).toFixed(1)+"deg");
      heroStack.style.setProperty("--tilt-x",(8 - py*8).toFixed(1)+"deg");
    });
    heroStage.addEventListener("mouseleave",function(){
      heroStack.style.setProperty("--tilt-y","-12deg");
      heroStack.style.setProperty("--tilt-x","8deg");
    });
  }
  // ---- hero: live memory decision replay ----
  // Each real settlement replays as a memory decision: recall → read → price
  // → serve → write. The "read memory" and "write memory" rows are the two
  // steps that make this a memory business. Nothing here is canned: each entry
  // is DERIVED on the fly from the live settlement journal (money.recent from
  // /house/ledger) + the live caller ledger, so a new serve appears in the
  // replay automatically with no code change. When a tx can't be matched to a
  // live row, it is derived from the recorded real settlement (trust 53,
  // caller 890fae) — a documented Basescan-verifiable event, not a fake.
  var replayScripts=[], rpIdx=0, rpTimer=null, rpPaused=false;
  var REPLAY_FALLBACK = {
    "0xd31364dcd77ce5888d0408a005fbc220db1bd5cc42210b69a72a5c3b0631c69e":
      {read:"none · new caller", price:"$0.01 · list price (new ×1.00)",
       serve:"first payment settled to the house wallet",
       write:"trust 50→53 (+3) · caller 890fae · segment new"}
  };
  function last6(s){return s?("0x…"+String(s).slice(-6)):"";}
  // Derive the 5-step decision for one settlement from live data. Returns a
  // {read, price, serve, write} object. `tx` is a live journal entry
  // ({tx,payer,route,amount_usdc,kind}); when it is null we fall back to the
  // recorded settlement. `callers` is the live ledger row list.
  function deriveDecision(tx, callers){
    var base = S.base_price!=null ? Number(S.base_price) : 0.01;
    // match this settlement to the caller row (by payer last-4/last-6)
    var row=null;
    if(tx && tx.payer){
      var p4=String(tx.payer).slice(-4);
      for(var i=0;i<callers.length;i++){
        var d=callers[i].address_last6||callers[i].addr_last6||(callers[i].address||"");
        if(d && d.slice(-4)===p4){row=callers[i];break;}
      }
    }
    if(!tx){
      // documented recorded settlement — the one real serve on Base
      var f=REPLAY_FALLBACK["0xd31364dcd77ce5888d0408a005fbc220db1bd5cc42210b69a72a5c3b0631c69e"];
      return f;
    }
    var amt = tx.amount_usdc!=null ? Number(tx.amount_usdc) : 0;
    var zero = amt<=0;
    var seg = row?(row.segment||"new"):"new";
    var mult = (SEG_MULT[seg]!=null)?SEG_MULT[seg]:1.0;
    var priceTxt = zero ? "net $0 · repeat served from memory"
      : (seg==="banned") ? "refused — 403, not charged"
      : money(base*mult)+" USDC ("+seg+" ×"+mult+")";
    var trustNow = row?(row.trust_score!=null?row.trust_score:50):null;
    var serves = row?(row.served!=null?row.served:(row.served_count!=null?row.served_count:0)):null;
    var readTxt, writeTxt;
    if(row){
      readTxt = "recall 0x…"+String(row.address_last6||row.addr_last6||"").slice(-4)
        + " · trust "+trustNow+" · segment "+seg;
      writeTxt = "trust →"+trustNow+" · "+serves+" serve"+(serves!==1?"s":"")
        + (row.dedup_hits? " · "+row.dedup_hits+" repeat":"")
        + " · segment "+seg;
    } else {
      readTxt = "no memory row yet — treated as a stranger (trust 50)";
      writeTxt = "trust 50→53 (+3) · first serve · segment new";
    }
    var serveTxt = zero ? "repeat request served from cache"
      : (amt>0 ? "$"+money(amt)+" settled to the house wallet" : "served");
    return {read:readTxt, price:priceTxt, serve:serveTxt, write:writeTxt};
  }
  function rebuildReplay(){
    var txs = S.liveTxs && S.liveTxs.length ? S.liveTxs : (S.txs||[]);
    var next=[];
    for(var i=0;i<txs.length;i++){
      var t=txs[i];
      next.push({hash:t.hash||t.tx, s:deriveDecision(t, S.callers||[])});
    }
    replayScripts=next;
    if(rpIdx>=replayScripts.length){rpIdx=0;}
  }
  rebuildReplay();
  function rpRender(){
    if(rpTimer){clearTimeout(rpTimer);rpTimer=null;}
    var body=$("replay-body"); if(!body) return;
    if(rpPaused){
      body.innerHTML="<div class='rp-line show'><span class='tag'>memory</span><span class='val'>disabled — the house is blind</span></div>";
      return;
    }
    if(!replayScripts.length){
      body.innerHTML="<div class='rp-line show'><span class='tag'>memory</span><span class='val'>no settlements yet</span></div>";
      return;
    }
    var item=replayScripts[rpIdx], s=item.s;
    var lines=[
      {tag:"recall", html:item.hash?"<a href='https://basescan.org/tx/"+esc(item.hash)+"' target='_blank' rel='noopener'>"+esc(shortHash(item.hash))+"</a>":"this settlement", cls:"recall"},
      {tag:"read memory", text:s.read, cls:"mem"},
      {tag:"price", text:s.price, cls:""},
      {tag:"serve", text:s.serve, cls:""},
      {tag:"write memory", text:s.write, cls:"mem"}
    ];
    body.innerHTML="";
    var k=0;
    function next(){
      if(rpPaused){return;}
      if(k<lines.length){
        var ln=document.createElement("div");
        ln.className="rp-line"+(lines[k].cls?" "+lines[k].cls:"");
        ln.innerHTML="<span class='tag'>"+esc(lines[k].tag)+"</span><span class='val'>"+(lines[k].html||esc(lines[k].text))+"</span>";
        body.appendChild(ln);
        requestAnimationFrame(function(){ln.classList.add("show");});
        k++;
        rpTimer=setTimeout(next, 430);
      }else{
        rpTimer=setTimeout(function(){rpIdx=(rpIdx+1)%replayScripts.length;rpProgress();rpRender();}, 1700);
      }
    }
    next();
  }
  function rpProgress(){
    var p=$("rp-progress"); if(!p) return;
    var h="";
    for(var i=0;i<replayScripts.length;i++){h+="<span class='seg"+(i===rpIdx?" on":"")+"'></span>";}
    p.innerHTML=h;
  }
  function rpStart(){rpProgress();rpRender();}

  // ---- the house remembers (per-wallet cards) ----
  // Per-card "how derived" — NOT a hardcoded blurb. Each card's explanation is
  // computed from that card's own live row (trust/segment/tx/dedup or quality/
  // jobs) plus the documented formulas (core/trust.py + core/config.py), so a
  // new wallet's card explains exactly the numbers it is showing right now.
  function callerDerive(c){
    var base = S.base_price!=null ? Number(S.base_price) : 0.01;
    var seg = c.segment||"new";
    var mult = (SEG_MULT[seg]!=null) ? SEG_MULT[seg] : null;
    var price = (mult==null) ? "refused — a 403, not charged" : money(base*mult)+" USDC ("+Math.round(mult*100)+"% of base)";
    var T = c.trust_score!=null ? c.trust_score : 50;
    var s = c.served!=null?c.served:(c.served_count!=null?c.served_count:0);
    var d = c.dedup_hits!=null?c.dedup_hits:0;
    var net = c.net_charged_usdc!=null?c.net_charged_usdc:0;
    var h = "";
    h += "<p>trust <b class='gl'>"+T+"</b> — a 0–100 score that starts at <b>50</b> for any stranger and moves <b>+3</b> per delivered serve, <b>−8</b> per caller-fault, <b>−15</b> per refund, clamped. The live ledger holds this wallet at <b>"+T+"</b> after <b>"+s+"</b> serve"+(s!==1?"s":"")+".</p>";
    h += "<p>segment <b class='gl'>"+esc(seg)+"</b> — re-derived from the counters on every request ("+SEG_THRESH[seg]+"), not trusted from a stale label. It sets the price at <b>"+price+"</b> off a "+money(base)+" USDC base.</p>";
    h += "<p>repeat serves <b class='gr'>"+d+"</b> — a re-asked request fingerprint is served from cache at <b>net $0</b>; the USDC that would have been re-charged is what the 'usdc saved' aggregate counts.</p>";
    h += "<p>lifetime charged <b>"+money4(net)+" USDC</b> — real USDC settled to the house wallet on Base, one row per settlement in the onchain proof below.</p>";
    return h;
  }
  function providerDerive(p){
    var q = p.quality_score!=null ? Number(p.quality_score) : null;
    var j = p.jobs_done!=null?p.jobs_done:0;
    var qt = (q==null) ? "standard" : (q>=0.8 ? "proven" : (q>=0.6 ? "standard" : "risky"));
    var prem = {proven:"50%", standard:"100%", risky:"220%"}[qt];
    var h = "";
    h += "<p>quality <b class='gl'>"+(q!=null?Number(q).toFixed(2):"—")+"</b> — the provider's measured delivery score (0–1) from completed work across <b>"+j+"</b> job"+(j!==1?"s":"")+".</p>";
    h += "<p>terms <b class='"+(p.hired?"gr":"rd")+"'>"+(p.hired?"drafted":"refused")+"</b> — priced from that record: a "+qt+" provider"+(q!=null?" at "+Number(q).toFixed(2):" (thin record)")+" carries a <b>"+prem+"</b> bond premium. The house only drafts a provider its own memory can underwrite.</p>";
    return h;
  }
  function paintRemember(){
    var grid=$("remember-grid"); if(!grid)return;
    var callers=S.callers||[], provs=S.providers||[];
    var h="";
    for(var i=0;i<callers.length;i++){
      var c=callers[i];
      var addr=c.address||"";
      var disp=c.address_last6||c.addr_last6||(addr?addr.slice(-6):"—");
      var seg=c.segment||"new";
      h+="<div class='rw-card "+esc(seg)+"'>"
        +"<div class='rw-top'>"
        +(addr?"<a class='rw-addr' href='https://basescan.org/address/"+esc(addr)+"' target='_blank' rel='noopener'>"+esc(disp)+"</a>":"<span class='rw-addr'>"+esc(disp)+"</span>")
        +"<span class='rw-seg "+esc(seg)+"'>"+esc(seg)+"</span>"
        +"</div>"
        +"<div class='rw-row'><span>trust</span><span class='v gl'>"+(c.trust_score!=null?c.trust_score:"—")+"</span></div>"
        +"<div class='rw-row'><span>serves</span><span class='v'>"+(c.served!=null?c.served:(c.served_count!=null?c.served_count:0))+"</span></div>"
        +"<div class='rw-row'><span>txs</span><span class='v'>"+(c.tx_count!=null?c.tx_count:0)+"</span></div>"
        +"<div class='rw-derive'><div class='d-inner'><div class='d-k'>how this was derived</div>"+callerDerive(c)+"</div></div>"
        +"<div class='rw-more'>how is this derived? ▾</div>"
        +"</div>";
    }
    for(var i=0;i<provs.length;i++){
      var p=provs[i];
      var paddr=p.provider||"";
      var pdisp=p.provider_last6||(paddr?paddr.slice(-6):"—");
      var pseg=p.segment||"unknown";
      h+="<div class='rw-card "+esc(pseg)+"'>"
        +"<div class='rw-top'>"
        +(paddr?"<a class='rw-addr' href='https://basescan.org/address/"+esc(paddr)+"' target='_blank' rel='noopener'>"+esc(pdisp)+"</a>":"<span class='rw-addr'>"+esc(pdisp)+"</span>")
        +"<span class='rw-seg "+esc(pseg)+"'>"+esc(pseg)+"</span>"
        +"</div>"
        +"<div class='rw-row'><span>quality</span><span class='v gl'>"+(p.quality_score!=null?Number(p.quality_score).toFixed(2):"—")+"</span></div>"
        +"<div class='rw-row'><span>jobs</span><span class='v'>"+(p.jobs_done!=null?p.jobs_done:0)+"</span></div>"
        +"<div class='rw-row'><span>terms</span><span class='v'>"+(p.hired?"drafted":"refused")+"</span></div>"
        +"<div class='rw-derive'><div class='d-inner'><div class='d-k'>how this was derived</div>"+providerDerive(p)+"</div></div>"
        +"<div class='rw-more'>how is this derived? ▾</div>"
        +"</div>";
    }
    var memMode=S.memory||"live";
    var emptyMsg = memMode==="disabled"
      ? "<div class='empty'>memory disabled — the ledger is hidden (data kept)</div>"
      : memMode==="purged"
        ? "<div class='empty'>memory purged — permanently. the ledger is gone.</div>"
        : "<div class='empty'>no wallets remembered yet</div>";
    grid.innerHTML = h || emptyMsg;
    var cnt=$("remember-count");
    if(cnt){var n=callers.length+provs.length;cnt.textContent=n+" remembered";}
  }

  // ---- hero 3D cards: live population ----
  function hrow(k,v,cls){return "<div class='hc-row'><span class='k'>"+k+"</span><span class='v "+(cls||"")+"'>"+v+"</span></div>";}
  function paintHeroCards(){
    var st=S.stats||{};
    var m=$("hc-main-body");
    if(m){m.innerHTML = hrow("counterparties", st.callers!=null?st.callers:"—")
      + hrow("mean trust", st.trust!=null?st.trust:"—","gl")
      + hrow("dedup hits", st.dedup_hits!=null?st.dedup_hits:"—")
      + hrow("scars", st.scars!=null?st.scars:"—");}
    var c=(S.callers||[])[0], cc=$("hc-caller-body");
    if(cc){
      if(c){cc.innerHTML = hrow("wallet", c.address_last6||"—")
        + hrow("segment", c.segment||"—","gl")
        + hrow("trust", c.trust_score!=null?c.trust_score:"—","gl")
        + hrow("txs", c.tx_count!=null?c.tx_count:"—");}
      else{cc.innerHTML = hrow("wallet","none yet")+hrow("pay once","it appears here","gl");}
    }
    var p=(S.providers||[])[0], pc=$("hc-provider-body");
    if(pc){
      if(p){pc.innerHTML = hrow("provider", p.provider_last6||"—")
        + hrow("quality", p.quality_score!=null?Number(p.quality_score).toFixed(2):"—","gl")
        + hrow("jobs", p.jobs_done!=null?p.jobs_done:"—")
        + hrow("terms", p.hired?"drafted":"refused", p.hired?"gr":"");}
      else{pc.innerHTML = hrow("provider","none yet")+hrow("acp rail","ready","gl");}
    }
    var txs=S.txs||[], sc=$("hc-settle-body");
    if(sc){
      var total=0; for(var i=0;i<txs.length;i++){total+=Number(txs[i].usdc||0);}
      sc.innerHTML = hrow("txs on base", txs.length)
        + hrow("settled", money4(total)+" usdc","gl")
        + hrow("audit","basescan","gr");
    }
  }

  // ---- helpers ----
  function fetchJson(url){
    return fetch(url,{cache:"no-store"}).then(function(r){return r.json();}).catch(function(){return null;});
  }
  var toastTimer=null;
  function toast(msg,type){
    var t=$("toast");
    t.textContent=msg;
    t.className="toast show"+(type?" "+type:"");
    if(toastTimer){clearTimeout(toastTimer);}
    toastTimer=setTimeout(function(){t.className="toast";},4200);
  }
  // map a live settlement-journal entry (money.recent) to the ledger row shape
  // the onchain table + replay render. Amounts are shown as they are on the
  // chain (a net-$0 repeat is a real memory decision, not hidden).
  function mapJournalToRows(recent){
    var rows=[];
    for(var i=0;i<(recent||[]).length;i++){
      var e=recent[i];
      var amt=(e.amount_usdc!=null)?Number(e.amount_usdc):0;
      var zero=amt<=0;
      var ts=e.ts;
      var tsTxt;
      if(typeof ts==="number"&&ts>0){
        var d=new Date(ts*1000);
        tsTxt=d.toISOString().slice(0,16).replace("T"," ")+" UTC";
      } else { tsTxt=ts||"onchain"; }
      rows.push({hash:e.tx, label:(e.route||"settlement")+" · buyer → house wallet",
        usdc:amt, note:"", ts:tsTxt});
    }
    return rows;
  }
  function refreshAll(){
    fetchJson("/house/ledger").then(function(j){
      if(!j)return;
      S.callers=j.callers||[];
      S.providers=S.providers||[];
      S.dedup=j.dedup||{};
      // the live settlement journal — new settles appear here automatically.
      var recent=(j.money&&j.money.recent)||[];
      S.liveTxs=mapJournalToRows(recent);
      S.txs=S.liveTxs.length?S.liveTxs:(S.txs||[]);
      S.stats.callers=S.callers.length;
      S.stats.dedup_hits=(j.dedup&&j.dedup.hits)||0;
      var trust=0;for(var i=0;i<S.callers.length;i++){trust+=S.callers[i].trust_score||0;}
      S.stats.trust = S.callers.length?Math.round(trust/S.callers.length*10)/10:0;
      paintRooms(); paintLedger(); paintHeroCards(); paintRemember();
      paintMemoryGraph(); paintTrustLadder();
      setNum("st-callers",S.stats.callers);
      setNum("st-trust",S.stats.trust,1);
      setNum("st-dedup",S.stats.dedup_hits);
      // a new serve lands in the ledger → the replay re-derives its steps from
      // the live rows and continues, so the decision feed reflects it.
      rebuildReplay();
      if(!rpPaused){rpProgress();rpRender();}
    });
    fetchJson("/house/front").then(function(j){
      if(!j)return;
      S.providers=j.board||[];
      var q=0;for(var i=0;i<S.providers.length;i++){q+=S.providers[i].quality_score||0;}
      S.stats.quality = S.providers.length?Math.round(q/S.providers.length*100)/100:0;
      setNum("st-quality",S.stats.quality,2);
      paintRooms(); paintHeroCards();
    });
    refreshGate();
  }



  paint();
  refreshAll();
  setInterval(refreshAll, 6000);
  // tick the header recovery timer every second when memory is disabled
  setInterval(updateRecover, 1000);
})();
</script>
</body>
</html>
"""
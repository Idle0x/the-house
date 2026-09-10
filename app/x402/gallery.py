"""M4 — the gallery: a live workbench, not a second landing page.

Pick a counterparty the house actually knows (subject), pick one of the seven
paid functions, and run it in the console — watch the live 402 quote, the
memory read→price→serve→write trace, the onchain artifact, and what memory is
worth (on vs off). Then the console hands you the next logical step.

Layout: dual-pane workbench on desktop (configure | console); on mobile it
becomes one pane at a time with a sticky 1·configure / 2·console stepper, and
journal tables stack into label/value cards instead of squeezing columns.

Design language matches the landing page: near-black, single glacier accent,
Space Grotesk + Space Mono, ambient grid, tooltips (data-tip), scroll reveals.

Rendering: plain ``.replace()`` placeholders (not string.Template), so the
inline JS can use ``$`` freely. The try-it modal is embedded from
``app/x402/_tryit.py`` so both pages share one implementation.
"""
from __future__ import annotations

import html
import json

from app.x402._tryit import TRYIT_CSS, TRYIT_HTML, TRYIT_JS
from app.x402.landing import REAL_SETTLEMENT_TXS, REAL_JOURNAL

_GALLERY_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>the-house · gallery — the workbench — Sibyl Labs Hackathon 2026</title>
<meta name="description" content="THE HOUSE workbench: pick a counterparty, run a function, watch memory decide. Built on Sibyl Memory for the Sibyl Labs Hackathon 2026.">
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E%3Crect%20width='32'%20height='32'%20fill='%230A0A0A'/%3E%3Cpath%20d='M11%208v16M21%208v16M11%2016h10'%20stroke='%23E8C547'%20stroke-width='3'%20stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#07090B; --surface:#0D1013; --surface2:#12161A; --inset:#090B0E;
    --border:rgba(255,255,255,.07); --border2:rgba(255,255,255,.11);
    --text:#F2F5F7; --muted:#79808A; --dim:#A9B2BC;
    --glacier:#8FC7FF; --glacier-deep:#4E8FE0; --glacier-dim:rgba(143,199,255,.10);
    --green:#27AE60; --green-dim:rgba(39,174,96,.12); --red:#C0392B; --red-dim:rgba(192,57,43,.12);
    --amber:#E8C547;
    --grotesk:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;
    --mono:"Space Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  html{scroll-behavior:smooth;}
  html,body{background:var(--bg);color:var(--text);
    font-family:var(--grotesk);-webkit-font-smoothing:antialiased;}
  body{line-height:1.55;overflow-x:hidden;}
  a{color:inherit;text-decoration:none;}
  ::selection{background:var(--glacier);color:#0A0A0A;}

  /* ---------- ambient ---------- */
  .ambient{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
  .grid-bg{position:absolute;inset:0;
    background-image:linear-gradient(rgba(143,199,255,.035) 1px,transparent 1px),
      linear-gradient(90deg,rgba(143,199,255,.035) 1px,transparent 1px);
    background-size:56px 56px;
    -webkit-mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 30%,transparent 75%);
            mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,#000 30%,transparent 75%);}
  .glow{position:absolute;border-radius:50%;filter:blur(90px);opacity:.4;will-change:transform;}
  .glow.a{width:520px;height:520px;top:-160px;left:8%;background:radial-gradient(circle,rgba(143,199,255,.22),transparent 70%);}
  .glow.b{width:420px;height:420px;top:30%;right:-120px;background:radial-gradient(circle,rgba(0,217,255,.12),transparent 70%);}

  /* ---------- tooltips: JS-managed floating box ---------- */
  .tip-float{position:fixed;z-index:300;max-width:300px;padding:10px 13px;border-radius:10px;
    background:rgba(16,20,24,.97);border:1px solid rgba(143,199,255,.28);
    box-shadow:0 18px 50px rgba(0,0,0,.65),0 0 0 1px rgba(0,0,0,.4);
    color:var(--dim);font-family:var(--mono);font-size:11.5px;line-height:1.6;letter-spacing:0;
    text-transform:none;font-weight:400;white-space:normal;text-align:left;
    opacity:0;pointer-events:none;transform:translate(-50%,-100%) translateY(6px);
    transition:opacity .16s ease,transform .16s ease;}
  .tip-float.below{transform:translate(-50%,0) translateY(-6px);}
  .tip-float.show{opacity:1;transform:translate(-50%,-100%) translateY(0);}
  .tip-float.below.show{opacity:1;transform:translate(-50%,0) translateY(0);}
  .tip-float::after{content:"";position:absolute;left:50%;bottom:-5px;transform:translateX(-50%) rotate(45deg);
    width:8px;height:8px;background:rgba(16,20,24,.97);border-right:1px solid rgba(143,199,255,.28);
    border-bottom:1px solid rgba(143,199,255,.28);}
  .tip-float.below::after{bottom:auto;top:-5px;border-right:none;border-bottom:none;
    border-left:1px solid rgba(143,199,255,.28);border-top:1px solid rgba(143,199,255,.28);}

  /* ---------- ? tooltips ---------- */
  .qmark{display:inline-flex;align-items:center;justify-content:center;
    width:15px;height:15px;flex:0 0 auto;margin-left:6px;border-radius:50%;
    border:1px solid rgba(143,199,255,.45);color:var(--glacier);
    font-family:var(--mono);font-size:10px;font-weight:600;line-height:1;
    cursor:help;user-select:none;-webkit-user-select:none;
    transition:background .15s ease,color .15s ease,box-shadow .15s ease;}
  .qmark:hover,.qmark:focus-visible{background:var(--glacier);color:#08131f;outline:none;
    box-shadow:0 0 0 3px rgba(143,199,255,.18);}

  /* ---------- bar (landing header, kept) ---------- */
  .bar{width:100%;border-bottom:1px solid var(--border);
    background:rgba(10,10,10,.82);backdrop-filter:blur(14px);position:sticky;top:0;z-index:50;}
  .bar-inner{max-width:1320px;margin:0 auto;padding:18px 28px 14px;
    display:flex;flex-direction:column;gap:13px;}
  .bar-row{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
  .bar-row.bottom{border-top:1px solid rgba(255,255,255,.05);padding-top:11px;flex-wrap:nowrap;}
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
  .wordmark .sibyl-credit{color:var(--muted);font-weight:400;font-size:10px;letter-spacing:.08em;}
  .wordmark .sibyl-credit:hover{color:var(--glacier);}
  .status-group{display:flex;align-items:center;gap:16px;}
  .status{display:flex;align-items:center;gap:9px;font-family:var(--mono);
    font-size:12px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;cursor:default;}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--green);animation:breath 3s ease-in-out infinite;}
  .dot.off{background:var(--red);animation:none;box-shadow:0 0 0 0 transparent;}
  @keyframes breath{0%,100%{opacity:.55;box-shadow:0 0 0 0 rgba(39,174,96,.4)}
    50%{opacity:1;box-shadow:0 0 12px 2px rgba(39,174,96,.45)}}
  .gate-link{background:none;border:1px solid rgba(192,57,43,.5);color:#ff8a7a;
    font-family:var(--mono);font-size:11px;letter-spacing:.06em;padding:6px 13px;border-radius:20px;
    cursor:pointer;transition:all .18s ease;}
  .gate-link:hover{color:#ffb3a8;border-color:var(--red);background:rgba(192,57,43,.16);}
  .nav{display:flex;gap:22px;align-items:center;font-family:var(--mono);font-size:12px;letter-spacing:.06em;}
  .nav a{color:var(--muted);transition:color .15s;}
  .nav a:hover{color:var(--glacier);}
  .nav a.active{color:var(--glacier);}
  .nav a.back-home{color:#ff8a7a;border:1px solid rgba(192,57,43,.5);padding:5px 12px;border-radius:20px;
    transition:all .18s ease;}
  .nav a.back-home:hover{color:#ffb3a8;border-color:var(--red);background:rgba(192,57,43,.16);}
  .hash{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.03em;opacity:.85;}

  .wrap{max-width:1320px;margin:0 auto;padding:26px 28px 64px;position:relative;z-index:2;}

  /* ---------- section head ---------- */
  .sec-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
    margin-bottom:12px;flex-wrap:wrap;}
  .sec-head h1{font-size:22px;font-weight:700;letter-spacing:-.015em;}
  .sec-head .sub{color:var(--muted);font-size:13.5px;margin-top:3px;max-width:62ch;}
  .seg{display:flex;gap:2px;background:var(--surface2);border:1px solid var(--border);
    border-radius:10px;padding:3px;}
  .seg button{background:none;border:none;font-family:var(--mono);font-size:11px;letter-spacing:.06em;
    color:var(--muted);padding:7px 14px;border-radius:7px;cursor:pointer;}
  .seg button.on{background:var(--glacier-dim);color:var(--glacier);}

  /* ---------- dual pane ---------- */
  .bench{display:grid;grid-template-columns:344px minmax(0,1fr);gap:12px;align-items:start;}
  .pane{background:var(--surface);border:1px solid var(--border);border-radius:12px;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .pane-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
    padding:14px 16px;border-bottom:1px solid var(--border);}
  .pane-head .t{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;color:var(--muted);text-transform:uppercase;}
  .step-badge{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;
    border-radius:50%;background:var(--glacier-dim);color:var(--glacier);font-family:var(--mono);
    font-size:10px;font-weight:700;margin-right:8px;}
  .pane-body{padding:14px 16px 16px;}

  /* subject rows */
  .subj{display:flex;align-items:center;gap:11px;width:100%;text-align:left;
    background:var(--surface2);border:1px solid var(--border);border-radius:11px;
    padding:11px 13px;margin-bottom:8px;cursor:pointer;transition:border-color .16s,background .16s;}
  .subj:hover{border-color:var(--border2);}
  .subj.on{border-color:var(--glacier);background:var(--glacier-dim);}
  .subj .av{width:26px;height:26px;border-radius:7px;background:var(--inset);flex:0 0 auto;
    display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:10px;color:var(--glacier);}
  .subj .meta{min-width:0;flex:1;}
  .subj .addr{font-family:var(--mono);font-size:11.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .subj .note{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.04em;}
  .subj .score{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--glacier);}
  .subj .score.dim{color:var(--muted);font-weight:400;}
  .tier{font-family:var(--mono);font-size:9px;letter-spacing:.1em;padding:2px 7px;border-radius:20px;}
  .tier.proven{background:var(--glacier-dim);color:var(--glacier);}
  .tier.regular{background:rgba(232,197,71,.14);color:var(--amber);}
  .tier.risky,.tier.banned{background:var(--red-dim);color:#e0a49c;}
  .tier.new,.tier.unknown{background:rgba(255,255,255,.06);color:var(--muted);}
  .add-wallet{width:100%;background:none;border:1px dashed var(--border2);border-radius:11px;
    padding:10px;font-family:var(--mono);font-size:11px;color:var(--muted);cursor:pointer;margin-bottom:16px;}
  .add-wallet:hover{border-color:var(--glacier);color:var(--glacier);}

  .rail-label{font-family:var(--mono);font-size:10px;letter-spacing:.16em;color:var(--muted);
    text-transform:uppercase;margin:0 0 9px;display:flex;align-items:center;justify-content:space-between;}

  /* function accordion */
  .fn{border:1px solid var(--border);border-radius:11px;margin-bottom:7px;overflow:hidden;
    background:var(--surface2);transition:border-color .16s;}
  .fn.on{border-color:var(--glacier);}
  .fn-head{display:flex;align-items:center;gap:10px;padding:11px 12px;cursor:pointer;width:100%;
    background:none;border:none;text-align:left;color:var(--text);}
  .fn-head .ico{color:var(--glacier);font-size:13px;width:16px;flex:0 0 auto;}
  .fn-head .nm{flex:1;font-size:13.5px;font-weight:500;}
  .fn-head .price{font-family:var(--mono);font-size:11px;color:var(--muted);}
  .fn-head .chev{color:var(--muted);font-size:10px;transition:transform .2s;}
  .fn.on .fn-head .chev{transform:rotate(180deg);}
  .fn-body{display:none;padding:2px 12px 13px;border-top:1px solid var(--border);}
  .fn.on .fn-body{display:block;}
  .fn-body .desc{color:var(--muted);font-size:12px;line-height:1.55;margin:10px 0 11px;}
  .fn-body .fields label{display:block;font-family:var(--mono);font-size:10px;color:var(--muted);margin-bottom:5px;letter-spacing:.06em;}
  .fn-body .fields input{width:100%;background:var(--inset);border:1px solid var(--border);border-radius:9px;
    color:var(--text);font-family:var(--mono);font-size:11.5px;padding:9px 11px;outline:none;}
  .fn-body .fields input:focus{border-color:var(--glacier);}
  .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;}
  .chip{background:var(--surface);border:1px solid var(--border);color:var(--muted);
    font-family:var(--mono);font-size:10px;padding:5px 10px;border-radius:20px;cursor:pointer;
    transition:border-color .18s ease,color .18s ease;}
  .chip:hover{color:var(--glacier);border-color:var(--glacier);}
  /* left-pane run-as: compact single-row segmented control, same language as console */
  .paths{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:11px;
    background:var(--inset);border:1px solid var(--border);border-radius:12px;padding:4px;
    box-shadow:inset 0 1px 2px rgba(0,0,0,.55),inset 0 0 0 1px rgba(0,0,0,.25);}
  .path{background:transparent;border:1px solid transparent;border-radius:9px;
    padding:9px 4px;font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:13px;font-weight:550;letter-spacing:-.01em;color:var(--muted);cursor:pointer;text-align:center;
    transition:all .18s ease;white-space:nowrap;}
  .path:hover{color:var(--dim);background:rgba(255,255,255,.03);}
  .path.on{color:var(--text);background:rgba(255,255,255,.07);
    border-color:rgba(255,255,255,.12);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.07),0 1px 6px rgba(0,0,0,.4);}
  .path.agent.on{color:var(--glacier);background:rgba(143,199,255,.12);
    border-color:rgba(143,199,255,.45);
    box-shadow:inset 0 1px 0 rgba(143,199,255,.18),0 1px 8px rgba(0,0,0,.4);}
  .path.wallet.on{color:#8fd9ac;background:rgba(39,174,96,.15);
    border-color:rgba(39,174,96,.5);
    box-shadow:inset 0 1px 0 rgba(39,174,96,.2),0 1px 8px rgba(0,0,0,.4);}
  .fn-cont{display:none;width:100%;margin-top:10px;background:var(--glacier);color:#08131f;
    border:none;border-radius:9px;padding:11px;font-family:var(--mono);font-size:11.5px;font-weight:700;
    letter-spacing:.04em;cursor:pointer;transition:background .16s;}
  .fn-cont:hover{background:#a9d6ff;}

  /* memory control */
  .mem-ctl{border:1px solid var(--border);border-radius:11px;background:var(--surface2);
    padding:12px;margin-top:16px;}
  .mem-ctl .st{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;}
  .mem-ctl .st .l{font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:var(--muted);}
  .mem-ctl .st .r{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:11px;color:var(--green);}
  .mem-ctl .st .r.off{color:#e0a49c;}
  .mem-btns{display:flex;gap:7px;}
  .mem-btns button{flex:1;background:var(--surface);border:1px solid var(--border);border-radius:8px;
    padding:8px;font-family:var(--mono);font-size:10.5px;color:var(--dim);cursor:pointer;}
  .mem-btns button:hover{border-color:var(--border2);color:var(--text);}
  .mem-btns button.danger{color:#d97b6f;border-color:rgba(192,57,43,.35);}
  .mem-btns button.danger:hover{border-color:#C0392B;color:#ff8a7a;}
  .subj-why{font-family:var(--mono);font-size:10px;color:var(--muted);line-height:1.55;margin:-2px 0 10px;}
  .del-test{margin-top:9px;font-family:var(--mono);font-size:10px;color:var(--muted);line-height:1.5;}

  /* ---------- console ---------- */
  .console{padding:14px;display:flex;flex-direction:column;gap:12px;}
  .csec{border:1px solid var(--border);border-radius:12px;background:var(--inset);overflow:hidden;}
  .csec > .h{display:flex;align-items:center;justify-content:space-between;gap:10px;
    padding:10px 14px;border-bottom:1px solid var(--border);background:rgba(255,255,255,.012);}
  .csec .h .l{display:flex;align-items:center;font-family:var(--mono);font-size:10px;
    letter-spacing:.14em;color:var(--muted);text-transform:uppercase;}
  .csec .h .r{font-family:var(--mono);font-size:10px;color:var(--muted);}
  .csec .body{padding:14px;}
  .csec .empty{font-family:var(--mono);font-size:11px;color:var(--muted);padding:6px 2px;}

  .runline{display:flex;align-items:center;gap:11px;flex-wrap:wrap;}
  .runline .path-badge{font-family:var(--mono);font-size:10.5px;color:var(--glacier);
    background:var(--glacier-dim);border:1px solid rgba(143,199,255,.25);padding:4px 10px;border-radius:20px;}
  .runline .amt{margin-left:auto;font-family:var(--mono);font-size:22px;font-weight:700;color:var(--glacier);}
  .runline .amt small{font-size:11px;color:var(--muted);font-weight:400;margin-left:5px;}
  .btn{background:var(--glacier-dim);border:1px solid rgba(143,199,255,.4);color:var(--glacier);
    font-family:var(--mono);font-size:11.5px;padding:9px 17px;border-radius:9px;cursor:pointer;transition:all .16s;}
  .btn:hover{background:rgba(143,199,255,.16);}
  .btn.ghost{background:none;border-color:var(--border2);color:var(--dim);}
  .btn.ghost:hover{border-color:var(--glacier);color:var(--glacier);}
  .btn.go{background:var(--green-dim);border-color:rgba(39,174,96,.45);color:#8fd9ac;}
  .btn.go:hover{background:rgba(39,174,96,.22);}
  .btn:disabled{opacity:.4;cursor:not-allowed;}

  .term{background:#0b0d10;border:1px solid var(--border);border-radius:11px;overflow:hidden;}
  .term .th{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);
    background:#0e1114;font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;}
  .dots3{display:flex;gap:5px;}
  .dots3 i{width:8px;height:8px;border-radius:50%;display:block;}
  .dots3 i:nth-child(1){background:#d97b6f;} .dots3 i:nth-child(2){background:#e5c07b;} .dots3 i:nth-child(3){background:#8fd9ac;}
  .term .cp{margin-left:auto;background:var(--surface2);border:1px solid var(--border);color:var(--muted);
    font-family:var(--mono);font-size:9px;padding:3px 9px;border-radius:6px;cursor:pointer;text-transform:none;letter-spacing:.04em;}
  .term .cp:hover{color:var(--glacier);border-color:var(--glacier);}
  .term code{display:block;padding:13px 15px;font-family:var(--mono);font-size:11.5px;
    color:#cfd8e3;white-space:pre-wrap;word-break:break-word;line-height:1.65;}
  .term .p{color:var(--green);font-weight:700;}
  .term .cm{color:var(--muted);}
  .term .cm a{color:var(--glacier);border-bottom:1px dotted rgba(143,199,255,.4);}

  /* agent prompt block — the complete brief an agent pastes in, not a one-liner */
  .aprompt{background:#0b0d10;border:1px solid rgba(143,199,255,.22);border-radius:11px;
    overflow:hidden;margin-top:12px;
    background-image:linear-gradient(180deg,rgba(143,199,255,.04),rgba(143,199,255,0) 40%);}
  .aprompt .th{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);
    background:#0e1114;font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:var(--muted);text-transform:uppercase;}
  .aprompt .th .cp{margin-left:auto;background:var(--surface2);border:1px solid var(--border);color:var(--muted);
    font-family:var(--mono);font-size:9px;padding:3px 9px;border-radius:6px;cursor:pointer;text-transform:none;letter-spacing:.04em;}
  .aprompt .th .cp:hover{color:var(--glacier);border-color:var(--glacier);}
  .aprompt pre{margin:0;padding:13px 15px;font-family:var(--mono);font-size:11.5px;line-height:1.7;
    color:#cfd8e3;white-space:pre-wrap;word-break:break-word;max-height:360px;overflow-y:auto;}

  .tabs{display:flex;gap:8px;margin-bottom:11px;flex-wrap:wrap;}
  .tab{background:var(--surface2);border:1px solid var(--border);border-radius:10px;
    font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;font-size:13px;font-weight:550;
    letter-spacing:-.01em;color:var(--muted);padding:8px 14px;cursor:pointer;
    transition:all .18s ease;}
  .tab.on{background:rgba(143,199,255,.12);border-color:rgba(143,199,255,.45);color:var(--glacier);
    box-shadow:inset 0 1px 0 rgba(143,199,255,.15);}
  .tab:hover{color:var(--text);border-color:var(--border2);}
  /* run-as selector — one compact single-row segmented control, not three cards.
     Manual / Agent = how you interact · Connect Wallet = the action to use the dapp. */
  .pathsel{margin-bottom:13px;}
  .pathsel-lb{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:12px;font-weight:550;letter-spacing:-.01em;
    color:var(--muted);margin-bottom:8px;display:flex;align-items:center;gap:8px;}
  .pathsel-lb .hint{color:var(--muted);opacity:.7;font-weight:500;font-size:11.5px;}
  .pathsel-lb::after{content:"";flex:1;height:1px;background:var(--border);}
  .popts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;
    background:var(--inset);border:1px solid var(--border);border-radius:12px;padding:4px;
    box-shadow:inset 0 1px 2px rgba(0,0,0,.55),inset 0 0 0 1px rgba(0,0,0,.25);}
  .popt{display:inline-flex;align-items:center;justify-content:center;gap:7px;
    min-height:44px;padding:10px 12px;cursor:pointer;white-space:nowrap;
    background:transparent;border:1px solid transparent;border-radius:9px;
    font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:14px;font-weight:550;letter-spacing:-.01em;color:var(--muted);
    transition:all .18s ease;}
  .popt svg{width:15px;height:15px;flex:0 0 auto;opacity:.85;}
  .popt:hover{color:var(--dim);background:rgba(255,255,255,.03);}
  .popt.on{color:var(--text);background:rgba(255,255,255,.07);
    border-color:rgba(255,255,255,.12);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.07),0 1px 6px rgba(0,0,0,.4);}
  .popt[data-p='agent'].on{color:var(--glacier);background:rgba(143,199,255,.12);
    border-color:rgba(143,199,255,.45);
    box-shadow:inset 0 1px 0 rgba(143,199,255,.18),0 1px 8px rgba(0,0,0,.4);}
  .popt[data-p='agent'].on svg{opacity:1;}
  .popt[data-p='wallet']{color:var(--dim);}
  .popt[data-p='wallet'] svg{color:#8fd9ac;opacity:.9;}
  .popt[data-p='wallet'].on{color:#8fd9ac;background:rgba(39,174,96,.16);
    border-color:rgba(39,174,96,.55);
    box-shadow:inset 0 1px 0 rgba(39,174,96,.22),0 1px 10px rgba(0,0,0,.45);}
  @media(max-width:560px){
    /* run-as stays one row on phones: shrink type/padding instead of stacking */
    .popts{grid-template-columns:1fr 1fr 1fr;gap:4px;}
    .popt{min-height:40px;font-size:12.5px;padding:8px 6px;gap:5px;}
    .popt svg{width:13px;height:13px;}
  }

  .qgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(126px,1fr));gap:10px;}
  .qcell{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:11px 12px;}
  .qcell .k{font-family:var(--mono);font-size:9.5px;letter-spacing:.11em;color:var(--muted);text-transform:uppercase;margin-bottom:5px;}
  .qcell .v{font-family:var(--mono);font-size:13px;color:var(--text);word-break:break-all;}
  .qcell .v.gl{color:var(--glacier);} .qcell .v.gr{color:#8fd9ac;} .qcell .v.am{color:var(--amber);}
  .qcell .v a{color:var(--glacier);border-bottom:1px solid rgba(143,199,255,.35);}

  .trace{display:flex;flex-direction:column;gap:0;}
  .tr{display:flex;align-items:flex-start;gap:11px;padding:10px 0;position:relative;}
  .tr:not(:last-child)::before{content:"";position:absolute;left:8px;top:28px;bottom:-2px;width:1px;
    background:linear-gradient(var(--border2),transparent);}
  .tr .n{width:17px;height:17px;border-radius:50%;flex:0 0 auto;display:flex;align-items:center;
    justify-content:center;font-family:var(--mono);font-size:9px;background:var(--glacier-dim);color:var(--glacier);}
  .tr.mem .n{background:rgba(232,197,71,.16);color:var(--amber);}
  .tr.done .n{background:var(--green-dim);color:#8fd9ac;}
  .tr .tx{flex:1;min-width:0;}
  .tr .tt{font-family:var(--mono);font-size:11.5px;color:var(--text);}
  .tr .td{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-top:3px;line-height:1.5;}
  .tr .tag{font-family:var(--mono);font-size:9px;letter-spacing:.1em;padding:2px 7px;border-radius:20px;
    background:rgba(232,197,71,.14);color:var(--amber);white-space:nowrap;}
  .tr .tag.ok{background:var(--green-dim);color:#8fd9ac;}

  .deriv{display:flex;flex-direction:column;gap:9px;}
  .dr .top{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10.5px;margin-bottom:5px;}
  .dr .top .k{color:var(--muted);} .dr .top .v{color:var(--text);}
  .dr .track{height:5px;border-radius:3px;background:rgba(255,255,255,.06);overflow:hidden;}
  .dr .fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--glacier-deep),var(--glacier));}
  .dr .fill.am{background:linear-gradient(90deg,#a8871f,var(--amber));}

  .diff{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
  .dcol{border:1px solid var(--border);border-radius:11px;padding:12px;background:var(--surface2);}
  .dcol.off{border-color:rgba(192,57,43,.30);}
  .dcol .hd{font-family:var(--mono);font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:9px;}
  .dcol.on .hd{color:var(--green);} .dcol.off .hd{color:#d97b6f;}
  .dcol .row{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;padding:5px 0;
    border-bottom:1px solid rgba(255,255,255,.04);}
  .dcol .row:last-child{border:none;}
  .dcol .row .k{color:var(--muted);} .dcol .row .v{color:var(--text);}
  .dcol.off .row .v{color:#e0a49c;}

  .next{border:1px solid rgba(143,199,255,.24);border-radius:13px;padding:14px;
    background:linear-gradient(180deg,rgba(143,199,255,.05),transparent);}
  .next .lb{font-family:var(--mono);font-size:10px;letter-spacing:.14em;color:var(--muted);
    text-transform:uppercase;margin-bottom:11px;}
  .next .btns{display:flex;gap:8px;flex-wrap:wrap;}
  .next .nb{background:var(--surface2);border:1px solid var(--border);border-radius:9px;
    padding:9px 13px;font-family:var(--mono);font-size:11px;color:var(--dim);cursor:pointer;transition:all .16s;}
  .next .nb:hover{border-color:var(--glacier);color:var(--glacier);}
  .next .nb.rec{border-color:rgba(143,199,255,.5);color:var(--glacier);background:var(--glacier-dim);}

  /* ---------- dock (journals) ---------- */
  .dock{margin-top:18px;}
  .dock-bar{display:flex;align-items:center;gap:11px;width:100%;background:var(--surface);
    border:1px solid var(--border);border-radius:12px;padding:12px 15px;cursor:pointer;margin-bottom:7px;
    text-align:left;color:var(--text);transition:border-color .16s;}
  .dock-bar:hover{border-color:var(--border2);}
  .dock-bar .chev{color:var(--muted);font-size:10px;transition:transform .2s;}
  .dock-bar.on .chev{transform:rotate(180deg);}
  .dock-bar .nm{flex:1;font-size:13.5px;font-weight:500;}
  .dock-bar .ct{font-family:var(--mono);font-size:10px;color:var(--muted);}
  .dock-body{display:none;border:1px solid var(--border);border-radius:12px;background:var(--surface);
    padding:14px;margin-bottom:7px;}
  .dock-bar.on + .dock-body{display:block;}
  table{width:100%;border-collapse:collapse;}
  th{font-family:var(--mono);font-size:9.5px;letter-spacing:.11em;color:var(--muted);text-transform:uppercase;
    text-align:left;padding:0 0 9px;border-bottom:1px solid var(--border);}
  td{font-family:var(--mono);font-size:11.5px;color:var(--dim);padding:10px 0;border-bottom:1px solid rgba(255,255,255,.04);}
  tr:last-child td{border:none;}
  td a{color:var(--glacier);border-bottom:1px solid rgba(143,199,255,.3);}
  td .cls.proven{color:var(--green);} td .cls.regular{color:var(--glacier);}
  td .cls.new,td .cls.unknown{color:var(--dim);} td .cls.risky,td .cls.banned{color:#e0a49c;}
  td .cls.CLEAR{color:var(--green);} td .cls.HOLD{color:var(--glacier);} td .cls.ABORT{color:#e0a49c;}
  .empty{font-family:var(--mono);font-size:11px;color:var(--muted);padding:6px 2px;}

  /* ---------- reveal ---------- */
  .reveal{opacity:0;transform:translateY(14px);transition:opacity .6s ease,transform .6s cubic-bezier(.16,1,.3,1);}
  .reveal.in{opacity:1;transform:none;}
  .no-js .reveal{opacity:1;transform:none;}

  /* ---------- mobile ---------- */
  .mob-toggle{display:none;position:sticky;top:112px;z-index:40;margin:0 0 12px;
    background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:5px;}
  .mob-toggle .seg{background:none;border:none;padding:0;width:100%;}
  .mob-toggle .seg button{flex:1;padding:11px;}
  .mob-toggle .seg button .n{display:inline-flex;width:15px;height:15px;border-radius:50%;
    background:rgba(255,255,255,.08);color:var(--muted);font-size:9px;align-items:center;justify-content:center;margin-right:6px;}
  .mob-toggle .seg button.on .n{background:rgba(143,199,255,.22);color:var(--glacier);}
  .done-hint{display:none;font-family:var(--mono);font-size:10px;color:var(--glacier);
    margin:-4px 0 10px;letter-spacing:.04em;}

  @media(max-width:900px){
    .wrap{padding:18px 16px 0;}
    .bar-inner{padding:15px 16px 12px;}
    .bench{grid-template-columns:1fr;gap:0;}
    .mob-toggle{display:block;}
    .pane.mobile-hidden{display:none;}
    .console{padding:14px;}
    .paths{display:none;}
    .fn-cont{display:block;}
    .diff{grid-template-columns:1fr;}
    .seg{width:100%;}
    .hash{font-size:9.5px;}
    /* bottom bar-row stays one row: shrink gaps, never wrap */
    .bar-row.bottom{gap:10px;}
    .bar-row.bottom .nav{gap:12px;}
    /* journals: stack the row instead of squeezing 5 columns */
    .dock-body table,.dock-body tbody,.dock-body tr,.dock-body td{display:block;width:100%;}
    .dock-body thead,.dock-body th{display:none;}
    .dock-body tr{border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:8px;}
    .dock-body td{border:none;padding:3px 0;font-size:11px;}
    .dock-body td:first-child{color:var(--glacier);}
    .dock-body td:last-child{border:none;}
  }
  @media(max-width:560px){
    .qgrid{grid-template-columns:1fr 1fr;}
    .sec-head h1{font-size:20px;}
    .btn{padding:8px 13px;font-size:11px;}
  }

  /* ---------- memory confirmation modal (same as the landing page) ---------- */
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
  @keyframes panelIn{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}

  /* ---------- memory countdown (header + control) ---------- */
  .status .recover{font-family:var(--mono);font-size:11px;color:var(--amber);letter-spacing:.04em;}
  .mem-ctl .countdown{font-family:var(--mono);font-size:11px;color:var(--amber);
    border:1px solid rgba(232,197,71,.3);background:rgba(232,197,71,.07);
    padding:9px 11px;border-radius:8px;margin-top:10px;display:none;}
  .mem-ctl .countdown.show{display:block;}
  .mem-ctl .countdown b{color:var(--amber);font-weight:700;}
  .mem-ctl .restore-row{display:none;margin-top:10px;}
  .mem-ctl .restore-row.show{display:block;}
  .mem-ctl .restore-row .btn{width:100%;justify-content:center;display:flex;}

  /* ---------- polish: tabs, cards, console, dock ---------- */
  .csec{box-shadow:0 1px 0 rgba(255,255,255,.02) inset;}
  .csec > .h{background:rgba(255,255,255,.015);}
  .qcell,.dcol,.subj,.fn{background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 32%);}
  .btn{transition:all .18s ease;}
  .btn:active{transform:translateY(1px);}
  .popt:active{transform:translateY(1px);}
  .dock-bar{transition:border-color .18s ease,background .18s ease;}
  .dock-body{background-image:linear-gradient(180deg,rgba(255,255,255,.015),rgba(255,255,255,0) 30%);}
  .reveal{transition:opacity .5s ease,transform .5s cubic-bezier(.16,1,.3,1);}
__TRYIT_CSS__
</style>
</head>
<body class="no-js">
<script>document.body.classList.remove('no-js');</script>
<div class="ambient" aria-hidden="true">
  <div class="grid-bg"></div>
  <div class="glow a"></div>
  <div class="glow b"></div>
</div>

<!-- header: kept from landing -->
<header class="bar">
  <div class="bar-inner">
    <div class="bar-row top">
      <div class="wordmark"><a href="/" class="home-link">THE<span class="tick">·</span>HOUSE</a><span class="tag-stack"><span class="sub">memory-native x402</span><span class="sibyl-credit">by Sibyl Labs</span></span></div>
      <div class="status-group">
        <div class="status" data-tip="The house's memory is live: pricing, dedup and refusals all run on remembered state." data-tip-pos="below"><span class="dot __DOT__" id="mem-dot"></span><span id="mem-status">MEMORY __MEMSTATUS__</span><span class="recover" id="mem-recover" style="display:none"></span></div>
        <button type="button" id="header-gate" class="gate-link" data-tip="Memory control — disable it (data kept, self-heals in 15 min) or purge it (permanent, irreversible)." data-tip-pos="below">disable memory</button>
      </div>
    </div>
    <div class="bar-row bottom">
      <div class="nav">
        <a href="/" class="back-home" data-tip="Back to the homepage." data-tip-pos="below">← back home</a>
        <a href="/house/ledger" data-tip="Raw JSON: every caller, trust score, dedup state." data-tip-pos="below">ledger</a>
        <a href="/manifest" data-tip="The house's machine-readable service manifest: every endpoint and its price." data-tip-pos="below">manifest</a>
      </div>
      <div class="hash">commit __COMMIT__</div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="sec-head">
    <div>
      <h1>gallery</h1>
      <div class="sub">Pick a counterparty the house knows, run a function, watch memory decide — then it hands you the next step.</div>
    </div>
  </div>

  <!-- mobile pane switch -->
  <div class="mob-toggle">
    <div class="seg">
      <button class="on" id="mob-configure"><span class="n">1</span>configure</button>
      <button id="mob-console"><span class="n">2</span>console</button>
    </div>
  </div>
  <div class="done-hint" id="done-hint"></div>

  <div class="bench">

    <!-- ============ LEFT PANE: configure ============ -->
    <div class="pane" id="pane-left">
      <div class="pane-head"><span class="t">configure</span><span class="t" style="color:var(--glacier)">1 → 2 → 3</span></div>
      <div class="pane-body">

        <div class="rail-label"><span><span class="step-badge">1</span>memory</span></div>
        <div class="mem-ctl">
          <div class="st"><span class="l">SIBYL MEMORY</span><span class="r" id="mem-ctl-state"><span class="dot"></span>live</span></div>
          <div class="mem-btns">
            <button id="mem-disable">disable</button>
            <button class="danger" id="mem-purge">purge</button>
          </div>
          <div class="countdown" id="mem-countdown"><span class="pdot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--amber);margin-right:8px;animation:breath 1s ease-in-out infinite"></span>memory disabled — <b>re-enables in <span id="mem-countdown-time">15:00</span></b></div>
          <div class="restore-row" id="mem-restore-row"><button class="btn" id="mem-restore">restore memory</button></div>
          <div class="del-test">Disable is reversible (15 min). Purge is permanent. Either way the console below recomputes — that is the deletion test, run live.</div>
        </div>

        <div class="rail-label" style="margin-top:16px"><span><span class="step-badge">2</span>subject</span><span id="subj-count" style="color:var(--glacier)">0</span></div>
        <div id="subject-list"><div class="empty">the house has not remembered anyone yet</div></div>
        <div class="subj-why">a subject is a wallet the house has served — one row in its memory: trust score, serves, scars. only wallets it actually knows are listed.</div>
        <button class="add-wallet" id="add-wallet">＋ watch / connect a wallet</button>

        <div class="rail-label" style="margin-top:16px"><span><span class="step-badge">3</span>function</span><span style="color:var(--glacier)">7</span></div>
        <div id="fn-list"></div>

      </div>
    </div>

    <!-- ============ RIGHT PANE: console ============ -->
    <div class="pane mobile-hidden" id="pane-right">
      <div class="pane-head">
        <span class="t">console · <span id="console-title">pick a function</span></span>
        <span class="t" style="color:var(--muted)">live</span>
      </div>
      <div class="console" id="console-body">
        <div class="csec"><div class="body"><div class="empty">Select a subject and a function on the left to run it here. Every number is read live from the house's memory.</div></div></div>
      </div>
    </div>
  </div>

  <!-- ============ DOCK: journals ============ -->
  <div class="dock" id="dock">
    <div class="sec-head" style="margin:20px 0 12px">
      <div><h1 style="font-size:17px">journals</h1>
      <div class="sub">The house's own records. They update as you work above.</div></div>
    </div>

    <button class="dock-bar on" data-dock="settle"><span class="nm">every settlement, with its transaction</span><span class="ct" id="d-settle-count">0</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-settle"></div></div>

    <button class="dock-bar" data-dock="desk"><span class="nm">the ledger of who it knows</span><span class="ct" id="d-desk-count">0</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-desk"></div></div>

    <button class="dock-bar" data-dock="acp"><span class="nm">the asset rail · Virtuals ACP</span><span class="ct" id="d-acp-count">0</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-acp"></div></div>

    <button class="dock-bar" data-dock="bonds"><span class="nm">the bond book</span><span class="ct" id="d-bonds-count">0</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-bonds"></div></div>

    <button class="dock-bar" data-dock="front"><span class="nm">the draft board</span><span class="ct" id="d-front-count">0</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-front"></div></div>

    <button class="dock-bar" data-dock="watch"><span class="nm">the verdict feed</span><span class="ct" id="d-watch-count">0</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-watch"></div></div>

    <button class="dock-bar" data-dock="log"><span class="nm">the season log</span><span class="ct">live</span><span class="chev">▾</span></button>
    <div class="dock-body"><div id="d-log"></div></div>
  </div>

  <footer style="border-top:1px solid var(--border);margin-top:48px;padding:22px 0 0;
    display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
    font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.08em;">
    <span>the-house · base mainnet · x402 exact scheme · $base_price base</span>
    <span>commit __COMMIT__ · __TS__</span>
  </footer>
</div>

__TRYIT_HTML__

<!-- memory action confirmation modal (same as the landing page) -->
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
  window.__HOUSE_SETTLE__ = __SETTLE_TXS_DATA__;
  window.__HOUSE_JOURNAL__ = __JOURNAL_DATA__;
</script>

<script>
  window.__TRYIT__ = {public_url: __PUBLIC_URL__};
__TRYIT_JS__
</script>

<script>
(function(){
  function $(id){return document.getElementById(id);}
  function esc(s){return (s==null?"":String(s)).replace(/[&<>\"]/g,function(c){
    return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]);});}
  function money(v){return (v==null?0:Number(v)).toFixed(4);}
  function age(s){
    if(s==null||s<0){return "—";}
    if(s<90){return Math.round(s)+"s";}
    if(s<5400){return Math.round(s/60)+"m";}
    if(s<172800){return Math.round(s/3600)+"h";}
    return Math.round(s/86400)+"d";
  }
  function fetchJson(url){
    return fetch(url,{cache:"no-store"}).then(function(r){return r.json();}).catch(function(){return null;});
  }
  function toast(msg,type){
    var t=document.getElementById("g-toast");
    if(!t){t=document.createElement("div");t.id="g-toast";t.className="toast";document.body.appendChild(t);}
    t.textContent=msg;t.className="toast show"+(type?" "+type:"");
    clearTimeout(t._t);t._t=setTimeout(function(){t.className="toast";},4200);
  }

  // ---------- state ----------
  var S = {
    subjects: [],      // [{kind:'caller'|'provider', addr, last, trust, segment, note}]
    subject: null,
    fn: null,          // key into window.TRYIT
    fnState: {},       // per-fn field values
    memory: "live",
    txs: window.__HOUSE_SETTLE__||[],
    journal: window.__HOUSE_JOURNAL__||[],
    acp: [],
    path: "manual"
  };

  var BASE = (window.__TRYIT__ && window.__TRYIT__.public_url) ? window.__TRYIT__.public_url : window.location.origin;

  // auto-advance chains: ran fn -> next offered (same subject)
  var NEXT = {
    "intel_quote": [["watch_screen","◈ screen this wallet"],["intel_entity","⌘ open its dossier"],["intel_quote","↻ fire a repeat (prove dedup → $0)"]],
    "bond_quote": [["scout_report","▤ provider report"],["scout_hire","⬢ hire decision"]],
    "watch_screen": null, // dynamic by verdict
    "scout_report": [["bond_quote","⬡ underwrite a provider"],["scout_hire","⬢ hire decision"]],
    "scout_hire": [["scout_report","▤ provider report"],["intel_entity","⌘ open its dossier"]],
    "intel_entity": [["intel_quote","◉ ask the house about this wallet"],["watch_screen","◈ screen it"]],
    "prepay": [["intel_quote","◉ ask the house again (credit is live)"]]
  };

  // ---------- subject list ----------
  function buildSubjects(ledger, front){
    var list=[];
    (ledger&&ledger.callers||[]).forEach(function(c){
      list.push({kind:"caller", last:c.addr_last6||"", trust:c.trust_score, segment:c.segment||"new",
        note:(c.tx_count||0)+" serve"+(c.tx_count===1?"":"s")});
    });
    (front&&front.board||[]).forEach(function(p){
      list.push({kind:"provider", last:p.provider_last6||"", trust:null, segment:p.segment||"unknown",
        note:"provider · "+(p.jobs_done||0)+" job"+(p.jobs_done===1?"":"s"), quality:p.quality_score});
    });
    // fallback: if the live ledger is empty (fresh boot / post-purge), surface the
    // documented real settlement so the workbench is never an empty shell. Same
    // fallback the landing page uses for its replay.
    if(!list.length && window.__HOUSE_SETTLE__ && window.__HOUSE_SETTLE__.length){
      window.__HOUSE_SETTLE__.forEach(function(t){
        var m=(t.note||"").match(/caller ([0-9a-f]{6})/i);
        if(m){ list.push({kind:"caller", last:m[1], trust:53, serves:1, segment:"new",
          note:"documented serve · trust 50→53"}); }
      });
    }
    // dedupe by last6, keep the first seen
    var seen={}, out=[];
    for(var i=0;i<list.length;i++){
      if(!list[i].last||seen[list[i].last]){continue;}
      seen[list[i].last]=1; out.push(list[i]);
    }
    S.subjects=out;
    renderSubjects();
    // keep selection if still present
    if(S.subject){
      var still=out.some(function(s){return s.last===S.subject.last;});
      if(!still){ S.subject=null; renderConsole(); }
    }
    // if a function was requested via ?fn= but no subject was chosen, auto-select the first
    if(S.fn && !S.subject && out.length){ S.subject=out[0]; renderSubjects(); renderConsole(); }
  }
  function renderSubjects(){
    var el=$("subject-list"); if(!el) return;
    if(!S.subjects.length){ el.innerHTML="<div class='empty'>the house has not remembered anyone yet</div>"; $("subj-count").textContent="0"; return; }
    $("subj-count").textContent=S.subjects.length;
    var h="";
    for(var i=0;i<S.subjects.length;i++){
      var s=S.subjects[i];
      var av=(s.last||"??").slice(0,3);
      var on=(S.subject&&S.subject.last===s.last)?" on":"";
      var score;
      if(s.trust!=null){ score="<span class='score'>"+s.trust+"</span>"; }
      else if(s.segment==="proven"||s.segment==="regular"){ score="<span class='tier "+esc(s.segment)+"'>"+esc(s.segment.toUpperCase())+"</span>"; }
      else { score="<span class='score dim'>—</span>"; }
      h+="<button class='subj"+on+"' data-i='"+i+"'><span class='av'>"+esc(av)+"</span>"
        +"<span class='meta'><span class='addr'>0x"+esc(s.last)+"</span><br><span class='note'>"+esc(s.note)+"</span></span>"
        +score+"</button>";
    }
    el.innerHTML=h;
    var btns=el.querySelectorAll(".subj");
    for(var b=0;b<btns.length;b++){
      btns[b].addEventListener("click",function(){
        var i=parseInt(this.getAttribute("data-i"),10);
        S.subject=S.subjects[i];
        renderSubjects(); renderConsole();
      });
    }
  }

  // ---------- functions ----------
  var FN_ORDER=["intel_quote","bond_quote","watch_screen","scout_report","scout_hire","intel_entity","prepay"];
  var FN_ICON={"intel_quote":"◉","bond_quote":"⬡","watch_screen":"◈","scout_report":"▤","scout_hire":"⬢","intel_entity":"⌘","prepay":"◍"};
  function renderFns(){
    var el=$("fn-list"); if(!el) return;
    var reg=window.TRYIT||{};
    var h="";
    for(var i=0;i<FN_ORDER.length;i++){
      var k=FN_ORDER[i], f=reg[k]; if(!f) continue;
      var on=(S.fn===k)?" on":"";
      h+="<div class='fn"+on+"' data-fn='"+k+"'>"
        +"<button class='fn-head'><span class='ico'>"+(FN_ICON[k]||"·")+"</span><span class='nm'>"+esc(f.title)+"</span><span class='price'>"+esc(f.room.split("·")[1]||"")+"</span><span class='chev'>▾</span></button>"
        +"<div class='fn-body'><div class='desc'>"+esc(f.desc)+"</div>";
      if(f.fields&&f.fields.length){
        h+="<div class='fields'>";
        for(var j=0;j<f.fields.length;j++){
          var fd=f.fields[j];
          var cur=(S.fnState[k]&&S.fnState[k][fd.k])||"";
          h+="<label>"+esc(fd.label)+"</label><input data-fn='"+k+"' data-k='"+fd.k+"' placeholder='"+esc(fd.ph)+"' value='"+esc(cur)+"'/>";
          if(fd.suggest&&fd.suggest.length){
            h+="<div class='chips'>";
            for(var s=0;s<fd.suggest.length;s++){ h+="<span class='chip' data-fn='"+k+"' data-k='"+fd.k+"' data-v='"+esc(fd.suggest[s])+"'>"+esc(fd.suggest[s])+"</span>"; }
            h+="</div>";
          }
        }
        h+="</div>";
      }
      h+="<div class='paths'>"
        +"<span class='path manual"+(S.fn===k&&S.path==="manual"?" on":"")+"' data-fn='"+k+"'>Manual</span>"
        +"<span class='path agent"+(S.fn===k&&S.path==="agent"?" on":"")+"' data-fn='"+k+"'>Agent</span>"
        +"<span class='path wallet"+(S.fn===k&&S.path==="wallet"?" on":"")+"' data-fn='"+k+"'>Connect Wallet</span>"
        +"</div>"
        +"<button class='fn-cont' data-fn='"+k+"'>continue → console</button>"
        +"</div></div>";
    }
    el.innerHTML=h;
    // bind
    var heads=el.querySelectorAll(".fn-head");
    for(var a=0;a<heads.length;a++){
      heads[a].addEventListener("click",function(){
        var fn=this.closest(".fn"), k=fn.getAttribute("data-fn");
        var wasOn=fn.classList.contains("on");
        el.querySelectorAll(".fn").forEach(function(x){x.classList.remove("on");});
        if(wasOn){
          // collapse: pressing the open container closes it + deselects
          S.fn=null;
        }else{
          fn.classList.add("on");
          S.fn=k;
        }
        S.path="manual";
        renderFns(); renderConsole();
      });
    }
    var ins=el.querySelectorAll(".fn-body input");
    for(var b=0;b<ins.length;b++){
      ins[b].addEventListener("input",function(){
        var k=this.getAttribute("data-fn"), fk=this.getAttribute("data-k");
        if(!S.fnState[k]) S.fnState[k]={};
        S.fnState[k][fk]=this.value;
        // if this is the function currently in the console, live-update the run
        // command + quote so the field value is reflected without losing focus
        if(k===S.fn){ updateConsoleCmd(); }
      });
    }
    var chips=el.querySelectorAll(".chip");
    for(var c=0;c<chips.length;c++){
      chips[c].addEventListener("click",function(){
        var k=this.getAttribute("data-fn"), fk=this.getAttribute("data-k"), v=this.getAttribute("data-v");
        if(!S.fnState[k]) S.fnState[k]={};
        S.fnState[k][fk]=v;
        var inp=el.querySelector("input[data-fn='"+k+"'][data-k='"+fk+"']");
        if(inp) inp.value=v;
        if(k===S.fn){ updateConsoleCmd(); }
      });
    }
    var conts=el.querySelectorAll(".fn-cont");
    for(var m=0;m<conts.length;m++){
      conts[m].addEventListener("click",function(e){
        e.stopPropagation();
        var k=this.getAttribute("data-fn");
        S.fn=k; S.path="manual";
        renderFns(); renderConsole();
        if(window.matchMedia&&window.matchMedia("(max-width:900px)").matches){ mobPane("right"); }
      });
    }
    var paths=el.querySelectorAll(".path");
    for(var d=0;d<paths.length;d++){
      paths[d].addEventListener("click",function(e){
        e.stopPropagation();
        var k=this.getAttribute("data-fn");
        S.fn=k;
        S.path=this.classList.contains("agent")?"agent":(this.classList.contains("wallet")?"wallet":"manual");
        // ensure the function is expanded so the selection is visible
        el.querySelectorAll(".fn").forEach(function(x){x.classList.remove("on");});
        var fn=el.querySelector(".fn[data-fn='"+k+"']");
        if(fn){ fn.classList.add("on"); }
        renderFns(); renderConsole();
      });
    }
  }

  // ---------- console ----------
  function currentFn(){ return window.TRYIT&&window.TRYIT[S.fn]?window.TRYIT[S.fn]:null; }
  function fnFields(k){ return S.fnState[k]||{}; }

  // live-update the run command + re-quote after a field value changes, without
  // rebuilding the whole console (so the input keeps focus)
  function updateConsoleCmd(){
    var f=currentFn(); if(!f) return;
    var code=document.querySelector("#console-body .term code");
    if(code){ code.innerHTML="<span class='p'>$</span> "+esc(buildCmd(f,fnFields(S.fn))); }
    var cp=document.querySelector("#console-body .cp[data-copy]");
    if(cp){ cp.setAttribute("data-copy", buildCmd(f,fnFields(S.fn))); }
    var ap=document.getElementById("agent-prompt-pre");
    if(ap){ ap.textContent=agentPrompt(f,fnFields(S.fn)); }
    var acp=document.getElementById("copy-agent-prompt");
    if(acp){ acp.setAttribute("data-copy", agentPrompt(f,fnFields(S.fn))); }
    fetchQuote();
  }

  function renderConsole(){
    var body=$("console-body"); if(!body) return;
    var f=currentFn();
    $("console-title").textContent = f?f.title:"pick a function";
    if(!f || !S.subject){
      body.innerHTML="<div class='csec'><div class='body'><div class='empty'>Select a subject and a function on the left to run it here. Every number is read live from the house's memory.</div></div></div>";
      return;
    }
    var subj=S.subject;
    var fields=fnFields(S.fn);
    var cmd=buildCmd(f,fields);
    var priceLabel="live"; // will be replaced by quote fetch

    var h="";
    // 1 · RUN
    h+="<div class='csec'><div class='h'><span class='l'><span class='step-badge'>1</span>run</span><span class='r'>subject 0x"+esc(subj.last)+"</span></div><div class='body'>";
    h+="<div class='pathsel'><div class='pathsel-lb'>run as <span class='hint'>— execution path</span></div><div class='popts' role='tablist'>"
      +"<button type='button' class='popt"+(S.path==='manual'?' on':'')+"' data-p='manual' role='tab'><svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><path d='M4 5l3 3-3 3'/><line x1='8.5' y1='12.5' x2='12' y2='12.5'/></svg>Manual</button>"
      +"<button type='button' class='popt"+(S.path==='agent'?' on':'')+"' data-p='agent' role='tab'><svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><path d='M8 1.5l1.7 3.8 3.8 1.7-3.8 1.7L8 12.5l-1.7-3.8-3.8-1.7 3.8-1.7z'/><path d='M12.5 11.5l.8 1.7 1.7.8-1.7.8-.8 1.7-.8-1.7-1.7-.8 1.7-.8z'/></svg>Agent</button>"
      +"<button type='button' class='popt"+(S.path==='wallet'?' on':'')+"' data-p='wallet' role='tab'><svg viewBox='0 0 16 16' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><rect x='1.5' y='3.5' width='13' height='9' rx='2'/><path d='M11 7.5h2.5v2H11a1 1 0 010-2z'/><circle cx='12' cy='8.5' r='.6' fill='currentColor'/></svg>Connect Wallet</button>"
      +"</div></div>";
    h+="<div class='runline'><span class='path-badge'>"+esc(f.method)+" "+esc(f.path)+"</span><span class='amt' id='console-amt'>—<small>USDC</small></span></div>";
    if(S.path==="manual"){
      h+="<div class='term' style='margin-top:12px'><div class='th'><span class='dots3'><i></i><i></i><i></i></span>your terminal<span class='cp' data-copy='"+esc(cmd)+"'>copy</span></div>"
        +"<code><span class='p'>$</span> "+esc(cmd)+"</code></div>";
      h+="<div style='display:flex;gap:8px;margin-top:11px;flex-wrap:wrap'><button class='btn' id='refresh-quote'>refresh quote</button></div>";
    } else if(S.path==="agent"){
      h+="<div class='term' style='margin-top:12px'><div class='th'><span class='dots3'><i></i><i></i><i></i></span>agent endpoint<span class='cp' data-copy='"+esc(cmd)+"'>copy</span></div>"
        +"<code><span class='p'>$</span> "+esc(cmd)+"</code></div>";
      h+="<div class='aprompt'><div class='th'><span>✦ agent prompt — paste the whole block</span><span class='cp' id='copy-agent-prompt' data-copy='"+esc(agentPrompt(f,fields))+"'>copy prompt</span></div>"
        +"<pre id='agent-prompt-pre'>"+esc(agentPrompt(f,fields))+"</pre></div>";
      h+="<div style='display:flex;gap:8px;margin-top:11px;flex-wrap:wrap'><button class='btn' id='refresh-quote'>refresh quote</button><button class='btn ghost' id='copy-prompt'>copy agent prompt</button></div>";
    } else {
      h+="<div class='term' style='margin-top:12px'><div class='th'><span class='dots3'><i></i><i></i><i></i></span>connect a wallet<span class='cp' id='wallet-status'>not connected</span></div>"
        +"<code><span class='cm'>Connect a Base wallet to sign the exact EIP-3009 authorization the house's facilitator verifies and settles. No gas, no broadcast — you only sign.</span></code></div>";
      h+="<div style='display:flex;gap:8px;margin-top:11px;flex-wrap:wrap'><button class='btn' id='connect-wallet'>connect wallet</button><button class='btn go' id='wallet-settle' disabled>sign &amp; settle →</button></div>";
    }
    h+="</div></div>";

    // 2 · QUOTE
    h+="<div class='csec'><div class='h'><span class='l'><span class='step-badge'>2</span>quote</span><span class='r'><span class='dot' id='quote-dot' style='display:inline-block;width:7px;height:7px'></span> <span id='quote-live-label'>live</span></span></div><div class='body' id='quote-body'><div class='empty'>fetching a live quote…</div></div></div>";

    // 3 · MEMORY TRACE
    h+="<div class='csec'><div class='h'><span class='l'><span class='step-badge'>3</span>memory trace</span><span class='r'>read before price · write after serve</span></div><div class='body'>";
    h+=renderTrace(subj);
    h+="</div></div>";

    // 4 · ARTIFACT
    h+="<div class='csec'><div class='h'><span class='l'><span class='step-badge'>4</span>artifact · onchain</span><span class='r'>Basescan-decodable</span></div><div class='body' id='artifact-body'><div class='empty'>settle to produce an onchain artifact</div></div></div>";

    // 5 · WHAT MEMORY IS WORTH
    h+="<div class='csec'><div class='h'><span class='l'>what memory is worth</span><span class='r'>same request, both ways</span></div><div class='body'>";
    h+=renderDiff(subj);
    h+="</div></div>";

    // 6 · NEXT STEP
    h+="<div class='next'><div class='lb'>next logical step</div><div class='btns' id='next-btns'></div></div>";

    body.innerHTML=h;
    bindConsole();
    fetchQuote();
  }

  // Full agent brief: goal, exact endpoint, the x402 signing flow, what the
  // house is, and the rules. Rebuilt live from the current field values so the
  // pasted block always matches the endpoint above it.
  function agentPrompt(f,fields){
    if(!f) return "";
    var L=[];
    L.push("You are an autonomous agent with your own crypto wallet on Base (chain eip155:8453, asset USDC).");
    L.push("");
    L.push("GOAL — "+f.title+": "+f.desc);
    L.push("");
    L.push("ENDPOINT — send exactly this first, with NO payment attached:");
    L.push(buildCmd(f,fields));
    L.push("");
    L.push("HOW — the x402 flow, step by step:");
    L.push("1. Expect HTTP 402 with a `payment-required` header (base64 JSON). Decode accepts[0]: amount (atomic USDC units), asset contract, payTo (the house wallet), network, maxTimeoutSeconds.");
    L.push("2. Cross-check against the live quote in console section 2 below — amount and payTo MUST match before you sign anything.");
    L.push("3. Sign an EIP-3009 TransferWithAuthorization via eth_signTypedData_v4 (EIP-712): from = your wallet, to = payTo, value = EXACTLY the quoted amount, validAfter = now, validBefore = now + maxTimeoutSeconds, plus a fresh random 32-byte nonce. Verifying contract = the quoted USDC asset.");
    L.push("4. Retry the SAME request with header `PAYMENT-RESPONSE: base64({authorization:{from,to,value,validAfter,validBefore,nonce},signature})`. The facilitator settles onchain — you only sign, never broadcast a transaction yourself.");
    L.push("5. Expect 200 plus a receipt. A 403 (risky / refused) or 404 (unknown entity) means UNCHARGED: do not pay and do not retry.");
    L.push("");
    L.push("CONTEXT — what you are dealing with: the house is a memory-native service. It recalls your wallet before pricing (a trust score can earn you a discount), serves exact repeat requests from memory at net $0 (dedup — ask twice, pay once), and refuses bad actors before money moves. After you are served: "+(f.after||"the house records your wallet and remembers what it served."));
    L.push("");
    L.push("RULES: pay EXACTLY the quoted amount — not more, not less. One payment attempt per quote; if the quote is stale, refresh it and start over. Keep validBefore comfortably in the future. Never expose your private key; signing happens locally in your own wallet.");
    return L.join("\n");
  }

  function buildCmd(f,fields){
    if(!f) return "";
    var url=BASE+f.path;
    if(f.method==="GET"){ url += f.body(fields); }
    var cmd="curl -sS -X "+f.method+" '"+url+"'";
    if(f.method==="POST"){ cmd+=" -H 'Content-Type: application/json' -d '"+f.body(fields)+"'"; }
    return cmd;
  }

  function renderTrace(subj){
    var trust = (subj.trust!=null?subj.trust:50);
    var serves = (subj.serves!=null?subj.serves : (subj.kind==="caller" ? (parseInt(subj.note,10)||0) : 0));
    var known = subj.kind==="caller";
    var h="<div class='trace'>";
    h+="<div class='tr mem'><span class='n'>R</span><span class='tx'><span class='tt'>recall 0x"+esc(subj.last)+"</span><br><span class='td'>Sibyl Memory · "+(known?"1 row found":"no row yet")+"</span></span><span class='tag'>memory</span></div>";
    h+="<div class='tr'><span class='n'>1</span><span class='tx'><span class='tt'>read memory → what it knows</span><br><span class='td'>"+(known?"trust "+trust+" · "+serves+" serve"+(serves===1?"":"s")+" · no scars":"new wallet — list price")+"</span></span></div>";
    h+="<div class='tr'><span class='n'>2</span><span class='tx'><span class='tt'>price from that row</span><br><span class='td'>base quote · trust tier → "+(known?"discounted":"list")+"</span></span></div>";
    h+="<div class='tr'><span class='n'>3</span><span class='tx'><span class='tt'>serve</span><br><span class='td'>answer returned</span></span></div>";
    h+="<div class='tr mem done'><span class='n'>W</span><span class='tx'><span class='tt'>write memory ← what it learned</span><br><span class='td'>"+(known?"serves "+serves+"→"+(serves+1)+" · trust "+trust+"→"+Math.min(100,trust+3):"new caller · trust 50→53")+"</span></span><span class='tag ok'>written</span></div>";
    h+="</div>";
    // derivation
    h+="<div style='margin-top:13px;padding-top:13px;border-top:1px solid var(--border)'><div class='rail-label'>how the number is derived</div><div class='deriv'>";
    h+="<div class='dr'><div class='top'><span class='k'>base</span><span class='v'>50 / 50</span></div><div class='track'><div class='fill' style='width:100%'></div></div></div>";
    var sPct=Math.min(100,serves*3/30*100);
    h+="<div class='dr'><div class='top'><span class='k'>serves · +3 each</span><span class='v'>"+Math.min(30,serves*3)+" / 30</span></div><div class='track'><div class='fill' style='width:"+sPct+"%'></div></div></div>";
    h+="<div class='dr'><div class='top'><span class='k'>segment · "+esc(subj.segment||"new")+" wallet</span><span class='v'>"+(known?"+0":"+0")+" / 20</span></div><div class='track'><div class='fill am' style='width:"+(known?"0%":"0%")+"'></div></div></div>";
    h+="</div></div>";
    return h;
  }

  function renderDiff(subj){
    var known=subj.kind==="caller";
    var h="<div class='diff'>";
    h+="<div class='dcol on'><div class='hd'>● memory on</div>"
      +"<div class='row'><span class='k'>price</span><span class='v'>"+(known?"discounted":"0.01")+"</span></div>"
      +"<div class='row'><span class='k'>dedup</span><span class='v'>repeat → $0</span></div>"
      +"<div class='row'><span class='k'>refusal</span><span class='v'>scars respected</span></div>"
      +"<div class='row'><span class='k'>trust</span><span class='v'>"+(known?subj.trust+" → "+Math.min(100,subj.trust+3):"50 → 53")+"</span></div></div>";
    h+="<div class='dcol off'><div class='hd'>○ memory off</div>"
      +"<div class='row'><span class='k'>price</span><span class='v'>0.01 list</span></div>"
      +"<div class='row'><span class='k'>dedup</span><span class='v'>none — pay again</span></div>"
      +"<div class='row'><span class='k'>refusal</span><span class='v'>cannot refuse</span></div>"
      +"<div class='row'><span class='k'>trust</span><span class='v'>—</span></div></div>";
    h+="</div>";
    return h;
  }

  // ---------- quote ----------
  function fetchQuote(){
    var f=currentFn(); if(!f) return;
    var fields=fnFields(S.fn);
    var opts={method:f.method,headers:{"Content-Type":"application/json"}};
    if(f.method==="POST"){ opts.body=f.body(fields); }
    var url=BASE+f.path+(f.method==="GET"?f.body(fields):"");
    fetch(url,opts).then(function(res){
      var pr=res.headers.get("payment-required");
      var q=null;
      if(pr){ try{ q=JSON.parse(atob(pr)); }catch(e){} }
      renderQuote(q);
    }).catch(function(){
      var qb=$("quote-body");
      if(qb){ qb.innerHTML="<div class='empty'>the house did not answer — the quote request failed.</div>"; }
    });
  }
  function renderQuote(q){
    var amtEl=$("console-amt");
    var qb=$("quote-body"); if(!qb) return;
    if(!q||!q.accepts||!q.accepts.length){
      qb.innerHTML="<div class='empty'>no live quote — the house may be refusing this counterparty.</div>";
      return;
    }
    var a=q.accepts[0];
    var amt=parseInt(a.amount,10)/1000000;
    var name=(a.extra&&a.extra.name)||"USDC";
    if(amtEl){ amtEl.innerHTML=amt.toFixed(2)+" <small>"+esc(name)+"</small>"; }
    var h="<div class='qgrid'>"
      +"<div class='qcell'><div class='k'>amount</div><div class='v gl'>"+amt.toFixed(2)+" "+esc(name)+"</div></div>"
      +"<div class='qcell'><div class='k'>network</div><div class='v'>"+esc(a.network||"eip155:8453")+"</div></div>"
      +"<div class='qcell'><div class='k'>pay to</div><div class='v'><a href='https://basescan.org/address/"+(a.payTo||"")+"' target='_blank' rel='noopener'>"+(a.payTo?esc(a.payTo.slice(0,8))+"…"+esc(a.payTo.slice(-6)):"—")+"</a></div></div>"
      +"<div class='qcell'><div class='k'>trust used</div><div class='v am'>"+(S.subject&&S.subject.trust!=null?S.subject.trust+" → +3":"new")+"</div></div>"
      +"</div>";
    if(S.path==="manual"){
      h+="<div style='display:flex;gap:8px;margin-top:12px;flex-wrap:wrap'><button class='btn go' id='copy-payto'>copy payment request</button></div>";
    }
    qb.innerHTML=h;
    var cp=$("copy-payto");
    if(cp){ cp.addEventListener("click",function(){
      var txt="Send "+amt.toFixed(2)+" "+name+" on "+a.network+" to\n  payTo: "+a.payTo+"\n  asset: "+a.asset+"\n  within "+a.maxTimeoutSeconds+"s";
      copyText(txt);
    }); }
    // remember the live quote for the wallet path (tagged with the function it priced)
    S.liveQuote=a;
    S.liveQuoteFn=S.fn;
  }

  // ---------- wallet path ----------
  var wallet = {connected:false, address:null};
  function connectWallet(){
    if(!window.ethereum){
      toast("no injected wallet — install MetaMask or Coinbase Wallet","err");
      return;
    }
    window.ethereum.request({method:"eth_requestAccounts"}).then(function(accs){
      wallet.connected=true; wallet.address=accs[0];
      var st=$("wallet-status"); if(st){ st.textContent=wallet.address.slice(0,8)+"…"+wallet.address.slice(-6); }
      var btn=$("wallet-settle"); if(btn){ btn.disabled=false; }
      toast("wallet connected","ok");
    }).catch(function(e){ toast("connection declined","err"); });
  }
  function walletSettle(){
    if(!wallet.connected||!wallet.address){ return; }
    if(!S.liveQuote){ toast("fetch a live quote first","err"); return; }
    // guard: the quote must be for the function currently in the console, else
    // the user would settle the wrong amount (stale quote from a previous fn)
    if(S.liveQuoteFn!==S.fn){
      toast("quote is stale — refresh it for "+((currentFn()||{}).title||"this function"),"err");
      fetchQuote();
      return;
    }
    var a=S.liveQuote;
    // build EIP-712 typed data for EIP-3009 TransferWithAuthorization
    var now=Math.floor(Date.now()/1000);
    var nonce="0x";
    var arr=new Uint8Array(32); if(window.crypto&&crypto.getRandomValues){ crypto.getRandomValues(arr); }
    for(var i=0;i<arr.length;i++){ nonce+=("0"+arr[i].toString(16)).slice(-2); }
    var typedData={
      types:{
        EIP712Domain:[{name:"name",type:"string"},{name:"version",type:"string"},{name:"chainId",type:"uint256"},{name:"verifyingContract",type:"address"}],
        TransferWithAuthorization:[{name:"from",type:"address"},{name:"to",type:"address"},{name:"value",type:"uint256"},{name:"validAfter",type:"uint256"},{name:"validBefore",type:"uint256"},{name:"nonce",type:"bytes32"}]
      },
      primaryType:"TransferWithAuthorization",
      domain:{name:(a.extra&&a.extra.name)||"USD Coin",version:(a.extra&&a.extra.version)||"2",chainId:8453,verifyingContract:a.asset},
      message:{from:wallet.address,to:a.payTo,value:parseInt(a.amount,10),validAfter:now,validBefore:now+(a.maxTimeoutSeconds||600),nonce:nonce}
    };
    window.ethereum.request({method:"eth_signTypedData_v4",params:[wallet.address,JSON.stringify(typedData)]})
      .then(function(sig){
        // build the exact payload the house server expects
        var payload={authorization:{from:wallet.address,to:a.payTo,value:String(parseInt(a.amount,10)),validAfter:String(now),validBefore:String(now+(a.maxTimeoutSeconds||600)),nonce:nonce},signature:sig};
        var header=btoa(JSON.stringify(payload));
        // re-request with the PAYMENT-RESPONSE header
        var f=currentFn(); if(!f) return;
        var fields=fnFields(S.fn);
        var opts={method:f.method,headers:{"Content-Type":"application/json","PAYMENT-RESPONSE":header}};
        if(f.method==="POST"){ opts.body=f.body(fields); }
        var url=BASE+f.path+(f.method==="GET"?f.body(fields):"");
        toast("signing…","ok");
        fetch(url,opts).then(function(res){
          if(res.ok){
            toast("settled — the house served you and is writing memory","ok");
            renderArtifact(wallet.address, a);
            // refresh the ledger so the subject list updates
            refreshAll();
          } else {
            res.text().then(function(t){ toast("settlement not accepted: "+t.slice(0,120),"err"); });
          }
        }).catch(function(){ toast("settlement failed","err"); });
      })
      .catch(function(e){ toast("signature declined","err"); });
  }
  function renderArtifact(payer,a){
    var el=$("artifact-body"); if(!el) return;
    var h="<div class='qgrid'>"
      +"<div class='qcell'><div class='k'>payer</div><div class='v'><a href='https://basescan.org/address/"+esc(payer)+"' target='_blank' rel='noopener'>"+esc(payer.slice(0,8))+"…"+esc(payer.slice(-6))+"</a></div></div>"
      +"<div class='qcell'><div class='k'>settled</div><div class='v gr'>"+(a?money(parseInt(a.amount,10)/1000000):"—")+" USDC</div></div>"
      +"<div class='qcell'><div class='k'>receiver</div><div class='v'>"+(a?esc(a.payTo.slice(0,8))+"…"+esc(a.payTo.slice(-6)):"—")+"</div></div>"
      +"<div class='qcell'><div class='k'>memory delta</div><div class='v am'>trust → +3</div></div>"
      +"</div>";
    el.innerHTML=h;
  }

  // ---------- console bind ----------
  function bindConsole(){
    var tabs=document.querySelectorAll("#console-body .popt");
    for(var i=0;i<tabs.length;i++){
      tabs[i].addEventListener("click",function(){
        S.path=this.getAttribute("data-p"); renderConsole();
      });
    }
    var rq=$("refresh-quote"); if(rq){ rq.addEventListener("click",fetchQuote); }
    var cps=document.querySelectorAll("#console-body .cp[data-copy]");
    for(var c=0;c<cps.length;c++){
      cps[c].addEventListener("click",function(){ copyText(this.getAttribute("data-copy")); });
    }
    var cpr=$("copy-prompt");
    if(cpr){ cpr.addEventListener("click",function(){
      var f=currentFn(); if(!f) return;
      copyText(agentPrompt(f,fnFields(S.fn)));
    }); }
    var cw=$("connect-wallet"); if(cw){ cw.addEventListener("click",connectWallet); }
    var ws=$("wallet-settle"); if(ws){ ws.addEventListener("click",walletSettle); }
    // next steps
    var nb=$("next-btns"); if(nb){ nb.innerHTML=renderNext(); var nbs=nb.querySelectorAll(".nb");
      for(var n=0;n<nbs.length;n++){
        nbs[n].addEventListener("click",function(){
          var k=this.getAttribute("data-fn");
          if(k){ S.fn=k; S.path="manual"; renderFns(); renderConsole(); }
        });
      }
    }
  }
  function renderNext(){
    if(!S.fn) return "";
    var chain=NEXT[S.fn];
    if(S.fn==="watch_screen"){ chain = (S.subject&&S.subject.segment==="risky"||S.subject&&S.subject.segment==="banned") ? [["intel_entity","⌘ open its dossier (why it fired)"],["intel_quote","◉ ask the house about it"]] : [["intel_quote","◉ ask the house about it"],["intel_entity","⌘ open its dossier"]]; }
    if(!chain||!chain.length) return "<span class='empty'>no further step</span>";
    var h="";
    for(var i=0;i<chain.length;i++){
      h+="<button class='nb"+(i===0?" rec":"")+"' data-fn='"+chain[i][0]+"'>"+chain[i][1]+"</button>";
    }
    return h;
  }

  // ---------- dock ----------
  function table(headers,rows,empty){
    if(!rows||!rows.length){ return "<div class='empty'>"+esc(empty||"no record yet")+"</div>"; }
    var h="<table><tr>";
    for(var i=0;i<headers.length;i++){ h+="<th>"+esc(headers[i][0])+"</th>"; }
    h+="</tr>";
    for(var r=0;r<rows.length;r++){
      h+="<tr>";
      for(var c=0;c<headers.length;c++){
        var cell=rows[r][c];
        if(cell&&cell.href){ h+="<td><a href='"+esc(cell.href)+"' target='_blank' rel='noopener'>"+esc(cell.t)+"</a></td>"; }
        else if(cell&&cell.cls){ h+="<td><span class='cls "+esc(cell.cls)+"'>"+esc(cell.t)+"</span></td>"; }
        else{ h+="<td>"+esc(cell==null?"—":cell)+"</td>"; }
      }
      h+="</tr>";
    }
    h+="</table>";
    return h;
  }
  function renderDock(ledger, bonds, front, watch, journal, acp){
    if(ledger){
      // settlements
      var txs=S.txs;
      var rows=txs.map(function(t){
        return [{t:(t.hash||"").slice(0,10)+"…",href:"https://basescan.org/tx/"+(t.hash||"")}, t.label||"—", money(t.usdc), t.note||"—"];
      });
      $("d-settle-count").textContent=rows.length;
      $("d-settle").innerHTML=table([["tx"],["what"],["usdc"],["memory delta"]],rows,"no settlements journaled yet");
      // desk
      var callers=ledger.callers||[];
      $("d-desk-count").textContent=callers.length;
      var drows=callers.map(function(c){
        return ["0x"+c.addr_last6,{t:c.segment||"—",cls:c.segment||""},c.trust_score!=null?c.trust_score:"—",c.tx_count||0,money(c.net_charged_usdc)];
      });
      $("d-desk").innerHTML=table([["wallet"],["segment"],["trust"],["tx"],["net $"]],drows,"no callers remembered yet");
    }
    if(acp){
      $("d-acp-count").textContent=acp.length;
      var arows=acp.map(function(j){
        var escrow=j.escrow_tx?{t:j.escrow_tx.slice(0,10)+"…",href:"https://basescan.org/tx/"+j.escrow_tx}:"—";
        return [j.job_id||"—", j.provider_name||"—", j.offering||"—", j.usdc!=null?money(j.usdc):"—", {t:j.status||"—",cls:(j.status==="completed"?"proven":(j.status==="session expired"?"risky":"new"))}, escrow];
      });
      $("d-acp").innerHTML=table([["job"],["provider"],["offering"],["usdc"],["status"],["escrow tx"]],arows,"no ACP jobs yet");
    }
    if(bonds){
      var b=bonds.book||{};
      $("d-bonds-count").textContent=(b.bonds_issued!=null?b.bonds_issued:0);
      var brows=(bonds.bonds||[]).map(function(bd){
        var cell=bd.claim_tx?{t:bd.claim_tx.slice(0,10)+"…",href:"https://basescan.org/tx/"+bd.claim_tx}:"—";
        return [bd.id||"—",bd.provider_last6||"—",money(bd.face_usdc),money(bd.premium_usdc),bd.segment||"—",bd.status||"—",cell];
      });
      $("d-bonds").innerHTML=table([["bond"],["prov"],["face $"],["prem $"],["seg"],["status"],["claim tx"]],brows,"no bonds issued yet");
    }
    if(front){
      $("d-front-count").textContent=(front.providers!=null?front.providers:0);
      var frows=(front.board||[]).map(function(p){
        return ["0x"+p.provider_last6,{t:p.segment||"—",cls:p.segment||""},p.jobs_done||0,p.quality_score!=null?Number(p.quality_score).toFixed(2):"—",p.default_events||0,p.hired?"drafted":"refused"];
      });
      $("d-front").innerHTML=table([["provider"],["segment"],["jobs"],["quality"],["defaults"],["terms"]],frows,"no providers remembered yet");
    }
    if(watch){
      var w=watch.stats||{};
      $("d-watch-count").textContent=(w.screens!=null?w.screens:0);
      var wrows=(watch.feed||[]).map(function(x){
        return [{t:x.verdict||"—",cls:x.verdict||""},(x.rules||[]).join(", ")||"clean",(x.ring&&x.ring.length?x.ring.map(function(a){return String(a).slice(-6);}).join(" "):"—")];
      });
      $("d-watch").innerHTML=table([["verdict"],["rule"],["ring"]],wrows,"no screens yet");
    }
    if(journal){
      var ev=journal;
      if(!ev.length){ ev=S.journal; }
      var lh="";
      for(var i=0;i<ev.length;i++){
        lh+="<div style='display:grid;grid-template-columns:150px 84px 1fr;gap:12px;padding:9px 2px;border-bottom:1px solid rgba(255,255,255,.04);align-items:baseline'>"
          +"<span style='color:var(--muted);font-size:11px'>"+esc(ev[i].ts||"")+"</span>"
          +"<span style='color:var(--glacier);font-size:10px;letter-spacing:.1em;text-transform:uppercase'>"+esc(ev[i].kind||"")+"</span>"
          +"<span style='color:var(--dim)'>"+esc(ev[i].text||"")+"</span></div>";
      }
      $("d-log").innerHTML=lh||"<div class='empty'>no journal entries yet</div>";
    }
  }

  // ---------- refresh ----------
  function refreshAll(){
    fetchJson("/house/ledger").then(function(j){
      if(j){
        if(j.memory){ setMemory(j.memory); }
        buildSubjects(j, null);
        renderDock(j, null, null, null, null, null);
      }
      fetchJson("/house/front").then(function(f){
        buildSubjects(j,f);
        renderDock(j, null, f, null, null, null);
      });
    });
    fetchJson("/house/bonds").then(function(b){ renderDock(null,b,null,null,null,null); });
    fetchJson("/house/watch").then(function(w){ renderDock(null,null,null,w,null,null); });
    fetchJson("/house/journal").then(function(j){ S.journal=j&&j.events||[]; renderDock(null,null,null,null,S.journal,null); });
    fetchJson("/house/acp/jobs").then(function(j){ S.acp=j&&j.jobs||[]; renderDock(null,null,null,null,null,S.acp); });
  }
  function setMemory(m){
    S.memory=m;
    var st=$("mem-status"); if(st){ st.textContent="MEMORY "+String(m).toUpperCase(); }
    // live = green breathing · disabled OR purged = solid red (no breathing)
    var dot=$("mem-dot"); if(dot){ dot.className="dot"+(m==="live"?"":" off"); }
    var cs=$("mem-ctl-state"); if(cs){ cs.className="r"+(m==="live"?"":" off"); cs.innerHTML=(m==="live"?"<span class='dot'></span>live":"<span class='dot off'></span>"+String(m).toUpperCase()); }
    var qd=$("quote-dot"); if(qd){ qd.className="dot"+(m==="live"?"":" off"); }
    var ql=$("quote-live-label"); if(ql){ ql.textContent=(m==="live"?"live":"memory off"); }
    // header button language: disable memory when live, restore memory when off
    var hg=$("header-gate");
    if(hg){
      if(m==="live"){ hg.textContent="disable memory"; hg.style.borderColor="rgba(192,57,43,.5)"; hg.style.color="#ff8a7a"; }
      else { hg.textContent="restore memory"; hg.style.borderColor="rgba(39,174,96,.5)"; hg.style.color="#8fd9ac"; }
    }
    // memory control: countdown + restore only when disabled (soft-off, self-heals)
    var cd=$("mem-countdown"), rr=$("mem-restore-row");
    if(cd){ cd.classList.toggle("show", m==="disabled"); }
    if(rr){ rr.classList.toggle("show", m==="disabled"); }
    // header recovery timer only for a soft-off (disabled) — it self-heals in 15 min
    var rec=$("mem-recover");
    if(m==="disabled" && rec){
      rec.style.display="inline";
      if(!recoverEndAt){ recoverEndAt=Date.now()+((gateState&&gateState.remaining_seconds)||900)*1000; }
      updateRecover();
    }else if(rec){
      rec.style.display="none"; recoverEndAt=null;
    }
  }
  var gateState=S.gateState||{};
  var recoverEndAt=null;
  function fmtCountdown(s){
    s=Math.max(0,Math.round(s||0));
    var m=Math.floor(s/60), sec=s%60;
    return m+"m "+String(sec).padStart(2,"0")+"s";
  }
  function updateRecover(){
    var rec=$("mem-recover");
    if(!rec||rec.style.display==="none")return;
    var rem;
    if(recoverEndAt){ rem=Math.max(0,Math.round((recoverEndAt-Date.now())/1000)); }
    else{ rem=(gateState&&gateState.remaining_seconds)||0; }
    rec.textContent=" · re-enables in "+fmtCountdown(rem);
    var cdTime=$("mem-countdown-time");
    if(cdTime){ cdTime.textContent=fmtCountdown(rem); }
    if(rem<=0){ refreshGate(); }
  }
  function refreshGate(){
    fetchJson("/house/memory/status").then(function(j){
      if(j&&j.memory){
        gateState=j;
        setMemory(j.memory);
      }
    });
  }

  // ---- memory actions (disable / purge / enable) via the confirmation modal ----
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
  function openPurgeModal(){
    pendingAction="purge";
    openModal("Purge the memory? (not recommended)",
      "Purging permanently erases the store: dedup savings, scars, refined trust and the journal are all gone. The house will have no recall of any counterparty.",
      "This is permanent and irreversible — the store is erased. There is no countdown and no way back. If you want memory off but recoverable, disable it instead.",
      "I understand — purge","danger");
  }
  $("mem-disable").addEventListener("click",openDisableModal);
  $("mem-purge").addEventListener("click",openPurgeModal);
  $("header-gate").addEventListener("click",function(){
    if(S.memory==="live"){ openDisableModal(); }
    else { enableMemory(); }
  });
  $("mem-restore").addEventListener("click",enableMemory);
  function enableMemory(){
    fetch("/house/memory/enable",{method:"POST",headers:{"Content-Type":"application/json"}})
      .then(function(r){return r.json();})
      .then(function(j){
        if(j.ok){
          toast("memory back on — everything remembered returns","ok");
          gateState=j; setMemory("live"); refreshAll();
        }else if(j.reason){ toast(j.reason,"err"); }
      }).catch(function(){ toast("re-enable failed","err"); });
  }
  $("modal-cancel").addEventListener("click",function(){$("modal-bg").classList.remove("show");});
  $("modal-bg").addEventListener("click",function(e){if(e.target===this){this.classList.remove("show");}});
  $("modal-confirm").addEventListener("click",function(){
    var act=pendingAction; pendingAction=null;
    var url = act==="disable" ? "/house/memory/disable" : "/house/memory/purge";
    var working = act==="disable" ? "disabling memory…" : "purging memory…";
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
          gateState=j; setMemory(j.memory); refreshAll();
          refreshGate();
        }else{
          $("modal-bg").classList.remove("show");
          toast(j.reason,"err");
        }
      }).catch(function(){ toast("memory action failed","err"); });
  });

  // ---------- copy ----------
  function copyText(text){
    if(navigator.clipboard&&window.isSecureContext){
      navigator.clipboard.writeText(text).then(function(){toast("copied","ok");},function(){legacyCopy(text);});
    } else { legacyCopy(text); }
  }
  function legacyCopy(text){
    var ta=document.createElement("textarea");ta.value=text;ta.style.position="fixed";ta.style.opacity="0";
    document.body.appendChild(ta);ta.select();
    try{document.execCommand("copy");toast("copied","ok");}catch(e){toast("select the command manually","err");}
    document.body.removeChild(ta);
  }

  // ---------- mobile pane switch ----------
  function mobPane(which){
    var l=$("pane-left"), r=$("pane-right");
    var b0=$("mob-configure"), b1=$("mob-console");
    var hint=$("done-hint");
    if(which==="left"){
      l.classList.remove("mobile-hidden"); r.classList.add("mobile-hidden");
      b0.classList.add("on"); b1.classList.remove("on"); hint.style.display="none";
    } else {
      r.classList.remove("mobile-hidden"); l.classList.add("mobile-hidden");
      b1.classList.add("on"); b0.classList.remove("on");
      hint.textContent="① configure is set — you are on the console. Tap ① to change the subject or function.";
      hint.style.display="block";
    }
    window.scrollTo({top:0,behavior:"smooth"});
  }
  $("mob-configure").addEventListener("click",function(){mobPane("left");});
  $("mob-console").addEventListener("click",function(){mobPane("right");});

  // ---------- seg: removed — workbench + journals always visible ----------

  $("add-wallet").addEventListener("click",function(){
    // switch the console to the wallet path for the current function (or connect)
    if(S.fn){ S.path="wallet"; renderConsole(); }
    else if(window.ethereum){ connectWallet(); }
    else { toast("pick a function first, or install a wallet","err"); }
  });

  // ---------- dock toggles ----------
  var dbs=document.querySelectorAll(".dock-bar");
  for(var db=0;db<dbs.length;db++){
    dbs[db].addEventListener("click",function(){ this.classList.toggle("on"); });
  }

  // ---------- tooltips ----------
  var tipEl=document.createElement("div");tipEl.className="tip-float";document.body.appendChild(tipEl);
  var tipCur=null;
  function showTip(el){
    if(!el||!el.getAttribute("data-tip")){hideTip();return;}
    if(tipCur===el){return;}
    hideTip();tipCur=el;tipEl.textContent=el.getAttribute("data-tip");
    var r=el.getBoundingClientRect();
    tipEl.style.visibility="hidden";tipEl.classList.add("show");
    var tw=tipEl.offsetWidth;
    var left=Math.max(tw/2+8,Math.min(window.innerWidth-tw/2-8,r.left+r.width/2));
    var below=r.top<70;
    tipEl.classList.toggle("below",below);
    tipEl.style.left=left+"px";tipEl.style.top=(below?r.bottom+10:r.top-10)+"px";
    tipEl.style.visibility="";
  }
  function hideTip(){tipCur=null;tipEl.classList.remove("show");}
  var tipHosts=document.querySelectorAll("[data-tip]");
  for(var hq=0;hq<tipHosts.length;hq++){
    (function(el){
      var q=document.createElement("span");q.className="qmark";q.setAttribute("role","button");q.setAttribute("tabindex","0");q.setAttribute("aria-label","More information");q.textContent="?";
      el.appendChild(q);
      q.addEventListener("mouseenter",function(){showTip(el);});
      q.addEventListener("mouseleave",hideTip);
      q.addEventListener("focus",function(){showTip(el);});
      q.addEventListener("blur",hideTip);
      q.addEventListener("click",function(e){e.preventDefault();e.stopPropagation();if(tipCur===el){hideTip();}else{showTip(el);}});
      q.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();e.stopPropagation();if(tipCur===el){hideTip();}else{showTip(el);}}});
    })(tipHosts[hq]);
  }
  document.addEventListener("click",function(e){if(!e.target.closest||!e.target.closest(".qmark")){hideTip();}});
  document.addEventListener("touchstart",function(e){if(!e.target.closest||!e.target.closest(".qmark")){hideTip();}},{passive:true});
  window.addEventListener("scroll",hideTip,{passive:true});
  window.addEventListener("resize",hideTip);

  // ---------- reveal ----------
  if("IntersectionObserver" in window){
    var io=new IntersectionObserver(function(entries){
      for(var i=0;i<entries.length;i++){if(entries[i].isIntersecting){entries[i].target.classList.add("in");io.unobserve(entries[i].target);}}
    },{threshold:.12});
    var reveals=document.querySelectorAll(".reveal");
    for(var r=0;r<reveals.length;r++){io.observe(reveals[r]);}
  }else{
    var rr=document.querySelectorAll(".reveal");
    for(var x=0;x<rr.length;x++){rr[x].classList.add("in");}
  }
  setTimeout(function(){
    var late=document.querySelectorAll(".reveal:not(.in)");
    for(var l=0;l<late.length;l++){late[l].classList.add("in");}
  },3500);

  // ---------- init ----------
  // read ?fn= to hand state from the landing
  var params=new URLSearchParams(window.location.search);
  var wantFn=params.get("fn");
  if(wantFn&&window.TRYIT&&window.TRYIT[wantFn]){ S.fn=wantFn; }
  renderFns();
  refreshAll();
  // if a function was requested but no subject, and one exists later, auto-select the first
  if(S.fn){ renderConsole(); }
  setInterval(refreshAll,6000);
})();
</script>
</body>
</html>
"""


def render_gallery(*, memory_live: bool, commit: str,
                   base_price: float, ts: str,
                   public_url: str = "") -> str:
    """Render the gallery workbench. Live aggregates come from the client
    polling the free /house/* endpoints; the console quotes live from the
    paid endpoints. Deletion -> memory status DISABLED + empty ledgers."""
    return (_GALLERY_HTML
            .replace("__SETTLE_TXS_DATA__", json.dumps(REAL_SETTLEMENT_TXS))
            .replace("__JOURNAL_DATA__", json.dumps(REAL_JOURNAL))
            .replace("__TRYIT_CSS__", TRYIT_CSS)
            .replace("__TRYIT_HTML__", TRYIT_HTML)
            .replace("__TRYIT_JS__", TRYIT_JS)
            .replace("__PUBLIC_URL__", json.dumps(public_url))
            .replace("__DOT__", "" if memory_live else "off")
            .replace("__MEMSTATUS__", "LIVE" if memory_live else "DISABLED")
            .replace("__COMMIT__", html.escape(commit))
            .replace("$base_price", f"{float(base_price):.2f}")
            .replace("__TS__", html.escape(ts)))
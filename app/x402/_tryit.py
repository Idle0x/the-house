"""Shared try-it modal: CSS + HTML + JS, embedded by both the landing page
and the gallery so every feature can be tried from either surface.

The JS is a self-contained IIFE (own $/esc/toast helpers, dynamic toast
element) and reads the public origin from ``window.__TRYIT__ =
{public_url: ...}`` — each page injects that before the script. The live
402 quote is always fetched from the real endpoint at open time — never
hardcoded.
"""
from __future__ import annotations

TRYIT_CSS = r"""  /* ---------- try-it modal ---------- */
  .tryit-bg{position:fixed;inset:0;background:rgba(0,0,0,.82);backdrop-filter:blur(8px);
    z-index:200;display:none;align-items:center;justify-content:center;padding:20px;overflow-y:auto;}
  .tryit-bg.show{display:flex;}
  .tryit{background:var(--surface);border:1px solid rgba(143,199,255,.22);border-radius:12px;
    background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 30%);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.03),0 24px 80px rgba(0,0,0,.55);max-width:700px;width:100%;padding:28px;
    animation:panelIn .25s ease;max-height:90vh;overflow-y:auto;position:relative;}
  .tryit .t-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:4px;}
  .tryit .t-title{font-size:24px;font-weight:700;letter-spacing:-.015em;}
  .tryit .t-room{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:10px;
    color:var(--glacier);letter-spacing:.12em;text-transform:uppercase;margin-top:10px;
    background:rgba(143,199,255,.08);border:1px solid rgba(143,199,255,.25);padding:4px 11px;border-radius:20px;}
  .tryit .t-room::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--green);}
  .tryit .t-close{background:none;border:none;color:#d97b6f;font-size:26px;cursor:pointer;line-height:1;padding:4px 6px;
    transition:color .15s ease,transform .15s ease;}
  .tryit .t-close:hover{color:#ff8a7a;transform:scale(1.12);}
  .tryit .t-desc{color:var(--dim);font-size:14px;line-height:1.65;margin:14px 0 20px;}
  .tryit .t-choose-label{font-family:Inter,Manrope,"Space Grotesk",system-ui,sans-serif;
    font-size:12px;font-weight:600;color:var(--muted);letter-spacing:.06em;
    text-transform:uppercase;margin-bottom:12px;}
  .tryit .t-path-ico{display:inline-flex;align-items:center;justify-content:center;
    width:30px;height:30px;border-radius:9px;margin-bottom:10px;
    background:rgba(143,199,255,.08);border:1px solid rgba(143,199,255,.25);color:var(--glacier);}
  .tryit .t-path-ico svg{width:15px;height:15px;}
  .tryit .t-price{display:flex;align-items:center;justify-content:space-between;gap:12px;font-family:var(--mono);
    font-size:13px;color:var(--text);border:1px solid rgba(143,199,255,.35);background:rgba(143,199,255,.06);
    padding:14px 16px;border-radius:12px;margin-bottom:20px;flex-wrap:wrap;}
  .tryit .t-price .amt{font-size:20px;font-weight:700;color:var(--glacier);}
  .tryit .t-price .amt small{font-size:12px;color:var(--muted);font-weight:500;margin-left:6px;}
  .tryit .t-price .lbl{color:var(--muted);font-size:11.5px;}
  .tryit .t-price .live{display:inline-flex;align-items:center;gap:6px;color:var(--green);font-size:10.5px;letter-spacing:.08em;}
  .tryit .t-price .live::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--green);animation:breath 2s ease-in-out infinite;}
  .tryit .t-back{background:none;border:none;color:var(--muted);font-family:var(--mono);font-size:12px;
    cursor:pointer;padding:4px 0;margin-bottom:14px;}
  .tryit .t-back:hover{color:var(--glacier);}
  .tryit .t-paths{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;}
  @media(max-width:640px){.tryit .t-paths{grid-template-columns:1fr;}}
  .tryit .t-path{border:1px solid var(--border);border-radius:12px;padding:18px;cursor:pointer;
    background:var(--surface2);background-image:linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0) 32%);
    transition:all .18s ease;position:relative;box-shadow:inset 0 1px 0 rgba(255,255,255,.03);}
  .tryit .t-path:hover{border-color:rgba(143,199,255,.45);transform:translateY(-2px);}
  .tryit .t-path:active{transform:translateY(0);}
  .tryit .t-path.selected{border-color:var(--glacier);background:rgba(143,199,255,.06);}
  .tryit .t-path .rec{position:absolute;top:-9px;right:12px;font-family:var(--mono);font-size:10px;
    letter-spacing:.08em;color:#0a0a0a;background:var(--glacier);padding:2px 8px;border-radius:10px;font-weight:700;}
  .tryit .t-path h4{font-size:15px;font-weight:700;margin-bottom:6px;}
  .tryit .t-path p{color:var(--muted);font-size:12.5px;line-height:1.55;margin:0;}
  .tryit .t-body{margin-top:4px;}
  .tryit .t-step{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:11px;color:var(--muted);
    letter-spacing:.1em;margin:20px 0 10px;text-transform:uppercase;}
  .tryit .t-step .n{display:inline-flex;width:18px;height:18px;align-items:center;justify-content:center;
    border-radius:50%;background:rgba(143,199,255,.12);color:var(--glacier);font-size:10px;font-weight:700;flex:0 0 auto;}
  .tryit .t-block{background:#0c0c0c;border:1px solid var(--border);border-radius:12px;
    font-family:var(--mono);font-size:12px;line-height:1.65;color:var(--dim);white-space:pre-wrap;
    word-break:break-word;position:relative;margin-bottom:10px;overflow:hidden;}
  .tryit .t-block.term .term-head{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);
    background:#111;font-size:10px;letter-spacing:.08em;color:var(--muted);text-transform:uppercase;}
  .tryit .t-block.term .term-head .dots{display:flex;gap:5px;}
  .tryit .t-block.term .term-head .dots i{width:8px;height:8px;border-radius:50%;display:block;}
  .tryit .t-block.term .term-head .dots i:first-child{background:#d97b6f;}
  .tryit .t-block.term .term-head .dots i:nth-child(2){background:#e5c07b;}
  .tryit .t-block.term .term-head .dots i:nth-child(3){background:#8fd9ac;}
  .tryit .t-block.term .term-head .copy{margin-left:auto;background:var(--surface2);border:1px solid var(--border);
    color:var(--muted);font-size:10px;font-family:var(--mono);padding:3px 10px;border-radius:6px;cursor:pointer;text-transform:none;}
  .tryit .t-block.term .term-head .copy:hover{color:var(--glacier);border-color:var(--glacier);}
  .tryit .t-block code{display:block;padding:14px 16px;white-space:pre-wrap;word-break:break-word;color:#cfd8e3;}
  .tryit .t-block .prompt{color:var(--green);font-weight:700;}
  .tryit .t-block.clickable{cursor:pointer;}
  .tryit .t-block.clickable:hover{border-color:rgba(143,199,255,.5);}
  .tryit .t-block.clickable:hover::after{content:"click to copy";position:absolute;bottom:8px;right:12px;font-size:9px;
    letter-spacing:.08em;color:var(--glacier);text-transform:uppercase;}
  .tryit .t-after{background:rgba(39,174,96,.05);border:1px solid rgba(39,174,96,.25);border-radius:12px;
    padding:16px;margin-top:16px;}
  .tryit .t-after b{color:var(--green);font-size:11px;font-family:var(--mono);letter-spacing:.1em;display:block;margin-bottom:6px;text-transform:uppercase;}
  .tryit .t-after p{color:var(--dim);font-size:13px;line-height:1.6;margin:0;}
  .tryit .t-actions{display:flex;gap:12px;justify-content:flex-end;margin-top:22px;flex-wrap:wrap;}
  .tryit .t-fields{margin-bottom:8px;}
  .tryit .t-fields .ti-field{margin-bottom:14px;}
  .tryit .t-fields label{display:block;font-family:var(--mono);font-size:11px;color:var(--muted);
    letter-spacing:.08em;margin-bottom:7px;}
  .tryit .t-fields .ti-wrap{position:relative;display:flex;align-items:center;}
  .tryit .t-fields .ti-caret{position:absolute;left:14px;color:var(--glacier);font-family:var(--mono);
    font-size:14px;pointer-events:none;animation:tiBlink 1.1s steps(2) infinite;}
  .tryit .t-fields .ti-field[data-empty="false"] .ti-caret{display:none;}
  .tryit .t-fields input{width:100%;background:#0c0c0c;border:1px solid var(--border);border-radius:10px;
    color:var(--text);font-family:var(--mono);font-size:13px;padding:12px 14px 12px 30px;outline:none;
    transition:border-color .18s ease,box-shadow .18s ease;}
  .tryit .t-fields input:focus{border-color:var(--glacier);box-shadow:0 0 0 3px rgba(143,199,255,.12);}
  .tryit .t-sugg{display:flex;gap:8px;flex-wrap:wrap;margin:-4px 0 14px;}
  .tryit .t-sugg .chip{background:var(--surface2);border:1px solid var(--border);color:var(--muted);
    font-family:var(--mono);font-size:11px;padding:6px 12px;border-radius:20px;cursor:pointer;transition:all .15s ease;}
  .tryit .t-sugg .chip:hover{color:var(--glacier);border-color:var(--glacier);}
  .tryit .t-sugg .chip:active{transform:scale(.97);}
  .tryit .t-tabs{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;}
  .tryit .t-tab{background:var(--surface2);border:1px solid var(--border);color:var(--muted);
    font-family:var(--mono);font-size:12px;padding:8px 14px;border-radius:20px;cursor:pointer;transition:all .15s ease;}
  .tryit .t-tab:hover{color:var(--text);}
  .tryit .t-tab.active{background:rgba(143,199,255,.1);border-color:var(--glacier);color:var(--glacier);}
  .tryit .t-loading{color:var(--muted);font-family:var(--mono);font-size:13px;padding:24px 0;text-align:center;}
  .tryit .t-loading .sp{display:inline-block;width:12px;height:12px;border:2px solid var(--glacier);
    border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;margin-right:8px;vertical-align:middle;}
  .tryit .t-error{text-align:center;padding:26px 0;color:var(--dim);font-size:13px;line-height:1.6;}
  .tryit .t-error .msg{color:#e0a49c;margin-bottom:14px;font-family:var(--mono);}
  .tryit .t-error .retry{background:var(--surface2);border:1px solid var(--border);color:var(--glacier);
    font-family:var(--mono);font-size:12px;padding:8px 18px;border-radius:8px;cursor:pointer;}
  .tryit .t-error .retry:hover{border-color:var(--glacier);}
  @keyframes spin{to{transform:rotate(360deg);}}
  @keyframes tiBlink{50%{opacity:0;}}
  @keyframes breath{0%,100%{opacity:.5}50%{opacity:1}}

  /* ---------- overflow safety + mobile ---------- */
  .tryit{overflow-wrap:anywhere;min-width:0;}
  .tryit .t-title{overflow-wrap:anywhere;max-width:100%;}
  .tryit .t-desc{overflow-wrap:anywhere;}
  .tryit .t-price .lbl{overflow-wrap:anywhere;}
  .tryit .t-path{min-width:0;}
  .tryit .t-path h4,.tryit .t-path p{overflow-wrap:anywhere;}
  .tryit .t-block{overflow-wrap:anywhere;max-width:100%;}
  .tryit .t-block code{overflow-wrap:anywhere;white-space:pre-wrap;word-break:break-word;}
  .tryit .t-fields input{min-width:0;}
  @media(max-width:520px){
    .tryit-bg{padding:10px;}
    .tryit{padding:20px 16px;border-radius:12px;max-height:92vh;}
    .tryit .t-title{font-size:19px;}
    .tryit .t-desc{font-size:13px;}
    .tryit .t-price{padding:10px 12px;gap:8px;}
    .tryit .t-price .amt{font-size:16px;}
    .tryit .t-path{padding:14px;}
    .tryit .t-actions{justify-content:stretch;}
    .tryit .t-actions .btn{flex:1 1 auto;justify-content:center;}
  }

  /* ---------- shared toast ---------- */
  .toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(120%);
    background:var(--surface2,#161616);border:1px solid var(--border,#1E1E1E);color:#cfcfcf;
    font-family:var(--mono);font-size:12px;padding:10px 16px;border-radius:10px;z-index:300;
    transition:transform .3s cubic-bezier(.16,1,.3,1),opacity .3s ease;opacity:0;pointer-events:none;}
  .toast.show{transform:translateX(-50%) translateY(0);opacity:1;}
  .toast.err{border-color:var(--red,#C0392B);color:#e0a49c;}
  .toast.ok{border-color:var(--green,#27AE60);color:#8fd9ac;}
"""

TRYIT_HTML = r"""<!-- try-it modal -->
<div class="tryit-bg" id="tryit-bg">
  <div class="tryit" id="tryit" role="dialog" aria-modal="true">
    <div class="t-head">
      <div>
        <div class="t-title" id="ti-title"></div>
        <div class="t-room" id="ti-room"></div>
      </div>
      <button class="t-close" id="ti-close" aria-label="close">×</button>
    </div>
    <div class="t-desc" id="ti-desc"></div>

    <!-- STEP 1: choose how to try it -->
    <div class="t-choose" id="ti-choose">
      <div class="t-choose-label">how do you want to try it?</div>
      <div class="t-paths">
        <div class="t-path" data-path="agent" id="ti-path-agent" data-tip="The real use case: your agent reads the 402 quote, pays from its own wallet, and retries. The house serves and remembers it.">
          <span class="rec">recommended</span>
          <span class="t-path-ico"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1.5l1.7 3.8 3.8 1.7-3.8 1.7L8 12.5l-1.7-3.8-3.8-1.7 3.8-1.7z"/><path d="M12.5 11.5l.8 1.7 1.7.8-1.7.8-.8 1.7-.8-1.7-1.7-.8 1.7-.8z"/></svg></span>
          <h4>Use your AI agent</h4>
          <p>Point your agent at the endpoint. It pays the x402 quote from its own wallet and gets served — the real use case.</p>
        </div>
        <div class="t-path" data-path="manual" id="ti-path-manual" data-tip="No agent: you get the live quote, the exact payTo + amount, send USDC from your wallet, then re-request with the payment proof.">
          <span class="t-path-ico"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5l3 3-3 3"/><line x1="8.5" y1="12.5" x2="12" y2="12.5"/></svg></span>
          <h4>Do it manually</h4>
          <p>Pay from your own wallet. You'll get a live quote, a tailored URL and the exact payment details.</p>
        </div>
      </div>
    </div>

    <!-- STEP 2: the flow (rendered after choosing) -->
    <div class="t-body" id="ti-body" style="display:none"></div>
  </div>
</div>"""

TRYIT_JS = r"""
(function(){
  function $(id){return document.getElementById(id);}
  function esc(s){return (s==null?"":String(s)).replace(/[&<>"]/g,function(c){
    return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]);});}
  var toastTimer=null;
  function toast(msg,type){
    var t=document.getElementById("tryit-toast");
    if(!t){t=document.createElement("div");t.id="tryit-toast";document.body.appendChild(t);}
    t.textContent=msg;
    t.className="toast show"+(type?" "+type:"");
    if(toastTimer){clearTimeout(toastTimer);}
    toastTimer=setTimeout(function(){t.className="toast";},4200);
  }
// ---- try-it modal ----
// Feature registry: every paid route the house sells, with plain-language
// explanation, request shape, and what happens after payment. The price is
// ALWAYS fetched live from the real 402 quote — never hardcoded.
// The command base URL is the PUBLIC production origin (Railway domain)
// injected by the server as S.public_url — NEVER the internal host/IP.
var BASE = (window.__TRYIT__ && window.__TRYIT__.public_url) ? window.__TRYIT__.public_url : window.location.origin;
var TRYIT = {
  "intel_quote": {
    room: "1 · trust desk", title: "Ask the house",
    desc: "Pay the house to answer a question from its memory — what it has experienced. A repeat question from the same wallet is served from memory at net $0 (dedup).",
    method: "GET", path: "/intel/quote",
    fields: [{k:"q", label:"your question", ph:"ask the house anything it remembers…",
      suggest:["what does the house remember about 0x8a8a8d2a443fd7f0a5321b89d28f893f01b4a10a?",
               "is 0x436f324eff0b32a405c5b9102e1a6ef85451cec1 a trusted provider?",
               "who has paid the house, and how much?"]}],
    body: function(f){return "?q="+encodeURIComponent(f.q||"");},
    after: "The house records your wallet and what it served. If you ask again, the same question is answered from memory — you are not charged a second time.",
    agent: function(f){return "curl -sS -X GET '"+BASE+"/intel/quote?q="+encodeURIComponent(f.q||"")+"'";}
  },
  "prepay": {
    room: "1 · trust desk", title: "Fund prepay credit",
    desc: "Add USDC credit to your wallet's account. A risky wallet needs prepay credit before the house will serve it — this is how it proves it can pay.",
    method: "POST", path: "/prepay/topup",
    fields: [{k:"amount", label:"amount (USDC)", ph:"0.05"}],
    body: function(f){return JSON.stringify({amount:parseFloat(f.amount)||0.05});},
    after: "The credit lands on your wallet's caller row. When the house later serves you, it spends against this credit instead of requiring a fresh payment.",
    agent: function(f){return "curl -sS -X POST '"+BASE+"/prepay/topup' -H 'Content-Type: application/json' -d '"+JSON.stringify({amount:parseFloat(f.amount)||0.05})+"'";}
  },
  "bond_quote": {
    room: "2 · underwriting", title: "Underwrite a provider",
    desc: "Ask the house to issue a bond on a provider. If the provider fails, the house pays out of its own wallet. The premium is priced from what the house remembers about that provider.",
    method: "POST", path: "/bond/quote",
    fields: [{k:"provider", label:"provider address", ph:"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"}],
    body: function(f){return JSON.stringify({provider:f.provider||"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"});},
    after: "A proven provider gets the discounted premium (rebated back as a real tx). A risky provider is refused with a 403 — you are not charged.",
    agent: function(f){return "curl -sS -X POST '"+BASE+"/bond/quote' -H 'Content-Type: application/json' -d '"+JSON.stringify({provider:f.provider||"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"})+"'";}
  },
  "watch_screen": {
    room: "4 · watchtower", title: "Screen a wallet",
    desc: "Pay the house to screen a wallet — CLEAR, HOLD or ABORT, with the evidence. The screen is a deterministic read of what the house remembers, not a guess.",
    method: "POST", path: "/watch/screen",
    fields: [{k:"wallet", label:"wallet address", ph:"0x…"}],
    body: function(f){return JSON.stringify({wallet:f.wallet||"0x8a8a8d2a443fd7f0a5321b89d28f893f01b4a10a"});},
    after: "The house remembers the wallet you screened and any funding relationship you declared. A wallet it flags as risky is refused before money moves.",
    agent: function(f){return "curl -sS -X POST '"+BASE+"/watch/screen' -H 'Content-Type: application/json' -d '"+JSON.stringify({wallet:f.wallet||"0x8a8a8d2a443fd7f0a5321b89d28f893f01b4a10a"})+"'";}
  },
  "scout_report": {
    room: "3 · front office", title: "Provider report",
    desc: "Pay the house for its record on a provider — jobs done, quality, on-time, defaults, bond claims — and the terms it would offer.",
    method: "POST", path: "/scout/report",
    fields: [{k:"provider", label:"provider address", ph:"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"}],
    body: function(f){return JSON.stringify({provider:f.provider||"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"});},
    after: "The house journals that you asked. The report you receive is priced by the provider's remembered quality — a costly provider quotes a premium.",
    agent: function(f){return "curl -sS -X POST '"+BASE+"/scout/report' -H 'Content-Type: application/json' -d '"+JSON.stringify({provider:f.provider||"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"})+"'";}
  },
  "scout_hire": {
    room: "3 · front office", title: "Hire decision",
    desc: "Pay the house for its hiring ruling on a provider — proven gets preferred terms, unknown gets standard, risky is refused.",
    method: "POST", path: "/scout/hire",
    fields: [{k:"provider", label:"provider address", ph:"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"}],
    body: function(f){return JSON.stringify({provider:f.provider||"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"});},
    after: "The ruling is hiring memory — it is journaled. A risky provider is refused with a 403 before any work, and you are not charged.",
    agent: function(f){return "curl -sS -X POST '"+BASE+"/scout/hire' -H 'Content-Type: application/json' -d '"+JSON.stringify({provider:f.provider||"0x436f324eff0b32a405c5b9102e1a6ef85451cec1"})+"'";}
  },
  "intel_entity": {
    room: "5 · dossier", title: "Entity dossier",
    desc: "Pay the house for its complete remembered picture of one wallet — across every room, every field timestamped. The house only sells what it has.",
    method: "GET", path: "/intel/entity/",
    fields: [{k:"entity", label:"entity address", ph:"0x8a8a8d2a443fd7f0a5321b89d28f893f01b4a10a"}],
    body: function(f){return encodeURIComponent(f.entity||"0x8a8a8d2a443fd7f0a5321b89d28f893f01b4a10a");},
    after: "A wallet the house has never seen returns 404 — the house never fabricates a profile it never remembered. A known wallet returns its full dossier.",
    agent: function(f){return "curl -sS -X GET '"+BASE+"/intel/entity/"+encodeURIComponent(f.entity||"0x8a8a8d2a443fd7f0a5321b89d28f893f01b4a10a")+"'";}
  }
};

var tiState = {feature:null, path:null, fields:{}, quote:null, quoteAt:0, countdown:null};
function openTryit(key){
  var f = TRYIT[key];
  if(!f) return;
  tiState.feature = f; tiState.path = null; tiState.fields = {}; tiState.quote = null; tiState.quoteAt = 0;
  if(tiState.countdown){ clearInterval(tiState.countdown); tiState.countdown = null; }
  $("ti-title").textContent = f.title;
  $("ti-room").textContent = f.room;
  $("ti-desc").textContent = f.desc;
  // reset to step 1 (choose) — nothing else shown until a path is picked
  $("ti-choose").style.display = "block";
  $("ti-body").style.display = "none";
  $("ti-body").innerHTML = "";
  $("ti-path-agent").classList.remove("selected");
  $("ti-path-manual").classList.remove("selected");
  $("tryit-bg").classList.add("show");
}
function closeTryit(){
  $("tryit-bg").classList.remove("show");
  if(tiState.countdown){ clearInterval(tiState.countdown); tiState.countdown = null; }
  tiState.feature = null;
}
function choosePath(p){
  tiState.path = p;
  $("ti-path-agent").classList.toggle("selected", p==="agent");
  $("ti-path-manual").classList.toggle("selected", p==="manual");
  $("ti-choose").style.display = "none";
  $("ti-body").style.display = "block";
  $("ti-body").innerHTML = '<div class="t-loading"><span class="sp"></span>getting a live quote…</div>';
  fetchQuote(tiState.feature);
}
function fetchQuote(f){
  var opts = {method:f.method, headers:{"Content-Type":"application/json"}};
  if(f.method==="POST"){ opts.body = f.body(tiState.fields); }
  var url = (BASE ? BASE : window.location.origin) + f.path + (f.method==="GET" ? f.body(tiState.fields) : "");
  fetch(url, opts).then(function(res){
    var pr = res.headers.get("payment-required");
    var quote = null;
    if(pr){ try{ quote = JSON.parse(atob(pr)); }catch(e){} }
    tiState.quote = quote;
    tiState.quoteAt = Date.now();
    renderTryitBody();
  }).catch(function(){
    $("ti-body").innerHTML = '<div class="t-error"><div class="msg">the house did not answer — the quote request failed.</div>'
      + '<button class="retry" id="ti-retry">try again</button></div>';
    var rt=$("ti-retry");
    if(rt){ rt.addEventListener("click", function(){ choosePath(tiState.path); }); }
  });
}
// a copyable terminal block: a title bar with a $ prompt, and the whole block
// click-to-copy (the raw command is kept on data-copy so the prompt is not copied)
function termBlock(cmd){
  return '<div class="t-block term clickable" data-copy="'+esc(cmd)+'">'
    + '<div class="term-head"><span class="dots"><i></i><i></i><i></i></span>your terminal'
    + '<span class="copy">copy</span></div>'
    + '<code><span class="prompt">$</span> '+esc(cmd)+'</code></div>';
}
function renderTryitBody(){
  var f = tiState.feature, q = tiState.quote;
  var h = '<button class="t-back" id="ti-back">← choose another way</button>';
  // price bar + live quote
  if(q && q.accepts && q.accepts.length){
    var a = q.accepts[0];
    var amt = (parseInt(a.amount,10)/1000000);
    var assetName = (a.extra&&a.extra.name)||"USDC";
    h += '<div class="t-price">'
      + '<span class="amt">'+amt.toFixed(2)+' <small>'+assetName+'</small></span>'
      + '<span class="lbl">on '+a.network+' · pay '+a.payTo.slice(0,8)+'…'+a.payTo.slice(-6)+'</span>'
      + '<span class="live">live quote</span>'
      + '</div>';
  }
  // fields (custom parameters) — blinking caret + suggested chips
  if(f.fields && f.fields.length){
    h += '<div class="t-fields">';
    for(var i=0;i<f.fields.length;i++){
      var fd=f.fields[i];
      var cur = tiState.fields[fd.k] || "";
      h += '<div class="ti-field" data-empty="'+(cur?"false":"true")+'">'
        + '<label>'+fd.label+'</label>'
        + '<div class="ti-wrap"><span class="ti-caret">▍</span>'
        + '<input id="ti-f-'+i+'" placeholder="'+fd.ph+'" value="'+esc(cur)+'" data-k="'+fd.k+'"/></div>';
      if(fd.suggest && fd.suggest.length){
        h += '<div class="t-sugg">';
        for(var s=0;s<fd.suggest.length;s++){
          h += '<button type="button" class="chip" data-k="'+fd.k+'" data-v="'+esc(fd.suggest[s])+'">'+esc(fd.suggest[s])+'</button>';
        }
        h += '</div>';
      }
      h += '</div>';
    }
    h += '</div>';
  }
  // path body
  if(tiState.path==="agent"){
    h += '<div class="t-step"><span class="n">1</span>point your agent at the endpoint</div>';
    h += termBlock(f.agent(tiState.fields));
    h += '<div class="t-step"><span class="n">2</span>your agent pays the 402</div>';
    h += '<div class="t-block">The house returns a 402 with a payment-required header. Your agent signs a transaction paying the quoted amount to the house wallet, then retries the request with the payment proof. The x402 client handles this automatically.</div>';
    h += '<div class="t-step"><span class="n">3</span>served, and remembered</div>';
    h += '<div class="t-after"><b>after payment</b><p>'+esc(f.after)+'</p></div>';
  } else {
    h += '<div class="t-step"><span class="n">1</span>request a quote</div>';
    h += termBlock(f.agent(tiState.fields));
    h += '<div class="t-step"><span class="n">2</span>pay from your wallet</div>';
    if(q && q.accepts && q.accepts.length){
      var a=q.accepts[0];
      var amt=(parseInt(a.amount,10)/1000000);
      h += '<div class="t-block">Send <b>'+amt.toFixed(2)+' '+((a.extra&&a.extra.name)||"USDC")+'</b> on <b>'+a.network+'</b> to\n'
        + '  payTo: '+a.payTo+'\n'
        + '  asset: '+a.asset+'\n'
        + '  within '+a.maxTimeoutSeconds+'s</div>';
    }
    h += '<div class="t-step"><span class="n">3</span>re-request with your payment proof</div>';
    h += '<div class="t-block">After paying, re-run the request with the settlement proof in the payment response header. The house verifies it and serves you.</div>';
    h += '<div class="t-step"><span class="n">4</span>served, and remembered</div>';
    h += '<div class="t-after"><b>after payment</b><p>'+esc(f.after)+'</p></div>';
  }
  h += '<div class="t-actions"><button class="btn ghost" id="ti-refresh">refresh quote</button></div>';
  $("ti-body").innerHTML = h;
  bindTryitEvents(f);
}
function bindTryitEvents(f){
  var back = $("ti-back");
  if(back){ back.addEventListener("click", function(){
    $("ti-choose").style.display = "block";
    $("ti-body").style.display = "none";
  }); }
  // copyable terminal blocks — whole block click-to-copy (raw command, no prompt)
  var blocks = document.querySelectorAll(".t-block[data-copy]");
  for(var i=0;i<blocks.length;i++){
    blocks[i].addEventListener("click", function(){
      copyText(this.getAttribute("data-copy"));
    });
  }
  // field inputs — live-update the command + caret state
  var ins = document.querySelectorAll(".t-fields input");
  for(var j=0;j<ins.length;j++){
    ins[j].addEventListener("input", function(){
      tiState.fields[this.getAttribute("data-k")] = this.value;
      var field=this.closest(".ti-field");
      if(field){ field.setAttribute("data-empty", this.value?"false":"true"); }
      renderTryitBody();
    });
  }
  // suggestion chips — fill the field, re-render
  var chips = document.querySelectorAll(".t-sugg .chip");
  for(var c=0;c<chips.length;c++){
    chips[c].addEventListener("click", function(){
      tiState.fields[this.getAttribute("data-k")] = this.getAttribute("data-v");
      renderTryitBody();
    });
  }
  var ref = $("ti-refresh");
  if(ref){ ref.addEventListener("click", function(){ choosePath(tiState.path); }); }
}
function copyText(text){
  // navigator.clipboard needs a secure context (HTTPS); fall back to a
  // hidden textarea + execCommand for HTTP previews.
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(text).then(function(){ toast("copied","ok"); },
      function(){ legacyCopy(text); });
  } else {
    legacyCopy(text);
  }
}
function legacyCopy(text){
  var ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try{ document.execCommand("copy"); toast("copied","ok"); }
  catch(e){ toast("select the command manually","err"); }
  document.body.removeChild(ta);
}

$("ti-close").addEventListener("click", closeTryit);
$("tryit-bg").addEventListener("click", function(e){ if(e.target===this) closeTryit(); });
$("ti-path-agent").addEventListener("click", function(){ choosePath("agent"); });
$("ti-path-manual").addEventListener("click", function(){ choosePath("manual"); });

  // expose so "try it" buttons anywhere can open a feature
  window.__openTryit = openTryit;
  // expose the feature registry so the gallery workbench console can reuse it
  window.TRYIT = TRYIT;
})();
"""

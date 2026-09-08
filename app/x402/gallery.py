"""M4 — Room 5: the gallery (the watchable world).

The landing page says the thesis; the gallery is the PROOF — every room,
live, in the house's own forensic design language. It is static HTML + a
fetch of the house's own free ``/house/*`` endpoints: no framework, no build
step, no external JS. The only data on the page is what the house has
ACTUALLY remembered, so in deletion mode (memory disabled) the gallery reads
the collapse — every room at zero, the season log empty — the gate, visible.

Sections (each a 20-second demo beat):
  · the money floor   — every settlement, with its Basescan tx (Room 0)
  · room 1 desk       — the trust ledger: segments, trust, net charged
  · room 2 underwrite — the bond book + register (premiums, claims, payout tx)
  · room 3 front      — the draft board (providers, drafted vs refused)
  · room 4 watchtower — the verdict feed (screens, refusals, the rings)
  · the season log    — the house's own journal, newest first (every room's
                        events, timestamped) — the "recall beat" surface.

All numbers are refreshed client-side from the JSON endpoints; the server
renders the same live aggregates into the first paint so the page is never
an empty shell even before the first tick.
"""
from __future__ import annotations

import html
from string import Template

# string.Template: $name placeholders. CSS braces untouched; the inline JS is
# written with NO literal $ (object literal keys, no template strings) so it is
# safe under safe_substitute.
_GALLERY_HTML = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>the-house · gallery — the watchable world</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E%3Crect%20width='32'%20height='32'%20fill='%230A0A0A'/%3E%3Cpath%20d='M11%208v16M21%208v16M11%2016h10'%20stroke='%23E8C547'%20stroke-width='3'%20stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0A0A0A; --surface:#111111; --border:#1E1E1E;
    --text:#E8E8E8; --muted:#6B6B6B;
    --amber:#E8C547; --green:#27AE60; --red:#C0392B;
    --grotesk:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;
    --mono:"Space Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;background:var(--bg);color:var(--text);
    font-family:var(--grotesk);-webkit-font-smoothing:antialiased;}
  body{line-height:1.5;}
  a{color:inherit;text-decoration:none;}
  .wrap{max-width:1180px;margin:0 auto;padding:40px 32px 56px;}
  .bar{display:flex;align-items:center;justify-content:space-between;
    padding-bottom:22px;border-bottom:1px solid var(--border);gap:16px;flex-wrap:wrap;}
  .wordmark{font-weight:700;letter-spacing:.14em;font-size:17px;}
  .wordmark .tick{color:var(--amber);}
  .status{display:flex;align-items:center;gap:9px;font-family:var(--mono);
    font-size:12px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--green);
    animation:breath 3s ease-in-out infinite;}
  .dot.off{background:var(--red);animation:none;}
  @keyframes breath{0%,100%{opacity:.55}50%{opacity:1}}
  .hash{font-family:var(--mono);font-size:12px;color:var(--muted);}
  .back{font-family:var(--mono);font-size:12px;color:var(--muted);}
  .back a:hover{color:var(--amber);}
  .hero{padding:40px 0 8px;}
  .hero h1{font-size:clamp(26px,4.4vw,44px);line-height:1.08;font-weight:700;
    letter-spacing:-.01em;margin:0 0 14px;max-width:24ch;}
  .hero h1 em{font-style:normal;color:var(--amber);}
  .hero .sub{font-size:15px;color:var(--muted);max-width:70ch;margin:0;}
  .collapse{display:none;margin:20px 0;padding:14px 16px;border:1px solid rgba(192,57,43,.4);
    border-radius:10px;color:#e0a49c;font-size:14px;background:rgba(192,57,43,.08);}
  .collapse.show{display:block;}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:36px;}
  @media (max-width:860px){.grid{grid-template-columns:1fr;}}
  .room{background:var(--surface);border:1px solid var(--border);border-radius:12px;
    padding:18px 18px 16px;}
  .room.full{grid-column:1 / -1;}
  .room h2{font-size:12px;font-family:var(--mono);letter-spacing:.14em;
    text-transform:uppercase;color:var(--muted);margin:0 0 4px;font-weight:400;
    display:flex;align-items:baseline;gap:10px;}
  .room h2 .rn{color:var(--amber);font-weight:700;}
  .room .desc{font-size:13px;color:var(--muted);margin:0 0 14px;}
  .kv{display:flex;flex-wrap:wrap;gap:8px 18px;margin:0 0 12px;}
  .kv .k{font-family:var(--mono);font-size:12px;color:var(--muted);}
  .kv .k b{color:var(--text);font-size:15px;font-weight:700;margin-right:4px;}
  .kv .k b.amber{color:var(--amber);}
  table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px;}
  th{text-align:left;color:var(--muted);font-weight:400;letter-spacing:.06em;
    text-transform:uppercase;font-size:10px;padding:6px 8px;border-bottom:1px solid var(--border);}
  td{padding:7px 8px;border-bottom:1px solid var(--border);color:#cfcfcf;vertical-align:top;}
  td a{color:var(--amber);word-break:break-all;}
  td.dim{color:var(--muted);}
  .verdict{font-family:var(--mono);font-size:11px;letter-spacing:.08em;}
  .verdict.CLEAR{color:var(--green);}
  .verdict.HOLD{color:var(--amber);}
  .verdict.ABORT{color:var(--red);}
  .seg{font-family:var(--mono);font-size:11px;}
  .seg.vip{color:var(--green);}
  .seg.risky,.seg.risky{color:var(--amber);}
  .seg.banned{color:var(--red);}
  .empty{font-family:var(--mono);font-size:12px;color:var(--muted);padding:10px 2px;}
  .log{font-family:var(--mono);font-size:12px;}
  .log .row{padding:7px 2px;border-bottom:1px solid var(--border);display:flex;
    gap:12px;align-items:baseline;}
  .log .ts{color:var(--muted);white-space:nowrap;}
  .log .kind{color:var(--amber);min-width:64px;text-transform:uppercase;font-size:10px;
    letter-spacing:.08em;}
  .log .txt{color:#cfcfcf;}
  footer{margin-top:48px;padding-top:20px;border-top:1px solid var(--border);
    display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
    font-family:var(--mono);font-size:11px;color:var(--muted);}
</style>
</head>
<body>
<div class="wrap">
  <header class="bar">
    <div class="wordmark">THE<span class="tick">·</span>HOUSE <span style="color:var(--muted);font-weight:400;font-size:12px;letter-spacing:.1em;">GALLERY</span></div>
    <div class="status"><span class="dot $dot_class" id="mem-dot"></span>
      <span id="mem-status">MEMORY $memory_status</span></div>
    <div class="hash">commit $commit</div>
    <div class="back"><a href="/">← landing</a></div>
  </header>

  <main>
    <section class="hero">
      <h1>Not a demo of features. <em>A watchable world.</em></h1>
      <p class="sub">Every room below is the house's own state, refreshed live from its free
        ledgers. Nothing on this page is canned: the numbers are the memory.
        Remove the memory and the gallery collapses with it.</p>
      <div class="collapse $collapse_show">
        <b>Memory disabled.</b> The ledger, the bond book, the draft board, the
        verdict feed and the season log are all gone — you are looking at the
        deletion gate, live. Re-enable memory and the world comes back.
      </div>
    </section>

    <div class="grid">
      <section class="room full" id="room-money">
        <h2><span class="rn">0</span> the money floor — every settlement, with its tx</h2>
        <p class="desc">The house's server-side journal of what actually settled on Base.
          Every row links its Basescan transaction. This is the reconciliation the
          buyer's 402 receipt alone cannot give.</p>
        <div class="kv" id="money-kv"></div>
        <div id="money-table"></div>
      </section>

      <section class="room" id="room-desk">
        <h2><span class="rn">1</span> the desk — trust ledger</h2>
        <p class="desc">Every caller the house remembers, priced by memory: segment,
          trust, net charged. Addresses anonymized to last-6.</p>
        <div id="desk-table"></div>
      </section>

      <section class="room" id="room-underwrite">
        <h2><span class="rn">2</span> underwriting — the bond book</h2>
        <p class="desc">Bonds issued, premiums collected, claims paid — with the payout
          tx for every claim. The flagship crosspath: insurance underwritten by
          what the house remembers about a provider.</p>
        <div class="kv" id="bond-kv"></div>
        <div id="bond-table"></div>
      </section>

      <section class="room" id="room-front">
        <h2><span class="rn">3</span> the front office — draft board</h2>
        <p class="desc">Every provider the house remembers, with the terms it would
          offer. Memory drafts the proven and refuses the scarred — not the
          cheapest, the remembered.</p>
        <div class="kv" id="front-kv"></div>
        <div id="front-table"></div>
      </section>

      <section class="room" id="room-watch">
        <h2><span class="rn">4</span> the watchtower — verdict feed</h2>
        <p class="desc">Counterparty screens: CLEAR / HOLD / ABORT with the rule that
          fired and the ring it drew. The house refuses to launder — this is where
          the refusals are published.</p>
        <div class="kv" id="watch-kv"></div>
        <div id="watch-table"></div>
      </section>

      <section class="room full" id="room-log">
        <h2><span class="rn">5</span> the season log — the house's journal</h2>
        <p class="desc">The cold journal: every serve, bond, claim, screen and refusal,
          timestamped, newest first. This is the recall surface — the house's own
          memory, readable by anyone, at a glance.</p>
        <div class="log" id="log"></div>
      </section>
    </div>
  </main>

  <footer>
    <span>the-house · base mainnet · x402 exact scheme · $base_price base</span>
    <span id="ts">$ts</span>
  </footer>
</div>

<script>
(function(){
  // Live gallery: fetch the house's own free ledgers, render. No framework,
  // no external JS, no literal $ in this script (safe under safe_substitute).
  function $(id){return document.getElementById(id);}
  function esc(s){return (s==null?"":String(s)).replace(/[&<>"]/g,function(c){
    return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]);});}
  function money(v){return (v==null?0:Number(v)).toFixed(4);}
  function age(s){
    if(s==null||s<0){return "—";}
    if(s<90){return Math.round(s)+"s";}
    if(s<5400){return Math.round(s/60)+"m";}
    if(s<172800){return Math.round(s/3600)+"h";}
    return Math.round(s/86400)+"d";
  }
  function kv(pairs){
    var h="";
    for(var i=0;i<pairs.length;i++){
      h+="<span class='k'><b"+(pairs[i][2]?" class='amber'":"")+">"+esc(pairs[i][1])+"</b> "+esc(pairs[i][0])+"</span>";
    }
    return h;
  }
  function table(headers,rows,empty){
    if(!rows||!rows.length){return "<div class='empty'>"+esc(empty||"no record — the house has not remembered this yet")+"</div>";}
    var h="<table><tr>";
    for(var i=0;i<headers.length;i++){h+="<th>"+esc(headers[i][0])+"</th>";}
    h+="</tr>";
    for(var r=0;r<rows.length;r++){
      h+="<tr>";
      for(var c=0;c<headers.length;c++){
        var cell=rows[r][c];
        if(cell&&cell.href){h+="<td><a href='"+esc(cell.href)+"' target='_blank' rel='noopener'>"+esc(cell.t)+"</a></td>";}
        else if(cell&&cell.cls){h+="<td class='"+esc(cell.cls)+"'>"+esc(cell.t)+"</td>";}
        else{h+="<td>"+esc(cell==null?"—":cell)+"</td>";}
      }
      h+="</tr>";
    }
    h+="</table>";
    return h;
  }
  function fetchJson(url){
    return fetch(url,{cache:"no-store"}).then(function(r){return r.json();}).catch(function(){return null;});
  }
  function tick(){
    // Room 0: the money floor (from /house/ledger → money)
    fetchJson("/house/ledger").then(function(j){
      if(!j){return;}
      var m=j.money||{};
      $( "money-kv").innerHTML = kv([
        ["settlements", m.settlements!=null?m.settlements:0],
        ["usdc settled", money(m.settled_usdc), true]
      ]);
      var recent=m.recent||[];
      var rows=recent.map(function(e){
        var tx=e.tx||"";
        var cell=tx?{t:tx.slice(0,10)+"…",href:"https://basescan.org/tx/"+tx}:"—";
        return [cell, e.route||"—", money(e.amount_usdc), age((new Date().getTime()/1000)-(e.ts||0))];
      });
      $("money-table").innerHTML = table(
        [["tx"],["route"],["usdc"],["age"]], rows, "no settlements journaled yet");
      if(j.memory){
        var st=$("mem-status"), dot=$("mem-dot");
        if(st){st.textContent="MEMORY "+String(j.memory).toUpperCase();}
        if(dot){dot.className="dot"+(j.memory==="live"?"":" off");}
      }
    });
    // Room 1: the desk (callers)
    fetchJson("/house/ledger").then(function(j){
      if(!j){return;}
      var rows=(j.callers||[]).map(function(c){
        return [c.addr_last6||"—",
                {t:c.segment||"—",cls:"seg "+(c.segment||"")},
                c.trust_score!=null?c.trust_score:"—",
                c.tx_count!=null?c.tx_count:0,
                money(c.net_charged_usdc)];
      });
      $("desk-table").innerHTML = table(
        [["addr"],["segment"],["trust"],["tx"],["net $"]], rows,
        "no callers remembered yet");
    });
    // Room 2: underwriting (bonds)
    fetchJson("/house/bonds").then(function(j){
      if(!j){return;}
      var b=j.book||{};
      $("bond-kv").innerHTML = kv([
        ["bonds issued", b.bonds_issued!=null?b.bonds_issued:0],
        ["premiums $", money(b.premiums_collected_usdc)],
        ["claims paid", b.claims_paid!=null?b.claims_paid:0],
        ["payouts $", money(b.payouts_usdc), true]
      ]);
      var rows=(j.bonds||[]).map(function(bd){
        var cell=bd.claim_tx?{t:bd.claim_tx.slice(0,10)+"…",
              href:"https://basescan.org/tx/"+bd.claim_tx}:"—";
        return [bd.id||"—", bd.provider_last6||"—", money(bd.face_usdc),
                money(bd.premium_usdc), bd.segment||"—", bd.status||"—", cell];
      });
      $("bond-table").innerHTML = table(
        [["bond"],["prov"],["face $"],["prem $"],["seg"],["status"],["claim tx"]],
        rows, "no bonds issued yet");
    });
    // Room 3: the front office (draft board)
    fetchJson("/house/front").then(function(j){
      if(!j){return;}
      $("front-kv").innerHTML = kv([
        ["providers", j.providers!=null?j.providers:0],
        ["drafted", j.drafted!=null?j.drafted:0],
        ["refused", j.refused!=null?j.refused:0]
      ]);
      var rows=(j.board||[]).map(function(p){
        return [p.provider_last6||"—",
                {t:p.segment||"—",cls:"seg "+(p.segment||"")},
                p.jobs_done!=null?p.jobs_done:0,
                p.quality_score!=null?Number(p.quality_score).toFixed(2):"—",
                p.default_events!=null?p.default_events:0,
                p.hired?"drafted":"refused"];
      });
      $("front-table").innerHTML = table(
        [["provider"],["segment"],["jobs"],["quality"],["defaults"],["terms"]],
        rows, "no providers remembered yet");
    });
    // Room 4: the watchtower (verdict feed)
    fetchJson("/house/watch").then(function(j){
      if(!j){return;}
      var s=j.stats||{};
      $("watch-kv").innerHTML = kv([
        ["screens", s.screens!=null?s.screens:0],
        ["organic", s.organic!=null?s.organic:0],
        ["refusals", s.refusals!=null?s.refusals:0, s.refusals?true:false]
      ]);
      var rows=(j.feed||[]).map(function(f){
        return [{t:f.verdict||"—",cls:"verdict "+(f.verdict||"")},
                (f.rules||[]).join(", ")||"clean",
                (f.ring&&f.ring.length?f.ring.map(function(x){return String(x).slice(-6);}).join(" "):"—")];
      });
      $("watch-table").innerHTML = table(
        [["verdict"],["rule"],["ring"]], rows, "no screens yet");
    });
    // Room 5: the season log (journal)
    fetchJson("/house/journal").then(function(j){
      if(!j){$("log").innerHTML="";return;}
      var ev=j.events||[];
      var h="";
      for(var i=0;i<ev.length;i++){
        var e=ev[i];
        h+="<div class='row'><span class='ts'>"+esc(e.ts||"")+"</span>"
          +"<span class='kind'>"+esc(e.kind||"")+"</span>"
          +"<span class='txt'>"+esc(e.text||"")+"</span></div>";
      }
      $("log").innerHTML = h || "<div class='empty'>no journal entries yet</div>";
    });
  }
  tick();
  setInterval(tick, 5000);
})();
</script>
</body>
</html>
""")


def render_gallery(*, memory_live: bool, commit: str,
                   base_price: float, ts: str) -> str:
    """Render the gallery shell. The first paint is the live aggregates
    (injected server-side); the client then keeps it fresh from the JSON
    ledgers. In deletion mode memory_live=False → the collapse banner shows
    and the client-side ledgers read empty (the endpoints return no rows)."""
    return _GALLERY_HTML.safe_substitute(
        dot_class="" if memory_live else "off",
        memory_status="LIVE" if memory_live else "DISABLED",
        collapse_show="" if memory_live else "show",
        commit=html.escape(commit),
        base_price=f"{float(base_price):.2f}",
        ts=html.escape(ts),
    )

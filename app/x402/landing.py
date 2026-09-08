"""THE HOUSE — landing page (the house's own design language).

Forensic / investigative, near-black + a single amber accent, Space Grotesk
+ Space Mono. Accent is used only for the most important thing in the frame
(amber = the thesis; green = the live pulse). All the numbers are LIVE —
rendered server-side from the real aggregates, so the page is a mirror of the
house's own state. When memory is disabled (SIBYL_DISABLED=1) the aggregates
collapse and the page reads the collapse: everything is 0, the pulse is dead.
That is the deletion gate, visible at a glance.

Kept in its own module so ``app/x402/seller.py`` stays a thin FastAPI/x402
boundary (F4 — the app is not a god-object).
"""
from __future__ import annotations

import html
from string import Template

# The template uses $name placeholders (string.Template). CSS braces are
# untouched; the inline JS is written with no literal $ so it is safe under
# safe_substitute. Numbers are injected server-side and then refreshed live
# from /manifest by the tiny script at the foot of the page.
_LANDING_HTML = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>the-house — memory-native x402 on Base</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2032%2032'%3E%3Crect%20width='32'%20height='32'%20fill='%230A0A0A'/%3E%3Cpath%20d='M11%208v16M21%208v16M11%2016h10'%20stroke='%23E8C547'%20stroke-width='3'%20stroke-linecap='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0A0A0A; --surface:#111111; --border:#1E1E1E;
    --text:#E8E8E8; --muted:#666666;
    --amber:#E8C547; --green:#27AE60; --red:#C0392B; --cyan:#00D9FF;
    --grotesk:"Space Grotesk",system-ui,-apple-system,"Segoe UI",sans-serif;
    --mono:"Space Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;background:var(--bg);color:var(--text);
    font-family:var(--grotesk);-webkit-font-smoothing:antialiased;}
  body{line-height:1.5;}
  a{color:inherit;text-decoration:none;}
  .wrap{max-width:1080px;margin:0 auto;padding:48px 40px 56px;}

  /* top bar */
  .bar{display:flex;align-items:center;justify-content:space-between;
    padding-bottom:28px;border-bottom:1px solid var(--border);gap:16px;flex-wrap:wrap;}
  .wordmark{font-weight:700;letter-spacing:.14em;font-size:18px;}
  .wordmark .tick{color:var(--amber);}
  .status{display:flex;align-items:center;gap:9px;font-family:var(--mono);
    font-size:12px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--green);
    box-shadow:0 0 0 0 rgba(39,174,96,.5);animation:breath 3s ease-in-out infinite;}
  .dot.off{background:var(--red);animation:none;box-shadow:none;}
  .hash{font-family:var(--mono);font-size:12px;color:var(--muted);letter-spacing:.06em;}
  @keyframes breath{0%,100%{opacity:.55}50%{opacity:1;box-shadow:0 0 10px 1px rgba(39,174,96,.35)}}

  /* hero */
  .hero{padding:64px 0 8px;}
  .hero h1{font-size:clamp(30px,5.2vw,56px);line-height:1.06;font-weight:700;
    letter-spacing:-.01em;margin:0 0 22px;max-width:20ch;}
  .hero h1 em{font-style:normal;color:var(--amber);}
  .hero .sub{font-size:clamp(15px,1.7vw,19px);color:var(--muted);
    max-width:64ch;margin:0;}

  /* stat strip — 5-across primary row, the 2 secondary stats wrap below */
  .stats{display:grid;grid-template-columns:repeat(5,1fr);
    gap:14px;margin:48px 0 8px;}
  .cell{background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.01));
    border:1px solid var(--border);border-radius:12px;padding:18px 18px 16px;
    backdrop-filter:blur(12px);}
  .cell .num{font-family:var(--mono);font-weight:700;font-size:clamp(26px,3vw,34px);
    color:var(--text);line-height:1;}
  .cell .num.amber{color:var(--amber);}
  .cell .lbl{font-family:var(--mono);font-size:11px;letter-spacing:.1em;
    text-transform:uppercase;color:var(--muted);margin-top:12px;}

  /* memory is load-bearing */
  .memory{margin-top:56px;}
  .memory h2{font-size:13px;font-family:var(--mono);letter-spacing:.16em;
    text-transform:uppercase;color:var(--muted);margin:0 0 22px;font-weight:400;}
  .feat{display:flex;gap:18px;padding:18px 0;border-top:1px solid var(--border);
    font-size:16px;color:#c9c9c9;}
  .feat:first-of-type{border-top:none;}
  .feat .tag{font-family:var(--mono);font-size:12px;color:var(--amber);
    border:1px solid rgba(232,197,71,.35);border-radius:4px;padding:2px 7px;
    min-width:38px;text-align:center;align-self:flex-start;}
  .feat b{color:var(--text);font-weight:600;}
  .collapse{display:none;margin-top:26px;padding:16px 18px;border:1px solid rgba(192,57,43,.4);
    border-radius:10px;color:#e0a49c;font-size:15px;background:rgba(192,57,43,.08);}
  .collapse.show{display:block;}
  .collapse .tag{color:var(--red);border-color:rgba(192,57,43,.4);}

  /* proof / links */
  .proof{margin-top:52px;padding-top:28px;border-top:1px solid var(--border);}
  .proof p{color:var(--muted);font-size:15px;max-width:64ch;margin:0 0 16px;}
  .links{display:flex;flex-wrap:wrap;gap:10px 22px;font-family:var(--mono);font-size:13px;}
  .links a{color:var(--text);border-bottom:1px solid var(--border);padding-bottom:2px;}
  .links a:hover{color:var(--amber);border-color:var(--amber);}
  .repo{font-family:var(--mono);font-size:13px;color:var(--muted);margin-top:18px;}
  .repo a{color:var(--text);border-bottom:1px solid var(--border);}

  footer{margin-top:56px;padding-top:24px;border-top:1px solid var(--border);
    display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
    font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--muted);}
  @media (max-width:680px){.stats{grid-template-columns:repeat(2,1fr);}}
  @media (max-width:560px){.wrap{padding:32px 22px 44px;}.hero{padding-top:40px;}}
</style>
</head>
<body>
<div class="wrap">

  <header class="bar">
    <div class="wordmark">THE<span class="tick">·</span>HOUSE</div>
    <div class="status"><span class="dot $dot_class" id="mem-dot"></span>
      <span id="mem-status">MEMORY $memory_status</span></div>
    <div class="hash">commit $commit</div>
  </header>

  <main>
    <section class="hero">
      <h1>Every x402 payment is anonymous and stateless. <em>The house assumes nothing.</em></h1>
      <p class="sub">A memory-native x402 service on Base mainnet that prices, serves, and
        retries financial work based on what it remembers about each counterparty —
        and gets better at every transaction.</p>
    </section>

    <section class="stats" aria-label="live ledger">
      <div class="cell"><div class="num" id="s-settle">$settlements</div><div class="lbl">settlements · tx</div></div>
      <div class="cell"><div class="num amber" id="s-usdc">$usdc</div><div class="lbl">usdc settled</div></div>
      <div class="cell"><div class="num" id="s-repeats">$repeats</div><div class="lbl">repeats cached</div></div>
      <div class="cell"><div class="num" id="s-saved">$saved</div><div class="lbl">usdc saved · dedup</div></div>
      <div class="cell"><div class="num" id="s-scars">$scars</div><div class="lbl">scars compiled</div></div>
      <div class="cell"><div class="num" id="s-rules">$rules</div><div class="lbl">active policy rules</div></div>
      <div class="cell"><div class="num" id="s-callers">$callers</div><div class="lbl">live callers</div></div>
    </section>

    <section class="memory">
      <h2>why memory is load-bearing</h2>
      <div class="feat"><span class="tag">F1</span><div><b>Trust ledger.</b> Every caller is
        priced by what the house remembers, not a flat list — VIPs pay less, strangers pay
        list, banned wallets are refused before a byte is served.</div></div>
      <div class="feat"><span class="tag">F2</span><div><b>Dedup-as-revenue.</b> A repeat of the
        same query is served from memory at net $0. The house never re-sells what you already
        bought, and it counts every cent it saved.</div></div>
      <div class="feat"><span class="tag">F3</span><div><b>Failure compiles.</b> When a route
        fails the house writes a scar; recurring scars compile into policy that a fresh
        session cites and hardens against — no re-learning on every boot.</div></div>
      <div class="feat"><span class="tag">F4</span><div><b>Kill-resilient execution.</b> Kill
        the agent mid-payment. It wakes, reads the job from memory, resumes — and settles
        exactly once. No double charge.</div></div>

      <div class="collapse $collapse_show">
        <span class="tag">gate</span> Memory is <b>disabled</b> — the ledger, the dedup
        cache, the scars and the resume state are all gone. Every wallet prices at list,
        nothing is refused, and a mid-payment kill would double-charge. That is why the
        memory is load-bearing: remove it and the business model is a stateless price list.
      </div>
    </section>

    <section class="proof">
      <p>The desk is free and live — callers anonymized to last-6, updating as the house
        serves. Open it and watch it move.</p>
      <div class="links">
        <a href="/house/ledger">/house/ledger</a>
        <a href="/house/jobs">/house/jobs</a>
        <a href="/house/audit">/house/audit</a>
        <a href="/house/calibrate">/house/calibrate</a>
        <a href="/manifest">manifest</a>
      </div>
      <p class="repo">$repo_line</p>
    </section>
  </main>

  <footer>
    <span>the-house · base mainnet · x402 exact scheme · $base_price base</span>
    <span class="ts" id="ts">$ts</span>
  </footer>

</div>

<script>
(function(){
  // Live refresh of the stat strip from /manifest (the JSON descriptor).
  // No external libs, no $ — plain DOM.
  function setText(id, v){var el=document.getElementById(id);if(el){el.textContent=v;}}
  function money(v){return Number(v).toFixed(2);}
  function tick(){
    fetch('/manifest',{cache:'no-store'}).then(function(r){return r.json();})
      .then(function(j){
        var s=j.stats||{};
        setText('s-settle', s.settlements!=null?s.settlements:0);
        setText('s-usdc', money(s.usdc_settled||0));
        setText('s-repeats', s.repeats_cached!=null?s.repeats_cached:0);
        setText('s-saved', money(s.usdc_saved||0));
        setText('s-scars', s.scars!=null?s.scars:0);
        setText('s-rules', s.active_rules!=null?s.active_rules:0);
        setText('s-callers', s.live_callers!=null?s.live_callers:0);
        if(j.memory){
          var st=document.getElementById('mem-status');
          var dot=document.getElementById('mem-dot');
          if(st){st.textContent='MEMORY '+j.memory.toUpperCase();}
          if(dot){dot.className='dot'+(j.memory==='live'?'':' off');}
        }
      }).catch(function(){});
  }
  setInterval(tick, 5000);
})();
</script>
</body>
</html>
""")


def render_landing(*, memory_live: bool,
                   settlements: int, usdc_settled: float,
                   repeats_cached: int, usdc_saved: float,
                   scars: int, active_rules: int, live_callers: int,
                   commit: str, base_price: float, repo_url: str,
                   ts: str) -> str:
    """Render the landing page from live aggregates.

    In deletion mode (memory_live False) every aggregate is 0, so the page
    itself shows the collapse — the gate, visible. The repo line is honest:
    it only links when a public repo URL is configured.
    """
    repo_line = (
        f"<a href=\"{html.escape(repo_url, quote=True)}\" "
        f"target=\"_blank\" rel=\"noopener\">{html.escape(repo_url)}</a>"
        if repo_url
        else "repository: private build page (public repo at submission)"
    )
    return _LANDING_HTML.safe_substitute(
        dot_class="" if memory_live else "off",
        memory_status="LIVE" if memory_live else "DISABLED",
        collapse_show="" if memory_live else "show",
        settlements=str(int(settlements)),
        usdc=f"{float(usdc_settled):.2f}",
        repeats=str(int(repeats_cached)),
        saved=f"{float(usdc_saved):.2f}",
        scars=str(int(scars)),
        rules=str(int(active_rules)),
        callers=str(int(live_callers)),
        commit=html.escape(commit),
        base_price=f"{float(base_price):.2f}",
        repo_line=repo_line,
        ts=html.escape(ts),
    )

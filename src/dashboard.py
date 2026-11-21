"""Build the GitHub Pages dashboard (site/index.html) from data/history.json.

  python src/dashboard.py [--history data/history.json] [--config config.yaml] [--out site/index.html]
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deals  # noqa: E402
import specs  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_data(history: dict, cfg: dict) -> dict:
    watch_names = {}
    for item in cfg.get("watchlist") or []:
        for u in item.get("urls") or []:
            watch_names[u] = item
    budget = (cfg.get("budget") or {}).get("max_price")
    window = ((cfg.get("settings") or {}).get("median_window_days")) or 30
    since = (deals.now() - timedelta(days=window)).strftime("%Y-%m-%d")
    today = deals.today()

    items = []
    for pid, r in history.get("products", {}).items():
        if r.get("specs_failed") or not r.get("days") or not r.get("last"):
            continue
        days = sorted(r["days"].items())
        past = [p for d, p in days if since <= d < today]
        item = None
        for u, it in watch_names.items():
            if r.get("url", "").split("?")[0] == u.split("?")[0] or (pid.startswith("amazon:") and pid.split(":")[1] in u):
                item = it
        items.append({
            "id": pid,
            "name": (item or {}).get("name") or r.get("name") or r.get("title", pid),
            "title": r.get("title", ""),
            "url": r.get("url"),
            "store": r.get("store") or pid.split(":")[0],
            "watch": bool(item) or r.get("kind") == "watch",
            "specs": specs.short(r.get("specs") or {}) if r.get("specs") else "",
            "price": r["last"],
            "mrp": r.get("mrp"),
            "low": min(p for _, p in days),
            "usual": int(statistics.median(past)) if past else None,
            "target": (item or {}).get("target_price") or r.get("target"),
            "in_stock": r.get("in_stock", True),
            "verified": bool(r.get("has_page")),
            "last_seen": r.get("last_seen"),
            "last_alert": r.get("last_alert"),
            "days": days,
        })
    sources = []
    for url, s in history.get("sources", {}).items():
        sources.append({"url": url, "ok": s.get("fails", 0) == 0, "fails": s.get("fails", 0),
                        "error": s.get("last_error"), "last_ok": s.get("last_ok")})
    return {
        "generated": deals.now().isoformat(),
        "last_run": history.get("meta", {}).get("last_run"),
        "budget": budget,
        "window": window,
        "items": items,
        "sources": sources,
    }


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Laptop deal tracker</title>
<meta name="robots" content="noindex">
<style>
:root {
  color-scheme: light;
  --bg: #f6f6f4; --surface-1: #fcfcfb; --surface-2: #f0efec; --border: #e2e1dc;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #77766f;
  --series-1: #2a78d6; --ref: #9c9b94;
  --good: #008300; --good-bg: #e6f4e6; --warn: #a86b00; --warn-bg: #fbf1dc; --bad: #c42b2b; --bad-bg: #fbe7e7;
  --accent: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --bg: #121211; --surface-1: #1a1a19; --surface-2: #232321; --border: #33332f;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
    --series-1: #3987e5; --ref: #6d6c66;
    --good: #0ca30c; --good-bg: #13261a; --warn: #e0a326; --warn-bg: #2b2414; --bad: #e66767; --bad-bg: #2d1717;
    --accent: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #121211; --surface-1: #1a1a19; --surface-2: #232321; --border: #33332f;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
  --series-1: #3987e5; --ref: #6d6c66;
  --good: #0ca30c; --good-bg: #13261a; --warn: #e0a326; --warn-bg: #2b2414; --bad: #e66767; --bad-bg: #2d1717;
  --accent: #3987e5;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text-primary);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); }
.wrap { max-width: 1180px; margin: 0 auto; padding: 24px 16px 64px; }
header { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 17px; margin: 32px 0 12px; }
.sub { color: var(--text-secondary); font-size: 14px; }
.theme { background: var(--surface-1); color: var(--text-secondary); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; font: inherit; font-size: 13px; cursor: pointer; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.stat .k { color: var(--text-secondary); font-size: 13px; }
.stat .v { font-size: 26px; font-weight: 650; font-variant-numeric: tabular-nums; margin-top: 2px; }
.stat .v small { font-size: 13px; font-weight: 500; color: var(--text-muted); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
  display: flex; flex-direction: column; gap: 8px; }
.card .name { font-weight: 600; line-height: 1.3; }
.card .row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.price { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.muted { color: var(--text-muted); }
.sec { color: var(--text-secondary); }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--text-secondary); white-space: nowrap; }
.chip.good { background: var(--good-bg); color: var(--good); font-weight: 600; }
.chip.warn { background: var(--warn-bg); color: var(--warn); font-weight: 600; }
.chip.bad { background: var(--bad-bg); color: var(--bad); font-weight: 600; }
.chip.watch { background: transparent; border: 1px solid var(--border); }
.btn { display: inline-block; text-decoration: none; font-weight: 600; font-size: 14px; padding: 7px 12px;
  border-radius: 8px; background: var(--accent); color: #fff; text-align: center; }
.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
.controls input[type=search], .controls select { font: inherit; font-size: 14px; padding: 7px 10px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary); }
.controls input[type=search] { flex: 1 1 220px; }
.controls label { font-size: 14px; color: var(--text-secondary); display: flex; gap: 6px; align-items: center; cursor: pointer; }
.tablewrap { overflow-x: auto; background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: middle; }
th { font-size: 12px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .04em;
  position: sticky; top: 0; background: var(--surface-1); }
tr:last-child td { border-bottom: 0; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td .t { font-weight: 600; }
td .s { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
tr.stale td { opacity: .55; }
.spark { display: block; overflow: visible; }
.spark-wrap { position: relative; }
.tip { position: absolute; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
  font-size: 12px; padding: 4px 7px; border-radius: 6px; white-space: nowrap; transform: translate(-50%, -115%);
  top: 0; display: none; font-variant-numeric: tabular-nums; z-index: 2; }
.legend { display: flex; gap: 16px; font-size: 12px; color: var(--text-secondary); margin: 8px 0 0; flex-wrap: wrap; }
.legend i { display: inline-block; width: 16px; height: 0; border-top: 2px solid var(--series-1); vertical-align: middle; margin-right: 6px; }
.legend i.ref { border-top: 1.5px dashed var(--ref); }
.sources { font-size: 13px; color: var(--text-secondary); }
.sources li { margin: 3px 0; word-break: break-all; }
.empty { padding: 24px; text-align: center; color: var(--text-muted); background: var(--surface-1);
  border: 1px dashed var(--border); border-radius: 12px; }
footer { margin-top: 40px; font-size: 12px; color: var(--text-muted); }
@media (max-width: 640px) { .hide-sm { display: none; } .price { font-size: 20px; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>💻 Laptop deal tracker</h1>
      <div class="sub" id="sub"></div>
    </div>
    <button class="theme" id="theme" type="button">Theme: auto</button>
  </header>

  <section class="stats" id="stats"></section>

  <h2>✅ In your budget now</h2>
  <div class="cards" id="inbudget"></div>

  <h2>All tracked laptops</h2>
  <div class="controls">
    <input type="search" id="q" placeholder="Search: LOQ, 5060, Ryzen, Flipkart…" aria-label="Search laptops">
    <select id="sort" aria-label="Sort">
      <option value="price">Sort: price (low → high)</option>
      <option value="drop">Sort: % below usual</option>
      <option value="gap">Sort: closest to budget</option>
      <option value="name">Sort: name</option>
    </select>
    <label><input type="checkbox" id="onlyWatch"> Watchlist only</label>
    <label><input type="checkbox" id="only5060"> RTX 5060+ only</label>
  </div>
  <div class="tablewrap">
    <table>
      <thead><tr>
        <th>Laptop</th><th class="hide-sm">Store</th><th class="num">Price</th>
        <th class="num hide-sm">Lowest seen</th><th class="num hide-sm">Usual</th>
        <th class="hide-sm">Trend</th><th></th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
  <div class="legend"><span><i></i>Daily lowest price</span><span><i class="ref"></i>Your budget</span></div>

  <h2>Store pages checked</h2>
  <ul class="sources" id="sources"></ul>

  <footer>
    Prices are listed prices (bank/card offers not included). "Usual" = median daily price over the last <span id="win"></span> days.
    Always check the store page before buying. Updated by GitHub Actions about every 30 min.
  </footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const inr = n => n == null ? '–' : '₹' + Math.round(n).toLocaleString('en-IN');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ago = iso => {
  if (!iso) return 'never';
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 1) return 'just now'; if (m < 60) return m + ' min ago';
  const h = Math.round(m / 60); if (h < 48) return h + ' h ago';
  return Math.round(h / 24) + ' days ago';
};
const B = D.budget;

// theme toggle: auto -> dark -> light
const root = document.documentElement;
const themes = ['auto', 'dark', 'light'];
let th = localStorage.getItem('theme') || 'auto';
const applyTheme = () => { if (th === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', th);
  $('theme').textContent = 'Theme: ' + th; };
$('theme').onclick = () => { th = themes[(themes.indexOf(th) + 1) % 3]; localStorage.setItem('theme', th); applyTheme(); };
applyTheme();

const items = D.items.map(it => ({...it,
  drop: it.usual ? (it.usual - it.price) / it.usual * 100 : null,
  inBudget: B && it.price <= B && it.in_stock,
  stale: it.last_seen && (Date.now() - new Date(it.last_seen)) > 2 * 864e5,
  gpuN: parseInt(((it.specs.match(/RTX (\d{4})/) || [])[1]) || '0', 10),
}));

$('sub').textContent = `Budget ${inr(B)} · last check ${ago(D.last_run)} · page built ${new Date(D.generated).toLocaleString('en-IN')}`;
$('win').textContent = D.window;

// stats
const okSrc = D.sources.filter(s => s.ok).length;
const cheapest5060 = items.filter(i => i.gpuN >= 5060 && !i.stale).sort((a, b) => a.price - b.price)[0];
$('stats').innerHTML = [
  ['Laptops tracked', items.filter(i => !i.stale).length, `<small>${items.filter(i => i.watch).length} on watchlist</small>`],
  ['In budget now', items.filter(i => i.inBudget && !i.stale).length, `<small>≤ ${inr(B)}</small>`],
  ['Cheapest RTX 5060+', cheapest5060 ? inr(cheapest5060.price) : '–', cheapest5060 ? `<small>${esc(cheapest5060.store)}</small>` : ''],
  ['Store pages OK', `${okSrc}/${D.sources.length}`, okSrc < D.sources.length ? '<small>see list below</small>' : ''],
].map(([k, v, x]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v} ${x}</div></div>`).join('');

// sparkline: one series (daily lowest price), dashed budget reference line, hover tooltip
function spark(it, w = 140, h = 36) {
  const pts = it.days; if (!pts.length) return '';
  const vals = pts.map(p => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (B && B >= lo * 0.9 && B <= hi * 1.1) { lo = Math.min(lo, B); hi = Math.max(hi, B); }
  if (hi === lo) { hi += 1000; lo -= 1000; }
  const pad = 4, X = i => pts.length === 1 ? w / 2 : pad + i * (w - 2 * pad) / (pts.length - 1),
        Y = v => pad + (hi - v) * (h - 2 * pad) / (hi - lo);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join(' ');
  const ref = (B && B >= lo && B <= hi) ? `<line x1="0" x2="${w}" y1="${Y(B).toFixed(1)}" y2="${Y(B).toFixed(1)}" stroke="var(--ref)" stroke-width="1.5" stroke-dasharray="3 3"/>` : '';
  const last = pts.length - 1;
  return `<div class="spark-wrap" style="width:${w}px" data-id="${esc(it.id)}" data-w="${w}" data-h="${h}"><svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img"
      aria-label="Price history: ${pts.length} days, from ${inr(vals[0])} to ${inr(vals[last])}">
    ${ref}<path d="${d}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${X(last)}" cy="${Y(vals[last])}" r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/>
    <circle class="hov" r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2" style="display:none"/>
    <rect x="0" y="0" width="${w}" height="${h}" fill="transparent"/>
  </svg><div class="tip"></div></div>`;
}
function wireSparks(scope) {
  scope.querySelectorAll('.spark-wrap').forEach(el => {
    const it = items.find(i => i.id === el.dataset.id); if (!it) return;
    const svg = el.querySelector('svg'), tip = el.querySelector('.tip'), hov = el.querySelector('.hov');
    const w = +el.dataset.w, h = +el.dataset.h, pts = it.days, vals = pts.map(p => p[1]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (B && B >= lo * 0.9 && B <= hi * 1.1) { lo = Math.min(lo, B); hi = Math.max(hi, B); }
    if (hi === lo) { hi += 1000; lo -= 1000; }
    const pad = 4, X = i => pts.length === 1 ? w / 2 : pad + i * (w - 2 * pad) / (pts.length - 1),
          Y = v => pad + (hi - v) * (h - 2 * pad) / (hi - lo);
    const show = e => {
      const r = svg.getBoundingClientRect(), x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      let i = pts.length === 1 ? 0 : Math.round((x - pad) / ((w - 2 * pad) / (pts.length - 1)));
      i = Math.max(0, Math.min(pts.length - 1, i));
      hov.setAttribute('cx', X(i)); hov.setAttribute('cy', Y(vals[i])); hov.style.display = '';
      tip.style.display = 'block'; tip.style.left = X(i) + 'px'; tip.style.top = Y(vals[i]) + 'px';
      tip.textContent = `${new Date(pts[i][0]).toLocaleDateString('en-IN', {day: 'numeric', month: 'short'})}: ${inr(vals[i])}`;
    };
    const hide = () => { tip.style.display = 'none'; hov.style.display = 'none'; };
    svg.addEventListener('mousemove', show); svg.addEventListener('touchstart', show, {passive: true});
    svg.addEventListener('mouseleave', hide); svg.addEventListener('touchend', hide);
  });
}

function badges(it) {
  const b = [];
  if (it.inBudget) b.push('<span class="chip good">✓ In budget</span>');
  else if (B) b.push(`<span class="chip">${inr(it.price - B)} over budget</span>`);
  if (it.target && it.price <= it.target) b.push('<span class="chip good">✓ Hit target</span>');
  if (it.drop != null && it.drop >= 5) b.push(`<span class="chip warn">↓ ${it.drop.toFixed(0)}% below usual</span>`);
  if (!it.in_stock) b.push('<span class="chip bad">✕ Out of stock</span>');
  if (it.watch) b.push('<span class="chip watch">★ Watchlist</span>');
  return b.join('');
}

// in-budget cards
const ib = items.filter(i => i.inBudget && !i.stale).sort((a, b) => a.price - b.price);
$('inbudget').innerHTML = ib.length ? ib.map(it => `
  <div class="card">
    <div class="name">${esc(it.name)}</div>
    <div class="chips">${it.specs.split(' · ').map(s => `<span class="chip">${esc(s)}</span>`).join('')}</div>
    <div class="row"><span class="price">${inr(it.price)}</span><span class="sec">${esc(it.store)}</span></div>
    <div class="row sec" style="font-size:13px"><span>Lowest ${inr(it.low)}${it.usual ? ' · usual ' + inr(it.usual) : ''}</span>
      ${it.target ? `<span>Target ${inr(it.target)}</span>` : ''}</div>
    <div class="chips">${badges(it)}</div>
    ${spark(it, 260, 40)}
    <a class="btn" href="${esc(it.url)}" target="_blank" rel="noopener">Open on ${esc(it.store)} →</a>
  </div>`).join('') : `<div class="empty">Nothing meeting your specs is at or under ${inr(B)} right now. The bot will message you when something drops into budget.</div>`;

function render() {
  const q = $('q').value.trim().toLowerCase();
  const onlyWatch = $('onlyWatch').checked, only5060 = $('only5060').checked;
  let list = items.filter(it => (!onlyWatch || it.watch) && (!only5060 || it.gpuN >= 5060) &&
    (!q || (it.name + ' ' + it.title + ' ' + it.specs + ' ' + it.store).toLowerCase().includes(q)));
  const s = $('sort').value;
  list.sort((a, b) => s === 'name' ? a.name.localeCompare(b.name)
    : s === 'drop' ? (b.drop ?? -99) - (a.drop ?? -99)
    : s === 'gap' ? Math.abs(a.price - B) - Math.abs(b.price - B)
    : a.price - b.price);
  list.sort((a, b) => a.stale - b.stale);
  $('rows').innerHTML = list.length ? list.map(it => `
    <tr class="${it.stale ? 'stale' : ''}">
      <td><div class="t">${esc(it.name)}</div><div class="s">${esc(it.specs)}${it.verified ? '' : ' · search-page price'}${it.stale ? ' · not seen for ' + ago(it.last_seen).replace(' ago', '') : ''}</div>
        <div class="chips" style="margin-top:4px">${badges(it)}</div></td>
      <td class="hide-sm">${esc(it.store)}</td>
      <td class="num"><b>${inr(it.price)}</b>${it.mrp && it.mrp > it.price ? `<div class="s"><s>${inr(it.mrp)}</s></div>` : ''}</td>
      <td class="num hide-sm">${inr(it.low)}</td>
      <td class="num hide-sm">${inr(it.usual)}</td>
      <td class="hide-sm">${spark(it)}</td>
      <td><a href="${esc(it.url)}" target="_blank" rel="noopener">Open&nbsp;→</a></td>
    </tr>`).join('') : `<tr><td colspan="7" class="muted" style="text-align:center;padding:24px">No laptops match these filters.</td></tr>`;
  wireSparks($('rows'));
}
['q', 'sort', 'onlyWatch', 'only5060'].forEach(id => $(id).addEventListener('input', render));
render();
wireSparks($('inbudget'));

$('sources').innerHTML = D.sources.map(s => `<li>${s.ok ? '✅' : '⚠️'} <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url.replace(/^https:\/\/(www\.)?/, '').slice(0, 90))}</a>
  ${s.ok ? '' : `<span class="muted">: failed ${s.fails}× (${esc(s.error || '')})</span>`}</li>`).join('');
</script>
</body>
</html>
"""


def build_html(history: dict, cfg: dict) -> str:
    data = json.dumps(build_data(history, cfg), ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__DATA__", data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default=os.path.join(ROOT, "data", "history.json"))
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "site", "index.html"))
    a = ap.parse_args()
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    history = deals.load_history(a.history)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build_html(history, cfg))
    print(f"Dashboard written to {a.out} ({len(history['products'])} laptops)")


if __name__ == "__main__":
    main()

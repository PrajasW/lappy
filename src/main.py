"""Laptop deal checker: fetch -> evaluate -> notify -> save.

Usage:
  python src/main.py                   normal run (Telegram alerts, saves history)
  python src/main.py --dry-run         print prices & would-be alerts; send/save nothing
  python src/main.py --test-telegram   send a test message
  python src/main.py --backfill N      fetch real past prices for up to N laptops this run (default from config)
"""
import argparse
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brands  # noqa: E402
import deals  # noqa: E402
import pricehistory  # noqa: E402
import specs  # noqa: E402
import telegram  # noqa: E402
from extract import extract_listing, extract_product, store_name, store_of  # noqa: E402
from fetch import FetchError, get  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND_PREFIXES = ("lenovo.com:", "hp.com:")
NON_LAPTOP = ("desktop", "monitor", "tablet", "ipad", "all-in-one", "all in one", "tower", "keyboard", "mouse", "backpack")

DEFAULT_SETTINGS = {
    "drop_pct_vs_median": 8,
    "median_window_days": 30,
    "min_days_for_median": 3,
    "new_low_min_drop_pct": 2,
    "realert_hours": 168,
    "fail_alert_after": 6,
    "max_alerts_per_run": 10,
    "refresh_per_run": 8,
    "backfill_per_run": 8,
}


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["settings"] = {**DEFAULT_SETTINGS, **(cfg.get("settings") or {})}
    for k in ("watchlist",):
        cfg[k] = cfg.get(k) or []
    for k in ("criteria", "specs", "budget", "brands", "notify"):
        cfg[k] = cfg.get(k) or {}
    return cfg


def load_env_file(path):
    """Minimal .env loader (KEY=value lines) so cron runs pick up secrets."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ------------------------------------------------------------------ fetching (parallel per store)

def run_jobs(jobs, history):
    """jobs: (kind, target, meta) with kind in product | listing | lenovo | hp.
    Jobs for the same store run sequentially; stores run in parallel.
    Returns [(job, products|None, error|None)]."""
    by_store = defaultdict(list)
    for j in jobs:
        key = j[0] if j[0] in ("lenovo", "hp") else store_of(j[1])
        by_store[key].append(j)
    hp_cache = history["meta"].setdefault("hp_specs", {})

    def worker(store_jobs):
        out = []
        for i, (kind, target, meta) in enumerate(store_jobs):
            if i:
                time.sleep(1.5 + random.random() * 2)
            try:
                if kind == "lenovo":
                    items = brands.lenovo_search(target)
                elif kind == "hp":
                    items = brands.hp_search(target, hp_cache)
                else:
                    html = get(target)
                    if kind == "product":
                        p = extract_product(target, html)
                        if p is None:
                            raise FetchError("page loaded but no price found (layout changed or unavailable)")
                        items = [p]
                    else:
                        items = extract_listing(target, html)
                if not items:
                    raise FetchError("no products found (layout changed?)")
                out.append(((kind, target, meta), items, None))
            except FetchError as e:
                out.append(((kind, target, meta), None, str(e)))
            except Exception as e:  # parsing/API bugs shouldn't kill the whole run
                out.append(((kind, target, meta), None, f"{type(e).__name__}: {e}"[:200]))
        return out

    results = []
    if jobs:
        with ThreadPoolExecutor(max_workers=len(by_store)) as ex:
            for out in ex.map(worker, by_store.values()):
                results.extend(out)
    return results


# ------------------------------------------------------------------ helpers

def in_track_range(price, budget):
    return budget.get("track_min_price", 0) <= price <= budget.get("track_max_price", 10**9)


def excluded(title, crit):
    t = title.lower()
    return any(x in t for x in NON_LAPTOP) or any(x.lower() in t for x in crit.get("exclude", []))


def history_line(rec):
    if not rec.get("ath_low"):
        return None
    on = f" on {rec['ath_low_on']}" if rec.get("ath_low_on") else ""
    return f"All-time low {deals.inr(rec['ath_low'])}{on} (per pricehistory.app)"


def build_alert(p, reasons, rec, label, dashboard):
    mrp = ""
    if p.mrp and p.mrp > p.price:
        mrp = f" (MRP {deals.inr(p.mrp)}, {round((p.mrp - p.price) / p.mrp * 100)}% off)"
    a = {"title": (label or p.title)[:160], "price": deals.inr(p.price) + mrp, "store": store_name(p.url),
         "specs": specs.short(rec.get("specs") or {}), "why": reasons, "url": p.url,
         "history_line": history_line(rec), "dashboard": dashboard}
    return a


# ------------------------------------------------------------------ main run

def run(cfg, history, dry_run, backfill_n):
    s, crit, spec_cfg, budget = cfg["settings"], cfg["criteria"], cfg["specs"], cfg["budget"]
    budget_max = budget.get("max_price")
    dashboard = cfg["notify"].get("dashboard_url")

    # -- 1. watchlist pages, store search pages, brand-store APIs
    jobs = []
    for item in cfg["watchlist"]:
        for url in item.get("urls") or []:
            jobs.append(("product", url, item))
    if crit.get("enabled"):
        for entry in crit.get("search_urls") or []:
            jobs.append(("listing", entry if isinstance(entry, str) else entry["url"], {}))
    for q in cfg["brands"].get("lenovo") or []:
        jobs.append(("lenovo", q, {}))
    for q in cfg["brands"].get("hp") or []:
        jobs.append(("hp", q, {}))
    print(f"Checking {len(jobs)} pages/queries...")
    results = run_jobs(jobs, history)

    candidates = {}  # pid -> {p, reasons, label, needs_page}
    health, watch_ids, seen = [], set(), set()

    def consider(p, rec, source, label=None, target=None, needs_page=False):
        """Record price; queue an alert if it's a deal on a laptop meeting your specs."""
        reasons = deals.evaluate(history, p, s, source, target, budget_max)
        limit = max(budget_max or 0, target or 0) or None
        if reasons and rec.get("match") and p.in_stock and (limit is None or p.price <= limit):
            candidates[p.id] = {"p": p, "reasons": reasons, "label": label, "needs_page": needs_page}

    for (kind, target, meta), products, err in results:
        src_key = target if kind in ("product", "listing") else f"{kind}: {target}"
        msg = deals.record_source(history, src_key, err is None, err, s)
        if msg:
            health.append(msg)
        label = src_key if kind in ("lenovo", "hp") else store_name(target)
        if err:
            print(f"  ✗ {src_key[:90]}\n      {err}")
            continue
        if kind == "product":
            p = products[0]
            watch_ids.add(p.id)
            seen.add(p.id)
            ok, sp, why = specs.check(p.title, spec_cfg, p.url)
            rec = deals.record(history, p, kind="watch", name=meta.get("name"), target=meta.get("target_price"),
                               store=store_name(target), specs=sp, in_stock=p.in_stock, match=True, why_not=None)
            stock = "" if p.in_stock else "  [OUT OF STOCK]"
            print(f"  ✓ {deals.inr(p.price):>10}  {store_name(target):<16} {meta.get('name', p.title)[:60]}{stock}")
            if p.in_stock:
                consider(p, rec, "page", meta.get("name"), meta.get("target_price"))
            continue

        n_all = n_match = 0
        for p in products:
            if p.id in seen or not in_track_range(p.price, budget) or excluded(p.title, crit):
                continue
            seen.add(p.id)
            n_all += 1
            ok, sp, why = specs.check(p.title, spec_cfg, p.url)
            prev = history["products"].get(p.id) or {}
            if prev.get("specs_failed"):
                ok, why = False, prev["specs_failed"]
            n_match += ok
            rec = deals.record(history, p, kind=prev.get("kind", "criteria"), store=store_name(p.url), specs=sp,
                               match=bool(ok), why_not=None if ok else why, in_stock=p.in_stock)
            if not ok:
                rec["match"] = False
            if p.id.startswith(BRAND_PREFIXES):
                consider(p, rec, "page")  # brand-store API prices are authoritative
            elif rec.get("has_page"):
                rec["listing_price"] = p.price
                if ok and p.price < (rec.get("last") or p.price) * 0.97:
                    candidates.setdefault(p.id, {"p": p, "reasons": [], "label": None, "needs_page": True})
            else:
                consider(p, rec, "listing", needs_page=True)
        print(f"  ✓ {label:<22.22} {len(products):>3} found, {n_all:>3} tracked, {n_match:>3} meet your specs")

    # -- 2. product-page checks: deal candidates + round-robin refresh of spec-matching laptops
    to_check = {pid: c["p"].url for pid, c in candidates.items() if c["needs_page"]}
    tracked = sorted((rec.get("last_verified", ""), pid) for pid, rec in history["products"].items()
                     if pid in seen and pid not in to_check and pid not in watch_ids and rec.get("match")
                     and not pid.startswith(BRAND_PREFIXES))
    queues = defaultdict(list)
    for _, pid in tracked:
        queues[pid.split(":", 1)[0]].append(pid)
    picked = []
    while len(picked) < s["refresh_per_run"] and any(queues.values()):
        for q in queues.values():
            if q and len(picked) < s["refresh_per_run"]:
                picked.append(q.pop(0))
    for pid in picked:
        to_check[pid] = history["products"][pid]["url"]
    if to_check:
        print(f"\nChecking {len(to_check)} product pages...")
    for (_, url, meta), products, err in run_jobs([("product", u, {"pid": pid}) for pid, u in to_check.items()], history):
        pid = meta["pid"]
        cand = candidates.get(pid)
        rec = history["products"][pid]
        rec["last_verified"] = deals.now().isoformat()
        if err or not products:
            print(f"  ✗ {url[:80]}: {err}")
            rec["page_error"] = err
            continue
        rec.pop("page_error", None)
        vp = products[0]
        vp.id = pid
        ok, sp, why = specs.check(vp.title, spec_cfg, vp.url) if len(vp.title) > 40 else (True, rec.get("specs"), "")
        if not ok and "GPU" not in why and "no RTX" not in why:
            rec.update(specs_failed=why, match=False, why_not=why)
            print(f"  ✗ specs: {why}: {vp.title[:70]}")
            candidates.pop(pid, None)
            continue
        if ok and sp:
            rec["specs"] = sp
        if len(vp.title) > len(rec.get("title", "")):
            rec["title"] = vp.title[:200]
        rec["in_stock"] = vp.in_stock
        listing_price = cand["p"].price if cand else None
        candidates.pop(pid, None)
        if not vp.in_stock:
            continue
        vp.mrp = vp.mrp or (cand["p"].mrp if cand else None) or rec.get("mrp")
        reasons = deals.evaluate(history, vp, s, "page", None, budget_max)
        if cand and not reasons and cand["reasons"] and listing_price and vp.price <= listing_price * 1.02:
            reasons = cand["reasons"]  # first page reading = baseline; keep the search-page reasons
        if reasons and budget_max and vp.price <= budget_max:
            candidates[pid] = {"p": vp, "reasons": reasons, "label": None, "needs_page": False}
            print(f"  ★ {deals.inr(vp.price)}  {vp.title[:70]}")
        else:
            print(f"  · {deals.inr(vp.price):>10}  {store_name(url):<16} {rec.get('title', '')[:60]}")

    # -- 3. backfill real past prices from pricehistory.app (Amazon/Flipkart only)
    todo = [(not rec.get("match"), rec.get("kind") != "watch", pid) for pid, rec in history["products"].items()
            if pid in seen and "ph_checked" not in rec and pricehistory.supported(rec.get("url", ""))]
    todo.sort()
    if todo and backfill_n:
        print(f"\nBackfilling price history for {min(backfill_n, len(todo))} of {len(todo)} laptops...")
    for _, _, pid in todo[:backfill_n]:
        rec = history["products"][pid]
        rec["ph_checked"] = deals.now().isoformat()
        try:
            ph = pricehistory.lookup(rec["url"])
        except Exception as e:
            print(f"  ✗ {rec.get('title', pid)[:50]}: {e}")
            continue
        if not ph or not ph["days"]:
            print(f"  – not on pricehistory.app: {rec.get('title', pid)[:60]}")
            continue
        rec["hist"] = ph["days"]
        rec.update(ph_url=ph["url"], ath_low=ph["ath_low"], ath_low_on=ph["ath_low_on"], ath_high=ph["ath_high"])
        print(f"  ✓ {len(ph['days']):>4} days, all-time low {deals.inr(ph['ath_low'])}: {rec.get('title', pid)[:55]}")
        time.sleep(1)

    # -- 4. send
    to_send = []
    for pid, c in candidates.items():
        if c["needs_page"] or not c["reasons"] or not deals.should_alert(history, pid, c["p"].price, s):
            continue
        a = build_alert(c["p"], c["reasons"], history["products"][pid], c["label"], dashboard)
        to_send.append((pid, c["p"].price, a))
    to_send = to_send[: s["max_alerts_per_run"]]

    print(f"\n{len(to_send)} deal alert(s), {len(health)} health message(s)")
    for pid, price, a in to_send:
        text = telegram.deal_message(a)
        if dry_run:
            print("\n--- would send ---\n" + text)
            continue
        try:
            telegram.send(text)
            deals.mark_alerted(history, pid, price)
            history["products"][pid]["last_alert"] = deals.now().isoformat()
        except Exception as e:
            print(f"  Telegram send failed: {e}")
    for msg in health:
        if dry_run:
            print("\n--- would send ---\n" + msg)
            continue
        try:
            telegram.send("⚠️ " + telegram.esc(msg))
        except Exception as e:
            print(f"  Telegram send failed: {e}")
    history["meta"]["last_run"] = deals.now().isoformat()
    history["meta"]["budget_max"] = budget_max


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-telegram", action="store_true")
    ap.add_argument("--backfill", type=int, default=None)
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--history", default=os.path.join(ROOT, "data", "history.json"))
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    load_env_file(os.path.join(ROOT, ".env"))

    if a.test_telegram:
        telegram.send("✅ <b>Lappy deal bot is connected.</b>\nLaptop deal alerts will arrive in this chat.")
        print("Sent.")
        return

    cfg = load_config(a.config)
    history = deals.load_history(a.history)
    t0 = datetime.now()
    backfill_n = a.backfill if a.backfill is not None else cfg["settings"]["backfill_per_run"]
    run(cfg, history, a.dry_run, backfill_n)
    print(f"Run took {(datetime.now() - t0).seconds}s")
    if not a.dry_run:
        deals.save_history(a.history, history)
        print(f"History saved to {a.history}")


if __name__ == "__main__":
    main()

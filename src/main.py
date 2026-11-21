"""Laptop deal checker: fetch -> evaluate -> notify -> save (+ dashboard data).

Usage:
  python src/main.py                     normal run (sends WhatsApp alerts, saves history)
  python src/main.py --dry-run           print prices & would-be alerts; send/save nothing
  python src/main.py --test-whatsapp     send a test alert to your WhatsApp
  python src/main.py --create-wa-templates   submit the 2 message templates to Meta
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

import deals  # noqa: E402
import specs  # noqa: E402
import whatsapp  # noqa: E402
from extract import extract_listing, extract_product, store_name, store_of  # noqa: E402
from fetch import FetchError, get  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_SETTINGS = {
    "drop_pct_vs_median": 8,
    "median_window_days": 30,
    "min_days_for_median": 3,
    "new_low_min_drop_pct": 2,
    "realert_hours": 168,
    "fail_alert_after": 6,
    "max_alerts_per_run": 10,
    "refresh_per_run": 8,
}


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["settings"] = {**DEFAULT_SETTINGS, **(cfg.get("settings") or {})}
    cfg["watchlist"] = cfg.get("watchlist") or []
    cfg["criteria"] = cfg.get("criteria") or {"enabled": False}
    cfg["specs"] = cfg.get("specs") or {}
    cfg["budget"] = cfg.get("budget") or {}
    return cfg


# ------------------------------------------------------------------ fetching (parallel per store)

def run_jobs(jobs):
    """jobs: list of (kind, url, meta) with kind 'product' or 'listing'.
    Same-store jobs run sequentially (polite); different stores in parallel.
    Returns list of (job, products|None, error|None)."""
    by_store = defaultdict(list)
    for j in jobs:
        by_store[store_of(j[1])].append(j)

    def worker(store_jobs):
        out = []
        for i, (kind, url, meta) in enumerate(store_jobs):
            if i:
                time.sleep(1.5 + random.random() * 2)
            try:
                html = get(url)
                if kind == "product":
                    p = extract_product(url, html)
                    if p is None:
                        raise FetchError("page loaded but no price found (layout changed or unavailable)")
                    out.append(((kind, url, meta), [p], None))
                else:
                    items = extract_listing(url, html)
                    if not items:
                        raise FetchError("page loaded but no products found (layout changed?)")
                    out.append(((kind, url, meta), items, None))
            except FetchError as e:
                out.append(((kind, url, meta), None, str(e)))
            except Exception as e:  # parsing bugs shouldn't kill the whole run
                out.append(((kind, url, meta), None, f"{type(e).__name__}: {e}"[:200]))
        return out

    results = []
    if not jobs:
        return results
    with ThreadPoolExecutor(max_workers=len(by_store)) as ex:
        for out in ex.map(worker, by_store.values()):
            results.extend(out)
    return results


# ------------------------------------------------------------------ helpers

def in_track_range(price, budget):
    return budget.get("track_min_price", 0) <= price <= budget.get("track_max_price", 10**9)


def excluded(title, crit):
    t = title.lower()
    return any(x.lower() in t for x in crit.get("exclude", []))


def build_alert(p, reasons, rec, label=None):
    title = label or p.title
    spec_s = specs.short(rec.get("specs") or {})
    mrp = ""
    if p.mrp and p.mrp > p.price:
        mrp = f" (MRP {deals.inr(p.mrp)}, {round((p.mrp - p.price) / p.mrp * 100)}% off)"
    why = "; ".join(reasons)
    text = (f"🔥 Laptop price alert\n\n*{title[:150]}*\n"
            f"Price: {deals.inr(p.price)}{mrp} at {store_name(p.url)}\n"
            f"Specs: {spec_s}\nWhy: {why}\n\nOpen: {p.url}\n"
            f"(Bank/card offers not included. Check the page before buying.)")
    return {"title": title[:150], "price": deals.inr(p.price) + mrp, "store": store_name(p.url),
            "specs": spec_s, "why": why, "url": p.url, "text": text}


# ------------------------------------------------------------------ main run

def run(cfg, history, dry_run):
    s, crit, spec_cfg, budget = cfg["settings"], cfg["criteria"], cfg["specs"], cfg["budget"]
    budget_max = budget.get("max_price")
    history["meta"]["last_run_started"] = deals.now().isoformat()

    # -- 1. watchlist product pages + search pages
    jobs = []
    for item in cfg["watchlist"]:
        for url in item.get("urls") or []:
            jobs.append(("product", url, item))
    if crit.get("enabled"):
        for entry in crit.get("search_urls") or []:
            e = entry if isinstance(entry, dict) else {"url": entry}
            jobs.append(("listing", e["url"], e))
    print(f"Checking {len(jobs)} pages...")
    results = run_jobs(jobs)

    candidates = {}  # pid -> dict(product, reasons, label, needs_page)
    health = []
    watch_ids = set()
    listing_ids = set()

    for (kind, url, meta), products, err in results:
        msg = deals.record_source(history, url, err is None, err, s)
        if msg:
            health.append(msg)
        if err:
            print(f"  ✗ {url}\n      {err}")
            continue
        if kind == "product":
            p = products[0]
            watch_ids.add(p.id)
            ok, sp, _ = specs.check(p.title, spec_cfg, p.url)
            rec = deals.record(history, p, kind="watch", name=meta.get("name"), target=meta.get("target_price"),
                               store=store_name(url), specs=sp, in_stock=p.in_stock)
            stock = "" if p.in_stock else "  [OUT OF STOCK]"
            print(f"  ✓ {deals.inr(p.price):>10}  {store_name(url):<16} {meta.get('name', p.title)[:60]}{stock}")
            if not p.in_stock:
                continue
            reasons = deals.evaluate(history, p, s, "page", meta.get("target_price"), budget_max)
            limit = max(budget_max or 0, meta.get("target_price") or 0) or None
            if reasons and (limit is None or p.price <= limit):
                candidates[p.id] = {"p": p, "reasons": reasons, "label": meta.get("name"), "needs_page": False}
        else:
            n_match = 0
            for p in products:
                if p.id in watch_ids or p.id in listing_ids or not p.in_stock:
                    continue
                if not in_track_range(p.price, budget) or excluded(p.title, crit):
                    continue
                ok, sp, _ = specs.check(p.title, spec_cfg, p.url)
                if not ok:
                    continue
                rec_existing = history["products"].get(p.id)
                if rec_existing and rec_existing.get("specs_failed"):
                    continue  # product page showed it doesn't meet specs
                listing_ids.add(p.id)
                n_match += 1
                kind_ = (rec_existing or {}).get("kind", "criteria")
                rec = deals.record(history, p, kind=kind_, store=store_name(p.url), specs=sp)
                if rec.get("has_page"):
                    # Series is product-page based; a noticeably lower search price -> re-check now.
                    if p.price < rec.get("last", p.price) * 0.97:
                        candidates.setdefault(p.id, {"p": p, "reasons": [], "label": None, "needs_page": True})
                    continue
                reasons = deals.evaluate(history, p, s, "listing", None, budget_max)
                if reasons and budget_max and p.price <= budget_max:
                    candidates[p.id] = {"p": p, "reasons": reasons, "label": None, "needs_page": True}
            print(f"  ✓ {store_name(meta['url']):<16} {len(products):>3} products, {n_match:>3} match your specs  ({meta['url'][:60]})")

    # -- 2. product-page checks: alert candidates + round-robin refresh of tracked laptops
    to_check = {pid: c["p"].url for pid, c in candidates.items() if c["needs_page"]}
    tracked = [(rec.get("last_verified", ""), pid) for pid, rec in history["products"].items()
               if pid in listing_ids and pid not in to_check and not rec.get("specs_failed")]
    tracked.sort()
    # Spread the refresh across stores (they're fetched in parallel, one store at a time each).
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
        print(f"\nChecking {len(to_check)} product pages ({sum(c['needs_page'] for c in candidates.values())} possible deals)...")
    page_results = run_jobs([("product", url, {"pid": pid}) for pid, url in to_check.items()])
    for (_, url, meta), products, err in page_results:
        pid = meta["pid"]
        cand = candidates.get(pid)
        if err or not products:
            print(f"  ✗ {url[:80]}: {err}")
            rec = history["products"].get(pid)
            if rec is not None:  # don't retry the same failing page every run
                rec["last_verified"] = deals.now().isoformat()
                rec["page_error"] = err
            continue  # unverified -> no alert
        vp = products[0]
        rec = history["products"][pid]
        rec.pop("page_error", None)
        vp.id = pid  # keep the id from the search page (same product)
        ok, sp, why_not = specs.check(vp.title, spec_cfg, vp.url) if len(vp.title) > 40 else (True, rec.get("specs"), "")
        if not ok and "GPU" not in why_not and "no RTX" not in why_not:
            rec["specs_failed"] = why_not
            print(f"  ✗ specs: {why_not}: {vp.title[:70]}")
            candidates.pop(pid, None)
            continue
        if ok and sp:
            rec["specs"] = sp
        if len(vp.title) > len(rec.get("title", "")):
            rec["title"] = vp.title[:200]
        rec["in_stock"] = vp.in_stock
        if not vp.in_stock:
            candidates.pop(pid, None)
            continue
        listing_price = cand["p"].price if cand else None
        reasons = deals.evaluate(history, vp, s, "page", None, budget_max)
        if cand and not reasons and cand["reasons"] and listing_price and vp.price <= listing_price * 1.02:
            reasons = cand["reasons"]  # first page reading is a baseline; keep the search-page reasons
        if reasons and budget_max and vp.price <= budget_max:
            vp.mrp = vp.mrp or (cand["p"].mrp if cand else None) or rec.get("mrp")
            candidates[pid] = {"p": vp, "reasons": reasons, "label": None, "needs_page": False, "verified": True}
            print(f"  ★ {deals.inr(vp.price)}  {vp.title[:70]}")
        else:
            candidates.pop(pid, None)
            print(f"  · {deals.inr(vp.price):>10}  {store_name(url):<16} {rec.get('title', '')[:60]}")

    # -- 3. send
    to_send = []
    for pid, c in candidates.items():
        if c["needs_page"] and not c.get("verified"):
            continue  # couldn't confirm on the product page
        if not c["reasons"] or not deals.should_alert(history, pid, c["p"].price, s):
            continue
        to_send.append(build_alert(c["p"], c["reasons"], history["products"][pid], c["label"]) | {"pid": pid, "price_n": c["p"].price})
    to_send = to_send[: s["max_alerts_per_run"]]

    print(f"\n{len(to_send)} deal alert(s), {len(health)} health message(s)")
    for a in to_send:
        if dry_run:
            print("\n--- would send ---\n" + a["text"])
            continue
        try:
            whatsapp.send_deal(a)
            deals.mark_alerted(history, a["pid"], a["price_n"])
            history["products"][a["pid"]]["last_alert"] = deals.now().isoformat()
        except Exception as e:
            print(f"  WhatsApp send failed: {e}")
    for msg in health:
        if dry_run:
            print("\n--- would send ---\n" + msg)
            continue
        try:
            whatsapp.send_notice(msg)
        except Exception as e:
            print(f"  WhatsApp send failed: {e}")
    history["meta"]["last_run"] = deals.now().isoformat()
    history["meta"]["budget_max"] = budget_max


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-whatsapp", action="store_true")
    ap.add_argument("--create-wa-templates", action="store_true")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--history", default=os.path.join(ROOT, "data", "history.json"))
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if a.create_wa_templates:
        whatsapp.create_templates()
        return
    if a.test_whatsapp:
        whatsapp.send_deal({
            "title": "TEST: laptop deal bot is connected", "price": "₹1,39,990", "store": "Flipkart",
            "specs": "Ryzen 7 250 · RTX 5060 · 16GB · 512GB SSD", "why": "This is a test message",
            "url": "https://github.com/PrajasW/lappy", "text": "✅ Laptop deal bot is connected. Deal alerts will arrive here.",
        })
        print("Sent.")
        return

    cfg = load_config(a.config)
    history = deals.load_history(a.history)
    t0 = datetime.now()
    run(cfg, history, a.dry_run)
    print(f"Run took {(datetime.now() - t0).seconds}s")
    if not a.dry_run:
        deals.save_history(a.history, history)
        print(f"History saved to {a.history}")


if __name__ == "__main__":
    main()

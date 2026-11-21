"""Price history + deal rules + alert de-duplication.

History is stored compactly: one lowest-price-of-the-day per product per day,
so data/history.json stays small even with many products over months.

Each product has one price series. It starts from search-page prices; the first
time the product page is checked, the series switches to product-page prices
only (search pages on some stores show stale/different prices, and mixing the
two would create fake "drops").
"""
import json
import os
import statistics
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
KEEP_DAYS = 120          # the bot's own daily readings
HIST_KEEP_DAYS = 400     # backfilled history from price-tracker sites
FORGET_AFTER_DAYS = 30  # drop products not seen on any page for this long


def now() -> datetime:
    return datetime.now(IST)


def today() -> str:
    return now().strftime("%Y-%m-%d")


def load_history(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
    else:
        h = {}
    for k in ("products", "alerts", "sources", "meta"):
        h.setdefault(k, {})
    return h


def save_history(path: str, h: dict) -> None:
    cutoff = (now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    forget = (now() - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    for pid in list(h["products"]):
        rec = h["products"][pid]
        rec["days"] = {d: p for d, p in rec.get("days", {}).items() if d >= cutoff}
        hist_cutoff = (now() - timedelta(days=HIST_KEEP_DAYS)).strftime("%Y-%m-%d")
        if rec.get("hist"):
            rec["hist"] = {d: p for d, p in rec["hist"].items() if d >= hist_cutoff}
        if not rec["days"] or rec.get("last_seen", "") < forget:
            del h["products"][pid]
    alert_cutoff = (now() - timedelta(days=30)).isoformat()
    h["alerts"] = {k: v for k, v in h["alerts"].items() if v.get("ts", "") >= alert_cutoff}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def record(h: dict, product, **fields) -> dict:
    """Create/update a product record's descriptive fields (not its price)."""
    rec = h["products"].setdefault(product.id, {"days": {}, "first_seen": now().isoformat()})
    if product.title and len(product.title) >= len(rec.get("title", "")) or not rec.get("title"):
        rec["title"] = product.title[:200]
    rec["url"] = product.url
    rec["last_seen"] = now().isoformat()
    for k, v in fields.items():
        if v is not None:
            rec[k] = v
    if product.mrp:
        rec["mrp"] = product.mrp
    return rec


def evaluate(h: dict, product, settings: dict, source: str, target: int | None = None,
             budget_max: int | None = None) -> list[str]:
    """Record a price (source = 'page' or 'listing') and return the reasons it's a deal."""
    rec = h["products"][product.id]
    price = product.price

    if source == "listing" and rec.get("has_page"):
        rec["listing_price"] = price  # informational; the series is page-only now
        return []
    if source == "page":
        rec["last_verified"] = now().isoformat()
        if not rec.get("has_page"):
            # Switch the series to product-page prices (drop search-page readings).
            rec["has_page"] = True
            rec["days"] = {}
            rec["last"] = None  # a search-page price must not count as "previous price"
            if not rec.get("hist"):
                rec["days"] = {today(): price}  # no tracker history: first reading is a silent baseline
                rec["last"] = price
                return []
            # With tracker history we can judge this price right away (falls through).

    days: dict = rec["days"]
    day = today()
    prev_last = rec.get("last")
    combined = combined_days(rec)  # backfilled tracker history + our own readings
    previous_low = min(combined.values()) if combined else None
    window_start = (now() - timedelta(days=settings["median_window_days"])).strftime("%Y-%m-%d")
    past = [p for d, p in combined.items() if window_start <= d < day]
    days[day] = min(price, days.get(day, price))
    rec["last"] = price

    reasons = []
    if target and price <= target:
        reasons.append(f"At/below your target of {inr(target)}")
    if budget_max and prev_last and prev_last > budget_max >= price:
        reasons.append(f"Just dropped into your budget (was {inr(prev_last)})")
    if previous_low is not None and price <= previous_low * (1 - settings["new_low_min_drop_pct"] / 100):
        reasons.append(f"Lowest price seen so far (previous low {inr(previous_low)})")
    if len(past) >= settings["min_days_for_median"]:
        med = statistics.median(past)
        drop = (med - price) / med * 100
        if drop >= settings["drop_pct_vs_median"]:
            reasons.append(f"{drop:.0f}% below its usual {inr(int(med))} (last {settings['median_window_days']} days)")
    return reasons


def combined_days(rec: dict) -> dict:
    """Price-tracker history (older) overlaid with the bot's own readings (authoritative)."""
    return {**(rec.get("hist") or {}), **(rec.get("days") or {})}


def should_alert(h: dict, pid: str, price: int, settings: dict) -> bool:
    """Skip repeats: same product, not cheaper than last alert, within the quiet window."""
    last = h["alerts"].get(pid)
    if not last:
        return True
    if price < last["price"] * 0.99:  # got meaningfully cheaper -> alert again
        return True
    return now() - datetime.fromisoformat(last["ts"]) > timedelta(hours=settings["realert_hours"])


def mark_alerted(h: dict, pid: str, price: int) -> None:
    h["alerts"][pid] = {"ts": now().isoformat(), "price": price}


def record_source(h: dict, url: str, ok: bool, error: str | None, settings: dict) -> str | None:
    """Track consecutive failures per URL. Returns a health message to send, if any."""
    src = h["sources"].setdefault(url, {"fails": 0, "warned": False})
    if ok:
        msg = f"Working again: {url}" if src["warned"] else None
        src.update(fails=0, warned=False, last_ok=now().isoformat())
        src.pop("last_error", None)
        return msg
    src["fails"] += 1
    src["last_error"] = error
    if src["fails"] >= settings["fail_alert_after"] and not src["warned"]:
        src["warned"] = True
        return (f"Could not check a page {src['fails']} times in a row ({error}). "
                f"Deals from it may be missed: {url}")
    return None


def inr(n: int | float | None) -> str:
    """Indian digit grouping: 123456 -> ₹1,23,456."""
    if n is None:
        return "?"
    s = str(int(round(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return "₹" + s

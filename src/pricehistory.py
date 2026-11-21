"""Backfill real past prices from pricehistory.app (supports Amazon.in and Flipkart).

lookup(url) -> {"code", "days": {YYYY-MM-DD: lowest price that day}, "ath_low", "ath_low_on", "ath_high"}
"""
import re
import time

from curl_cffi import requests

BASE = "https://pricehistory.app"
SUPPORTED = ("amazon.in", "flipkart.com")


def supported(url: str) -> bool:
    return any(d in url for d in SUPPORTED)


def lookup(url: str) -> dict | None:
    if not supported(url):
        return None
    s = requests.Session(impersonate="chrome124")
    r = s.post(f"{BASE}/api/search", json={"url": url}, timeout=30)
    if r.status_code != 200 or not r.json().get("status"):
        return None
    code = r.json()["code"]
    page_url = f"{BASE}/p/{code}"
    time.sleep(1)
    html = s.get(page_url, timeout=30).text
    page = re.search(r'append\("page","([^"]+)"\)', html)
    token = re.search(r'append\("token","([^"]+)"\)', html)
    if not (page and token):
        return None
    time.sleep(1)
    r = s.post(f"{BASE}/api/price/{page.group(1)}", timeout=30,
               headers={"Content-Type": "application/json", "page": page.group(1),
                        "token": token.group(1), "Referer": page_url})
    if r.status_code != 200:
        return None
    data = r.json()
    days: dict[str, int] = {}
    for pt in (data.get("History") or {}).get("Price") or []:
        try:
            d, p = str(pt["x"])[:10], int(pt["y"])
        except (KeyError, ValueError, TypeError):
            continue
        if 1000 <= p <= 2_000_000:
            days[d] = min(p, days.get(d, p))
    summary = data.get("Price") or {}
    return {
        "code": code,
        "url": page_url,
        "days": days,
        "ath_low": summary.get("MinPrice"),
        "ath_low_on": str(summary.get("MinPriceOn") or "")[:10] or None,
        "ath_high": summary.get("MaxPrice"),
    }

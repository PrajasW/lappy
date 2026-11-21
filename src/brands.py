"""Official brand stores: Lenovo India and HP India (both have public JSON APIs).

Each returns extract.Product objects whose title is "<name> | <cpu> | <gpu> | <ram> | <ssd>"
so specs.parse() can read them like any store title.

Not supported (checked Nov 2026): Acer store (blocks bots), Dell India (now redirects
to a reseller store), ASUS eShop India (no stable listing URL), MSI/Gigabyte (don't sell direct).
"""
import re
import time
import urllib.parse

from curl_cffi import requests

from extract import Product, parse_price

UA = "chrome124"


# --------------------------------------------------------------------------- Lenovo

def lenovo_search(query: str, rows: int = 40) -> list[Product]:
    s = requests.Session(impersonate=UA)
    url = ("https://openapi.lenovo.com/in/en/ofp/search/global/cache/products/get/_tsc?"
           + urllib.parse.urlencode({"text": query, "rows": rows, "sort": "Recomm"}))
    r = s.get(url, headers={"Referer": "https://www.lenovo.com/", "Origin": "https://www.lenovo.com"}, timeout=30)
    r.raise_for_status()
    out = []

    def walk(o):
        if isinstance(o, dict):
            if "finalPrice" in o and "productCode" in o:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)

    for d in walk(r.json()):
        if not str(d.get("url", "")).startswith("/p/laptops/"):
            continue
        spec = {c.get("a"): c.get("b") for c in d.get("classification") or [] if isinstance(c, dict)}
        summary = re.sub(r"^Lenovo\s+", "", str(d.get("summary") or d.get("productName") or ""))
        parts = [f"Lenovo {summary}".strip()]
        for k in ("Processor", "Graphic Card", "Graphics", "Memory", "Storage", "Hard Drive"):
            if spec.get(k):
                parts.append(re.sub(r"<[^>]+>", " ", str(spec[k])))
        price = parse_price(d.get("finalPrice"))
        if not price:
            continue
        code = str(d["productCode"]).lower()
        out.append(Product(
            id=f"lenovo.com:{code}",
            title=" | ".join(parts)[:400],
            url="https://www.lenovo.com/in/en" + d["url"],
            price=price,
            mrp=parse_price(d.get("webPrice")),
            in_stock=str(d.get("marketingStatus", "")).lower() == "available" and d.get("inventoryStatus", 1) != 0,
        ))
    return out


# --------------------------------------------------------------------------- HP

HP_GQL = "https://www.hp.com/in-en/shop/graphql"


def _hp_specs_from_page(html: str) -> str:
    """Pull CPU / GPU / RAM / SSD strings from an HP product page."""
    t = re.sub(r"<[^>]+>", " ", html).replace("™", "").replace("®", "")
    t = re.sub(r"\s+", " ", t)
    found = []
    for pat in (r"AMD Ryzen\s*(?:AI\s*)?\d\s*(?:-\s*)?\d{3,4}[A-Z]{0,3}",
                r"Intel Core\s*(?:Ultra\s*)?i?\d[\s-]*\d{3,5}[A-Z]{0,2}",
                r"RTX\s*\d{4}(?:\s*Ti)?",
                r"\d{1,2}\s*GB\s*(?:LP)?DDR\d",
                r"\d+(?:\.\d)?\s*(?:GB|TB)\s*(?:PCIe\s*)?(?:Gen\d\s*)?(?:NVMe\s*)?(?:TLC\s*)?(?:M\.2\s*)?SSD"):
        m = re.search(pat, t, re.I)
        if m:
            found.append(m.group(0).replace(" - ", " "))
    return " | ".join(found)


def hp_search(query: str, spec_cache: dict) -> list[Product]:
    """spec_cache: {product_id: spec_text}; filled for new products (one page fetch each)."""
    s = requests.Session(impersonate=UA)
    q = ('{products(search:%s,pageSize:60){items{name sku url_key stock_status '
         'price_range{minimum_price{final_price{value} regular_price{value}}}}}}') % _gql_str(query)
    r = s.get(HP_GQL + "?query=" + urllib.parse.quote(q), timeout=30)
    r.raise_for_status()
    items = ((r.json().get("data") or {}).get("products") or {}).get("items") or []
    out = []
    for it in items:
        if not str(it.get("url_key", "")).startswith("products/laptops/"):
            continue
        pid = f"hp.com:{it['sku'].lower()}"
        url = f"https://www.hp.com/in-en/shop/{it['url_key']}"
        if pid not in spec_cache:
            try:
                time.sleep(1)
                spec_cache[pid] = _hp_specs_from_page(s.get(url, timeout=30).text)
            except Exception:
                spec_cache[pid] = ""
        pr = (it.get("price_range") or {}).get("minimum_price") or {}
        price = parse_price((pr.get("final_price") or {}).get("value"))
        if not price:
            continue
        out.append(Product(
            id=pid,
            title=f"HP {it['name']} | {spec_cache[pid]}"[:400],
            url=url,
            price=price,
            mrp=parse_price((pr.get("regular_price") or {}).get("value")),
            in_stock=it.get("stock_status") == "IN_STOCK",
        ))
    return out


def _gql_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

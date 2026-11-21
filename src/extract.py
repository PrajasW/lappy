"""Turn store HTML into products: (id, title, url, price, mrp).

Two entry points:
  extract_product(url, html)  -> one product (watchlist pages)
  extract_listing(url, html)  -> many products (search / category pages)
"""
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

PRICE_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.\d{1,2})?)")


@dataclass
class Product:
    id: str
    title: str
    url: str
    price: int | None
    mrp: int | None = None
    in_stock: bool = True


# --------------------------------------------------------------------------- stores

STORE_DOMAINS = {
    "amazon.in": "amazon",
    "flipkart.com": "flipkart",
    "croma.com": "croma",
    "vijaysales.com": "vijaysales",
    "reliancedigital.in": "reliance",
    "tatacliq.com": "tatacliq",
}

STORE_NAMES = {
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "croma": "Croma",
    "vijaysales": "Vijay Sales",
    "reliance": "Reliance Digital",
    "tatacliq": "Tata CLiQ",
}


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def store_of(url: str) -> str:
    d = domain_of(url)
    for dom, key in STORE_DOMAINS.items():
        if d == dom or d.endswith("." + dom):
            return key
    return d  # brand stores etc.: the domain is the store name


def store_name(url: str) -> str:
    s = store_of(url)
    return STORE_NAMES.get(s, s)


def product_id(url: str) -> str | None:
    """Stable product id from a product URL, or None if it isn't a product URL."""
    store = store_of(url)
    p = urlparse(url)
    path = p.path
    if store == "amazon":
        m = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", path)
        return f"amazon:{m.group(1)}" if m else None
    if store == "flipkart":
        if "/p/itm" not in path:
            return None
        pid = parse_qs(p.query).get("pid", [None])[0]
        return f"flipkart:{pid or path.rsplit('/', 1)[-1]}"
    if store == "croma":
        m = re.search(r"/p/(\d+)", path)
        return f"croma:{m.group(1)}" if m else None
    if store == "vijaysales":
        m = re.match(r"^/(?:p/)?(\d{5,})/", path)
        return f"vijaysales:{m.group(1)}" if m else None
    if store == "reliance":
        m = re.match(r"^/product/([^/?#]+)", path)
        return f"reliance:{m.group(1)}" if m else None
    if store == "tatacliq":
        m = re.search(r"/p-(mp\d+)", path, re.I)
        return f"tatacliq:{m.group(1).lower()}" if m else None
    return f"{store}:{path.rstrip('/')}"


def canonical_url(url: str) -> str:
    """Clean product URL (drops tracking params)."""
    store = store_of(url)
    pid = product_id(url)
    if store == "amazon" and pid:
        return f"https://www.amazon.in/dp/{pid.split(':', 1)[1]}"
    p = urlparse(url)
    if store == "flipkart":
        pid_q = parse_qs(p.query).get("pid", [None])[0]
        q = f"?pid={pid_q}" if pid_q else ""
        return f"https://{p.netloc}{p.path}{q}"
    return f"https://{p.netloc}{p.path}"


# --------------------------------------------------------------------------- helpers

def parse_price(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = int(round(value))
    else:
        s = str(value)
        m = PRICE_RE.search(s)
        s = m.group(1) if m else s
        s = re.sub(r"[^0-9.]", "", s)
        if not s or s == ".":
            return None
        try:
            v = int(round(float(s)))
        except ValueError:
            return None
    return v if 1000 <= v <= 2_000_000 else None  # sanity range for a laptop


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _js_blobs(html: str):
    """Yield JSON objects assigned to window.__SOMETHING__ in inline scripts."""
    for m in re.finditer(r"window\.(__[A-Z_]+__)\s*=\s*", html):
        start = m.end()
        try:
            obj, _ = json.JSONDecoder().raw_decode(html, start)
            yield obj
            continue
        except ValueError:
            pass
        # Some sites embed JS object literals with `undefined`; patch and retry.
        end = html.find("</script>", start)
        chunk = html[start:end].rstrip().rstrip(";")
        chunk = re.sub(r"(?<=[:\[,])\s*undefined\b", "null", chunk)
        try:
            obj, _ = json.JSONDecoder().raw_decode(chunk)
            yield obj
        except ValueError:
            continue


def _walk(o, depth=0):
    if depth > 60:
        return
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, depth + 1)


# --------------------------------------------------------------------------- product pages

def _jsonld_product(soup) -> tuple[str | None, int | None, int | None, bool | None]:
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw, strict=False)  # strict=False tolerates raw newlines in strings
        except ValueError:
            m = re.search(r'"@type"\s*:\s*"Offer".{0,600}?"price"\s*:\s*"?([0-9.]+)', raw, re.S)
            if m and '"Product"' in raw:
                nm = re.search(r'"name"\s*:\s*"([^"]{5,300})"', raw)
                return (_clean(nm.group(1)) if nm else None), parse_price(m.group(1)), None, None
            continue
        for d in _walk(data):
            t = d.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Product" not in types:
                continue
            offers = d.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers] if offers else []
            prices, stock = [], None
            for off in offer_list:
                if not isinstance(off, dict):
                    continue
                p = parse_price(off.get("price") or off.get("lowPrice"))
                if p:
                    prices.append(p)
                av = str(off.get("availability", ""))
                if av:
                    stock = "InStock" in av or "LimitedAvailability" in av or "PreOrder" in av
            if prices:
                return _clean(d.get("name")), min(prices), None, stock
    return None, None, None, None


def _meta_price(soup) -> int | None:
    for attrs in (
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ):
        tag = soup.find(attrs=attrs)
        if tag:
            p = parse_price(tag.get("content") or tag.get_text())
            if p:
                return p
    return None


def _amazon_product(soup):
    title = _clean(soup.select_one("#productTitle").get_text()) if soup.select_one("#productTitle") else None
    price = None
    for sel in (
        "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#corePrice_feature_div .a-price .a-offscreen",
        "#apex_desktop .a-price .a-offscreen",
        ".priceToPay .a-offscreen",
        "#priceblock_dealprice",
        "#priceblock_ourprice",
    ):
        el = soup.select_one(sel)
        if el and parse_price(el.get_text()):
            price = parse_price(el.get_text())
            break
    if price is None:  # newer layout: whole + fraction spans
        whole = soup.select_one("#corePriceDisplay_desktop_feature_div .a-price-whole")
        if whole:
            price = parse_price(whole.get_text())
    mrp = None
    el = soup.select_one("#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen")
    if el:
        mrp = parse_price(el.get_text())
    avail = soup.select_one("#availability")
    in_stock = True
    if avail and re.search(r"unavailable|out of stock", avail.get_text(), re.I):
        in_stock = False
    if price is None and soup.select_one("#outOfStock"):
        in_stock = False
    return title, price, mrp, in_stock


def _croma_products(html: str):
    """Croma embeds product data in window.__INITIAL_DATA__."""
    out = []
    for blob in _js_blobs(html):
        for d in _walk(blob):
            code, name, price = d.get("code"), d.get("name"), d.get("price")
            if isinstance(code, str) and code.isdigit() and isinstance(name, str) and isinstance(price, dict):
                p = parse_price(price.get("value"))
                if not p:
                    continue
                mrp = parse_price((d.get("mrp") or {}).get("value")) if isinstance(d.get("mrp"), dict) else None
                url = d.get("url") or f"/p/{code}"
                if not str(url).startswith("http"):
                    url = "https://www.croma.com" + (url if url.startswith("/") else "/" + url)
                stock = d.get("stock")
                in_stock = True
                if isinstance(stock, dict) and str(stock.get("stockLevelStatus", "")).lower() == "outofstock":
                    in_stock = False
                out.append(Product(f"croma:{code}", _clean(name), url, p, mrp, in_stock))
    return out


def extract_product(url: str, html: str) -> Product | None:
    store = store_of(url)
    pid = product_id(url) or f"{store}:{urlparse(url).path}"
    soup = _soup(html)

    title = price = mrp = None
    in_stock = None
    if store == "amazon":
        title, price, mrp, in_stock = _amazon_product(soup)
    if store == "croma" and price is None:
        code = pid.split(":", 1)[1]
        for p in _croma_products(html):
            if p.id == f"croma:{code}":
                title, price, mrp, in_stock = p.title, p.price, p.mrp, p.in_stock
                break
    if price is None:
        t2, price, _, s2 = _jsonld_product(soup)
        title = title or t2
        in_stock = in_stock if in_stock is not None else s2
    if price is None:
        price = _meta_price(soup)
    if not title:
        og = soup.find("meta", property="og:title")
        title = _clean(og.get("content")) if og else _clean(soup.title.get_text() if soup.title else "")
    if price is None:
        return None
    return Product(pid, title or url, canonical_url(url), price, mrp, in_stock is not False)


# --------------------------------------------------------------------------- listing pages

def _amazon_listing(soup, base_url):
    out = []
    for card in soup.select('div[data-component-type="s-search-result"][data-asin]'):
        asin = card.get("data-asin")
        if not asin:
            continue
        if card.select_one(".puis-sponsored-label-text, .s-sponsored-label-text"):
            pass  # sponsored items are still real listings; keep them
        h2 = card.select_one("h2")
        title = _clean(h2.get_text(" ") if h2 else "")
        a = card.select_one("h2 a, a.a-link-normal[href*='/dp/']")
        alt_title = _clean(a.get("aria-label")) if a else ""
        title = max([title, alt_title], key=len)
        el = card.select_one(".a-price:not(.a-text-price) .a-offscreen")
        price = parse_price(el.get_text()) if el else None
        el = card.select_one(".a-price.a-text-price .a-offscreen")
        mrp = parse_price(el.get_text()) if el else None
        if price:
            out.append(Product(f"amazon:{asin}", title, f"https://www.amazon.in/dp/{asin}", price, mrp))
    return out


def _generic_listing(soup, base_url):
    """Find product links, then climb to the smallest 'card' holding one product + a price."""
    anchors = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        pid = product_id(href)
        if pid:
            anchors.setdefault(pid, []).append((a, href))

    out = []
    for pid, links in anchors.items():
        # Prefer image alt / title attributes (clean product names) over anchor
        # text, which on some stores contains the whole card (ratings, specs...).
        title, best_rank = "", 99
        for a, _ in links:
            img = a.find("img")
            for rank, cand in enumerate((img.get("alt") if img else None, a.get("title"), a.get("aria-label"), a.get_text(" "))):
                c = _clean(cand)
                c = re.split(r"\s\d(?:\.\d)?\s[\d,]+\sRatings", c)[0]  # Flipkart: cut at "4.2 1,303 Ratings"
                if len(c) < 15 or PRICE_RE.search(c[:20]):
                    continue
                if rank < best_rank or (rank == best_rank and len(c) > len(title)):
                    title, best_rank = c, rank
        price = mrp = None
        for a, _ in links:
            node = a
            for _ in range(10):
                node = node.parent
                if node is None or node.name in ("body", "html"):
                    break
                ids = {product_id(urljoin(base_url, x["href"])) for x in node.find_all("a", href=True)}
                ids.discard(None)
                if len(ids) > 1:
                    break  # climbed into a multi-product container
                prices = [parse_price(m) for m in PRICE_RE.findall(node.get_text(" "))]
                prices = [p for p in prices if p]
                if prices:
                    price = prices[0]
                    if len(prices) > 1 and prices[1] > price:
                        mrp = prices[1]
                    if not title:
                        title = _clean(node.get_text(" "))[:150]
                    break
            if price:
                break
        title = re.sub(r"^(?:Add to Compare|Compare)\s+", "", title, flags=re.I)
        if price and title:
            out.append(Product(pid, title[:250], canonical_url(links[0][1]), price, mrp))
    return out


def _reliance_listing(html):
    out = []
    for blob in _js_blobs(html):
        for d in _walk(blob):
            if not (isinstance(d.get("name"), str) and isinstance(d.get("slug"), str) and isinstance(d.get("price"), dict)):
                continue
            pr = d["price"]
            eff = (pr.get("effective") or {}) if isinstance(pr.get("effective"), dict) else {}
            mk = (pr.get("marked") or {}) if isinstance(pr.get("marked"), dict) else {}
            price = parse_price(eff.get("min") or eff.get("max"))
            mrp = parse_price(mk.get("max") or mk.get("min"))
            if price:
                url = f"https://www.reliancedigital.in/product/{d['slug']}"
                out.append(Product(f"reliance:{d['slug']}", _clean(d["name"]), url, price, mrp, d.get("sellable", True) is not False))
    return out


def extract_listing(url: str, html: str) -> list[Product]:
    store = store_of(url)
    soup = _soup(html)
    items: list[Product] = []
    if store == "amazon":
        items = _amazon_listing(soup, url)
    elif store == "croma":
        items = _croma_products(html)
    elif store == "reliance":
        items = _reliance_listing(html)
    if not items:
        items = _generic_listing(soup, url)
    # de-duplicate by id, keep the lowest price seen on the page
    best: dict[str, Product] = {}
    for p in items:
        if p.id not in best or (p.price or 1e12) < (best[p.id].price or 1e12):
            best[p.id] = p
    return list(best.values())

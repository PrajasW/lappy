"""HTTP fetching with browser impersonation, retries and block detection."""
import random
import time

from curl_cffi import requests

# Different browser TLS fingerprints. Some stores (notably Amazon) randomly
# reject one fingerprint but accept another, so we rotate on failure.
IMPERSONATIONS = ["chrome124", "safari", "edge101", "chrome", "chrome131"]

BLOCK_MARKERS = [
    "api-services-support@amazon.com",  # Amazon robot page
    "Enter the characters you see below",
    "<title>Access Denied</title>",
    "errors.edgesuite.net",  # Akamai block (Croma etc.)
    "Are you a human?",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


class FetchError(Exception):
    pass


def _looks_blocked(status: int, text: str) -> str | None:
    if status in (403, 429, 503):
        return f"HTTP {status}"
    if status >= 400:
        return f"HTTP {status}"
    head = text[:20000]
    for marker in BLOCK_MARKERS:
        if marker in head:
            return f"blocked ({marker[:30]})"
    if len(text) < 2000:
        return "suspiciously small page"
    return None


def get(url: str, attempts: int = 4) -> str:
    """Fetch a page, rotating browser fingerprints until one gets through."""
    last = "unknown error"
    order = IMPERSONATIONS[:]
    random.shuffle(order)
    for i in range(attempts):
        imp = order[i % len(order)]
        try:
            s = requests.Session(impersonate=imp)
            r = s.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
            problem = _looks_blocked(r.status_code, r.text)
            if problem is None:
                return r.text
            last = problem
        except Exception as e:  # network errors, timeouts
            last = f"{type(e).__name__}: {e}"[:200]
        time.sleep(2 + random.random() * 3)
    raise FetchError(last)

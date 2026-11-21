"""Parse laptop specs (CPU / GPU / RAM / SSD) out of store product titles.

Store titles are messy ("Intel Core i7 13th Gen 13645HX - (16 GB/1 TB SSD/...",
"AMD Ryzen 7 250 (Coequal R7 8845HS), 16GB RAM, 512GB SSD", ...), so this is
regex-based and deliberately conservative about the CPU and GPU.
"""
import re

DEFAULT_GPUS = ["5050", "4060", "5060", "4070", "5070", "4080", "5080", "4090", "5090"]


def _cpu(t: str) -> tuple[bool, str | None]:
    """Return (meets 'i7 13th gen+ / Ryzen 7 equivalent' bar, short label)."""
    # --- Intel -------------------------------------------------------------
    m = re.search(r"core\s*(?:\(tm\)|™)?\s*ultra\s*([579])\b\s*(?:\(?series\s*\d\)?\s*)?(?:processor\s*)?(\d{3}[a-z]{0,2})?", t)
    if m:
        tier, model = m.group(1), (m.group(2) or "").upper()
        return tier in "79", f"Core Ultra {tier} {model}".strip()
    m = re.search(r"\bi([3579])[\s-]*(1[0-9])(\d{3})([a-z]{0,2})\b", t)  # i7-13620H, i7 14650HX
    if m:
        tier, gen = m.group(1), int(m.group(2))
        return tier in "79" and gen >= 13, f"i{tier}-{m.group(2)}{m.group(3)}{m.group(4).upper()}"
    m = re.search(r"\bi([3579])\b(?:[^,/|()]{0,40}?)\b(1[0-9])(?:th|st|nd|rd)\s*gen", t) or \
        re.search(r"\b(1[0-9])(?:th|st|nd|rd)\s*gen[^,/|()]{0,40}?\bi([3579])\b", t)
    if m:
        a, b = m.group(1), m.group(2)
        tier, gen = (a, int(b)) if len(a) == 1 else (b, int(a))
        return tier in "79" and gen >= 13, f"i{tier} {gen}th Gen"
    m = re.search(r"\bcore\s*(?:\(tm\)|™)?\s*([3579])\s*(?:processor\s*)?(?:series\s*\d\s*)?(\d{3})([a-z]{0,2})\b", t)
    if m:  # Intel Core 7 240H (Series 1/2/3, no "i")
        tier = m.group(1)
        return tier in "79" and m.group(3) in ("h", "hx", ""), f"Core {tier} {m.group(2)}{m.group(3).upper()}"
    if re.search(r"\bi[79]\b", t):
        return False, "Intel i7 (gen unknown)"
    # --- AMD ---------------------------------------------------------------
    m = re.search(r"ryzen\s*(?:™\s*)?ai\s*(?:max\+?\s*)?([579])\b[^0-9]{0,20}(\d{3})?", t)
    if m:
        tier = m.group(1)
        return tier in "79", f"Ryzen AI {tier} {m.group(2) or ''}".strip()
    m = re.search(r"ryzen\s*(?:™\s*)?([3579])\b(?:\s*(?:octa|hexa)\s*core)?[\s-]*(\d{3,4})([a-z]{0,3})\b", t)
    if m:
        tier, model, suf = m.group(1), m.group(2), m.group(3).upper()
        label = f"Ryzen {tier} {model}{suf}"
        if tier not in "79":
            return False, label
        if len(model) == 3:  # 2025+ naming: 250, 260, 270 (Zen 4) ok; 170 (Zen 3+) not
            return int(model) >= 200, label
        series, num = int(model[0]), int(model[1:])
        if series in (8, 9):  # 8845HS, 8945HS, 9955HX...
            return True, label
        if series == 7:  # 7840HS/7940HS (Zen 4) ok; 7435/7445/7735 (Zen 3/older/6-core) not
            return model[1] in "89" or model in ("7745", "7845", "7945"), label
        return False, label  # 5000/6000 series
    if re.search(r"ryzen\s*([79])\b", t):
        return False, "Ryzen 7 (model unknown)"
    return False, None


def parse(title: str) -> dict:
    t = title.lower().replace("®", "").replace("™", "")
    cpu_ok, cpu_label = _cpu(t)

    g = re.search(r"rtx\s*[-™]*\s*(\d{4})\s*(ti)?", t)
    gpu = (g.group(1) + (" Ti" if g.group(2) else "")) if g else None

    ram = None
    for pat in (r"\((\d{1,2})\s*gb\s*/",                       # Flipkart "(16 GB/512 GB SSD"
                r"(\d{1,2})\s*gb\s*(?:lp)?ddr\d",               # 16GB DDR5
                r"(\d{1,2})\s*gb\s*(?:of\s*)?(?:system\s*)?ram",  # 16GB RAM
                r"/\s*(\d{1,2})\s*gb\s*/",                      # Reliance ".../16 GB/512 GB SSD"
                r"\b(\d{1,2})\s*gb\s*[,:\s]\s*\d{3,4}\s*gb\b"):  # "16GB:512GB" / "16 GB,512 GB"
        m = re.search(pat, t)
        if m and int(m.group(1)) in (8, 12, 16, 18, 24, 32, 48, 64):
            ram = int(m.group(1))
            break

    ssd = None
    cands = list(re.finditer(r"(\d+(?:\.\d)?)\s*(gb|tb)\s*(?:pcie\s*|nvme\s*|m\.2\s*|gen\s*\d\s*)*ssd", t)) or \
        list(re.finditer(r"(?=\b\d{1,2}\s*gb\s*[,:/\s]\s*(\d+(?:\.\d)?)\s*(gb|tb)\b)", t))  # overlapping
    for m in cands:  # "16 GB,512 GB": take the first storage-sized value
        v = int(float(m.group(1)) * (1024 if m.group(2) == "tb" else 1))
        if v >= 128:
            ssd = v
            break

    return {"cpu_ok": cpu_ok, "cpu": cpu_label, "gpu": gpu, "ram": ram, "ssd": ssd}


def _slug_words(url: str) -> str:
    """Product URLs often carry the full product name: /lenovo-loq-...-rtx-5060-.../p/itm..."""
    from urllib.parse import urlparse
    path = urlparse(url or "").path
    return re.sub(r"[-_/]+", " ", path)


def check(title: str, spec_cfg: dict, url: str = "") -> tuple[bool, dict, str]:
    """Does the laptop meet the configured specs? Returns (ok, parsed, reason).

    Specs come from the title; anything missing there (e.g. Flipkart cuts long
    titles short) is filled in from the product URL slug.
    """
    s = parse(title)
    if url and any(s[k] is None for k in ("cpu", "gpu", "ram", "ssd")):
        extra = parse(_slug_words(url))
        for k in ("gpu", "ram", "ssd"):
            if s[k] is None:
                s[k] = extra[k]
        if s["cpu"] is None and extra["cpu"]:
            s["cpu"], s["cpu_ok"] = extra["cpu"], extra["cpu_ok"]
    allowed = [str(x) for x in spec_cfg.get("gpus", DEFAULT_GPUS)]
    gpu = s["gpu"]
    if gpu is None:
        return False, s, "no RTX GPU found"
    if gpu.split()[0] not in allowed:
        return False, s, f"GPU RTX {gpu} not in list"
    if spec_cfg.get("require_cpu", True) and not s["cpu_ok"]:
        return False, s, f"CPU {s['cpu'] or 'unknown'} below bar"
    if s["ram"] is not None and s["ram"] < spec_cfg.get("min_ram_gb", 16):
        return False, s, f"RAM {s['ram']}GB"
    if s["ssd"] is not None and s["ssd"] < spec_cfg.get("min_ssd_gb", 512):
        return False, s, f"SSD {s['ssd']}GB"
    return True, s, "ok"


def short(s: dict) -> str:
    parts = [s.get("cpu") or "?", f"RTX {s['gpu']}" if s.get("gpu") else "?"]
    if s.get("ram"):
        parts.append(f"{s['ram']}GB")
    if s.get("ssd"):
        parts.append(f"{s['ssd'] // 1024}TB SSD" if s["ssd"] >= 1024 else f"{s['ssd']}GB SSD")
    return " · ".join(parts)

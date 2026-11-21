"""WhatsApp alerts through Meta's official WhatsApp Cloud API.

Env vars:
  WHATSAPP_TOKEN            permanent System User access token
  WHATSAPP_PHONE_NUMBER_ID  "Phone number ID" from the app's WhatsApp > API Setup page
  WHATSAPP_TO               your number with country code, digits only (e.g. 9198XXXXXXXX)
  WHATSAPP_WABA_ID          WhatsApp Business Account ID (only for --create-wa-templates)
  WHATSAPP_API_VERSION      optional, default v23.0

Messages the bot starts must use an approved template (Meta rule). If the
template send is rejected, we fall back to a plain text message, which Meta
only delivers within 24h of you last messaging the bot's number.
"""
import os
import re

from curl_cffi import requests

DEAL_TEMPLATE = "laptop_deal_alert"
NOTICE_TEMPLATE = "laptop_bot_notice"
LANG = "en"

TEMPLATES = [
    {
        "name": DEAL_TEMPLATE,
        "category": "UTILITY",
        "language": LANG,
        "components": [{
            "type": "BODY",
            "text": "🔥 Laptop price alert\n\n*{{1}}*\nPrice: {{2}} at {{3}}\nSpecs: {{4}}\nWhy: {{5}}\n\nOpen: {{6}}",
            "example": {"body_text": [[
                "Lenovo LOQ 15 Ryzen 7 250 RTX 5060",
                "₹1,42,990",
                "Flipkart",
                "Ryzen 7 250 · RTX 5060 · 16GB · 512GB SSD",
                "Just dropped into your budget (was ₹1,62,990)",
                "https://www.flipkart.com/example",
            ]]},
        }],
    },
    {
        "name": NOTICE_TEMPLATE,
        "category": "UTILITY",
        "language": LANG,
        "components": [{
            "type": "BODY",
            "text": "Laptop deal bot notice: {{1}}",
            "example": {"body_text": [["Could not check a store page 6 times in a row."]]},
        }],
    },
]


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} is not set")
    return v


def _base() -> str:
    return f"https://graph.facebook.com/{os.environ.get('WHATSAPP_API_VERSION', 'v23.0')}"


def _post(path: str, payload: dict) -> dict:
    r = requests.post(
        f"{_base()}/{path}",
        json=payload,
        headers={"Authorization": f"Bearer {_env('WHATSAPP_TOKEN')}"},
        timeout=30,
    )
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:300]}
    if r.status_code >= 300 or "error" in data:
        err = data.get("error", data)
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise RuntimeError(f"WhatsApp API {r.status_code}: {msg}"[:400])
    return data


def _param(s: str, limit: int = 300) -> str:
    """Template parameters can't contain newlines/tabs or 4+ consecutive spaces."""
    s = re.sub(r"[\r\n\t]+", " ", s or "-")
    s = re.sub(r" {2,}", " ", s).strip()
    return (s[: limit - 1] + "…") if len(s) > limit else (s or "-")


def send_template(name: str, params: list[str]) -> None:
    _post(f"{_env('WHATSAPP_PHONE_NUMBER_ID')}/messages", {
        "messaging_product": "whatsapp",
        "to": _env("WHATSAPP_TO"),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": LANG},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": _param(p)} for p in params]}],
        },
    })


def send_text(body: str) -> None:
    _post(f"{_env('WHATSAPP_PHONE_NUMBER_ID')}/messages", {
        "messaging_product": "whatsapp",
        "to": _env("WHATSAPP_TO"),
        "type": "text",
        "text": {"body": body[:4000], "preview_url": True},
    })


def send_deal(d: dict) -> None:
    """d: title, price, store, specs, why, url, text (plain-text fallback)."""
    try:
        send_template(DEAL_TEMPLATE, [d["title"], d["price"], d["store"], d["specs"], d["why"], d["url"]])
    except RuntimeError as e:
        print(f"  template send failed ({e}); trying plain text")
        send_text(d["text"])


def send_notice(msg: str) -> None:
    try:
        send_template(NOTICE_TEMPLATE, [msg])
    except RuntimeError as e:
        print(f"  template send failed ({e}); trying plain text")
        send_text("Laptop deal bot notice: " + msg)


def create_templates() -> None:
    waba = _env("WHATSAPP_WABA_ID")
    for t in TEMPLATES:
        try:
            res = _post(f"{waba}/message_templates", t)
            print(f"  {t['name']}: submitted, status={res.get('status')} category={res.get('category')}")
        except RuntimeError as e:
            print(f"  {t['name']}: {e}")

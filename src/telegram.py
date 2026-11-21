"""Telegram Bot API notifier.

Env vars: TELEGRAM_BOT_TOKEN (from @BotFather), TELEGRAM_CHAT_ID (your user id or a channel id/@name).
"""
import html
import os

from curl_cffi import requests

API = "https://api.telegram.org/bot{token}/{method}"


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} is not set")
    return v


def send(text: str) -> None:
    r = requests.post(
        API.format(token=_env("TELEGRAM_BOT_TOKEN"), method="sendMessage"),
        data={"chat_id": _env("TELEGRAM_CHAT_ID"), "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "false"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text[:300]}")


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def deal_message(a: dict) -> str:
    """a: title, price, store, specs, why (list), url, history_line (optional)."""
    lines = [f"🔥 <b>{esc(a['title'])}</b>",
             f"💰 <b>{esc(a['price'])}</b> on <b>{esc(a['store'])}</b>"]
    if a.get("specs"):
        lines.append(f"⚙️ {esc(a['specs'])}")
    for w in a["why"]:
        lines.append(f"📉 {esc(w)}")
    if a.get("history_line"):
        lines.append(f"🕘 {esc(a['history_line'])}")
    lines.append(f'🔗 <a href="{esc(a["url"])}">Open deal</a>')
    if a.get("dashboard"):
        lines.append(f'📊 <a href="{esc(a["dashboard"])}">Dashboard</a>')
    lines.append("<i>Bank/card offers not included. Check the page before buying.</i>")
    return "\n".join(lines)

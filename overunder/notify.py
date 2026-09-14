"""Optional Telegram delivery. Silently no-ops when not configured."""

import requests

from .config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN, TELEGRAM_VIP_CHAT_ID


def send_telegram(text, chat_id=None):
    """Send to the given chat, or TELEGRAM_CHAT_ID by default. Returns True on success."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if not (TELEGRAM_TOKEN and cid):
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": cid, "text": text[:4000]},
                          timeout=15)
        return r.ok
    except requests.RequestException:
        return False


def send_vip(text):
    """Send to the VIP channel when TELEGRAM_VIP_CHAT_ID is configured."""
    return send_telegram(text, chat_id=TELEGRAM_VIP_CHAT_ID) if TELEGRAM_VIP_CHAT_ID else False

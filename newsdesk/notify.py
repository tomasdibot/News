"""Daily reminder.

Default: a notification from the installed app itself (see push.py).
Optional WhatsApp providers:

Providers (pick with notification.provider):
  callmebot - free, for sending WhatsApp messages to YOUR OWN number.
              Env: WHATSAPP_PHONE, CALLMEBOT_APIKEY
  twilio    - Twilio WhatsApp API (sandbox or approved sender); also sends the top photo.
              Env: WHATSAPP_PHONE, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
  greenapi  - Green API (green-api.com): links YOUR WhatsApp by QR code and sends to your
              "Message yourself" chat, with the top story's photo. Free Developer plan.
              Env: WHATSAPP_PHONE, GREENAPI_ID_INSTANCE, GREENAPI_API_TOKEN, optional GREENAPI_API_URL
  console   - just prints the message (for testing).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .lexicon import UI

log = logging.getLogger(__name__)

WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}
MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
}


class NotifyError(RuntimeError):
    pass


def format_date(d: datetime, lang: str) -> str:
    lang = lang if lang in WEEKDAYS else "en"
    wd, month = WEEKDAYS[lang][d.weekday()], MONTHS[lang][d.month - 1]
    return f"{wd} {d.day} de {month}" if lang == "es" else f"{wd}, {month} {d.day}"


def compose_message(edition: dict, cfg: dict, now: datetime | None = None) -> str:
    lang = cfg["site"]["ui_language"]
    ui = UI.get(lang, UI["en"])
    tz = ZoneInfo(cfg["notification"]["timezone"])
    now = (now or datetime.now(tz)).astimezone(tz)

    stories, seen = [], set()
    for s in edition["top"] + edition["local"]:
        if s["link"] not in seen:
            seen.add(s["link"])
            stories.append(s)
    stories = stories[: cfg["notification"]["headlines"]]

    lines = [f"*{ui['greeting'].format(date=format_date(now, lang))}*", ""]
    if not stories:
        lines.append(ui["empty"])
    for i, s in enumerate(stories, 1):
        n = len(s["outlets"])
        cov = ui["sources_one"] if n == 1 else ui["sources_many"].format(n=n)
        lines.append(f"{i}. {s['title']} _({cov})_")
    url = cfg["site"].get("url")
    if url:
        lines += ["", f"👉 {ui['more']}: {url}"]
    return "\n".join(lines)


def _phone() -> str:
    phone = os.environ.get("WHATSAPP_PHONE", "").strip()
    if not phone:
        raise NotifyError("WHATSAPP_PHONE is not set (international format, e.g. +5491122334455)")
    return phone if phone.startswith("+") else "+" + phone


def send_callmebot(text: str, image: str | None = None) -> None:
    key = os.environ.get("CALLMEBOT_APIKEY")
    if not key:
        raise NotifyError("CALLMEBOT_APIKEY is not set (see README: 'WhatsApp setup')")
    resp = requests.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": _phone(), "text": text, "apikey": key},
        timeout=30,
    )
    body = resp.text.lower()
    if resp.status_code != 200 or ("queued" not in body and ("error" in body or "invalid" in body)):
        raise NotifyError(f"CallMeBot answered {resp.status_code}: {resp.text[:300]}")


def send_twilio(text: str, image: str | None = None) -> None:
    sid, token = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g. +14155238886 (sandbox)
    if not (sid and token and sender):
        raise NotifyError("TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM must be set")
    sender = sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}"
    data = {"From": sender, "To": f"whatsapp:{_phone()}", "Body": text[:1600]}
    if image:
        data["MediaUrl"] = image
    resp = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data, auth=(sid, token), timeout=30
    )
    if resp.status_code >= 300:
        raise NotifyError(f"Twilio answered {resp.status_code}: {resp.text[:300]}")


def send_greenapi(text: str, image: str | None = None) -> None:
    instance, token = os.environ.get("GREENAPI_ID_INSTANCE"), os.environ.get("GREENAPI_API_TOKEN")
    if not (instance and token):
        raise NotifyError("GREENAPI_ID_INSTANCE and GREENAPI_API_TOKEN must be set (see README: 'WhatsApp setup')")
    # Each instance lives on a specific host; the console shows it as "apiUrl".
    base = (os.environ.get("GREENAPI_API_URL") or "https://api.green-api.com").rstrip("/")
    chat_id = _phone().lstrip("+") + "@c.us"
    url = f"{base}/waInstance{instance}/{{method}}/{token}"
    if image:
        resp = requests.post(url.format(method="sendFileByUrl"), timeout=30,
                             json={"chatId": chat_id, "urlFile": image, "fileName": "news.jpg", "caption": text})
        if resp.status_code < 300:
            return
        log.warning("Green API could not send the photo (%s), sending text only", resp.status_code)
    resp = requests.post(url.format(method="sendMessage"), json={"chatId": chat_id, "message": text}, timeout=30)
    if resp.status_code >= 300:
        raise NotifyError(f"Green API answered {resp.status_code}: {resp.text[:300]}")


def send_console(text: str, image: str | None = None) -> None:
    print(text)
    if image:
        print(f"[image] {image}")


PROVIDERS = {"callmebot": send_callmebot, "greenapi": send_greenapi, "twilio": send_twilio, "console": send_console}


def notify(edition: dict, cfg: dict, provider: str | None = None) -> str:
    """Send the daily reminder. `provider` may list several, e.g. "push,callmebot"."""
    from .push import PushError, send_push

    chosen = provider or os.environ.get("NEWSDESK_NOTIFY_PROVIDER") or cfg["notification"]["provider"]
    names = [p.strip() for p in chosen.split(",") if p.strip()]
    for name in names:
        if name != "push" and name not in PROVIDERS:
            raise NotifyError(f"unknown provider {name!r}; choose from push, {', '.join(sorted(PROVIDERS))}")

    text = compose_message(edition, cfg)
    image = next((s["image"] for s in edition["top"] if s.get("image")), None)
    errors = []
    for name in names:
        try:
            if name == "push":
                send_push(edition, cfg)
            else:
                PROVIDERS[name](text, image)
            log.info("notification sent via %s", name)
        except (NotifyError, PushError) as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise NotifyError("; ".join(errors))
    return text

from django import template
from django.utils.translation import gettext as _

register = template.Library()


def _parse_log(message):
    if not message or "STATUS:" not in message:
        return None
    parts = [p for p in message.split(";") if ":" in p]
    data = {}
    for part in parts:
        key, value = part.split(":", 1)
        data[key.strip().upper()] = value.strip()
    return data if "STATUS" in data else None


def _parse_title(title):
    if not title or "ACTION:" not in title:
        return None
    parts = [p for p in title.split(";") if ":" in p]
    data = {}
    for part in parts:
        key, value = part.split(":", 1)
        data[key.strip().upper()] = value.strip()
    return data if "ACTION" in data else None


@register.filter
def admin_log_title(title):
    data = _parse_title(title)
    if not data:
        return title
    action = (data.get("ACTION") or "").lower()
    month = data.get("MONTH")
    if action == "telegram_group":
        label = _("Telegram group send")
    elif action == "generate":
        label = _("Generate bills")
    else:
        label = _("Action")
    if month:
        return f"{label} {month}"
    return label


@register.filter
def admin_log_status(message):
    data = _parse_log(message)
    if not data:
        return ""
    status = (data.get("STATUS") or "").lower()
    if status in ("success", "failed"):
        return status
    return ""


@register.filter
def admin_log_line(message):
    data = _parse_log(message)
    if not data:
        return message
    action = (data.get("ACTION") or "").lower()
    status = (data.get("STATUS") or "").lower()
    total = data.get("TOTAL") or "0"
    failed = data.get("FAILED") or "0"
    done = data.get("DONE")
    if done is None:
        try:
            done = str(max(0, int(total) - int(failed)))
        except Exception:
            done = "0"
    label = _("Completed") if status == "success" else _("Failed")
    action_label = ""
    if action == "telegram_group":
        action_label = _("Telegram group")
    elif action == "generate":
        action_label = _("Generate bills")
    if action_label:
        line = f"{action_label}: {label} {_('Done')} {done}/{total}. {_('Failed')}: {failed}"
    else:
        line = f"{label}: {_('Done')} {done}/{total}. {_('Failed')}: {failed}"
    rooms = data.get("ROOMS")
    if rooms:
        line = f"{line} — {_('Rooms')}: {rooms}"
    return line

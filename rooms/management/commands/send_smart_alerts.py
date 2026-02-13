import datetime
import json
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils import timezone

from rooms.models import Electricity, MonthlyBill, Room, SmartAlertLog, Water


def _post_json(url, payload, timeout=20, retries=2, backoff=1.5):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionResetError) as exc:
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise RuntimeError(f"Telegram network error: {exc}") from exc


def _prev_month(value):
    first = value.replace(day=1)
    return (first - datetime.timedelta(days=1)).replace(day=1)


def _last_day_of_month(value):
    next_month = value.replace(day=28) + datetime.timedelta(days=4)
    return next_month - datetime.timedelta(days=next_month.day)


def _get_usage(model, room, month):
    current = model.objects.filter(room=room, date=month).first()
    if not current:
        return None
    prev = (
        model.objects.filter(room=room, date__lt=month)
        .order_by("-date")
        .first()
    )
    if not prev:
        return None
    usage = current.meter_value - prev.meter_value
    return usage if usage >= 0 else None


def _get_recent_usages(model, room, month, count=3):
    usages = []
    cursor = month
    for _ in range(count):
        cursor = _prev_month(cursor)
        usage = _get_usage(model, room, cursor)
        if usage is not None:
            usages.append(usage)
    return usages


def _should_send(month, alert_type, room=None):
    return not SmartAlertLog.objects.filter(
        month=month, alert_type=alert_type, room=room
    ).exists()


def _log_sent(month, alert_type, message, room=None):
    SmartAlertLog.objects.create(
        month=month, alert_type=alert_type, room=room, message=message[:500]
    )


def _send_message(chat_id, token, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = _post_json(url, {"chat_id": chat_id, "text": text})
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram error: {resp}")


class Command(BaseCommand):
    help = "Send smart Telegram alerts to landlord"

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN is not configured.")

        chat_id = getattr(settings, "ADMIN_TELEGRAM_CHAT_ID", "")
        if not chat_id:
            raise CommandError("ADMIN_TELEGRAM_CHAT_ID is not configured.")

        if not getattr(settings, "SMART_ALERTS_ENABLED", True):
            self.stdout.write(self.style.WARNING("Smart alerts are disabled."))
            return

        due_days = int(getattr(settings, "SMART_ALERT_DUE_DAYS", 5))
        pct = float(getattr(settings, "SMART_ALERT_USAGE_PCT", 30))

        today = timezone.localdate()

        # Alert 1: unpaid N days after successful Telegram send for the month
        months = (
            MonthlyBill.objects.values_list("month", flat=True)
            .distinct()
            .order_by("-month")
        )
        for month in months:
            sent_at = (
                MonthlyBill.objects.filter(
                    month=month,
                    status__in=[MonthlyBill.Status.SENT, MonthlyBill.Status.PAID],
                )
                .exclude(sent_at__isnull=True)
                .order_by("-sent_at")
                .values_list("sent_at", flat=True)
                .first()
            )
            if not sent_at:
                continue
            due_date = sent_at.date() + datetime.timedelta(days=due_days)
            if today <= due_date:
                continue
            unpaid = MonthlyBill.objects.filter(
                month=month,
                status__in=[MonthlyBill.Status.ISSUED, MonthlyBill.Status.SENT],
            )
            if not unpaid.exists():
                continue
            if not _should_send(month, "unpaid_overdue"):
                continue
            rooms = ", ".join(unpaid.values_list("room__room_number", flat=True))
            message = (
                "⚠ បន្ទប់ %(room)s មិនទាន់បង់ប្រាក់ %(days)d ថ្ងៃហើយ។\n"
                "សូមទាក់ទងអ្នកជួល។"
            ) % {"room": rooms, "days": due_days}
            try:
                _send_message(chat_id, token, message)
            except RuntimeError as exc:
                self.stderr.write(str(exc))
            else:
                _log_sent(month, "unpaid_overdue", message)

        # Alert 2: usage spike vs last month
        latest_month = (
            MonthlyBill.objects.values_list("month", flat=True)
            .distinct()
            .order_by("-month")
            .first()
        )
        if latest_month:
            for room in Room.objects.all():
                for model, alert_key in (
                    (Water, "usage_water_high"),
                    (Electricity, "usage_electricity_high"),
                ):
                    current = _get_usage(model, room, latest_month)
                    recent = _get_recent_usages(model, room, latest_month, count=3)
                    if current is None or len(recent) < 2:
                        continue
                    avg_recent = sum(recent) / len(recent)
                    if avg_recent == 0:
                        continue
                    if current <= avg_recent * (1 + pct / 100):
                        continue
                    if not _should_send(latest_month, alert_key, room):
                        continue
                    if model is Water:
                        message = (
                            "⚠ ទឹកបន្ទប់ %(room)s ប្រើច្រើនជាងធម្មតា។\n"
                            "សូមពិនិត្យ។"
                        ) % {"room": room.room_number}
                    else:
                        message = (
                            "⚠ ភ្លើងបន្ទប់ %(room)s ប្រើច្រើនជាងខែមុន។\n"
                            "សូមពិនិត្យ។"
                        ) % {"room": room.room_number}
                    try:
                        _send_message(chat_id, token, message)
                    except RuntimeError as exc:
                        self.stderr.write(str(exc))
                    else:
                        _log_sent(latest_month, alert_key, message, room=room)

        # Alert 3: all rooms fully paid
        if latest_month:
            bills = MonthlyBill.objects.filter(month=latest_month)
            if bills.exists():
                all_paid = not bills.exclude(status=MonthlyBill.Status.PAID).exists()
                if all_paid and _should_send(latest_month, "all_paid"):
                    message = "✅ ខែនេះទទួលប្រាក់បាន 100% ហើយ។"
                    try:
                        _send_message(chat_id, token, message)
                    except RuntimeError as exc:
                        self.stderr.write(str(exc))
                    else:
                        _log_sent(latest_month, "all_paid", message)

        # Alert 4: monthly summary on the 1st
        if latest_month:
            if _should_send(latest_month, "monthly_summary"):
                bills = MonthlyBill.objects.filter(month=latest_month)
                income = bills.aggregate(total=Sum("total"))["total"] or 0
                unpaid_count = bills.filter(
                    status__in=[MonthlyBill.Status.ISSUED, MonthlyBill.Status.SENT]
                ).count()

                water_total = 0
                elec_total = 0
                prev_month = _prev_month(latest_month)
                for room in Room.objects.all():
                    water_usage = _get_usage(Water, room, latest_month)
                    elec_usage = _get_usage(Electricity, room, latest_month)
                    if water_usage:
                        water_total += water_usage
                    if elec_usage:
                        elec_total += elec_usage

                kh_months = {
                    1: "មករា",
                    2: "កុម្ភៈ",
                    3: "មិនា",
                    4: "មេសា",
                    5: "ឧសភា",
                    6: "មិថុនា",
                    7: "កក្កដា",
                    8: "សីហា",
                    9: "កញ្ញា",
                    10: "តុលា",
                    11: "វិច្ឆិកា",
                    12: "ធ្នូ",
                }
                month_label = f"{kh_months.get(latest_month.month, latest_month.month)} {latest_month.year}"
                message = (
                    f"📊 របាយការណ៍ខែ {month_label}\n\n"
                    f"💰 ទទួលបាន: {int(income):,}៛\n"
                    f"🔴 មិនទាន់បង់: {unpaid_count} បន្ទប់\n"
                    f"💧 ទឹកសរុប: {int(water_total)} m³\n"
                    f"⚡ ភ្លើងសរុប: {int(elec_total)} kWh"
                )
                try:
                    _send_message(chat_id, token, message)
                except RuntimeError as exc:
                    self.stderr.write(str(exc))
                else:
                    _log_sent(latest_month, "monthly_summary", message)

        self.stdout.write(self.style.SUCCESS("Smart alerts completed."))

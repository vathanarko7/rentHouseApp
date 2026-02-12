import datetime
import json
import os
import urllib.request
import urllib.error

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.utils import timezone
from django.utils.formats import date_format

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

from rooms.models import MonthlyBill, UnitPrice


def _post_multipart(url, fields, files, timeout=30):
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    data = []
    for key, value in fields.items():
        data.append(f"--{boundary}")
        data.append(f'Content-Disposition: form-data; name="{key}"')
        data.append("")
        data.append(str(value))
    for key, (filename, content, content_type) in files.items():
        data.append(f"--{boundary}")
        data.append(
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"'
        )
        data.append(f"Content-Type: {content_type}")
        data.append("")
        data.append(content)
    data.append(f"--{boundary}--")

    body = b""
    for part in data:
        if isinstance(part, bytes):
            body += part + b"\r\n"
        else:
            body += part.encode("utf-8") + b"\r\n"

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _month_from_arg(value):
    try:
        dt = datetime.datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise CommandError("Month must be in YYYY-MM format.") from exc
    return dt.date().replace(day=1)


def _previous_month(date_value):
    first = date_value.replace(day=1)
    return (first - datetime.timedelta(days=1)).replace(day=1)


def _format_khr(value):
    return f"{value:,.0f} KHR"


def _format_usd(value):
    return f"{value:,.2f} USD"


def _generate_report_pdf(
    month,
    income,
    water_cost,
    electricity_cost,
    expense,
    profit,
    unpaid_rooms,
    exchange_rate,
    output_path,
):
    styles = getSampleStyleSheet()
    title = f"Monthly Report {date_format(month, 'F Y')}"
    story = [Paragraph(title, styles["Title"]), Spacer(1, 10)]

    summary_data = [
        ["Total income", _format_khr(income)],
        ["Utility total", _format_khr(expense)],
        ["Profit", _format_khr(profit)],
    ]
    if exchange_rate:
        summary_data.extend(
            [
                ["Total income (USD)", _format_usd(income / exchange_rate)],
                ["Utility total (USD)", _format_usd(expense / exchange_rate)],
                ["Profit (USD)", _format_usd(profit / exchange_rate)],
            ]
        )

    table = Table(summary_data, hAlign="LEFT", colWidths=[180, 140])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14))

    story.append(
        Paragraph(
            f"Water cost: {_format_khr(water_cost)}", styles["Normal"]
        )
    )
    story.append(
        Paragraph(
            f"Electricity cost: {_format_khr(electricity_cost)}", styles["Normal"]
        )
    )
    story.append(Spacer(1, 10))

    unpaid_count = len(unpaid_rooms)
    unpaid_label = ", ".join(unpaid_rooms) if unpaid_rooms else "None"
    story.append(Paragraph(f"Unpaid rooms: {unpaid_count}", styles["Normal"]))
    story.append(Paragraph(f"Rooms: {unpaid_label}", styles["Normal"]))

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    doc.build(story)


class Command(BaseCommand):
    help = "Generate monthly report PDF and send to admin/staff Telegram chats."

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            help="Target month in YYYY-MM format (defaults to previous month).",
        )

    def handle(self, *args, **options):
        month_arg = options.get("month")
        today = timezone.localdate()
        month = _month_from_arg(month_arg) if month_arg else _previous_month(today)

        bills = MonthlyBill.objects.filter(month=month)
        income = bills.aggregate(total=Sum("total"))["total"] or 0
        totals = bills.aggregate(
            water=Sum("water_cost"), electricity=Sum("electricity_cost")
        )
        water_cost = totals["water"] or 0
        electricity_cost = totals["electricity"] or 0
        expense = water_cost + electricity_cost
        profit = income - expense

        unpaid = bills.filter(status__in=[MonthlyBill.Status.ISSUED, MonthlyBill.Status.SENT])
        unpaid_rooms = list(unpaid.values_list("room__room_number", flat=True))

        exchange_rate = None
        try:
            unit_price = UnitPrice.objects.get(date=month)
            exchange_rate = unit_price.exchange_rate
        except UnitPrice.DoesNotExist:
            exchange_rate = None

        media_root = getattr(settings, "MEDIA_ROOT", "")
        if not media_root:
            raise CommandError("MEDIA_ROOT is not configured.")
        reports_dir = os.path.join(media_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        filename = f"monthly_report_{month.strftime('%Y_%m')}.pdf"
        output_path = os.path.join(reports_dir, filename)

        _generate_report_pdf(
            month=month,
            income=income,
            water_cost=water_cost,
            electricity_cost=electricity_cost,
            expense=expense,
            profit=profit,
            unpaid_rooms=unpaid_rooms,
            exchange_rate=exchange_rate,
            output_path=output_path,
        )

        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN is not configured.")

        chat_ids = []
        admin_chat_id = getattr(settings, "ADMIN_TELEGRAM_CHAT_ID", "")
        if admin_chat_id:
            chat_ids.append(admin_chat_id)

        if not chat_ids:
            User = get_user_model()
            staff_users = User.objects.filter(is_staff=True)
            for user in staff_users:
                profile = getattr(user, "client_profile", None)
                chat_id = getattr(profile, "telegram_chat_id", None)
                if chat_id:
                    chat_ids.append(chat_id)

        if not chat_ids:
            raise CommandError("No admin/staff Telegram chat IDs found.")

        with open(output_path, "rb") as f:
            pdf_bytes = f.read()

        url = f"https://api.telegram.org/bot{token}/sendDocument"
        caption = f"Monthly Report {date_format(month, 'F Y')}"
        for chat_id in chat_ids:
            resp = _post_multipart(
                url,
                {"chat_id": chat_id, "caption": caption},
                {"document": (filename, pdf_bytes, "application/pdf")},
            )
            if not resp.get("ok"):
                raise CommandError(f"Telegram send failed: {resp}")

        self.stdout.write(self.style.SUCCESS("Monthly report sent."))

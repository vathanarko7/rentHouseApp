from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.conf import settings
from datetime import date
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
import os

from django.urls import reverse
import io
from zipfile import ZipFile

from .models import MonthlyBill, Room, ClientProfile, UnitPrice
from django.utils.formats import date_format
from django.utils.translation import override
from django.utils import timezone
from .services import calculate_monthly_bill, generate_invoice_for_bill
import json
import mimetypes
import uuid
import urllib.request
import urllib.error
import urllib.parse


def _invoice_storage_path(bill, filename):
    return (
        f"invoices/images/{bill.month.strftime('%Y_%m')}/{filename}".replace("\\", "/")
    )


def download_invoice(request, bill_id, lang):
    if lang not in ("kh", "en", "fr"):
        raise Http404("Invalid language")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
        and bill.room.renter_id != request.user.id
    ):
        raise Http404("Not found")
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
        and bill.status
        not in (
            MonthlyBill.Status.SENT,
            MonthlyBill.Status.PAID,
        )
    ):
        raise Http404("Not found")
    filename = generate_invoice_for_bill(bill, lang=lang)

    storage_path = _invoice_storage_path(bill, filename)
    if not default_storage.exists(storage_path):
        raise Http404("Invoice file not found")

    return FileResponse(
        default_storage.open(storage_path, "rb"),
        as_attachment=True,
        filename=filename,
        content_type="image/png",
    )


def preview_invoice(request, bill_id):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
        and bill.room.renter_id != request.user.id
    ):
        raise Http404("Not found")
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
        and bill.status
        not in (
            MonthlyBill.Status.SENT,
            MonthlyBill.Status.PAID,
        )
    ):
        raise Http404("Not found")

    filename = generate_invoice_for_bill(bill, lang="kh")
    storage_path = _invoice_storage_path(bill, filename)
    if not default_storage.exists(storage_path):
        raise Http404("Invoice file not found")

    return FileResponse(
        default_storage.open(storage_path, "rb"),
        as_attachment=False,
        filename=filename,
        content_type="image/png",
    )


def regenerate_invoice_view(request, bill_id):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if bill.status != MonthlyBill.Status.DRAFT:
        messages.error(request, "Invoice can only be re-generated in Draft status.")
        return redirect("..")

    for lang in ("kh", "en", "fr"):
        generate_invoice_for_bill(bill=bill, lang=lang)

    messages.success(request, "Invoice re-generated successfully.")
    return redirect(reverse("admin:rooms_monthlybill_changelist"))


def issue_invoice_view(request, bill_id):
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if bill.status != MonthlyBill.Status.DRAFT:
        messages.error(request, "Invoice can only be issued from Draft status.")
        return redirect(reverse("admin:rooms_monthlybill_changelist"))

    bill.status = MonthlyBill.Status.ISSUED
    bill.issued_at = timezone.now()
    bill.save(update_fields=["status", "issued_at"])
    messages.success(request, "Invoice issued successfully.")
    return redirect(reverse("admin:rooms_monthlybill_changelist"))


def mark_paid_view(request, bill_id):
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if bill.status != MonthlyBill.Status.SENT:
        messages.error(request, "Invoice can only be marked Paid after it is Sent.")
        return redirect(reverse("admin:rooms_monthlybill_changelist"))

    bill.status = MonthlyBill.Status.PAID
    bill.paid_at = timezone.now()
    bill.save(update_fields=["status", "paid_at"])
    messages.success(request, "Invoice marked as Paid.")
    return redirect(reverse("admin:rooms_monthlybill_changelist"))


def _post_multipart(url, fields, files, timeout=15):
    boundary = uuid.uuid4().hex
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")

    for name, file_value in files.items():
        if isinstance(file_value, tuple):
            filename, file_data = file_value
        else:
            filename = os.path.basename(file_value)
            with open(file_value, "rb") as f:
                file_data = f.read()
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
        body.extend(file_data)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("User-Agent", "rentHouseApp/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code} {e.reason} {detail}".strip()) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from e


def send_invoice_telegram_view(request, bill_id):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if bill.status not in (MonthlyBill.Status.ISSUED, MonthlyBill.Status.SENT):
        messages.error(request, "Invoice can only be sent when status is Issued or Sent.")
        return redirect("..")

    renter = bill.room.renter
    chat_id = None
    if renter:
        chat_id = getattr(
            getattr(renter, "client_profile", None), "telegram_chat_id", None
        )
    if not chat_id:
        messages.error(request, "Tenant Telegram chat ID is missing.")
        return redirect("..")

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return redirect("..")

    filename = generate_invoice_for_bill(bill=bill, lang="kh")
    storage_path = _invoice_storage_path(bill, filename)
    if not default_storage.exists(storage_path):
        messages.error(request, "Invoice file not found.")
        return redirect("..")

    with default_storage.open(storage_path, "rb") as f:
        invoice_bytes = f.read()

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    unit_price = UnitPrice.objects.get(date=bill.month)
    with override("km"):
        month_label = date_format(bill.month, "F Y")
    total_khr = f"{bill.total:,.0f}"
    total_usd = bill.total / unit_price.exchange_rate
    caption = (
        f"📄 វិក័យប័ត្រ ខែ {month_label}\n"
        f"បន្ទប់: {bill.room.room_number}\n"
        f"សរុប: {total_khr}៛ ({total_usd:,.2f}$)\n"
        "\n"
        "📎 ទាញយក និងផ្ទៀងផ្ទាត់វិក័យប័ត្រខាងលើ"
    )
    try:
        resp = _post_multipart(
            url,
            {"chat_id": chat_id, "caption": caption},
            {"photo": (filename, invoice_bytes)},
        )
        if not resp.get("ok"):
            messages.error(request, f"Telegram error: {resp}")
            return redirect("..")
    except Exception as e:
        messages.error(request, f"Telegram send failed: {str(e)}")
        return redirect("..")

    bill.status = MonthlyBill.Status.SENT
    bill.sent_at = timezone.now()
    bill.save(update_fields=["status", "sent_at"])
    messages.success(request, "Invoice sent via Telegram.")
    return redirect(reverse("admin:rooms_monthlybill_changelist"))


def test_telegram_connection_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return redirect(reverse("admin:rooms_monthlybill_changelist"))

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            messages.error(request, f"Telegram test failed: {data}")
            return redirect(reverse("admin:rooms_monthlybill_changelist"))
        result = data.get("result") or {}
        bot_name = result.get("username") or result.get("first_name") or "Unknown"
        messages.success(request, f"Telegram connection OK: {bot_name}")
    except Exception as e:
        messages.error(request, f"Telegram test failed: {str(e)}")
    return redirect(reverse("admin:rooms_monthlybill_changelist"))


def test_tenant_telegram_view(request, bill_id):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    renter = bill.room.renter
    chat_id = None
    if renter:
        chat_id = getattr(
            getattr(renter, "client_profile", None), "telegram_chat_id", None
        )
    if not chat_id:
        messages.error(request, "Tenant Telegram chat ID is missing.")
        return redirect("..")

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return redirect("..")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    template = getattr(
        settings,
        "TELEGRAM_TEST_MESSAGE_TEMPLATE",
        "Test message for room {room_number}.",
    )
    try:
        text = template.format(
            room_number=bill.room.room_number,
            month=bill.month.strftime("%Y-%m"),
            bill_id=bill.id,
        )
    except Exception:
        text = f"Test message for room {bill.room.room_number}."
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            messages.error(request, f"Telegram test failed: {data}")
            return redirect("..")
        messages.success(request, "Tenant Telegram test message sent.")
    except Exception as e:
        messages.error(request, f"Telegram test failed: {str(e)}")
    return redirect("..")


def test_clientprofile_telegram_view(request, profile_id):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    profile = get_object_or_404(ClientProfile, pk=profile_id)
    chat_id = getattr(profile, "telegram_chat_id", None)
    if not chat_id:
        messages.error(request, "Tenant Telegram chat ID is missing.")
        return redirect("admin:rooms_clientprofile_changelist")

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return redirect("admin:rooms_clientprofile_changelist")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    template = getattr(
        settings,
        "TELEGRAM_TEST_MESSAGE_TEMPLATE",
        "Test message for room {room_number}.",
    )
    room_number = ""
    if profile.user_id:
        room = Room.objects.filter(renter_id=profile.user_id).first()
        if room:
            room_number = room.room_number
    try:
        text = template.format(
            room_number=room_number,
            month="",
            bill_id="",
        )
    except Exception:
        text = "Test message."
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            messages.error(request, f"Telegram test failed: {data}")
            return redirect("admin:rooms_clientprofile_changelist")
        messages.success(request, "Tenant Telegram test message sent.")
    except Exception as e:
        messages.error(request, f"Telegram test failed: {str(e)}")
    return redirect("admin:rooms_clientprofile_changelist")


# View to generate invoices for selected rooms and month
def generate_invoices_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        month = request.POST.get("month")
        room_ids = request.POST.getlist("rooms")

        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)
        generated_count = 0

        rooms_qs = (
            Room.objects.all() if not room_ids else Room.objects.filter(id__in=room_ids)
        )
        for room in rooms_qs:
            try:
                # now generate invoice
                bill = calculate_monthly_bill(room, bill_month)
                generate_invoice_for_bill(
                    bill=bill,
                    lang="kh",
                )
                generated_count += 1
            except ValidationError as e:
                # Show a friendly error message in the admin UI
                messages.error(
                    request, f"Room {room.room_number}: {'; '.join(e.messages)}"
                )
            except Exception as e:
                # catch-all for unexpected errors
                messages.error(
                    request, f"Room {room.room_number}: Unexpected error: {str(e)}"
                )

        messages.success(
            request, f"{generated_count} invoice(s) generated successfully"
        )
        return redirect("..")

    rooms = Room.objects.all()
    return render(
        request,
        "admin/rooms/generate_invoices.html",
        {
            "rooms": rooms,
        },
    )


# View to generate and download all invoices as ZIP
def generate_and_download_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        month = request.POST.get("month")
        room_ids = request.POST.getlist("rooms")

        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)

        buffer = io.BytesIO()
        zip_file = ZipFile(buffer, "w")

        generated_count = 0

        rooms_qs = (
            Room.objects.all() if not room_ids else Room.objects.filter(id__in=room_ids)
        )
        for room in rooms_qs:
            try:
                # now generate invoice
                bill = calculate_monthly_bill(room, bill_month)
                file_name = generate_invoice_for_bill(
                    bill=bill,
                    lang="kh",
                )
                storage_path = _invoice_storage_path(bill, file_name)
                if default_storage.exists(storage_path):
                    with default_storage.open(storage_path, "rb") as f:
                        zip_file.writestr(file_name, f.read())
                    generated_count += 1
                else:
                    messages.warning(
                        request, f"Invoice file not found for room {room.room_number}"
                    )
            except ValidationError as e:
                messages.error(
                    request, f"Room {room.room_number}: {'; '.join(e.messages)}"
                )
            except Exception as e:
                messages.error(
                    request, f"Room {room.room_number}: Unexpected error: {str(e)}"
                )

        zip_file.close()
        buffer.seek(0)

        if generated_count == 0:
            messages.warning(request, "No invoices generated to download.")
            return redirect("..")

        response = HttpResponse(buffer, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="invoices_{month}.zip"'
        return response

    rooms = Room.objects.all()
    return render(
        request,
        "admin/rooms/generate_invoices.html",
        {
            "rooms": rooms,
        },
    )


# View to bulk download existing invoice images
def bulk_download_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        month = request.POST.get("month")
        room_ids = request.POST.getlist("rooms")

        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)

        buffer = io.BytesIO()
        zip_file = ZipFile(buffer, "w")

        if room_ids:
            bills = MonthlyBill.objects.filter(month=bill_month, room__id__in=room_ids)
        else:
            bills = MonthlyBill.objects.filter(month=bill_month)

        for bill in bills:
            # path to existing invoice image
            filename = (
                f"invoice_room_{bill.room.room_number}_{bill.month.strftime('%Y_%m')}_kh.png"
            )
            invoice_path = _invoice_storage_path(bill, filename)

            if default_storage.exists(invoice_path):
                with default_storage.open(invoice_path, "rb") as f:
                    zip_file.writestr(filename, f.read())
            else:
                messages.warning(
                    request, f"Invoice not found for room {bill.room.room_number}"
                )

        zip_file.close()
        buffer.seek(0)

        response = HttpResponse(buffer, content_type="application/zip")
        response["Content-Disposition"] = (
            f'attachment; filename="invoices_{month}_existing.zip"'
        )
        return response

    rooms = Room.objects.all()
    return render(
        request,
        "admin/rooms/generate_invoices.html",
        {
            "rooms": rooms,
        },
    )

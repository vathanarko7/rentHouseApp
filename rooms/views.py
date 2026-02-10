from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
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

from .models import (
    MonthlyBill,
    Room,
    ClientProfile,
    UnitPrice,
    Water,
    Electricity,
    TelegramBatchJob,
)
from django.utils.formats import date_format
from django.utils.translation import override, gettext as _
from django.utils import timezone
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.cache import cache
from .services import calculate_monthly_bill, generate_invoice_for_bill
from rooms.invoice_i18n import INVOICE_LANGUAGES
import json
import mimetypes
import uuid
import urllib.request
import urllib.error
import urllib.parse
import time
import threading
from django.db import close_old_connections


def _invoice_storage_path(bill, filename):
    return (
        f"invoices/images/{bill.month.strftime('%Y_%m')}/{filename}".replace("\\", "/")
    )


def _invoice_filename(bill, lang):
    lang_cfg = INVOICE_LANGUAGES.get(lang)
    if not lang_cfg:
        return ""
    room_number = bill.room.room_number
    suffix = lang_cfg["suffix"]
    return f"invoice_room_{room_number}_{bill.month.strftime('%Y_%m')}_{suffix}.png"


def _has_missing_utility_data(bill):
    if not UnitPrice.objects.filter(date=bill.month).exists():
        return True
    if not Water.objects.filter(room=bill.room, date=bill.month).exists():
        return True
    if not Water.objects.filter(room=bill.room, date__lt=bill.month).exists():
        return True
    if not Electricity.objects.filter(room=bill.room, date=bill.month).exists():
        return True
    if not Electricity.objects.filter(room=bill.room, date__lt=bill.month).exists():
        return True
    return False


def _redirect_back(request, fallback_url=None):
    if fallback_url is None:
        fallback_url = reverse("admin:rooms_monthlybill_changelist")
    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
    )
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback_url)


def _set_job_result(bill, status, message):
    bill.last_job_status = status
    bill.last_job_message = message[:255]
    bill.last_job_at = timezone.now()
    bill.save(
        update_fields=[
            "last_job_status",
            "last_job_message",
            "last_job_at",
        ]
    )


def _admin_action_log(request, title, message):
    try:
        ct = ContentType.objects.get_for_model(MonthlyBill)
        entry = LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ct.pk,
            object_id="",
            object_repr=title,
            action_flag=CHANGE,
            change_message=message,
        )
        return entry.pk if entry else None
    except Exception:
        return None


def download_invoice(request, bill_id, lang):
    if lang not in ("kh", "en", "fr"):
        raise Http404("Invalid language")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if _has_missing_utility_data(bill):
        messages.error(
            request,
            "Invoice is unavailable because required utility data is missing.",
        )
        return _redirect_back(request)
    renter = bill.room.renter
    if renter and not hasattr(renter, "client_profile"):
        messages.warning(
            request,
            "Renter profile is missing. Some invoice fields may be blank.",
        )
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
    filename = _invoice_filename(bill, lang)
    storage_path = _invoice_storage_path(bill, filename) if filename else ""
    if not filename or not default_storage.exists(storage_path):
        if bill.status == MonthlyBill.Status.DRAFT:
            try:
                calculate_monthly_bill(room=bill.room, month=bill.month)
                generate_invoice_for_bill(bill=bill, lang=lang)
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))
                return _redirect_back(request)
            storage_path = _invoice_storage_path(bill, filename) if filename else ""
        if not filename or not default_storage.exists(storage_path):
            messages.error(
                request,
                "Invoice file is not available yet.",
            )
            return _redirect_back(request)

    return FileResponse(
        default_storage.open(storage_path, "rb"),
        as_attachment=True,
        filename=filename,
        content_type="image/png",
    )


def preview_invoice(request, bill_id):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if _has_missing_utility_data(bill):
        messages.error(
            request,
            "Invoice is unavailable because required utility data is missing.",
        )
        return _redirect_back(request)
    renter = bill.room.renter
    if renter and not hasattr(renter, "client_profile"):
        messages.warning(
            request,
            "Renter profile is missing. Some invoice fields may be blank.",
        )
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

    filename = _invoice_filename(bill, "kh")
    storage_path = _invoice_storage_path(bill, filename) if filename else ""
    if not filename or not default_storage.exists(storage_path):
        if bill.status == MonthlyBill.Status.DRAFT:
            try:
                calculate_monthly_bill(room=bill.room, month=bill.month)
                generate_invoice_for_bill(bill=bill, lang="kh")
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))
                return _redirect_back(request)
            storage_path = _invoice_storage_path(bill, filename) if filename else ""
        if not filename or not default_storage.exists(storage_path):
            messages.error(
                request,
                "Invoice file is not available yet.",
            )
            return _redirect_back(request)

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
    if _has_missing_utility_data(bill):
        messages.error(
            request,
            "Cannot re-generate invoice: required utility data is missing.",
        )
        return _redirect_back(request)
    if bill.status != MonthlyBill.Status.DRAFT:
        messages.error(request, "Invoice can only be re-generated in Draft status.")
        return _redirect_back(request)

    def _regen():
        close_old_connections()
        try:
            calculate_monthly_bill(room=bill.room, month=bill.month)
            generate_invoice_for_bill(bill=bill, lang="kh")
            _set_job_result(bill, "success", "Invoice regenerated.")
        except Exception as e:
            _set_job_result(bill, "failed", f"Re-generate failed: {str(e)}")
        finally:
            bill.async_job_pending = False
            bill.async_job_type = ""
            bill.save(update_fields=["async_job_pending", "async_job_type"])

    if getattr(settings, "ASYNC_TASKS", True):
        bill.async_job_pending = True
        bill.async_job_type = "regen"
        bill.save(update_fields=["async_job_pending", "async_job_type"])
        _set_job_result(bill, "pending", "Re-generate queued.")
        threading.Thread(target=_regen, daemon=True).start()
        messages.success(request, "Invoice re-generation queued.")
        return _redirect_back(request)

    try:
        _regen()
    except ValidationError as e:
        _set_job_result(bill, "failed", "; ".join(e.messages))
        messages.error(request, "; ".join(e.messages))
        return _redirect_back(request)

    messages.success(request, "Invoice re-generated successfully.")
    return _redirect_back(request)


def issue_invoice_view(request, bill_id):
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if _has_missing_utility_data(bill):
        messages.error(
            request,
            "Cannot issue invoice: required utility data is missing.",
        )
        return _redirect_back(request)
    if bill.status != MonthlyBill.Status.DRAFT:
        messages.error(request, "Invoice can only be issued from Draft status.")
        return _redirect_back(request)

    bill.status = MonthlyBill.Status.ISSUED
    bill.issued_at = timezone.now()
    bill.save(update_fields=["status", "issued_at"])
    _admin_action_log(
        request,
        _("Issue invoice %(room)s %(month)s")
        % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
        _("Issued invoice for %(room)s, %(month)s.")
        % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
    )

    def _generate_issue_invoice():
        close_old_connections()
        try:
            calculate_monthly_bill(room=bill.room, month=bill.month)
            generate_invoice_for_bill(bill=bill, lang="kh")
            _set_job_result(bill, "success", "Invoice issued and generated.")
        except Exception as e:
            _set_job_result(bill, "failed", f"Issue failed: {str(e)}")
        finally:
            bill.async_job_pending = False
            bill.async_job_type = ""
            bill.save(update_fields=["async_job_pending", "async_job_type"])

    if getattr(settings, "ASYNC_TASKS", True):
        bill.async_job_pending = True
        bill.async_job_type = "issue"
        bill.save(update_fields=["async_job_pending", "async_job_type"])
        _set_job_result(bill, "pending", "Issue queued.")
        threading.Thread(target=_generate_issue_invoice, daemon=True).start()

    messages.success(request, "Invoice issued successfully.")
    return _redirect_back(request)


def mark_paid_view(request, bill_id):
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if bill.status != MonthlyBill.Status.SENT:
        messages.error(request, "Invoice can only be marked Paid after it is Sent.")
        return _redirect_back(request)

    bill.status = MonthlyBill.Status.PAID
    bill.paid_at = timezone.now()
    bill.save(update_fields=["status", "paid_at"])
    _admin_action_log(
        request,
        _("Mark paid %(room)s %(month)s")
        % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
        _("Marked paid for %(room)s, %(month)s.")
        % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
    )
    messages.success(request, "Invoice marked as Paid.")
    return _redirect_back(request)


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


def _send_invoice_telegram_worker(bill, chat_id, token):
    close_old_connections()
    try:
        filename = _invoice_filename(bill, "kh")
        storage_path = _invoice_storage_path(bill, filename) if filename else ""
        if not filename or not default_storage.exists(storage_path):
            _set_job_result(bill, "failed", "Invoice file missing.")
            return
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
            "📎 ទាញដាក់ និងផ្ទៀងផ្ទាត់វិក័យប័ត្រខាងលើ"
        )
        resp = _post_multipart(
            url,
            {"chat_id": chat_id, "caption": caption},
            {"photo": (filename, invoice_bytes)},
        )
        if not resp.get("ok"):
            _set_job_result(bill, "failed", f"Telegram error: {resp}")
            return
        bill.status = MonthlyBill.Status.SENT
        bill.sent_at = timezone.now()
        _set_job_result(bill, "success", "Sent via Telegram.")
    finally:
        bill.async_job_pending = False
        bill.async_job_type = ""
        bill.save(update_fields=["status", "sent_at", "async_job_pending", "async_job_type"])


def send_invoice_telegram_view(request, bill_id):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if _has_missing_utility_data(bill):
        messages.error(
            request,
            "Cannot send invoice: required utility data is missing.",
        )
        return _redirect_back(request)
    if bill.status != MonthlyBill.Status.ISSUED:
        messages.error(request, "Invoice can only be sent when status is Issued.")
        return _redirect_back(request)

    renter = bill.room.renter
    chat_id = None
    if renter:
        chat_id = getattr(
            getattr(renter, "client_profile", None), "telegram_chat_id", None
        )
    if not chat_id:
        messages.error(request, "Tenant Telegram chat ID is missing.")
        return _redirect_back(request)

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return _redirect_back(request)

    if getattr(settings, "ASYNC_TASKS", True):
        _admin_action_log(
            request,
            _("Send invoice %(room)s %(month)s")
            % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
            _("Send invoice to tenant for %(room)s, %(month)s.")
            % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
        )
        threading.Thread(
            target=_send_invoice_telegram_worker,
            args=(bill, chat_id, token),
            daemon=True,
        ).start()
        bill.async_job_pending = True
        bill.async_job_type = "send"
        bill.save(update_fields=["async_job_pending", "async_job_type"])
        _set_job_result(bill, "pending", "Send queued.")
        messages.success(request, "Sending invoice in background.")
        return _redirect_back(request)

    filename = _invoice_filename(bill, "kh")
    storage_path = _invoice_storage_path(bill, filename) if filename else ""
    if not filename or not default_storage.exists(storage_path):
        messages.error(
            request,
            "Invoice file not generated yet. Please issue the invoice first.",
        )
        return _redirect_back(request)

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
            _set_job_result(bill, "failed", f"Telegram error: {resp}")
            messages.error(request, f"Telegram error: {resp}")
            return _redirect_back(request)
    except Exception as e:
        _set_job_result(bill, "failed", f"Telegram send failed: {str(e)}")
        messages.error(request, f"Telegram send failed: {str(e)}")
        return _redirect_back(request)

    bill.status = MonthlyBill.Status.SENT
    bill.sent_at = timezone.now()
    bill.save(update_fields=["status", "sent_at"])
    _set_job_result(bill, "success", "Sent via Telegram.")
    _admin_action_log(
        request,
        _("Send invoice %(room)s %(month)s")
        % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
        _("Send invoice to tenant for %(room)s, %(month)s.")
        % {"room": bill.room.room_number, "month": bill.month.strftime("%Y-%m")},
    )
    messages.success(request, "Invoice sent via Telegram.")
    return _redirect_back(request)


def _send_telegram_album(chat_id, token, items):
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    media = []
    files = {}
    for idx, item in enumerate(items):
        attach_name = f"file{idx}"
        media.append(
            {
                "type": "photo",
                "media": f"attach://{attach_name}",
                "caption": item.get("caption", ""),
            }
        )
        files[attach_name] = (item["filename"], item["bytes"])
    return _post_multipart(
        url,
        {"chat_id": chat_id, "media": json.dumps(media)},
        files,
        timeout=30,
    )


def _set_generate_job(
    job_id,
    status=None,
    message=None,
    completed=None,
    failed=None,
    total=None,
    errors=None,
    log_id=None,
    month=None,
    room_label=None,
    lang_code=None,
):
    key = f"generate_bills_job:{job_id}"
    job = cache.get(key, {}) or {}
    if status is not None:
        job["status"] = status
    if message is not None:
        job["message"] = message
    if completed is not None:
        job["completed"] = completed
    if failed is not None:
        job["failed"] = failed
    if total is not None:
        job["total"] = total
    if errors is not None:
        job["errors"] = errors
    if log_id is not None:
        job["log_id"] = log_id
    if month is not None:
        job["month"] = month
    if room_label is not None:
        job["room_label"] = room_label
    if lang_code is not None:
        job["lang_code"] = lang_code
    cache.set(key, job, timeout=3600)

def _update_admin_log(log_id, message):
    if not log_id:
        return
    try:
        LogEntry.objects.filter(pk=log_id).update(change_message=message[:255])
    except Exception:
        return


def _set_batch_job(job_id, status, message=None, completed=None, failed=None):
    job = TelegramBatchJob.objects.filter(pk=job_id).first()
    if not job:
        return
    if status:
        job.status = status
    if message is not None:
        job.message = message[:255]
    if completed is not None:
        job.completed_batches = completed
    if failed is not None:
        job.failed_batches = failed
    job.save(
        update_fields=[
            "status",
            "message",
            "completed_batches",
            "failed_batches",
            "updated_at",
        ]
    )


def _set_group_send_cache(job_id, errors=None, log_id=None, lang_code=None):
    key = f"telegram_group_job:{job_id}"
    job = cache.get(key, {}) or {}
    if errors is not None:
        job["errors"] = errors
    if log_id is not None:
        job["log_id"] = log_id
    if lang_code is not None:
        job["lang_code"] = lang_code
    cache.set(key, job, timeout=3600)


def _send_group_invoices_worker(job_id, chat_id, token, items, bill_ids):
    close_old_connections()
    total_batches = (len(items) + 9) // 10
    _set_batch_job(job_id, TelegramBatchJob.Status.RUNNING, "Sending albums...")
    cache_job = cache.get(f"telegram_group_job:{job_id}") or {}
    _set_group_send_cache(job_id, errors=cache_job.get("errors") or [])
    completed = 0
    failed = 0
    errors = []
    for i in range(0, len(items), 10):
        batch = items[i : i + 10]
        try:
            resp = _send_telegram_album(chat_id, token, batch)
            if not resp.get("ok"):
                failed += 1
                errors.extend([item.get("room", "") for item in batch if item.get("room")])
            else:
                completed += 1
        except Exception as e:
            failed += 1
            errors.extend([item.get("room", "") for item in batch if item.get("room")])
        errors = list(dict.fromkeys([e for e in errors if e]))
        _set_group_send_cache(job_id, errors=errors[:20])
        _set_batch_job(job_id, None, None, completed=completed, failed=failed)

    if completed == total_batches and failed == 0:
        MonthlyBill.objects.filter(
            id__in=bill_ids, status=MonthlyBill.Status.ISSUED
        ).update(status=MonthlyBill.Status.SENT, sent_at=timezone.now())
        _set_batch_job(
            job_id, TelegramBatchJob.Status.SUCCESS, "All albums sent."
        )
    elif completed > 0:
        _set_batch_job(
            job_id,
            TelegramBatchJob.Status.FAILED,
            "Some albums failed.",
        )
    else:
        _set_batch_job(job_id, TelegramBatchJob.Status.FAILED, "All albums failed.")
    try:
        job = TelegramBatchJob.objects.filter(pk=job_id).first()
        if job:
            cache_job = cache.get(f"telegram_group_job:{job_id}") or {}
            log_id = cache_job.get("log_id")
            status_label = job.status
            err_text = ", ".join(errors[:6])
            done_count = max(0, int(completed))
            msg = f"ACTION:telegram_group;STATUS:{status_label};DONE:{done_count};TOTAL:{total_batches};FAILED:{failed}"
            if err_text:
                msg = f"{msg};ROOMS:{err_text}"
            _update_admin_log(log_id, msg)
    except Exception:
        pass


def send_group_invoices_telegram_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    if request.method != "POST":
        return _redirect_back(request)

    month = request.POST.get("month", "")
    if not month:
        messages.error(request, "Please select a month.")
        return _redirect_back(request)

    try:
        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)
    except Exception:
        messages.error(request, "Invalid month format.")
        return _redirect_back(request)

    room_ids = request.POST.getlist("rooms")
    rooms_qs = Room.objects.all()
    if room_ids:
        rooms_qs = rooms_qs.filter(id__in=room_ids)
    rooms = list(rooms_qs)
    bills = MonthlyBill.objects.filter(month=bill_month, room__in=rooms)

    if not rooms:
        messages.warning(request, _("No rooms found for the selected month."))
        return _redirect_back(request)

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TENANTS_TELEGRAM_GROUP_CHAT_ID", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return _redirect_back(request)
    if not chat_id:
        messages.error(request, "Telegram group chat ID is not configured.")
        return _redirect_back(request)

    items = []
    bill_ids = []
    missing = []
    draft_rooms = []

    bills_by_room = {b.room_id: b for b in bills}
    for room in rooms:
        bill = bills_by_room.get(room.id)
        if not bill:
            missing.append(room.room_number)
            continue
        if bill.status == MonthlyBill.Status.DRAFT:
            draft_rooms.append(room.room_number)
            continue
        filename = _invoice_filename(bill, "kh")
        storage_path = _invoice_storage_path(bill, filename) if filename else ""
        if not filename or not default_storage.exists(storage_path):
            missing.append(room.room_number)
            continue
        with default_storage.open(storage_path, "rb") as f:
            data = f.read()
        items.append(
            {"filename": filename, "bytes": data, "caption": "", "room": room.room_number}
        )
        bill_ids.append(bill.id)

    if missing or draft_rooms:
        if draft_rooms:
            messages.error(
                request,
                _("Draft invoices found for rooms: %(rooms)s")
                % {"rooms": ", ".join(draft_rooms)},
            )
        if missing:
            messages.error(
                request,
                _("Missing invoice files for rooms: %(rooms)s")
                % {"rooms": ", ".join(missing)},
            )
        messages.error(
            request, _("No invoices were sent. Fix issues and try again.")
        )
        return _redirect_back(request)

    if not items:
        messages.warning(request, _("No invoice files found to send."))
        return _redirect_back(request)

    with override("km"):
        kh_month = date_format(bill_month, "F")
    kh_year = bill_month.strftime("%Y")
    album_caption = (
        f"📄 វិក្កយបត្រ ខែ {kh_month} ឆ្នាំ {kh_year}\n"
        "📎 ទាញយក និងផ្ទៀងផ្ទាត់វិក្កយបត្រខាងលើ មុននឹងបង់ប្រាក់"
    )

    for i in range(0, len(items), 10):
        if items[i : i + 10]:
            items[i]["caption"] = album_caption

    job = TelegramBatchJob.objects.create(
        created_by=request.user,
        month=bill_month,
        total_batches=(len(items) + 9) // 10,
        status=TelegramBatchJob.Status.PENDING,
        message="Queued.",
    )
    request.session["telegram_group_job_id"] = job.id
    room_label = "all rooms" if not room_ids else f"{len(room_ids)} room(s)"
    log_id = _admin_action_log(
        request,
        f"ACTION:telegram_group;MONTH:{bill_month.strftime('%Y-%m')}",
        f"Send to Telegram group ({bill_month.strftime('%Y-%m')}), {room_label}.",
    )
    _set_group_send_cache(
        job.id,
        errors=[],
        log_id=log_id,
        lang_code=getattr(request, "LANGUAGE_CODE", None),
    )

    if getattr(settings, "ASYNC_TASKS", True):
        threading.Thread(
            target=_send_group_invoices_worker,
            args=(job.id, chat_id, token, items, bill_ids),
            daemon=True,
        ).start()
        messages.success(
            request, _("Sending invoices to Telegram group in background.")
        )
        return _redirect_back(request)

    _send_group_invoices_worker(job.id, chat_id, token, items, bill_ids)
    return _redirect_back(request)


def telegram_group_status_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    job_id = request.session.get("telegram_group_job_id")
    if not job_id:
        return JsonResponse({"active": False})

    job = TelegramBatchJob.objects.filter(pk=job_id).first()
    if not job:
        request.session.pop("telegram_group_job_id", None)
        return JsonResponse({"active": False})

    done = job.status in (TelegramBatchJob.Status.SUCCESS, TelegramBatchJob.Status.FAILED)
    if done:
        request.session.pop("telegram_group_job_id", None)
        cache.delete(f"telegram_group_job:{job_id}")

    cache_job = cache.get(f"telegram_group_job:{job_id}") or {}
    errors = cache_job.get("errors") or []

    return JsonResponse(
        {
            "active": True,
            "status": job.status,
            "message": job.message,
            "total": job.total_batches,
            "completed": job.completed_batches,
            "failed": job.failed_batches,
            "errors": errors,
            "done": done,
        }
    )


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
        return _redirect_back(request, reverse("admin:rooms_clientprofile_changelist"))

    url = f"https://api.telegram.org/bot{token}/getMe"
    last_error = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                messages.error(request, f"Telegram test failed: {data}")
                return _redirect_back(
                    request, reverse("admin:rooms_clientprofile_changelist")
                )
            result = data.get("result") or {}
            bot_name = result.get("username") or result.get("first_name") or "Unknown"
            messages.success(
                request,
                _("Telegram connection OK: %(bot_name)s") % {"bot_name": bot_name},
            )
            return _redirect_back(
                request, reverse("admin:rooms_clientprofile_changelist")
            )
        except Exception as e:
            last_error = e
            if attempt == 0:
                time.sleep(0.5)
                continue
    messages.error(request, f"Telegram test failed: {str(last_error)}")
    return _redirect_back(request, reverse("admin:rooms_clientprofile_changelist"))


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
        return _redirect_back(request)

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return _redirect_back(request)

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
    last_error = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=payload)
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                messages.error(request, f"Telegram test failed: {data}")
                return _redirect_back(request)
            messages.success(request, "Tenant Telegram test message sent.")
            return _redirect_back(request)
        except Exception as e:
            last_error = e
            if attempt == 0:
                time.sleep(0.5)
                continue
    messages.error(request, f"Telegram test failed: {str(last_error)}")
    return _redirect_back(request)


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
        return _redirect_back(request, reverse("admin:rooms_clientprofile_changelist"))

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        messages.error(request, "Telegram bot token is not configured.")
        return _redirect_back(request, reverse("admin:rooms_clientprofile_changelist"))

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
    last_error = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=payload)
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                messages.error(request, f"Telegram test failed: {data}")
                return _redirect_back(
                    request, reverse("admin:rooms_clientprofile_changelist")
                )
            messages.success(request, "Tenant Telegram test message sent.")
            return _redirect_back(
                request, reverse("admin:rooms_clientprofile_changelist")
            )
        except Exception as e:
            last_error = e
            if attempt == 0:
                time.sleep(0.5)
                continue
    messages.error(request, f"Telegram test failed: {str(last_error)}")
    return _redirect_back(request, reverse("admin:rooms_clientprofile_changelist"))


# View to generate invoices for selected rooms and month
def _generate_invoices_worker(job_id, bill_month, room_ids):
    close_old_connections()
    rooms_qs = Room.objects.all()
    if room_ids:
        rooms_qs = rooms_qs.filter(id__in=room_ids)
    rooms = list(rooms_qs)
    total = len(rooms)
    completed = 0
    failed = 0
    errors = []
    _set_generate_job(
        job_id,
        status="running",
        message="Generating invoices...",
        total=total,
        errors=errors,
    )
    for room in rooms:
        try:
            bill = calculate_monthly_bill(room, bill_month)
            generate_invoice_for_bill(bill=bill, lang="kh")
        except ValidationError as e:
            failed += 1
            msg = "; ".join(e.messages)
            errors.append(f"{room.room_number}: {msg}")
        except Exception as e:
            failed += 1
            errors.append(f"{room.room_number}: {str(e)}")
        completed += 1
        _set_generate_job(
            job_id,
            completed=completed,
            failed=failed,
            message=f"Generating {completed}/{total}",
            errors=errors[:12],
        )
    final_status = "success" if failed == 0 else "failed"
    _set_generate_job(
        job_id,
        status=final_status,
        message="Completed",
        completed=completed,
        failed=failed,
        total=total,
        errors=errors[:12],
    )
    key = f"generate_bills_job:{job_id}"
    meta = cache.get(key) or {}
    month_label = meta.get("month") or bill_month.strftime("%Y-%m")
    room_label = meta.get("room_label") or ""
    log_id = meta.get("log_id")
    err_rooms = []
    for err in errors:
        room = (err.split(":", 1)[0] or "").strip()
        if room:
            err_rooms.append(room)
    err_rooms = list(dict.fromkeys(err_rooms))
    err_text = ", ".join(err_rooms[:6])
    status_label = "success" if failed == 0 else "failed"
    done_count = max(0, int(completed))
    msg = f"ACTION:generate;STATUS:{status_label};DONE:{done_count};TOTAL:{total};FAILED:{failed}"
    if err_text:
        msg = f"{msg};ROOMS:{err_text}"
    _update_admin_log(log_id, msg)


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
        room_label = (
            _("all rooms") if not room_ids else _("%(count)s room(s)") % {"count": len(room_ids)}
        )
        if not getattr(settings, "ASYNC_TASKS", True):
            _admin_action_log(
                request,
                f"ACTION:generate;MONTH:{month}",
                _("Generate bills for %(month)s, %(rooms)s.")
                % {"month": month, "rooms": room_label},
            )

        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)
        generated_count = 0

        if getattr(settings, "ASYNC_TASKS", True):
            log_id = _admin_action_log(
                request,
                f"ACTION:generate;MONTH:{month}",
                _("Generate bills for %(month)s, %(rooms)s.")
                % {"month": month, "rooms": room_label},
            )
            job_id = str(uuid.uuid4())
            rooms_qs = (
                Room.objects.all()
                if not room_ids
                else Room.objects.filter(id__in=room_ids)
            )
            total = rooms_qs.count()
            if total == 0:
                messages.warning(request, _("No rooms found for the selected month."))
                return _redirect_back(request)
            _set_generate_job(
                job_id,
                status="pending",
                message="Queued.",
                total=total,
                completed=0,
                failed=0,
                log_id=log_id,
                month=month,
                room_label=room_label,
                lang_code=getattr(request, "LANGUAGE_CODE", None),
            )
            request.session["generate_invoices_job_id"] = job_id
            threading.Thread(
                target=_generate_invoices_worker,
                args=(job_id, bill_month, room_ids),
                daemon=True,
            ).start()
            messages.success(request, _("Generating invoices in background."))
            return _redirect_back(request)

        rooms_qs = (
            Room.objects.all() if not room_ids else Room.objects.filter(id__in=room_ids)
        )
        for room in rooms_qs:
            try:
                bill = calculate_monthly_bill(room, bill_month)
                try:
                    generate_invoice_for_bill(
                        bill=bill,
                        lang="kh",
                    )
                    generated_count += 1
                except ValidationError as e:
                    messages.warning(
                        request, f"Room {room.room_number}: {'; '.join(e.messages)}"
                    )
            except ValidationError as e:
                messages.error(
                    request, f"Room {room.room_number}: {'; '.join(e.messages)}"
                )
            except Exception as e:
                messages.error(
                    request, f"Room {room.room_number}: Unexpected error: {str(e)}"
                )

        messages.success(
            request, f"{generated_count} invoice(s) generated successfully"
        )
        return _redirect_back(request)

    rooms = Room.objects.all()
    return render(
        request,
        "admin/rooms/generate_invoices.html",
        {
            "rooms": rooms,
        },
    )


def generate_invoices_status_view(request):
    if (
        request.user.is_active
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Not allowed")

    job_id = request.session.get("generate_invoices_job_id")
    if not job_id:
        return JsonResponse({"active": False})

    key = f"generate_bills_job:{job_id}"
    job = cache.get(key)
    if not job:
        request.session.pop("generate_invoices_job_id", None)
        return JsonResponse({"active": False})

    status = (job.get("status") or "").lower()
    done = status in ("success", "failed")
    if done:
        request.session.pop("generate_invoices_job_id", None)

    return JsonResponse(
        {
            "active": True,
            "status": status or "pending",
            "message": job.get("message") or "",
            "total": job.get("total") or 0,
            "completed": job.get("completed") or 0,
            "failed": job.get("failed") or 0,
            "errors": job.get("errors") or [],
            "done": done,
        }
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
        room_label = (
            _("all rooms") if not room_ids else _("%(count)s room(s)") % {"count": len(room_ids)}
        )
        _admin_action_log(
            request,
            _("Generate and download bills %(month)s") % {"month": month},
            _("Generate and download bills for %(month)s, %(rooms)s.")
            % {"month": month, "rooms": room_label},
        )

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
                try:
                    file_name = generate_invoice_for_bill(
                        bill=bill,
                        lang="kh",
                    )
                except ValidationError as e:
                    messages.warning(
                        request, f"Room {room.room_number}: {'; '.join(e.messages)}"
                    )
                    continue
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
            return _redirect_back(request)

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
        room_label = (
            _("all rooms") if not room_ids else _("%(count)s room(s)") % {"count": len(room_ids)}
        )
        _admin_action_log(
            request,
            _("Download bills %(month)s") % {"month": month},
            _("Download bills for %(month)s, %(rooms)s.")
            % {"month": month, "rooms": room_label},
        )

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

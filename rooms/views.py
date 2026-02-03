from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.conf import settings
from datetime import date
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.exceptions import ValidationError
import os

from django.urls import reverse
import io
from zipfile import ZipFile

from .models import MonthlyBill, Room
from .services import calculate_monthly_bill, generate_invoice_for_bill


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
    filename = generate_invoice_for_bill(bill, lang=lang)

    invoices_dir = os.path.join(
        settings.MEDIA_ROOT, "invoices", "images", bill.month.strftime("%Y_%m")
    )
    filepath = os.path.join(invoices_dir, filename)

    return FileResponse(
        open(filepath, "rb"),
        as_attachment=True,
        filename=filepath.split("/")[-1],
        content_type="image/png",
    )


# View to generate invoices for selected rooms and month
def generate_invoices_view(request):
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        month = request.POST.get("month")
        room_ids = request.POST.getlist("rooms")

        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)
        generated_count = 0

        rooms_qs = Room.objects.all() if not room_ids else Room.objects.filter(id__in=room_ids)
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
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
        return HttpResponseForbidden("Not allowed")
    if request.method == "POST":
        month = request.POST.get("month")
        room_ids = request.POST.getlist("rooms")

        year, month_num = map(int, month.split("-"))
        bill_month = date(year, month_num, 1)

        buffer = io.BytesIO()
        zip_file = ZipFile(buffer, "w")

        invoice_dir = os.path.join(
            settings.MEDIA_ROOT, "invoices/images", bill_month.strftime("%Y_%m")
        )

        generated_count = 0

        rooms_qs = Room.objects.all() if not room_ids else Room.objects.filter(id__in=room_ids)
        for room in rooms_qs:
            try:
                # now generate invoice
                bill = calculate_monthly_bill(room, bill_month)
                file_name = generate_invoice_for_bill(
                    bill=bill,
                    lang="kh",
                )
                file_path = os.path.join(invoice_dir, file_name)
                if os.path.exists(file_path):
                    zip_file.write(file_path, file_name)
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
    if request.user.is_active and not request.user.is_staff and not request.user.is_superuser:
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
            invoice_dir = os.path.join(
                settings.MEDIA_ROOT, "invoices/images", bill_month.strftime("%Y_%m")
            )
            filename = f"invoice_room_{bill.room.room_number}_{bill.month.strftime('%Y_%m')}_kh.png"
            invoice_path = os.path.join(invoice_dir, filename)

            if os.path.exists(invoice_path):
                zip_file.write(invoice_path, os.path.basename(invoice_path))
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

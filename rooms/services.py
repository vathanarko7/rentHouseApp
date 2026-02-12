from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage

from rooms.invoice_image import generate_invoice_image
from rooms.invoice_i18n import INVOICE_LANGUAGES
from .models import UnitPrice, MonthlyBill, Water, Electricity

# from rooms.invoice_pdf import generate_invoice_pdf, generate_khmer_invoice_pdf


def get_previous_meter(model, room, date):
    """
    Finds the latest meter reading before the given date.
    Raises clear error if missing.
    """
    previous = model.objects.filter(room=room, date__lt=date).order_by("-date").first()

    if not previous:
        raise ValidationError(
            f"No previous meter reading found for {model.__name__} in room {room.room_number}"
        )

    return previous


def calculate_monthly_bill(room, month):
    """
    month = first day of billing month (date)
    """

    pending_data = False
    try:
        unit_price = UnitPrice.objects.get(date=month)
    except UnitPrice.DoesNotExist:
        unit_price = None
        pending_data = True

    # ---------- WATER ----------
    water_cost = Decimal(0)
    if unit_price:
        try:
            water_current = Water.objects.get(room=room, date=month)
            try:
                water_previous = get_previous_meter(Water, room, month)
            except ValidationError:
                water_previous = None
                pending_data = True
            if water_previous:
                water_usage = water_current.meter_value - water_previous.meter_value
                if water_usage < 0:
                    raise ValidationError("Water meter value cannot decrease")
                water_cost = Decimal(water_usage) * unit_price.water_unit_price
        except Water.DoesNotExist:
            water_cost = Decimal(0)
            pending_data = True
    else:
        pending_data = True

    # ---------- ELECTRICITY ----------
    electricity_cost = Decimal(0)
    if unit_price:
        try:
            elec_current = Electricity.objects.get(room=room, date=month)
            try:
                elec_previous = get_previous_meter(Electricity, room, month)
            except ValidationError:
                elec_previous = None
                pending_data = True
            if elec_previous:
                electricity_usage = elec_current.meter_value - elec_previous.meter_value
                if electricity_usage < 0:
                    raise ValidationError("Electricity meter value cannot decrease")
                electricity_cost = (
                    Decimal(electricity_usage) * unit_price.electricity_unit_price
                )
        except Electricity.DoesNotExist:
            electricity_cost = Decimal(0)
            pending_data = True
    else:
        pending_data = True

    # ---------- ROOM PRICE (USD → KHR) ----------
    room_cost = room.price * unit_price.exchange_rate if unit_price else Decimal(0)

    total = room_cost + water_cost + electricity_cost
    data_note = "Pending data" if pending_data else ""

    bill, _ = MonthlyBill.objects.update_or_create(
        room=room,
        month=month,
        defaults={
            "room_cost": room_cost,
            "water_cost": water_cost,
            "electricity_cost": electricity_cost,
            "total": total,
            "data_note": data_note,
        },
    )

    return bill




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


def delete_invoice_images_for_bill(bill):
    for lang in INVOICE_LANGUAGES.keys():
        filename = _invoice_filename(bill, lang)
        if not filename:
            continue
        storage_path = _invoice_storage_path(bill, filename)
        if default_storage.exists(storage_path):
            default_storage.delete(storage_path)
# ---------- PDF INVOICE GENERATION ----------
def generate_invoice_for_bill(bill, lang="kh"):
    renter = bill.room.renter
    if not renter:
        raise ValidationError(
            f"Cannot generate invoice: no renter for room {bill.room.room_number}."
        )
    if not hasattr(renter, "client_profile"):
        raise ValidationError(
            f"Cannot generate invoice: renter profile missing for room {bill.room.room_number}."
        )
    current_name = renter.get_full_name() or renter.username
    if bill.tenant_name_snapshot != current_name:
        bill.tenant_name_snapshot = current_name
        bill.save(update_fields=["tenant_name_snapshot"])
    try:
        unit_price = UnitPrice.objects.get(date=bill.month)
    except UnitPrice.DoesNotExist as e:
        raise ValidationError(
            f"Missing unit price for {bill.month.strftime('%Y-%m')}."
        ) from e

    try:
        water_current = Water.objects.get(room=bill.room, date=bill.month)
    except Water.DoesNotExist as e:
        raise ValidationError(
            f"Missing water reading for {bill.room.room_number} ({bill.month.strftime('%Y-%m')})."
        ) from e
    water_previous = get_previous_meter(Water, bill.room, bill.month)

    try:
        elec_current = Electricity.objects.get(room=bill.room, date=bill.month)
    except Electricity.DoesNotExist as e:
        raise ValidationError(
            f"Missing electricity reading for {bill.room.room_number} ({bill.month.strftime('%Y-%m')})."
        ) from e
    elec_previous = get_previous_meter(Electricity, bill.room, bill.month)

    water_usage = water_current.meter_value - water_previous.meter_value
    elec_usage = elec_current.meter_value - elec_previous.meter_value

    # pdf_eng = generate_invoice_pdf(
    #     bill=bill, water_usage=water_usage, elec_usage=elec_usage, unit_price=unit_price
    # )

    # pdf_khmer = generate_khmer_invoice_pdf(
    #     bill=bill, water_usage=water_usage, elec_usage=elec_usage, unit_price=unit_price
    # )

    image_invoice = generate_invoice_image(
        bill=bill,
        water_current=water_current,
        water_previous=water_previous,
        elec_current=elec_current,
        elec_previous=elec_previous,
        water_usage=water_usage,
        elec_usage=elec_usage,
        unit_price=unit_price,
        language=lang,
    )
    return image_invoice

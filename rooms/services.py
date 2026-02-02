from decimal import Decimal
from django.core.exceptions import ValidationError

from rooms.invoice_image import generate_invoice_image
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

    unit_price = UnitPrice.objects.get(date=month)

    # ---------- WATER ----------
    water_current = Water.objects.get(room=room, date=month)
    water_previous = get_previous_meter(Water, room, month)

    water_usage = water_current.meter_value - water_previous.meter_value
    if water_usage < 0:
        raise ValidationError("Water meter value cannot decrease")

    water_cost = Decimal(water_usage) * unit_price.water_unit_price

    # ---------- ELECTRICITY ----------
    elec_current = Electricity.objects.get(room=room, date=month)
    elec_previous = get_previous_meter(Electricity, room, month)

    electricity_usage = elec_current.meter_value - elec_previous.meter_value
    if electricity_usage < 0:
        raise ValidationError("Electricity meter value cannot decrease")

    electricity_cost = Decimal(electricity_usage) * unit_price.electricity_unit_price

    # ---------- ROOM PRICE (USD → KHR) ----------
    room_cost = room.price * unit_price.exchange_rate

    total = room_cost + water_cost + electricity_cost

    bill, _ = MonthlyBill.objects.update_or_create(
        room=room,
        month=month,
        defaults={
            "room_cost": room_cost,
            "water_cost": water_cost,
            "electricity_cost": electricity_cost,
            "total": total,
        },
    )

    return bill


# ---------- PDF INVOICE GENERATION ----------
def generate_invoice_for_bill(bill, lang="kh"):
    unit_price = UnitPrice.objects.get(date=bill.month)

    water_current = Water.objects.get(room=bill.room, date=bill.month)
    water_previous = Water.objects.filter(room=bill.room, date__lt=bill.month).latest(
        "date"
    )

    elec_current = Electricity.objects.get(room=bill.room, date=bill.month)
    elec_previous = Electricity.objects.filter(
        room=bill.room, date__lt=bill.month
    ).latest("date")

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

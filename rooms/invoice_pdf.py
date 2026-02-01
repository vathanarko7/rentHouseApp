from django.conf import settings
from datetime import date
from dateutil.relativedelta import relativedelta
import os
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

from rooms.utils import normalize_to_month_start, khmer_style, khmer_style_title


# -------- ENGLISH VERSION --------
def generate_invoice_pdf(bill, water_usage, elec_usage, unit_price):
    """
    Returns absolute file path of generated PDF
    """

    invoices_dir = os.path.join(settings.MEDIA_ROOT, "invoices/pdfs")
    os.makedirs(invoices_dir, exist_ok=True)

    filename = (
        f"invoice_room_{bill.room.room_number}_{bill.month.strftime('%Y_%m')}.pdf"
    )
    filepath = os.path.join(invoices_dir, filename)

    doc = SimpleDocTemplate(filepath, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # -------- TITLE --------
    elements.append(Paragraph("<b>RENT INVOICE</b>", styles["Title"]))
    elements.append(
        Paragraph(f"Billing Month: {bill.month.strftime('%B %Y')}", styles["Normal"])
    )
    elements.append(
        Paragraph(
            f"From date: {(normalize_to_month_start(bill.month) - relativedelta(months=1)).strftime('%d/%m/%Y')}",
            styles["Normal"],
        )
    )
    elements.append(
        Paragraph(
            f"To date: {normalize_to_month_start(bill.month).strftime('%d/%m/%Y')}",
            styles["Normal"],
        )
    )
    elements.append(
        Paragraph(f"Generated on: {date.today().strftime}", styles["Normal"])
    )
    elements.append(Paragraph("<br/>", styles["Normal"]))

    # -------- CLIENT INFO --------
    renter = bill.room.renter
    profile = renter.client_profile
    elements.append(Paragraph("<b>Client Information</b>", styles["Heading2"]))
    elements.append(
        Paragraph(
            f"Client: {renter.get_full_name() or renter.username}", styles["Normal"]
        )
    )
    elements.append(Paragraph(f"Sex: {profile.get_sex_display()}", styles["Normal"]))
    elements.append(Paragraph(f"Phone: {profile.phone}", styles["Normal"]))
    elements.append(Paragraph(f"ID Card: {profile.id_card_number}", styles["Normal"]))
    elements.append(Paragraph(f"Enter Date: {profile.enter_date}", styles["Normal"]))
    elements.append(
        Paragraph(f"Exit Date: {profile.exit_date or '-'}", styles["Normal"])
    )
    elements.append(Paragraph(f"Room: {bill.room.room_number}", styles["Normal"]))
    elements.append(Paragraph("<br/>", styles["Normal"]))

    # -------- BILL TABLE --------
    table_data = [
        ["Description", "Details", "Amount (EUR)"],
        [
            "Room Rent",
            f"{bill.room.price} USD × {unit_price.exchange_rate} KHR/USD",
            f"{bill.room_cost:.2f}",
        ],
        [
            "Water",
            f"{water_usage} units × {unit_price.water_unit_price}",
            f"{bill.water_cost:.2f}",
        ],
        [
            "Electricity",
            f"{elec_usage} units × {unit_price.electricity_unit_price}",
            f"{bill.electricity_cost:.2f}",
        ],
        ["", "", ""],
        ["TOTAL", "", f"{bill.total:.2f} EUR"],
    ]

    table = Table(table_data, colWidths=[200, 200, 100])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONT", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )

    elements.append(table)

    doc.build(elements)

    return filepath


# -------- KHMER VERSION --------
def generate_khmer_invoice_pdf(bill, water_usage, elec_usage, unit_price):
    """
    bill: MonthlyBill object
    water_usage: int
    elec_usage: int
    unit_price: UnitPrice object
    Returns path to PDF
    """

    invoices_dir = os.path.join(settings.MEDIA_ROOT, "invoices/pdfs")
    os.makedirs(invoices_dir, exist_ok=True)

    filename = (
        f"invoice_room_{bill.room.room_number}_{bill.month.strftime('%Y_%m')}_khmer.pdf"
    )
    filepath = os.path.join(invoices_dir, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    elements = []

    renter = bill.room.renter
    profile = renter.client_profile

    # -------- TITLE --------
    elements.append(Paragraph("<b>វិក័យប័ត្រ</b>", khmer_style_title))
    elements.append(Spacer(1, 12))

    # -------- BILL PERIOD & CONTACT --------
    table_data = [
        [
            "ពីថ្ងៃ",
            # bill.month.replace(month=bill.month.month).strftime("%d/%m/%Y"),
            (normalize_to_month_start(bill.month) - relativedelta(months=1)).strftime(
                "%d/%m/%Y"
            ),
            "",
            "ថ្ងៃចេញវិក័យប័ត្រ :",
            date.today().strftime("%d/%m/%Y"),
        ],
        [
            "ដល់ថ្ងៃ",
            # bill.month.strftime("%d/%m/%Y"),
            normalize_to_month_start(bill.month).strftime("%d/%m/%Y"),
            "",
            "Tel :",
            "092 46 68 18, 070 46 68 18, 088 932 32 59",
        ],
    ]
    table = Table(table_data, colWidths=[60, 100, 20, 100, 150])
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (1, 0), (1, 0)),
                ("SPAN", (4, 1), (4, 1)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, -1), "KhmerFont"),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 12))

    # -------- CLIENT INFO --------
    elements.append(Paragraph("ឈ្មោះអ្នកជួល និងព័ត៌មាន", khmer_style))
    client_data = [
        [
            "ឈ្មោះអ្នកជួល",
            profile.user.get_full_name() or profile.user.username,
            "ភេទ",
            profile.get_sex_display(),
            "លេខសម្គាល់",
            normalize_to_month_start(bill.month).strftime("%Y%m")
            + "-"
            + bill.room.room_number,
        ],
        [
            "លេខអត្តសញ្ញាណប័ណ្ណ",
            profile.id_card_number,
            "លេខទូរស័ព្ទ",
            profile.phone,
            "លេខបន្ទប់",
            bill.room.room_number,
        ],
    ]
    client_table = Table(client_data, colWidths=[100, 120, 50, 80, 80, 80])
    client_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, -1), "KhmerFont"),
            ]
        )
    )
    elements.append(client_table)
    elements.append(Spacer(1, 12))

    # -------- USAGE TABLE --------
    usage_data = [
        ["បរិយាយ", "ខែចាស់", "ខែថ្មី", "បរិមាណ", "តម្លៃឯកតា", "តម្លៃសរុប"],
        ["បន្ទប់", "", "", "1", f"{bill.room.price}$", f"{bill.room.price}$"],
        [
            "ទឹក (m³)",
            str(bill.water_usage_prev),
            str(bill.water_usage_curr),
            f"{water_usage:05}",
            f"{unit_price.water_unit_price:,.0f}៛",
            f"{bill.water_cost:,.0f}៛",
        ],
        [
            "ភ្លើងអគ្គិសនី (kWh)",
            str(bill.electricity_usage_prev),
            str(bill.electricity_usage_curr),
            f"{elec_usage:05}",
            f"{unit_price.electricity_unit_price:,.0f}៛",
            f"{bill.electricity_cost:,.0f}៛",
        ],
        ["", "", "", "", "$0,00", ""],
        [
            "សរុប",
            "",
            "",
            "",
            "",
            f"{(bill.total/bill.exchange_rate):.2f}$ / {bill.total:,.0f}៛",
        ],
    ]
    usage_table = Table(usage_data, colWidths=[100, 60, 60, 60, 80, 80])
    usage_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (-2, 1), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, -1), "KhmerFont"),
            ]
        )
    )
    elements.append(usage_table)
    elements.append(Spacer(1, 24))

    # -------- SIGNATURES --------
    sig_data = [["ហត្ថលេខាអ្នកបង់ប្រាក់", "", "ហត្ថលេខាអ្នកទទួលប្រាក់"], ["", "", "គ្រូឌី"]]
    sig_table = Table(sig_data, colWidths=[200, 50, 200])
    sig_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("FONTNAME", (0, 0), (-1, -1), "KhmerFont"),
            ]
        )
    )
    elements.append(sig_table)

    # -------- BUILD PDF --------
    doc.build(elements)

    return filepath

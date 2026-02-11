from playwright.sync_api import sync_playwright
from rooms.invoice_i18n import INVOICE_LANGUAGES
from django.utils.formats import number_format

# from PIL import Image, ImageDraw, ImageFont
from datetime import date
import base64
from dateutil.relativedelta import relativedelta
from rentHouseApp import settings
import os
import tempfile
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rooms.utils import normalize_to_month_start


# -------- KHMER VERSION IMAGE --------
def generate_invoice_image(
    bill,
    water_current,
    water_previous,
    elec_current,
    elec_previous,
    water_usage,
    elec_usage,
    unit_price,
    language="kh",
    font_path=settings.DEFAULT_KH_FONT_PATH,
):
    """
    Generate a Khmer invoice image using headless Chromium (Playwright)
    """
    # -------- Language Setup --------
    lang = INVOICE_LANGUAGES.get(language, INVOICE_LANGUAGES["kh"])
    T = lang["texts"]

    # Prepare HTML template
    period_start = (
        normalize_to_month_start(bill.month) - relativedelta(months=1)
    ).strftime("%d/%m/%Y")
    period_end = normalize_to_month_start(bill.month).strftime("%d/%m/%Y")
    invoice_date = date.today().strftime("%d/%m/%Y")
    renter = bill.room.renter
    profile = getattr(renter, "client_profile", None) if renter else None
    client_name = "-"
    sex = ""
    id_number = ""
    phone = ""
    if bill.tenant_name_snapshot:
        client_name = bill.tenant_name_snapshot
    elif renter:
        client_name = renter.get_full_name() or renter.username
    if profile:
        sex = profile.get_sex_display()
        id_number = profile.id_card_number
        phone = profile.phone
    room_number = bill.room.room_number

    font_url = str(font_path).replace("\\", "/")
    font_data_url = ""
    try:
        with open(font_path, "rb") as f:
            font_b64 = base64.b64encode(f.read()).decode("ascii")
        font_data_url = f"data:font/ttf;base64,{font_b64}"
    except Exception:
        font_data_url = ""
    # A4 landscape at 96 DPI
    a4_width = 1123
    a4_height = 794

    def fmt_money(value, decimals=0):
        return number_format(value, decimal_pos=decimals, use_l10n=True, force_grouping=True)

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        @font-face {{
            font-family: '{lang["font"]}';
            src: url("{font_data_url if font_data_url else f'file:///{font_url}'}") format("truetype");
        }}
        @page {{
            size: A4 landscape;
            margin: 0;
        }}
        html, body {{
            width: {a4_width}px;
            height: {a4_height}px;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: '{lang["font"]}', {lang["font_fallback"]};
            font-size: 16px;
            padding: 40px;
            box-sizing: border-box;
            color: #000;
        }}
        .center {{
            text-align: center;
        }}
        .right {{
            text-align: right;
        }}
        .left {{
            text-align: left;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        td, th {{
            padding: 4px;
            vertical-align: middle;
        }}
        .border th, .border td {{
            border: 1px solid #000;
        }}
        .title {{
            font-size: 28px;
            font-weight: bold;
            color: #00205B;
        }}
        .small {{
            font-size: 14px;
        }}
        .header {{
            font-size: 16px;
            font-weight: bold;
            background-color: #00205B;
            color: white;
        }}
        .total, .owner {{
            font-weight: bold;
            font-size: 18px;
            color: #00205B;
        }}
        .signature {{
            height: 80px;
        }}
    </style>
    </head>

    <body>
    <div class="center title">{T["invoice"]}</div>
    <br>
    <table>
        <colgroup>
            <col style="width:10%">
            <col style="width:60%">
            <col style="width:15%">
            <col style="width:15%">
        </colgroup>
        <tr>
            <td>{T["from_date"]}</td>
            <td>{period_start}</td>
            <td class="right">{T["invoice_date"]}</td>
            <td>{invoice_date}</td>
        </tr>
        <tr>
            <td>{T["to_date"]}</td>
            <td>{period_end}</td>
            <td class="right">Tel :</td>
            <td>092 46 68 18</td>
        </tr>
        <tr>
            <td colspan="3"></td>
            <td>070 46 68 18</td>
        </tr>
        <tr>
            <td colspan="3"></td>
            <td>088 932 32 59</td>
        </tr>
    </table>

    <br><br>

    <table>
        <colgroup>
            <col style="width:17%">
            <col style="width:23%">
            <col style="width:10%">
            <col style="width:25%">
            <col style="width:10%">
            <col style="width:15%">
        </colgroup>
        <tr>
            <td>{T["tenant_name"]}</td><td>{client_name}</td>
            <td>{T["sex"]}</td><td>{sex}</td>
            <td>{T["identifier"]}</td><td>{bill.month.strftime("%Y%m")}-{room_number}</td>
        </tr>
        <tr>
            <td>{T["id_card"]}</td><td>{id_number or ""}</td>
            <td>{T["phone"]}</td><td>{phone or ""}</td>
            <td>{T["room"]}</td><td>{room_number}</td>
        </tr>
    </table>

        <br>

    <table class="border">
        <colgroup>
            <col style="width:25%">
            <col style="width:15%">
            <col style="width:15%">
            <col style="width:15%">
            <col style="width:15%">
            <col style="width:15%">
        </colgroup>
        <tr class="header">
            <th class="left">{T["desc"]}</th>
            <th class="right">{T["prev"]}</th>
            <th class="right">{T["curr"]}</th>
            <th class="right">{T["qty"]}</th>
            <th class="right">{T["unit_price"]}</th>
            <th class="right">{T["total_price"]}</th>
        </tr>

        <tr>
            <td>{T["room_fee"]}</td>
            <td></td><td></td>
            <td class="right">1</td>
            <td class="right">{fmt_money(bill.room.price, 2)}$</td>
            <td class="right">{fmt_money(bill.room.price, 2)}$</td>
        </tr>

        <tr>
            <td>{T["water"]}</td>
            <td class="right">{water_previous.meter_value:04}</td>
            <td class="right">{water_current.meter_value:04}</td>
            <td class="right">{water_usage:04}</td>
            <td class="right">{fmt_money(unit_price.water_unit_price, 0)}៛</td>
            <td class="right">{fmt_money(bill.water_cost, 0)}៛</td>
        </tr>

        <tr>
            <td>{T["electricity"]}</td>
            <td class="right">{elec_previous.meter_value:05}</td>
            <td class="right">{elec_current.meter_value:05}</td>
            <td class="right">{elec_usage:05}</td>
            <td class="right">{fmt_money(unit_price.electricity_unit_price, 0)}៛</td>
            <td class="right">{fmt_money(bill.electricity_cost, 0)}៛</td>
        </tr>
    </table>

    <table>
        <colgroup>
            <col style="width:25%">
            <col style="width:15%">
            <col style="width:15%">
            <col style="width:15%">
            <col style="width:15%">
            <col style="width:15%">
        </colgroup>
        <tr>
            <td colspan="4" style="font-style: italic;">{T["note"]}</td>
            <td class="right total">{T["total"]}</td>
            <td class="right total">{fmt_money(bill.total/unit_price.exchange_rate, 2)}$</td>
        </tr>

        <tr>
            <td colspan="4"></td>
            <td class="right total">{T["total_khr"]}</td>
            <td class="right total">{fmt_money(bill.total, 0)}៛</td>
        </tr>
    </table>

    <br>

    <table>
    <tr class="signature">
        <td class="center">{T["payer_sig"]}</td>
        <td></td>
        <td class="center">{T["receiver_sig"]}</td>
    </tr>
    <tr>
        <td></td><td></td>
        <td class="center owner">គ្រូឌី</td>
    </tr>
    </table>

    </body>
    </html>
    """
    # filename and storage path
    suffix = lang["suffix"]
    filename = (
        f"invoice_room_{room_number}_" f"{bill.month.strftime('%Y_%m')}_{suffix}.png"
    )
    storage_path = os.path.join(
        "invoices",
        "images",
        bill.month.strftime("%Y_%m"),
        filename,
    ).replace("\\", "/")

    # ---------- Render HTML in headless Chromium ----------
    tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--allow-file-access-from-files"]
        )
        page = browser.new_page(
            viewport={"width": a4_width, "height": a4_height},
            device_scale_factor=1,
        )
        page.set_content(html_content, wait_until="networkidle")
        # Take screenshot at exact A4 size
        page.screenshot(
            path=tmp_path,
            clip={"x": 0, "y": 0, "width": a4_width, "height": a4_height},
        )
        browser.close()

    with open(tmp_path, "rb") as f:
        if default_storage.exists(storage_path):
            default_storage.delete(storage_path)
        default_storage.save(storage_path, ContentFile(f.read()))
    os.unlink(tmp_path)

    return filename

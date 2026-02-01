from datetime import date
from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle

# Utility functions for the rooms app


def first_day_of_current_month():
    today = date.today()
    return date(today.year, today.month, 1)


def normalize_to_month_start(month_date):
    return month_date.replace(day=1)


# Register Khmer font
khmer_font_path = "rooms/fonts/NotoSansKhmer-Regular.ttf"
pdfmetrics.registerFont(TTFont("KhmerFont", khmer_font_path))

# ----- Paragraph style -----
khmer_style = ParagraphStyle(
    "KhmerStyle", fontName="KhmerFont", fontSize=12, leading=14
)

khmer_style_title = ParagraphStyle(
    "KhmerTitle", fontName="KhmerFont", fontSize=20, leading=24
)

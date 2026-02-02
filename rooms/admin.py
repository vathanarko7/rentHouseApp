from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from types import MethodType
from rooms.models import ClientProfile, MonthlyBill, Room, UnitPrice, Water, Electricity
from django.utils.html import format_html
from rooms.views import (
    download_invoice,
    generate_invoices_view,
    generate_and_download_view,
    bulk_download_view,
)
from django.urls import reverse, path

# Register your models here.
admin.site.site_header = "Rent House Administration"
admin.site.site_title = "Rent House Admin Portal"
admin.site.index_title = "Welcome to Rent House Admin Portal"
# admin.site.register(Room)
# admin.site.register(MonthlyBill)


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "sex",
        "phone",
        "id_card_number",
        "enter_date",
        "exit_date",
    )
    search_fields = ("user__username", "phone", "id_card_number")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("room_number", "renter_name", "price")
    search_fields = (
        "room_number",
        "renter__username",
        "renter__first_name",
        "renter__last_name",
    )
    ordering = ("room_number",)

    def renter_name(self, obj):
        renter = obj.renter
        if renter:
            name = renter.get_full_name() or renter.username
            phone = getattr(getattr(renter, "client_profile", None), "phone", None)
            if phone:
                return f"{name} ({phone})"
            return name
        return "-"

    renter_name.short_description = "Renter"


class MonthlyBillMonthFilter(SimpleListFilter):
    title = "month"
    parameter_name = "month"

    def lookups(self, request, model_admin):
        months = MonthlyBill.objects.dates("month", "month", order="DESC")
        return [(d.strftime("%Y-%m"), d.strftime("%Y-%m")) for d in months]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        parts = value.split("-")
        if len(parts) != 2:
            return queryset
        year, month = parts
        return queryset.filter(month__year=year, month__month=month)


class ReadingMonthFilter(SimpleListFilter):
    title = "month"
    parameter_name = "month"

    def lookups(self, request, model_admin):
        months = model_admin.model.objects.dates("date", "month", order="DESC")
        return [(d.strftime("%Y-%m"), d.strftime("%Y-%m")) for d in months]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        parts = value.split("-")
        if len(parts) != 2:
            return queryset
        year, month = parts
        return queryset.filter(date__year=year, date__month=month)


@admin.register(UnitPrice)
class UnitPriceAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "water_unit_price",
        "electricity_unit_price",
        "exchange_rate",
    )
    list_filter = (ReadingMonthFilter,)
    ordering = ("-date",)


@admin.register(Water)
class WaterAdmin(admin.ModelAdmin):
    list_display = ("date", "room", "meter_value")
    list_filter = ("room", ReadingMonthFilter)
    search_fields = ("room__room_number",)
    ordering = ("-date", "room__room_number")


@admin.register(Electricity)
class ElectricityAdmin(admin.ModelAdmin):
    list_display = ("date", "room", "meter_value")
    list_filter = ("room", ReadingMonthFilter)
    search_fields = ("room__room_number",)
    ordering = ("-date", "room__room_number")


@admin.register(MonthlyBill)
class MonthlyBillAdmin(admin.ModelAdmin):
    list_display = ("id", "month", "room", "renter", "total", "invoice_actions")
    list_filter = ("room", MonthlyBillMonthFilter)
    search_fields = (
        "room__room_number",
        "room__renter__username",
        "room__renter__first_name",
        "room__renter__last_name",
    )
    ordering = ("-month", "room__room_number")
    list_per_page = 25

    def renter(self, obj):
        renter = obj.room.renter
        if renter:
            return renter.get_full_name() or renter.username
        return "-"

    renter.short_description = "Renter"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:bill_id>/invoice/<str:lang>/",
                self.admin_site.admin_view(download_invoice),
                name="rooms_monthlybill_download_invoice",
            ),
            path(
                "generate-invoices/",
                self.admin_site.admin_view(generate_invoices_view),
                name="rooms_generate_invoices",
            ),
            path(
                "generate-download/",
                self.admin_site.admin_view(generate_and_download_view),
                name="rooms_generate_download",
            ),
            path(
                "bulk-download/",
                self.admin_site.admin_view(bulk_download_view),
                name="rooms_bulk_download",
            ),
        ]
        return custom_urls + urls

    def invoice_actions(self, obj):
        return format_html(
            '<a class="button" href="{}">KH</a> '
            '<a class="button" href="{}">EN</a> '
            '<a class="button" href="{}">FR</a>',
            reverse("admin:rooms_monthlybill_download_invoice", args=[obj.id, "kh"]),
            reverse("admin:rooms_monthlybill_download_invoice", args=[obj.id, "en"]),
            reverse("admin:rooms_monthlybill_download_invoice", args=[obj.id, "fr"]),
        )

    invoice_actions.short_description = "Invoice"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(
            {
                "generate_invoice_url": reverse("admin:rooms_generate_invoices"),
                "generate_download_url": reverse("admin:rooms_generate_download"),
                "bulk_download_url": reverse("admin:rooms_bulk_download"),
                "rooms": Room.objects.all(),
            }
        )
        return super().changelist_view(request, extra_context)


def _custom_get_app_list(self, request, app_label=None):
    app_list = admin.AdminSite.get_app_list(self, request, app_label=app_label)
    monthly_bill_model = None

    for app in app_list:
        if app.get("app_label") != "rooms":
            continue
        models = app.get("models", [])
        by_name = {m.get("object_name"): m for m in models}
        if "MonthlyBill" in by_name:
            monthly_bill_model = by_name.get("MonthlyBill")

        order = [
            "ClientProfile",
            "Room",
            "Electricity",
            "Water",
            "UnitPrice",
        ]
        ordered = [by_name[name] for name in order if name in by_name]
        for model in models:
            name = model.get("object_name")
            if name == "MonthlyBill":
                continue
            if name not in order:
                ordered.append(model)
        app["models"] = ordered

    if monthly_bill_model:
        invoice_app = {
            "name": "Invoice",
            "app_label": "invoice",
            "app_url": monthly_bill_model.get("admin_url", ""),
            "has_module_perms": True,
            "models": [monthly_bill_model],
        }
        app_list.append(invoice_app)

    return app_list


admin.site.get_app_list = MethodType(_custom_get_app_list, admin.site)

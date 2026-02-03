from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from types import MethodType
from django.contrib.auth.models import User
from django import forms
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


class ClientProfileAdminForm(forms.ModelForm):
    username = forms.CharField(max_length=150, required=True)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to set an unusable password.",
    )

    class Meta:
        model = ClientProfile
        fields = ("sex", "phone", "id_card_number", "enter_date", "exit_date")
        field_order = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "sex",
            "phone",
            "id_card_number",
            "enter_date",
            "exit_date",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            user = self.instance.user
            if user:
                self.initial.update(
                    {
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "email": user.email,
                    }
                )
            for name in ("username", "first_name", "last_name", "email", "password"):
                self.fields[name].required = False
                self.fields[name].disabled = True

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if not username:
            return username
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if not email:
            return email
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Email already exists.")
        return email


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    form = ClientProfileAdminForm
    fieldsets = (
        (
            "Account Info",
            {
                "fields": (
                    "username",
                    "first_name",
                    "last_name",
                    "email",
                    "password",
                )
            },
        ),
        (
            "Profile Info",
            {
                "classes": ("collapse",),
                "fields": (
                    "sex",
                    "phone",
                    "id_card_number",
                    "enter_date",
                    "exit_date",
                ),
            },
        ),
    )
    list_display = (
        "user",
        "sex",
        "email",
        "phone",
        "id_card_number",
        "enter_date",
        "exit_date",
    )
    search_fields = ("user__username", "phone", "id_card_number")

    def email(self, obj):
        user = obj.user
        return user.email if user else ""

    email.short_description = "Email"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(
            user__is_active=True,
            user__is_staff=False,
            user__is_superuser=False,
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change and not obj.user_id:
            username = form.cleaned_data.get("username")
            first_name = form.cleaned_data.get("first_name", "")
            last_name = form.cleaned_data.get("last_name", "")
            email = form.cleaned_data.get("email", "")
            password = form.cleaned_data.get("password", "")

            user = User(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            if password:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save()
            obj.user = user

            existing_profile = ClientProfile.objects.filter(user=user).first()
            if existing_profile and existing_profile.pk != obj.pk:
                existing_profile.sex = form.cleaned_data.get("sex")
                existing_profile.phone = form.cleaned_data.get("phone")
                existing_profile.id_card_number = form.cleaned_data.get(
                    "id_card_number"
                )
                existing_profile.enter_date = form.cleaned_data.get("enter_date")
                existing_profile.exit_date = form.cleaned_data.get("exit_date")
                existing_profile.save()
                return

        super().save_model(request, obj, form, change)


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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "renter":
            kwargs["queryset"] = User.objects.filter(
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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

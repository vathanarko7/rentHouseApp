from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin import SimpleListFilter
from types import MethodType
from django.contrib.auth.models import User
from django.contrib.auth import login as auth_login
from django.contrib.auth.forms import AuthenticationForm
from django.template.response import TemplateResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.utils.formats import date_format
from django.shortcuts import redirect
from django.conf import settings
from django.utils import timezone
import os
from django import forms
from rooms.models import (
    ClientProfile,
    MonthlyBill,
    Room,
    UnitPrice,
    Water,
    Electricity,
    RoomHistory,
)
from django.utils.html import format_html
from rooms.views import (
    download_invoice,
    generate_invoices_view,
    bulk_download_view,
    regenerate_invoice_view,
    issue_invoice_view,
    mark_paid_view,
    preview_invoice,
    send_invoice_telegram_view,
    test_telegram_connection_view,
    test_clientprofile_telegram_view,
    _post_multipart,
)
from rooms.services import generate_invoice_for_bill
from django.urls import reverse, path, re_path
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.core.exceptions import PermissionDenied

# Register your models here.
admin.site.site_header = "Rent House Administration"
admin.site.site_title = "Rent House Admin Portal"
admin.site.index_title = "Welcome to Rent House Admin Portal"
admin.ModelAdmin.save_on_top = True
# admin.site.register(Room)
# admin.site.register(MonthlyBill)


def _is_tenant(user):
    return (
        user.is_active
        and not user.is_staff
        and not user.is_superuser
        and getattr(user, "client_profile", None) is not None
    )


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
        fields = (
            "sex",
            "phone",
            "telegram_chat_id",
            "id_card_number",
            "enter_date",
            "exit_date",
        )
        field_order = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password",
            "sex",
            "phone",
            "telegram_chat_id",
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

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if not username:
            return username
        qs = User.objects.filter(username=username)
        if self.instance and self.instance.pk and self.instance.user_id:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("Username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if not email:
            return email
        qs = User.objects.filter(email=email)
        if self.instance and self.instance.pk and self.instance.user_id:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
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
                    "telegram_chat_id",
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
        "telegram_test_action",
        "id_card_number",
        "enter_date",
        "exit_date",
    )
    search_fields = ("user__username", "phone", "id_card_number")

    def has_module_permission(self, request):
        return not _is_tenant(request.user)

    def has_view_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_add_permission(self, request):
        return not _is_tenant(request.user)

    def has_change_permission(self, request, obj=None):
        if _is_tenant(request.user):
            return False
        if obj is None:
            return True
        return obj.status == MonthlyBill.Status.DRAFT

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and obj.status != MonthlyBill.Status.DRAFT:
            messages.error(request, "This bill is locked and cannot be edited.")
            return redirect("admin:rooms_monthlybill_changelist")
        return super().change_view(request, object_id, form_url, extra_context)

    def has_delete_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != MonthlyBill.Status.DRAFT:
            return [
                "room_cost",
                "water_cost",
                "electricity_cost",
                "total",
            ]
        return super().get_readonly_fields(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    def delete_queryset(self, request, queryset):
        paid_qs = queryset.filter(status=MonthlyBill.Status.PAID)
        if paid_qs.exists():
            self.message_user(
                request,
                "Paid invoices cannot be deleted.",
                level=messages.ERROR,
            )
            queryset = queryset.exclude(status=MonthlyBill.Status.PAID)
        super().delete_queryset(request, queryset)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != MonthlyBill.Status.DRAFT:
            return [field.name for field in obj._meta.fields]
        return super().get_readonly_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != MonthlyBill.Status.DRAFT:
            return [field.name for field in obj._meta.fields]
        return super().get_readonly_fields(request, obj)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if request.user.is_staff and not request.user.is_superuser:
            raise PermissionDenied
        return super().save_model(request, obj, form, change)

    def email(self, obj):
        user = obj.user
        return user.email if user else ""

    email.short_description = "Email"

    def telegram_test_action(self, obj):
        request = getattr(self, "_request", None)
        if not request:
            return "-"
        if not (request.user.is_staff or request.user.is_superuser):
            return "-"
        chat_id = getattr(obj, "telegram_chat_id", None)
        if not chat_id:
            return format_html(
                '<span style="color: var(--body-quiet-color, #6b7280);">{}</span>',
                "No chat ID",
            )
        return format_html(
            '<a class="button" href="{}">Test Chat</a>',
            reverse("admin:rooms_clientprofile_test_telegram", args=[obj.id]),
        )

    telegram_test_action.short_description = "Telegram"

    def get_queryset(self, request):
        self._request = request
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

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:profile_id>/telegram/test/",
                self.admin_site.admin_view(test_clientprofile_telegram_view),
                name="rooms_clientprofile_test_telegram",
            ),
        ]
        return custom_urls + urls

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
        if change and obj.user_id:
            user = obj.user
            user.username = form.cleaned_data.get("username") or user.username
            user.first_name = form.cleaned_data.get("first_name", "") or ""
            user.last_name = form.cleaned_data.get("last_name", "") or ""
            user.email = form.cleaned_data.get("email", "") or ""
            password = form.cleaned_data.get("password")
            if password:
                user.set_password(password)
            user.save()


class RoomHistoryInline(admin.TabularInline):
    model = RoomHistory
    extra = 0
    can_delete = False
    readonly_fields = ("renter", "start_date", "end_date")
    classes = ("collapse",)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and (
            request.user.is_staff or request.user.is_superuser
        )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    inlines = (RoomHistoryInline,)
    list_display = ("room_number", "renter_name", "price")
    search_fields = (
        "room_number",
        "renter__username",
        "renter__first_name",
        "renter__last_name",
    )
    ordering = ("room_number",)
    fieldsets = (
        (
            "Modification de room",
            {
                "fields": ("room_number", "price", "renter"),
            },
        ),
    )

    class Media:
        js = ("admin/rooms/room_form_order.js",)

    def save_model(self, request, obj, form, change):
        previous_renter = None
        if change:
            try:
                previous_renter = Room.objects.get(pk=obj.pk).renter
            except Room.DoesNotExist:
                previous_renter = None
        super().save_model(request, obj, form, change)

        if previous_renter and previous_renter != obj.renter:
            prev_profile = getattr(previous_renter, "client_profile", None)
            start_date = getattr(prev_profile, "enter_date", None)
            end_date = getattr(prev_profile, "exit_date", None)
            existing_open = RoomHistory.objects.filter(
                room=obj, renter=previous_renter, end_date__isnull=True
            ).first()
            if existing_open:
                existing_open.end_date = end_date or existing_open.end_date
                existing_open.save()
            elif start_date:
                RoomHistory.objects.create(
                    room=obj,
                    renter=previous_renter,
                    start_date=start_date,
                    end_date=end_date,
                )

        if obj.renter:
            current_profile = getattr(obj.renter, "client_profile", None)
            start_date = getattr(current_profile, "enter_date", None)
            if start_date:
                existing_open = RoomHistory.objects.filter(
                    room=obj, renter=obj.renter, end_date__isnull=True
                ).first()
                if not existing_open:
                    RoomHistory.objects.create(
                        room=obj,
                        renter=obj.renter,
                        start_date=start_date,
                        end_date=None,
                    )

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

    def has_module_permission(self, request):
        return not _is_tenant(request.user)

    def has_view_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_add_permission(self, request):
        return not _is_tenant(request.user)

    def has_change_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_delete_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "renter":
            kwargs["queryset"] = User.objects.filter(
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        try:
            room = Room.objects.get(pk=object_id)
        except Room.DoesNotExist:
            return super().change_view(request, object_id, form_url, extra_context)

        elec_readings = (
            Electricity.objects.filter(room=room)
            .order_by("date")
            .values_list("date", "meter_value")
        )
        water_readings = (
            Water.objects.filter(room=room)
            .order_by("date")
            .values_list("date", "meter_value")
        )

        label_dates = sorted(
            {d for d, _ in elec_readings}.union({d for d, _ in water_readings})
        )
        labels = [d.strftime("%Y-%m-%d") for d in label_dates]

        elec_map = {d: v for d, v in elec_readings}
        water_map = {d: v for d, v in water_readings}

        elec_values = [elec_map.get(d) for d in label_dates]
        water_values = [water_map.get(d) for d in label_dates]

        extra_context["electricity_chart_labels"] = labels
        extra_context["electricity_chart_datasets"] = [
            {
                "label": _("Electricity (kWh)"),
                "data": elec_values,
                "borderColor": "#2563eb",
                "backgroundColor": "rgba(37, 99, 235, 0.12)",
                "fill": True,
                "tension": 0.25,
                "yAxisID": "y",
            },
            {
                "label": _("Water (m³)"),
                "data": water_values,
                "borderColor": "#0ea5e9",
                "backgroundColor": "rgba(14, 165, 233, 0.10)",
                "fill": True,
                "tension": 0.25,
                "yAxisID": "y",
            },
        ]
        extra_context["electricity_chart_texts"] = {
            "axis_readings": _("Readings"),
            "tooltip_electricity": _("Electricity"),
            "tooltip_water": _("Water"),
        }
        return super().change_view(request, object_id, form_url, extra_context)


class MonthlyBillMonthFilter(SimpleListFilter):
    title = "month"
    parameter_name = "month"

    def lookups(self, request, model_admin):
        months = model_admin.get_queryset(request).dates("month", "month", order="DESC")
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
        months = model_admin.get_queryset(request).dates("date", "month", order="DESC")
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
        "month_year",
        "water_unit_price",
        "electricity_unit_price",
        "exchange_rate",
    )
    list_filter = (ReadingMonthFilter,)
    ordering = ("-date",)

    def month_year(self, obj):
        return date_format(obj.date, "F Y")

    month_year.short_description = "Month"

    def has_module_permission(self, request):
        return not _is_tenant(request.user)

    def has_view_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_add_permission(self, request):
        return not _is_tenant(request.user)

    def has_change_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_delete_permission(self, request, obj=None):
        return not _is_tenant(request.user)


@admin.register(Water)
class WaterAdmin(admin.ModelAdmin):
    list_display = ("month_year", "room", "meter_value")
    list_filter = ("room", ReadingMonthFilter)
    search_fields = ("room__room_number",)
    ordering = ("-date", "room__room_number")
    list_display_links = ("room",)

    def month_year(self, obj):
        return date_format(obj.date, "F Y")

    month_year.short_description = "Month"

    def room_name(self, obj):
        return obj.room.room_number

    room_name.short_description = "Room"

    def get_list_filter(self, request):
        if _is_tenant(request.user):
            return (ReadingMonthFilter,)
        return self.list_filter

    def get_list_display(self, request):
        if _is_tenant(request.user):
            return ("month_year", "room_name", "meter_value")
        return self.list_display

    def get_list_display_links(self, request, list_display):
        if _is_tenant(request.user):
            return None
        return self.list_display_links

    def has_module_permission(self, request):
        return (
            True if _is_tenant(request.user) else super().has_module_permission(request)
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if _is_tenant(request.user):
            return qs.filter(room__renter=request.user)
        return qs

    def has_view_permission(self, request, obj=None):
        if not _is_tenant(request.user):
            return True
        if obj is None:
            return True
        return obj.room.renter_id == request.user.id

    def has_add_permission(self, request):
        return not _is_tenant(request.user)

    def has_change_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_delete_permission(self, request, obj=None):
        return not _is_tenant(request.user)


@admin.register(Electricity)
class ElectricityAdmin(admin.ModelAdmin):
    list_display = ("month_year", "room", "meter_value")
    list_filter = ("room", ReadingMonthFilter)
    search_fields = ("room__room_number",)
    ordering = ("-date", "room__room_number")
    list_display_links = ("room",)

    def month_year(self, obj):
        return date_format(obj.date, "F Y")

    month_year.short_description = "Month"

    def room_name(self, obj):
        return obj.room.room_number

    room_name.short_description = "Room"

    def get_list_filter(self, request):
        if _is_tenant(request.user):
            return (ReadingMonthFilter,)
        return self.list_filter

    def get_list_display(self, request):
        if _is_tenant(request.user):
            return ("month_year", "room_name", "meter_value")
        return self.list_display

    def get_list_display_links(self, request, list_display):
        if _is_tenant(request.user):
            return None
        return self.list_display_links

    def has_module_permission(self, request):
        return (
            True if _is_tenant(request.user) else super().has_module_permission(request)
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if _is_tenant(request.user):
            return qs.filter(room__renter=request.user)
        return qs

    def has_view_permission(self, request, obj=None):
        if not _is_tenant(request.user):
            return True
        if obj is None:
            return True
        return obj.room.renter_id == request.user.id

    def has_add_permission(self, request):
        return not _is_tenant(request.user)

    def has_change_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def has_delete_permission(self, request, obj=None):
        return not _is_tenant(request.user)


@admin.register(MonthlyBill)
class MonthlyBillAdmin(admin.ModelAdmin):
    list_display = (
        "month_year",
        "room",
        "renter",
        "status_badge",
        "status_date",
        "total",
        "invoice_actions",
        "row_actions",
    )
    list_filter = (MonthlyBillMonthFilter, "room", "status")
    search_fields = (
        "room__room_number",
        "room__renter__username",
        "room__renter__first_name",
        "room__renter__last_name",
    )
    ordering = ("-month", "room__room_number")
    list_per_page = 25
    actions = ["bulk_send_telegram"]

    def has_module_permission(self, request):
        return (
            True if _is_tenant(request.user) else super().has_module_permission(request)
        )

    def get_list_filter(self, request):
        if _is_tenant(request.user):
            return (MonthlyBillMonthFilter,)
        return self.list_filter

    def get_list_display(self, request):
        if _is_tenant(request.user):
            return (
                "month_year",
                "room_name",
                "renter",
                "status_badge",
                "status_date",
                "total",
                "row_actions",
            )
        return self.list_display

    def get_list_display_links(self, request, list_display):
        if _is_tenant(request.user):
            return None
        return super().get_list_display_links(request, list_display)

    def get_queryset(self, request):
        self._request = request
        qs = super().get_queryset(request)
        if _is_tenant(request.user):
            return qs.filter(
                room__renter=request.user,
                status__in=[
                    MonthlyBill.Status.SENT,
                    MonthlyBill.Status.PAID,
                ],
            )
        return qs

    def bulk_send_telegram(self, request, queryset):
        if _is_tenant(request.user):
            self.message_user(request, "Not allowed.", level=messages.ERROR)
            return

        if "post" not in request.POST:
            if not queryset.exists():
                self.message_user(
                    request, "Select at least one invoice.", level=messages.ERROR
                )
                return
            context = {
                **self.admin_site.each_context(request),
                "title": "Confirm bulk send",
                "action_name": "bulk_send_telegram",
                "queryset": queryset,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/rooms/monthlybill/bulk_send_confirm.html",
                context,
            )

        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            self.message_user(
                request, "Telegram bot token is not configured.", level=messages.ERROR
            )
            return

        sent_count = 0
        skipped = 0
        for bill in queryset:
            if bill.status != MonthlyBill.Status.ISSUED:
                skipped += 1
                continue
            renter = bill.room.renter
            chat_id = None
            if renter:
                chat_id = getattr(
                    getattr(renter, "client_profile", None), "telegram_chat_id", None
                )
            if not chat_id:
                skipped += 1
                continue

            filename = generate_invoice_for_bill(bill=bill, lang="kh")
            invoices_dir = os.path.join(
                settings.MEDIA_ROOT, "invoices", "images", bill.month.strftime("%Y_%m")
            )
            filepath = os.path.join(invoices_dir, filename)
            if not os.path.exists(filepath):
                skipped += 1
                continue

            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            try:
                resp = _post_multipart(
                    url,
                    {"chat_id": chat_id},
                    {"photo": filepath},
                )
                if not resp.get("ok"):
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue

            bill.status = MonthlyBill.Status.SENT
            bill.sent_at = timezone.now()
            bill.save(update_fields=["status", "sent_at"])
            sent_count += 1

        if sent_count:
            self.message_user(
                request, f"Sent {sent_count} invoice(s).", level=messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request, f"Skipped {skipped} invoice(s).", level=messages.WARNING
            )

    bulk_send_telegram.short_description = "Send via Telegram"

    def has_view_permission(self, request, obj=None):
        if not _is_tenant(request.user):
            return True
        if obj is None:
            return True
        return obj.room.renter_id == request.user.id

    def has_add_permission(self, request):
        if _is_tenant(request.user):
            return False
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if _is_tenant(request.user):
            return False
        if not request.user.is_superuser:
            return False
        if obj is None:
            return True
        return obj.status == MonthlyBill.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return not _is_tenant(request.user)

    def renter(self, obj):
        renter = obj.room.renter
        if renter:
            return renter.get_full_name() or renter.username
        return "-"

    renter.short_description = "Renter"

    def room_name(self, obj):
        return obj.room.room_number

    room_name.short_description = "Room"

    def status_badge(self, obj):
        color_map = {
            MonthlyBill.Status.DRAFT: "#f59e0b",
            MonthlyBill.Status.ISSUED: "#3b82f6",
            MonthlyBill.Status.SENT: "#8b5cf6",
            MonthlyBill.Status.PAID: "#10b981",
        }
        label_map = {
            MonthlyBill.Status.DRAFT: "Draft",
            MonthlyBill.Status.ISSUED: "Issued",
            MonthlyBill.Status.SENT: "Sent",
            MonthlyBill.Status.PAID: "Paid",
        }
        color = color_map.get(obj.status, "#6b7280")
        label = label_map.get(obj.status, obj.status)
        return format_html(
            '<span style="padding:2px 8px;border-radius:10px;'
            'background:{};color:#fff;font-size:12px;">{}</span>',
            color,
            label,
        )

    status_badge.short_description = "Status"

    def status_date(self, obj):
        if obj.status == MonthlyBill.Status.ISSUED and obj.issued_at:
            return date_format(obj.issued_at, "SHORT_DATETIME_FORMAT")
        if obj.status == MonthlyBill.Status.SENT and obj.sent_at:
            return date_format(obj.sent_at, "SHORT_DATETIME_FORMAT")
        if obj.status == MonthlyBill.Status.PAID and obj.paid_at:
            return date_format(obj.paid_at, "SHORT_DATETIME_FORMAT")
        return ""

    status_date.short_description = "Status date"

    def month_year(self, obj):
        return date_format(obj.month, "F Y")

    month_year.short_description = "Month"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:bill_id>/invoice/regenerate/",
                self.admin_site.admin_view(regenerate_invoice_view),
                name="rooms_monthlybill_regenerate_invoice",
            ),
            path(
                "<int:bill_id>/issue/",
                self.admin_site.admin_view(issue_invoice_view),
                name="rooms_monthlybill_issue",
            ),
            path(
                "<int:bill_id>/mark-paid/",
                self.admin_site.admin_view(mark_paid_view),
                name="rooms_monthlybill_mark_paid",
            ),
            path(
                "<int:bill_id>/invoice/send-telegram/",
                self.admin_site.admin_view(send_invoice_telegram_view),
                name="rooms_monthlybill_send_invoice_telegram",
            ),
            path(
                "telegram/test/",
                self.admin_site.admin_view(test_telegram_connection_view),
                name="rooms_monthlybill_test_telegram",
            ),
            path(
                "<int:bill_id>/invoice/preview/",
                self.admin_site.admin_view(preview_invoice),
                name="rooms_monthlybill_preview_invoice",
            ),
            re_path(
                r"^(?P<bill_id>\d+)/invoice/(?P<lang>kh|en|fr)/$",
                self.admin_site.admin_view(download_invoice),
                name="rooms_monthlybill_download_invoice",
            ),
            path(
                "generate-invoices/",
                self.admin_site.admin_view(generate_invoices_view),
                name="rooms_generate_invoices",
            ),
            path(
                "bulk-download/",
                self.admin_site.admin_view(bulk_download_view),
                name="rooms_bulk_download",
            ),
        ]
        return custom_urls + urls

    def invoice_actions(self, obj):
        req = getattr(self, "_request", None)
        is_tenant = _is_tenant(req.user) if req else False
        regen_link = ""
        if not is_tenant and obj.status == MonthlyBill.Status.DRAFT:
            regen_link = format_html(
                '<a class="button regen-btn btn-sm" href="{}">Re-generate</a> ',
                reverse("admin:rooms_monthlybill_regenerate_invoice", args=[obj.id]),
            )
        issue_link = ""
        if not is_tenant and obj.status == MonthlyBill.Status.DRAFT:
            issue_confirm = _("Issue this invoice? It will be locked.")
            issue_link = format_html(
                '<a class="button issue-btn btn-sm" href="{}" '
                'data-confirm-message="{}">Issue</a> ',
                reverse("admin:rooms_monthlybill_issue", args=[obj.id]),
                issue_confirm,
            )
        send_link = ""
        if not is_tenant and obj.status == MonthlyBill.Status.ISSUED:
            send_confirm = _("Send this invoice to the tenant?")
            send_link = format_html(
                '<a class="button send-btn btn-sm" href="{}" '
                'data-confirm-message="{}">Send</a> ',
                reverse("admin:rooms_monthlybill_send_invoice_telegram", args=[obj.id]),
                send_confirm,
            )
        resend_link = ""
        if not is_tenant and obj.status == MonthlyBill.Status.SENT:
            resend_confirm = _("Re-send this invoice to the tenant?")
            resend_link = format_html(
                '<a class="button send-btn btn-sm" href="{}" '
                'data-confirm-message="{}">Re-send</a> ',
                reverse("admin:rooms_monthlybill_send_invoice_telegram", args=[obj.id]),
                resend_confirm,
            )
        paid_link = ""
        if not is_tenant and obj.status == MonthlyBill.Status.SENT:
            paid_confirm = _("Mark this invoice as paid?")
            paid_link = format_html(
                '<a class="button paid-btn btn-sm" href="{}" '
                'data-confirm-message="{}">Mark Paid</a> ',
                reverse("admin:rooms_monthlybill_mark_paid", args=[obj.id]),
                paid_confirm,
            )
        test_link = ""
        if not (regen_link or issue_link or send_link or resend_link or paid_link or test_link):
            return "-"
        return format_html(
            "{}{}{}{}{}{}",
            regen_link,
            issue_link,
            send_link,
            resend_link,
            paid_link,
            test_link,
        )

    invoice_actions.short_description = "Invoice"

    def row_actions(self, obj):
        req = getattr(self, "_request", None)
        is_tenant = _is_tenant(req.user) if req else False
        show_preview = True
        if is_tenant and obj.status not in (
            MonthlyBill.Status.PAID,
            MonthlyBill.Status.SENT,
        ):
            show_preview = False
        if not show_preview:
            return "-"
        preview_btn = format_html(
            '<button class="button preview-invoice-btn preview-btn btn-sm" '
            'data-preview-url="{}" type="button">Preview</button>',
            reverse("admin:rooms_monthlybill_preview_invoice", args=[obj.id]),
        )
        download_btn = format_html(
            ' <a class="button download-btn btn-sm" href="{}">Download</a>',
            reverse("admin:rooms_monthlybill_download_invoice", args=[obj.id, "kh"]),
        )
        return format_html("{}{}", preview_btn, download_btn)

    row_actions.short_description = "Actions"

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        if not _is_tenant(request.user):
            extra_context.update(
                {
                    "generate_invoice_url": reverse("admin:rooms_generate_invoices"),
                    "bulk_download_url": reverse("admin:rooms_bulk_download"),
                    "telegram_test_url": reverse(
                        "admin:rooms_monthlybill_test_telegram"
                    ),
                    "rooms": Room.objects.all(),
                }
            )
        return super().changelist_view(request, extra_context)


def _custom_get_app_list(self, request, app_label=None):
    app_list = admin.AdminSite.get_app_list(self, request, app_label=app_label)
    monthly_bill_model = None
    dashboard_app = None

    for app in app_list:
        if app.get("app_label") != "rooms":
            continue
        models = app.get("models", [])
        models = [m for m in models if any(m.get("perms", {}).values())]
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
        dashboard_model = None
        ordered = [by_name[name] for name in order if name in by_name]
        for model in models:
            name = model.get("object_name")
            if name == "MonthlyBill":
                continue
            if name not in order:
                ordered.append(model)
        app["models"] = ordered
        dashboard_app = {
            "name": "Reports & Dashboard",
            "app_label": "dashboard",
            "app_url": reverse("admin:dashboard"),
            "has_module_perms": True,
            "models": [
                {
                    "name": "Reports & Dashboard",
                    "object_name": "Dashboard",
                    "admin_url": reverse("admin:dashboard"),
                    "perms": {
                        "view": True,
                        "add": False,
                        "change": False,
                        "delete": False,
                    },
                }
            ],
        }

    if monthly_bill_model:
        invoice_app = {
            "name": "Invoice",
            "app_label": "invoice",
            "app_url": monthly_bill_model.get("admin_url", ""),
            "has_module_perms": True,
            "models": [monthly_bill_model],
        }
        app_list.append(invoice_app)

    if dashboard_app:
        app_list.insert(0, dashboard_app)

    app_list = [app for app in app_list if app.get("models")]
    return app_list


admin.site.get_app_list = MethodType(_custom_get_app_list, admin.site)


def _custom_has_permission(self, request):
    user = request.user
    return user.is_active and (user.is_staff or user.is_superuser or _is_tenant(user))


admin.site.has_permission = MethodType(_custom_has_permission, admin.site)


class TenantAdminAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError(
                _("This account is inactive."),
                code="inactive",
            )
        if user.is_staff or user.is_superuser or _is_tenant(user):
            return
        raise forms.ValidationError(
            _("This account does not have access to the admin site."),
            code="no_admin_access",
        )


def _custom_admin_login(self, request, extra_context=None):
    redirect_to = request.POST.get("next", request.GET.get("next", ""))
    if request.method == "POST":
        form = TenantAdminAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            if _is_tenant(user):
                return redirect("tenant_dashboard")
            return redirect("admin:dashboard")
            if not url_has_allowed_host_and_scheme(
                url=redirect_to,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                redirect_to = reverse("admin:index")
            return redirect(redirect_to or "admin:index")
    else:
        form = TenantAdminAuthenticationForm(request)

    context = {
        **self.each_context(request),
        "title": _("Log in"),
        "form": form,
        "app_path": request.get_full_path(),
        "username": (
            request.user.get_username() if request.user.is_authenticated else ""
        ),
        "next": redirect_to,
    }
    if extra_context:
        context.update(extra_context)
    return TemplateResponse(request, "admin/login.html", context)


admin.site.login = MethodType(_custom_admin_login, admin.site)


def dashboard_view(request):
    if not request.user.is_active:
        raise PermissionDenied

    is_tenant = _is_tenant(request.user)

    bills = MonthlyBill.objects.all()
    waters = Water.objects.all()
    electrics = Electricity.objects.all()

    if is_tenant:
        bills = bills.filter(room__renter=request.user)
        waters = waters.filter(room__renter=request.user)
        electrics = electrics.filter(room__renter=request.user)

    income_by_month = (
        bills.annotate(m=TruncMonth("month"))
        .values("m")
        .annotate(total=Sum("total"))
        .order_by("m")
    )
    water_by_month = (
        waters.annotate(m=TruncMonth("date"))
        .values("m")
        .annotate(total=Sum("meter_value"))
        .order_by("m")
    )
    elec_by_month = (
        electrics.annotate(m=TruncMonth("date"))
        .values("m")
        .annotate(total=Sum("meter_value"))
        .order_by("m")
    )

    def build_series(qs):
        labels = []
        values = []
        for row in qs:
            if not row["m"]:
                continue
            labels.append(row["m"].strftime("%B %Y"))
            values.append(float(row["total"] or 0))
        return labels, values

    income_labels, income_values = build_series(income_by_month)
    water_labels, water_values = build_series(water_by_month)
    elec_labels, elec_values = build_series(elec_by_month)

    context = {
        **admin.site.each_context(request),
        "title": "Reports & Dashboard",
        "is_tenant": is_tenant,
        "income_labels": income_labels,
        "income_values": income_values,
        "water_labels": water_labels,
        "water_values": water_values,
        "elec_labels": elec_labels,
        "elec_values": elec_values,
    }
    return TemplateResponse(request, "admin/dashboard.html", context)


admin.site.get_urls = MethodType(
    lambda self: [path("dashboard/", self.admin_view(dashboard_view), name="dashboard")]
    + admin.AdminSite.get_urls(self),
    admin.site,
)

from django.contrib import admin
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
from django import forms
from rooms.models import ClientProfile, MonthlyBill, Room, UnitPrice, Water, Electricity, RoomHistory
from django.utils.html import format_html
from rooms.views import (
    download_invoice,
    generate_invoices_view,
    generate_and_download_view,
    bulk_download_view,
)
from django.urls import reverse, path
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
        return request.user.is_active and (request.user.is_staff or request.user.is_superuser)

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

    def month_year(self, obj):
        return date_format(obj.date, "F Y")

    month_year.short_description = "Month"

    def get_list_filter(self, request):
        if _is_tenant(request.user):
            return (ReadingMonthFilter,)
        return self.list_filter

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

    def month_year(self, obj):
        return date_format(obj.date, "F Y")

    month_year.short_description = "Month"

    def get_list_filter(self, request):
        if _is_tenant(request.user):
            return (ReadingMonthFilter,)
        return self.list_filter

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
    list_display = ("id", "month_year", "room", "renter", "total", "invoice_actions")
    list_filter = ("room", MonthlyBillMonthFilter)
    search_fields = (
        "room__room_number",
        "room__renter__username",
        "room__renter__first_name",
        "room__renter__last_name",
    )
    ordering = ("-month", "room__room_number")
    list_per_page = 25

    def has_module_permission(self, request):
        return (
            True if _is_tenant(request.user) else super().has_module_permission(request)
        )

    def get_list_filter(self, request):
        if _is_tenant(request.user):
            return (MonthlyBillMonthFilter,)
        return self.list_filter

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

    def renter(self, obj):
        renter = obj.room.renter
        if renter:
            return renter.get_full_name() or renter.username
        return "-"

    renter.short_description = "Renter"

    def month_year(self, obj):
        return date_format(obj.month, "F Y")

    month_year.short_description = "Month"

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
        if not _is_tenant(request.user):
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
            auth_login(request, form.get_user())
            if _is_tenant(request.user):
                return redirect("admin:rooms_monthlybill_changelist")
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

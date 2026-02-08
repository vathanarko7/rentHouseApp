from django.db import models
from django.contrib.auth.models import User
from django.forms import ValidationError

from rooms.utils import first_day_of_current_month
from django.utils.translation import gettext_lazy as _
from django.conf import settings


# Create your models here.
class Room(models.Model):
    room_number = models.CharField(max_length=10, unique=True, verbose_name=_("Room number"))
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Price"))

    # 1 room - 1 client (user)
    renter = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="room",
        verbose_name=_("Renter"),
    )

    def __str__(self):
        return _("Room %(number)s") % {"number": self.room_number}

    class Meta:
        verbose_name = _("Room")
        verbose_name_plural = _("Rooms")


class RoomHistory(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="history")
    renter = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="room_history",
        verbose_name=_("Renter"),
    )
    start_date = models.DateField(verbose_name=_("Start date"))
    end_date = models.DateField(null=True, blank=True, verbose_name=_("End date"))

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = _("Room History")

    def __str__(self):
        renter_name = self.renter.get_full_name() if self.renter else _("Unknown")
        return f"{self.room.room_number} - {renter_name}"


# Utility Water meter readings
class Water(models.Model):
    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="waters", verbose_name=_("Room")
    )
    date = models.DateField(default=first_day_of_current_month, verbose_name=_("Date"))
    meter_value = models.PositiveIntegerField(verbose_name=_("Meter value"))

    is_initial = models.BooleanField(
        default=False,
        help_text=_("Initial meter reading at move-in"),
        verbose_name=_("Is initial"),
    )

    class Meta:
        unique_together = ("room", "date")
        verbose_name = _("Water")
        verbose_name_plural = _("Water Readings")
        ordering = ["date"]

    def __str__(self):
        return _("Water of room %(room)s - %(month)s") % {
            "room": self.room.room_number,
            "month": self.date.strftime("%Y-%m"),
        }


# Utility Electricity meter readings
class Electricity(models.Model):
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="electricities",
        verbose_name=_("Room"),
    )
    date = models.DateField(default=first_day_of_current_month, verbose_name=_("Date"))
    meter_value = models.PositiveIntegerField(verbose_name=_("Meter value"))

    is_initial = models.BooleanField(
        default=False,
        help_text=_("Initial meter reading at move-in"),
        verbose_name=_("Is initial"),
    )

    class Meta:
        unique_together = ("room", "date")
        ordering = ["date"]
        verbose_name = _("Electricity")
        verbose_name_plural = _("Electricity Readings")

    def __str__(self):
        return _("Electricity of room %(room)s - %(month)s") % {
            "room": self.room.room_number,
            "month": self.date.strftime("%Y-%m"),
        }


# Unit prices for utilities
class UnitPrice(models.Model):
    date = models.DateField(
        default=first_day_of_current_month,
        help_text=_("First day of month"),
        verbose_name=_("Date"),
    )

    water_unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=2000,
        verbose_name=_("Water unit price"),
    )
    electricity_unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1000,
        verbose_name=_("Electricity unit price"),
    )

    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=4000,
        help_text=_("Exchange rate USD to KHR"),
        verbose_name=_("Exchange rate"),
    )

    class Meta:
        unique_together = ("date",)
        verbose_name = _("Unit Price")
        verbose_name_plural = _("Utility Rates")

    def __str__(self):
        return _("Unit Price of %(month)s") % {"month": self.date.strftime("%Y-%m")}


# Client profile extending User model
class ClientProfile(models.Model):
    SEX_CHOICES = (
        ("M", _("Male")),
        ("F", _("Female")),
        ("O", _("Other")),
    )

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="client_profile"
    )

    sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)

    phone = models.CharField(max_length=20, null=True, blank=True)
    telegram_chat_id = models.CharField(max_length=64, null=True, blank=True)
    id_card_number = models.CharField(max_length=50, unique=True, null=True, blank=True)

    enter_date = models.DateField(null=True, blank=True, help_text=_("Move-in date"))
    exit_date = models.DateField(null=True, blank=True, help_text=_("Move-out date"))

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"

    def clean(self):
        if self.exit_date and self.exit_date <= self.enter_date:
            raise ValidationError(_("Exit date cannot be before enter date"))

    class Meta:
        verbose_name = _("Tenant")
        verbose_name_plural = _("Tenants")


# Monthly bill for a room
class MonthlyBill(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")
        SENT = "sent", _("Sent")
        PAID = "paid", _("Paid")

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="bills", verbose_name=_("Room")
    )

    month = models.DateField(verbose_name=_("Month"))

    room_cost = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name=_("Room cost")
    )
    water_cost = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name=_("Water cost")
    )
    electricity_cost = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name=_("Electricity cost")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name=_("Total")
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, verbose_name=_("Status")
    )
    issued_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Issued at"))
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Sent at"))
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Paid at"))
    async_job_pending = models.BooleanField(
        default=False, verbose_name=_("Async job pending")
    )
    async_job_type = models.CharField(
        max_length=32, blank=True, default="", verbose_name=_("Async job type")
    )
    data_note = models.CharField(
        max_length=100, blank=True, default="", verbose_name=_("Data note")
    )
    tenant_name_snapshot = models.CharField(
        max_length=150, blank=True, default="", verbose_name=_("Tenant name snapshot")
    )
    last_job_status = models.CharField(
        max_length=12, blank=True, default="", verbose_name=_("Last job status")
    )
    last_job_message = models.CharField(
        max_length=255, blank=True, default="", verbose_name=_("Last job message")
    )
    last_job_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last job at")
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    class Meta:
        unique_together = ("room", "month")
        verbose_name = _("Monthly bill")
        verbose_name_plural = _("Monthly Bills")

    def __str__(self):
        return _("Bill %(room)s %(month)s") % {
            "room": self.room.room_number,
            "month": self.month.strftime("%Y-%m"),
        }

    def clean(self):
        if not self.pk:
            return
        current = MonthlyBill.objects.filter(pk=self.pk).values_list("status", flat=True).first()
        if not current:
            return
        order = {
            self.Status.DRAFT: 0,
            self.Status.ISSUED: 1,
            self.Status.SENT: 2,
            self.Status.PAID: 3,
        }
        if order.get(self.status, 0) < order.get(current, 0):
            raise ValidationError(_("Status cannot move backward."))


class TelegramBatchJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        RUNNING = "running", _("Running")
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="telegram_batch_jobs",
    )
    month = models.DateField()
    total_batches = models.PositiveIntegerField(default=0)
    completed_batches = models.PositiveIntegerField(default=0)
    failed_batches = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    message = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Telegram batch {self.month.strftime('%Y-%m')} ({self.status})"

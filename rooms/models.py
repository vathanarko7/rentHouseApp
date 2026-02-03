from django.db import models
from django.contrib.auth.models import User
from django.forms import ValidationError

from rooms.utils import first_day_of_current_month


# Create your models here.
class Room(models.Model):
    room_number = models.CharField(max_length=10, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # 1 room - 1 client (user)
    renter = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="room"
    )

    def __str__(self):
        return f"Room {self.room_number}"

    class Meta:
        verbose_name_plural = "Rooms"


class RoomHistory(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="history")
    renter = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="room_history"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = "Room History"

    def __str__(self):
        renter_name = self.renter.get_full_name() if self.renter else "Unknown"
        return f"{self.room.room_number} - {renter_name}"


# Utility Water meter readings
class Water(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="waters")
    date = models.DateField(default=first_day_of_current_month)
    meter_value = models.PositiveIntegerField()

    is_initial = models.BooleanField(
        default=False, help_text="Initial meter reading at move-in"
    )

    class Meta:
        unique_together = ("room", "date")
        verbose_name_plural = "Water Readings"
        ordering = ["date"]

    def __str__(self):
        return f"Water of room {self.room.room_number} - {self.date.strftime('%Y-%m')}"


# Utility Electricity meter readings
class Electricity(models.Model):
    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="electricities"
    )
    date = models.DateField(default=first_day_of_current_month)
    meter_value = models.PositiveIntegerField()

    is_initial = models.BooleanField(
        default=False, help_text="Initial meter reading at move-in"
    )

    class Meta:
        unique_together = ("room", "date")
        ordering = ["date"]
        verbose_name_plural = "Water Readings"
        verbose_name_plural = "Electricity Readings"

    def __str__(self):
        return f"Electricity of room {self.room.room_number} - {self.date.strftime('%Y-%m')}"


# Unit prices for utilities
class UnitPrice(models.Model):
    date = models.DateField(
        default=first_day_of_current_month, help_text="First day of month"
    )

    water_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=2000
    )
    electricity_unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=1000
    )

    exchange_rate = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=4000,
        help_text="Exchange rate USD → KHR",
    )

    class Meta:
        unique_together = ("date",)
        verbose_name_plural = "Utility Rates"

    def __str__(self):
        return f"UnitPrice of {self.date.strftime('%Y-%m')}"


# Client profile extending User model
class ClientProfile(models.Model):
    SEX_CHOICES = (
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
    )

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="client_profile"
    )

    sex = models.CharField(max_length=1, choices=SEX_CHOICES, blank=True)

    phone = models.CharField(max_length=20, null=True, blank=True)
    id_card_number = models.CharField(max_length=50, unique=True, null=True, blank=True)

    enter_date = models.DateField(null=True, blank=True, help_text="Move-in date")
    exit_date = models.DateField(null=True, blank=True, help_text="Move-out date")

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"

    def clean(self):
        if self.exit_date and self.exit_date <= self.enter_date:
            raise ValidationError("Exit date cannot be before enter date")

    class Meta:
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"


# Monthly bill for a room
class MonthlyBill(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="bills")

    month = models.DateField()

    room_cost = models.DecimalField(max_digits=12, decimal_places=2)
    water_cost = models.DecimalField(max_digits=12, decimal_places=2)
    electricity_cost = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("room", "month")
        verbose_name_plural = "Monthly Bills"

    def __str__(self):
        return f"Bill {self.room.room_number} {self.month.strftime('%Y-%m')}"

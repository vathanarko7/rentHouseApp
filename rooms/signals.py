from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import ClientProfile, MonthlyBill, Water, Electricity, UnitPrice
from .services import calculate_monthly_bill


@receiver(post_save, sender=User)
def create_client_profile(sender, instance, created, **kwargs):
    if created:
        ClientProfile.objects.create(user=instance)


def _recalculate_draft(room, month):
    if not MonthlyBill.objects.filter(
        room=room, month=month, status=MonthlyBill.Status.DRAFT
    ).exists():
        return
    calculate_monthly_bill(room=room, month=month)


@receiver(post_save, sender=Water)
def recalc_draft_on_water_save(sender, instance, **kwargs):
    _recalculate_draft(instance.room, instance.date)


@receiver(post_save, sender=Electricity)
def recalc_draft_on_electricity_save(sender, instance, **kwargs):
    _recalculate_draft(instance.room, instance.date)


@receiver(post_save, sender=UnitPrice)
def recalc_draft_on_unitprice_save(sender, instance, **kwargs):
    bills = MonthlyBill.objects.filter(
        month=instance.date, status=MonthlyBill.Status.DRAFT
    ).select_related("room")
    for bill in bills:
        calculate_monthly_bill(room=bill.room, month=bill.month)

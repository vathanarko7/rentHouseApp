from django.contrib import admin
from rooms.models import ClientProfile, MonthlyBill, Room, UnitPrice, Water, Electricity

# Register your models here.
admin.site.site_header = "Rent House Administration"
admin.site.site_title = "Rent House Admin Portal"
admin.site.index_title = "Welcome to Rent House Admin Portal"
admin.site.register(Room)
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


@admin.register(Water)
class WaterAdmin(admin.ModelAdmin):
    list_display = ("room", "date", "meter_value")
    list_filter = ("date",)
    search_fields = ("room__room_number",)


@admin.register(Electricity)
class ElectricityAdmin(admin.ModelAdmin):
    list_display = ("room", "date", "meter_value")
    list_filter = ("date",)
    search_fields = ("room__room_number",)


@admin.register(UnitPrice)
class UnitPriceAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "water_unit_price",
        "electricity_unit_price",
        "exchange_rate",
    )
    list_filter = ("date",)

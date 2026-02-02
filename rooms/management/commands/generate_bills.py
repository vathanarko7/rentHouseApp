from datetime import date
from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
from rooms.models import Room
from rooms.invoice_pdf import generate_invoice_pdf
from rooms.services import calculate_monthly_bill, generate_invoice_for_bill


class Command(BaseCommand):
    help = "Generate monthly bills for all rooms"

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            type=str,
            required=True,
            help="Billing month in format YYYY-MM (e.g. 2025-01)",
        )

    def handle(self, *args, **options):
        year, month = map(int, options["month"].split("-"))
        billing_month = date(year, month, 1)

        self.stdout.write(
            self.style.NOTICE(f"Generating bills for {billing_month.strftime('%Y-%m')}")
        )

        rooms = Room.objects.all()
        success_count = 0
        error_count = 0

        for room in rooms:
            try:
                bill = calculate_monthly_bill(room, billing_month)
                success_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✔ Room {room.room_number}: Bill generated successfully."
                    )
                )
                img_invoice = generate_invoice_for_bill(bill, lang="kh")
                self.stdout.write(f"  🖼️  Invoice (Image): {img_invoice}")
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f"✖ Room {room.room_number}: {str(e)}")
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Done! Success: {success_count}, Errors: {error_count}")
        )


# # Usage:
# python manage.py generate_bills --month 2025-01

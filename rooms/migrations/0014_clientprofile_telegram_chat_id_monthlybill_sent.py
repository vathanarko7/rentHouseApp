from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0013_monthlybill_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofile",
            name="telegram_chat_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="monthlybill",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("issued", "Issued"),
                    ("sent", "Sent"),
                    ("paid", "Paid"),
                ],
                default="draft",
                max_length=10,
            ),
        ),
    ]

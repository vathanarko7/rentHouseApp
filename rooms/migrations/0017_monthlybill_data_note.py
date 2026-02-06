from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0016_monthlybill_sent_at_paid_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlybill",
            name="data_note",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]

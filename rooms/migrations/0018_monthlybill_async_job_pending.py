from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0017_monthlybill_data_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlybill",
            name="async_job_pending",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="monthlybill",
            name="async_job_type",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]

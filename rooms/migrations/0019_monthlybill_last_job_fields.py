from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0018_monthlybill_async_job_pending"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlybill",
            name="last_job_status",
            field=models.CharField(blank=True, default="", max_length=12),
        ),
        migrations.AddField(
            model_name="monthlybill",
            name="last_job_message",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="monthlybill",
            name="last_job_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

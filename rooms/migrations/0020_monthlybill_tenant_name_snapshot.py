from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rooms", "0019_monthlybill_last_job_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlybill",
            name="tenant_name_snapshot",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
    ]

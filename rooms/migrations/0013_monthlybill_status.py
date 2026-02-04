from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0012_roomhistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlybill",
            name="status",
            field=models.CharField(
                choices=[("draft", "Draft"), ("issued", "Issued"), ("paid", "Paid")],
                default="draft",
                max_length=10,
            ),
        ),
    ]

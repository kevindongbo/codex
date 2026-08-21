from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("erp", "0033_analytics_profit_creator_workflows")]

    operations = [
        migrations.AlterField(
            model_name="creatorattribution",
            name="source",
            field=models.CharField(
                choices=[
                    ("unattributed", "未归因"),
                    ("manual", "手工录入"),
                    ("authorized", "平台正式授权"),
                ],
                max_length=16,
            ),
        ),
    ]

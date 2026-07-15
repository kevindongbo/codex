from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("erp", "0014_internal_accounts_and_sync_state")]

    operations = [
        migrations.AlterField(
            model_name="competitorproduct",
            name="name",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="competitorproduct",
            name="url",
            field=models.URLField(blank=True, max_length=1000),
        ),
    ]

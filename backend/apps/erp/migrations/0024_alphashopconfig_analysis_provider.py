from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0023_purchase_tracking_membership_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="alphashopconfig",
            name="analysis_enabled",
            field=models.BooleanField(default=False, verbose_name="启用选品大模型分析"),
        ),
        migrations.AddField(
            model_name="alphashopconfig",
            name="analysis_provider",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="alphashop_selection_configs", to="erp.aiproviderconfig", verbose_name="选品分析模型"),
        ),
    ]

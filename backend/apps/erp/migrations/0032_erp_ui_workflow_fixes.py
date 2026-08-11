import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0031_repair_0028_replenishment_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="stocktransferline",
            name="exception_closed_quantity",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=14, verbose_name="在途异常关闭数量"),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="erp_cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="erp_cancelled_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="erp_cancelled_sales_orders", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="fulfillment_override",
            field=models.CharField(default="normal", max_length=24),
        ),
        migrations.CreateModel(
            name="ProfitCalculationWorkingConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("config", models.JSONField(default=dict)),
                ("rate_mode", models.CharField(default="auto", max_length=12)),
                ("manual_cny_per_myr", models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True)),
                ("manual_usd_per_myr", models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_profit_calculation_working_configs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("organization",), name="uniq_org_profit_working_config"),
                    models.CheckConstraint(condition=models.Q(("rate_mode__in", ["auto", "manual"])), name="profit_working_rate_mode_valid"),
                ],
            },
        ),
    ]

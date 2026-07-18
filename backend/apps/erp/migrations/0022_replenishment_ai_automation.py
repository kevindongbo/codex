import uuid
from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0021_replenishment_velocity_window_15_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="replenishmentsettings",
            name="velocity_weight_3",
            field=models.DecimalField(decimal_places=3, default=Decimal("0.400"), max_digits=5, verbose_name="近 3 天权重"),
        ),
        migrations.AlterField(
            model_name="replenishmentsettings",
            name="velocity_weight_7",
            field=models.DecimalField(decimal_places=3, default=Decimal("0.300"), max_digits=5, verbose_name="近 7 天权重"),
        ),
        migrations.AlterField(
            model_name="replenishmentsettings",
            name="velocity_weight_15",
            field=models.DecimalField(decimal_places=3, default=Decimal("0.200"), max_digits=5, verbose_name="近 15 天权重"),
        ),
        migrations.AlterField(
            model_name="replenishmentsettings",
            name="velocity_weight_30",
            field=models.DecimalField(decimal_places=3, default=Decimal("0.100"), max_digits=5, verbose_name="近 30 天权重"),
        ),
        migrations.AddField(
            model_name="replenishmentsettings",
            name="ai_enabled",
            field=models.BooleanField(default=False, verbose_name="自动 AI 分析"),
        ),
        migrations.AddField(
            model_name="replenishmentsettings",
            name="ai_debounce_minutes",
            field=models.PositiveSmallIntegerField(default=5, verbose_name="AI 合并分析等待分钟"),
        ),
        migrations.AddField(
            model_name="replenishmentsettings",
            name="ai_provider",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="replenishment_settings", to="erp.aiproviderconfig", verbose_name="补货分析模型"),
        ),
        migrations.CreateModel(
            name="ReplenishmentAIJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sku_ids", models.JSONField(blank=True, default=list)),
                ("reasons", models.JSONField(blank=True, default=list)),
                ("due_at", models.DateTimeField()),
                ("status", models.CharField(choices=[("queued", "等待执行"), ("running", "执行中"), ("completed", "已完成"), ("failed", "失败")], default="queued", max_length=16)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="replenishment_ai_jobs", to="erp.warehouse")),
            ],
        ),
        migrations.AddConstraint(
            model_name="replenishmentsettings",
            constraint=models.CheckConstraint(condition=models.Q(("ai_debounce_minutes__gte", 1), ("ai_debounce_minutes__lte", 60)), name="replenishment_settings_ai_debounce_range"),
        ),
        migrations.AddConstraint(
            model_name="replenishmentaijob",
            constraint=models.UniqueConstraint(fields=("organization", "warehouse"), name="uniq_replenishment_ai_job_warehouse"),
        ),
    ]

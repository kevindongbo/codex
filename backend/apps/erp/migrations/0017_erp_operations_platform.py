from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0016_productimage_data_url"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="competitorproduct",
            name="image_url",
            field=models.URLField(blank=True, max_length=4096),
        ),
        migrations.AlterField(
            model_name="competitorproduct",
            name="url",
            field=models.URLField(blank=True, max_length=2000),
        ),
        migrations.AlterField(
            model_name="stockledger",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("receipt", "采购收货"), ("adjustment", "库存调整"), ("reserve", "锁定"),
                    ("release", "释放"), ("shipment", "出库"), ("return", "退货入库"),
                    ("transfer_out", "调拨发出"), ("transfer_in", "调拨收货"),
                    ("transfer_cancel", "调拨撤回"), ("manual_inbound", "手动入库"),
                    ("manual_outbound", "手动出库"), ("reversal", "库存流水撤回"),
                ], max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="ReplenishmentSettings",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("safety_days", models.DecimalField(decimal_places=2, default=Decimal("7"), max_digits=6, verbose_name="安全库存覆盖天数")),
                ("default_lead_time_days", models.PositiveIntegerField(default=14, verbose_name="默认采购备货周期（天）")),
                ("review_cycle_days", models.PositiveIntegerField(default=7, verbose_name="默认复核周期（天）")),
                ("target_days", models.PositiveIntegerField(default=30, verbose_name="默认目标覆盖天数")),
                ("service_level_factor", models.DecimalField(decimal_places=2, default=Decimal("1.65"), max_digits=5, verbose_name="销售波动服务系数")),
                ("initial_reference_shipment_count", models.PositiveIntegerField(default=3, verbose_name="使用初始安全库存参考的最少出库单数")),
                ("velocity_weight_7", models.DecimalField(decimal_places=3, default=Decimal("0.500"), max_digits=5, verbose_name="近 7 天权重")),
                ("velocity_weight_14", models.DecimalField(decimal_places=3, default=Decimal("0.300"), max_digits=5, verbose_name="近 14 天权重")),
                ("velocity_weight_30", models.DecimalField(decimal_places=3, default=Decimal("0.200"), max_digits=5, verbose_name="近 30 天权重")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
            ],
            options={"verbose_name": "智能补货全局参数", "verbose_name_plural": "智能补货全局参数"},
        ),
        migrations.CreateModel(
            name="StockLedgerReversal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("reason", models.CharField(blank=True, max_length=240, verbose_name="撤回原因")),
                ("reversed_at", models.DateTimeField(auto_now_add=True, verbose_name="撤回时间")),
                ("original_ledger", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="erp.stockledger", verbose_name="原库存流水")),
                ("reversal_ledger", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reverses", to="erp.stockledger", verbose_name="撤回库存流水")),
                ("reversed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="stock_ledger_reversals", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "库存流水撤回", "verbose_name_plural": "库存流水撤回"},
        ),
        migrations.CreateModel(
            name="TikTokShopOAuthState",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("state_hash", models.CharField(max_length=128, unique=True)), ("redirect_uri", models.URLField(max_length=1000)),
                ("region", models.CharField(default="MY", max_length=8)), ("expires_at", models.DateTimeField()), ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tiktok_oauth_states", to="erp.organization")),
            ],
        ),
        migrations.CreateModel(
            name="TikTokShopConnection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(blank=True, max_length=120, verbose_name="店铺备注名称")), ("region", models.CharField(default="MY", max_length=8, verbose_name="市场")),
                ("open_id", models.CharField(max_length=200, verbose_name="TikTok 授权主体")), ("shop_id", models.CharField(blank=True, max_length=200, verbose_name="店铺 ID")),
                ("access_token_encrypted", models.TextField(blank=True, verbose_name="Access Token 密文")), ("refresh_token_encrypted", models.TextField(blank=True, verbose_name="Refresh Token 密文")),
                ("access_token_expires_at", models.DateTimeField(blank=True, null=True)), ("refresh_token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("granted_scopes", models.JSONField(blank=True, default=list, verbose_name="授权范围")),
                ("status", models.CharField(choices=[("connected", "已授权"), ("expired", "已过期"), ("disconnected", "已解绑"), ("error", "授权异常")], default="connected", max_length=16)),
                ("last_error", models.CharField(blank=True, max_length=500)), ("authorized_at", models.DateTimeField(blank=True, null=True)), ("disconnected_at", models.DateTimeField(blank=True, null=True)),
                ("authorized_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
            ],
            options={"verbose_name": "TikTok Shop 授权店铺", "verbose_name_plural": "TikTok Shop 授权店铺"},
        ),
        migrations.CreateModel(
            name="TikTokShopSyncRun",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("resource", models.CharField(choices=[("products", "商品"), ("orders", "订单"), ("inventory", "库存"), ("shop", "店铺信息")], max_length=20)),
                ("status", models.CharField(choices=[("queued", "已排队"), ("running", "同步中"), ("completed", "已完成"), ("failed", "失败")], default="queued", max_length=16)),
                ("summary", models.JSONField(blank=True, default=dict)), ("error_message", models.CharField(blank=True, max_length=500)),
                ("started_at", models.DateTimeField(blank=True, null=True)), ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sync_runs", to="erp.tiktokshopconnection")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="AIProviderConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)), ("api_base_url", models.URLField(max_length=1000)), ("model_name", models.CharField(max_length=160)),
                ("api_key_encrypted", models.TextField()), ("default_parameters", models.JSONField(blank=True, default=dict)),
                ("timeout_seconds", models.PositiveIntegerField(default=45)), ("max_retries", models.PositiveSmallIntegerField(default=2)), ("enabled", models.BooleanField(default=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
            ],
            options={"verbose_name": "大模型服务配置", "verbose_name_plural": "大模型服务配置"},
        ),
        migrations.CreateModel(
            name="AIInvocationLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("feature", models.CharField(max_length=60)), ("model_name", models.CharField(blank=True, max_length=160)), ("status", models.CharField(max_length=20)),
                ("attempts", models.PositiveSmallIntegerField(default=0)), ("latency_ms", models.PositiveIntegerField(default=0)),
                ("input_tokens", models.PositiveIntegerField(blank=True, null=True)), ("output_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=80)), ("error_message", models.CharField(blank=True, max_length=500)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("provider", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invocations", to="erp.aiproviderconfig")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AIRecommendation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(choices=[("inventory_forecast", "库存预测"), ("replenishment", "补货建议"), ("product_analysis", "商品分析"), ("copywriting", "文案生成")], max_length=40)),
                ("input_data", models.JSONField(blank=True, default=dict)), ("proposal", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("proposed", "待确认"), ("confirmed", "已确认"), ("rejected", "已拒绝")], default="proposed", max_length=16)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)), ("rejection_reason", models.CharField(blank=True, max_length=240)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("provider", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="erp.aiproviderconfig")),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="confirmed_ai_recommendations", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(model_name="aiproviderconfig", constraint=models.UniqueConstraint(fields=("organization", "name"), name="uniq_ai_provider_name")),
        migrations.AddConstraint(model_name="replenishmentsettings", constraint=models.UniqueConstraint(fields=("organization",), name="uniq_replenishment_settings_org")),
        migrations.AddConstraint(model_name="replenishmentsettings", constraint=models.CheckConstraint(condition=models.Q(("safety_days__gte", 0)), name="replenishment_settings_safety_nonnegative")),
        migrations.AddConstraint(model_name="replenishmentsettings", constraint=models.CheckConstraint(condition=models.Q(("default_lead_time_days__gt", 0)), name="replenishment_settings_lead_positive")),
        migrations.AddConstraint(model_name="replenishmentsettings", constraint=models.CheckConstraint(condition=models.Q(("review_cycle_days__gt", 0)), name="replenishment_settings_review_positive")),
        migrations.AddConstraint(model_name="replenishmentsettings", constraint=models.CheckConstraint(condition=models.Q(("target_days__gt", 0)), name="replenishment_settings_target_positive")),
        migrations.AddConstraint(model_name="replenishmentsettings", constraint=models.CheckConstraint(condition=models.Q(("service_level_factor__gte", 0)), name="replenishment_settings_service_nonnegative")),
        migrations.AddConstraint(model_name="tiktokshopconnection", constraint=models.UniqueConstraint(fields=("organization", "open_id"), name="uniq_tiktok_connection_open_id")),
    ]

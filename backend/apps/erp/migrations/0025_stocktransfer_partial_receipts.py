import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0024_alphashopconfig_analysis_provider"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stocktransfer",
            name="status",
            field=models.CharField(choices=[("draft", "草稿"), ("in_transit", "调拨在途"), ("partially_received", "部分收货"), ("received", "已收货"), ("cancelled", "已取消")], default="draft", max_length=20, verbose_name="状态"),
        ),
        migrations.AddField(
            model_name="stocktransferline",
            name="received_quantity",
            field=models.DecimalField(decimal_places=3, default=Decimal("0"), max_digits=14, verbose_name="累计收货数量"),
        ),
        migrations.CreateModel(
            name="StockTransferReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.CharField(max_length=120)),
                ("quantities", models.JSONField(default=dict)),
                ("organization", models.ForeignKey(on_delete=models.deletion.PROTECT, to="erp.organization")),
                ("received_by", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("transfer", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="receipt_events", to="erp.stocktransfer")),
            ],
        ),
        migrations.AddConstraint(
            model_name="stocktransferreceipt",
            constraint=models.UniqueConstraint(fields=("organization", "idempotency_key"), name="uniq_org_transfer_receipt_idem"),
        ),
    ]

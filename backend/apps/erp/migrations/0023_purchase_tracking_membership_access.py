import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0022_replenishment_ai_automation"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="display_name",
            field=models.CharField(blank=True, max_length=80, verbose_name="成员名称"),
        ),
        migrations.AddField(
            model_name="membership",
            name="authorized_warehouses",
            field=models.ManyToManyField(blank=True, related_name="authorized_memberships", to="erp.warehouse", verbose_name="可访问仓库"),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="purchaser",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="erp_purchase_orders", to=settings.AUTH_USER_MODEL, verbose_name="采购人"),
        ),
        migrations.CreateModel(
            name="PurchaseShipment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tracking_number", models.CharField(max_length=120)),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shipments", to="erp.purchaseorder")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="PurchaseShipmentLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("quantity_shipped", models.DecimalField(decimal_places=3, max_digits=14)),
                ("purchase_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shipment_lines", to="erp.purchaseorderline")),
                ("purchase_shipment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="erp.purchaseshipment")),
            ],
        ),
        migrations.AddField(
            model_name="receipt",
            name="purchase_shipment",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="receipts", to="erp.purchaseshipment"),
        ),
        migrations.AddConstraint(
            model_name="purchaseshipment",
            constraint=models.UniqueConstraint(fields=("purchase_order", "tracking_number"), name="uniq_purchase_tracking_number"),
        ),
        migrations.AddConstraint(
            model_name="purchaseshipmentline",
            constraint=models.UniqueConstraint(fields=("purchase_shipment", "purchase_line"), name="uniq_purchase_shipment_line"),
        ),
        migrations.AddConstraint(
            model_name="purchaseshipmentline",
            constraint=models.CheckConstraint(condition=models.Q(("quantity_shipped__gt", 0)), name="purchase_shipment_qty_positive"),
        ),
    ]

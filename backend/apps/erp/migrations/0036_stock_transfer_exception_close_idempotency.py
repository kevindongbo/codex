import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0035_sku_replenishment_profile_v3"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="stocktransfercompletionevent",
            name="reason",
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.CreateModel(
            name="StockTransferExceptionCloseEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.CharField(max_length=120)),
                ("request_hash", models.CharField(max_length=64)),
                ("reason", models.CharField(blank=True, max_length=240)),
                ("quantities", models.JSONField(default=dict)),
                ("result", models.JSONField(default=dict)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="stock_transfer_exception_close_events", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("transfer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="exception_close_events", to="erp.stocktransfer")),
            ],
        ),
        migrations.AddConstraint(
            model_name="stocktransferexceptioncloseevent",
            constraint=models.UniqueConstraint(fields=("organization", "idempotency_key"), name="uniq_org_transfer_exception_close_idem"),
        ),
    ]

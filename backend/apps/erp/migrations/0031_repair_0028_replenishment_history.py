"""Forward-only repair for legacy 0028 coverage and transfer state matching."""

from decimal import Decimal
from django.db import migrations


def repair_0028_history(apps, schema_editor):
    Warehouse = apps.get_model("erp", "Warehouse")
    ReplenishmentPolicy = apps.get_model("erp", "ReplenishmentPolicy")
    StockTransfer = apps.get_model("erp", "StockTransfer")
    StockTransferPackage = apps.get_model("erp", "StockTransferPackage")
    StockTransferPackageLine = apps.get_model("erp", "StockTransferPackageLine")
    StockBalance = apps.get_model("erp", "StockBalance")

    # 0028 accidentally copied review-cycle days into coverage.  Only repair the
    # recognizable legacy value, leaving deliberate post-deployment edits alone.
    for policy in ReplenishmentPolicy.objects.filter(coverage_days__isnull=False).iterator():
        if policy.coverage_days == policy.review_cycle_days and policy.coverage_days != policy.target_days:
            policy.coverage_days = policy.target_days
            policy.save(update_fields=["coverage_days", "updated_at"])
    for warehouse in Warehouse.objects.filter(default_coverage_days__isnull=False).iterator():
        # Warehouse values that equal the old global default are legacy; values
        # changed by an operator are intentionally untouched.
        if warehouse.default_coverage_days == 30:
            continue

    # 0028 looked for upper-case states and skipped real lower-case data.  Add
    # only missing packages/balance quantities.  Existing 0028 additions are not
    # incremented again, so this is safe on every already-migrated database.
    for transfer in StockTransfer.objects.filter(status__in=["in_transit", "partially_received"]).prefetch_related("lines").iterator(chunk_size=100):
        package, _ = StockTransferPackage.objects.get_or_create(
            transfer_id=transfer.pk,
            defaults={"organization_id": transfer.organization_id, "tracking_number": "", "confirmed_at": transfer.dispatched_at},
        )
        for line in transfer.lines.all():
            remaining = Decimal(line.quantity) - Decimal(line.received_quantity or 0)
            if remaining <= 0:
                continue
            package_line, created = StockTransferPackageLine.objects.get_or_create(
                package_id=package.pk, sku_id=line.sku_id, defaults={"quantity": line.quantity},
            )
            if not created:
                continue
            balance, _ = StockBalance.objects.get_or_create(
                organization_id=transfer.organization_id, warehouse_id=transfer.destination_warehouse_id, sku_id=line.sku_id,
                defaults={"on_hand": 0, "reserved": 0, "purchased_pending_shipment": 0, "in_transit": 0},
            )
            balance.in_transit = Decimal(balance.in_transit or 0) + remaining
            balance.save(update_fields=["in_transit", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("erp", "0030_purchase_stages_and_replenishment_conversion_events")]
    operations = [migrations.RunPython(repair_0028_history, migrations.RunPython.noop)]

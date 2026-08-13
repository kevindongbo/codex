from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.erp.models import (
    AuditLog,
    Organization,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    SKU,
    StockBalance,
    Supplier,
    Warehouse,
)


class ReconcileInboundBalancesCommandTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="东铂", slug="inbound-reconcile")
        self.warehouse = Warehouse.objects.create(
            organization=self.organization, code="MY", name="马来仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="SUP", name="供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="豹纹托特-棕色", status=Product.Status.ACTIVE
        )
        self.sku = SKU.objects.create(
            organization=self.organization, product=product, code="AI-BAG-BROWN-05"
        )
        self.balance = StockBalance.objects.create(
            organization=self.organization,
            warehouse=self.warehouse,
            sku=self.sku,
            purchased_pending_shipment="0",
        )
        purchase = PurchaseOrder.objects.create(
            organization=self.organization,
            number="PO-20260805-2715",
            supplier=supplier,
            warehouse=self.warehouse,
            status=PurchaseOrder.Status.SUBMITTED,
        )
        PurchaseOrderLine.objects.create(
            purchase_order=purchase, sku=self.sku, quantity_ordered="150", unit_cost="10"
        )

    def test_dry_run_reports_difference_without_writing(self):
        output = StringIO()
        call_command(
            "reconcile_inbound_balances",
            organization=self.organization.slug,
            stdout=output,
        )
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.purchased_pending_shipment, Decimal("0"))
        self.assertIn("calculated_pending=150.000", output.getvalue())
        self.assertIn("DRY-RUN differences=1", output.getvalue())
        self.assertFalse(AuditLog.objects.exists())

    def test_apply_is_audited_and_idempotent(self):
        first = StringIO()
        call_command(
            "reconcile_inbound_balances",
            organization=self.organization.slug,
            apply=True,
            stdout=first,
        )
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.purchased_pending_shipment, Decimal("150"))
        self.assertEqual(AuditLog.objects.filter(action="inventory.inbound_balance_reconcile").count(), 1)

        second = StringIO()
        call_command(
            "reconcile_inbound_balances",
            organization=self.organization.slug,
            apply=True,
            stdout=second,
        )
        self.assertIn("APPLIED differences=1", first.getvalue())
        self.assertIn("DRY-RUN differences=0", second.getvalue())
        self.assertEqual(AuditLog.objects.filter(action="inventory.inbound_balance_reconcile").count(), 1)

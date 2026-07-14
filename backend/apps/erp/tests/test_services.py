from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.erp.models import (
    AuditLog, Membership, Organization, Product, PurchaseOrder, PurchaseOrderLine, Receipt,
    ReturnLine, ReturnOrder, ReturnReceipt, SalesOrder, SalesOrderLine, Shipment,
    SKU, StockBalance, StockLedger, StockReservation, Supplier, Warehouse,
)
from apps.erp.services import (
    adjust_inventory, allocate_order, cancel_order, cancel_purchase, confirm_order,
    receive_purchase, receive_return, ship_order, start_picking, submit_purchase,
    verify_order,
)


class InventoryServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", password="test-pass-123")
        self.organization = Organization.objects.create(name="东铂跨境", slug="dongbo")
        Membership.objects.create(
            organization=self.organization, user=self.user, role=Membership.Role.ADMIN
        )
        self.warehouse = Warehouse.objects.create(
            organization=self.organization, code="CN-01", name="深圳仓"
        )
        self.product = Product.objects.create(
            organization=self.organization, name="测试商品", status=Product.Status.ACTIVE
        )
        self.sku = SKU.objects.create(
            organization=self.organization, product=self.product, code="SKU-001", cost="10"
        )

    def test_adjustment_is_atomic_idempotent_and_cannot_go_negative(self):
        first = adjust_inventory(
            organization=self.organization, warehouse=self.warehouse, sku=self.sku,
            delta="8", reason="盘盈", idempotency_key="adjust-001", actor=self.user,
        )
        second = adjust_inventory(
            organization=self.organization, warehouse=self.warehouse, sku=self.sku,
            delta="8", reason="重复请求", idempotency_key="adjust-001", actor=self.user,
        )
        self.assertEqual(first.pk, second.pk)
        balance = StockBalance.objects.get(warehouse=self.warehouse, sku=self.sku)
        self.assertEqual(balance.on_hand, Decimal("8"))
        self.assertEqual(StockLedger.objects.count(), 1)
        with self.assertRaises(ValidationError):
            adjust_inventory(
                organization=self.organization, warehouse=self.warehouse, sku=self.sku,
                delta="7", reason="同键不同数量", idempotency_key="adjust-001", actor=self.user,
            )
        with self.assertRaises(ValidationError):
            adjust_inventory(
                organization=self.organization, warehouse=self.warehouse, sku=self.sku,
                delta="-9", reason="错误盘亏", idempotency_key="adjust-002", actor=self.user,
            )
        balance.refresh_from_db()
        self.assertEqual(balance.on_hand, Decimal("8"))

    def test_receipt_updates_purchase_and_stock_only_once(self):
        supplier = Supplier.objects.create(
            organization=self.organization, code="SUP-01", name="供应商"
        )
        purchase = PurchaseOrder.objects.create(
            organization=self.organization, number="PO-001", supplier=supplier,
            warehouse=self.warehouse, status=PurchaseOrder.Status.SUBMITTED,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=purchase, sku=self.sku, quantity_ordered="5", unit_cost="12.5"
        )
        params = {
            "organization": self.organization,
            "purchase_order": purchase,
            "number": "RCV-001",
            "lines": [{"purchase_line": line, "quantity": "5", "unit_cost": "12.5"}],
            "idempotency_key": "receive-001",
            "actor": self.user,
        }
        first = receive_purchase(**params)
        second = receive_purchase(**params)
        self.assertEqual(first.pk, second.pk)
        purchase.refresh_from_db()
        line.refresh_from_db()
        self.sku.refresh_from_db()
        balance = StockBalance.objects.get(warehouse=self.warehouse, sku=self.sku)
        self.assertEqual(purchase.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(line.quantity_received, Decimal("5"))
        self.assertEqual(balance.on_hand, Decimal("5"))
        self.assertEqual(self.sku.cost, Decimal("12.5"))
        self.assertEqual(StockLedger.objects.filter(event_type=StockLedger.Type.RECEIPT).count(), 1)
        receipt_audit = AuditLog.objects.get(action="purchase.receive", object_id=str(first.pk))
        self.assertEqual(receipt_audit.after["cost_changes"][0]["before"], "10.0000")
        self.assertEqual(receipt_audit.after["cost_changes"][0]["after"], "12.5")
        with self.assertRaises(ValidationError):
            receive_purchase(
                **{**params, "lines": [{"purchase_line": line, "quantity": "4"}]}
            )

    def test_order_allocate_and_ship_are_idempotent(self):
        adjust_inventory(
            organization=self.organization, warehouse=self.warehouse, sku=self.sku,
            delta="10", reason="期初库存", idempotency_key="opening", actor=self.user,
        )
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-001", warehouse=self.warehouse,
            status=SalesOrder.Status.READY,
        )
        SalesOrderLine.objects.create(order=order, sku=self.sku, quantity="4", unit_price="20")
        first_allocation = allocate_order(order=order, idempotency_key="alloc-001", actor=self.user)
        replayed_allocation = allocate_order(order=order, idempotency_key="alloc-001", actor=self.user)
        self.assertEqual(first_allocation.pk, replayed_allocation.pk)
        with self.assertRaises(ValidationError):
            allocate_order(order=order, idempotency_key="alloc-002", actor=self.user)
        balance = StockBalance.objects.get(warehouse=self.warehouse, sku=self.sku)
        self.assertEqual(balance.on_hand, Decimal("10"))
        self.assertEqual(balance.reserved, Decimal("4"))
        self.assertEqual(StockReservation.objects.count(), 1)

        self.assertEqual(start_picking(order=order, actor=self.user).status, SalesOrder.Status.PICKING)
        self.assertEqual(start_picking(order=order, actor=self.user).status, SalesOrder.Status.PICKING)
        self.assertEqual(verify_order(order=order, actor=self.user).status, SalesOrder.Status.VERIFIED)
        self.assertEqual(verify_order(order=order, actor=self.user).status, SalesOrder.Status.VERIFIED)

        first = ship_order(
            order=order, number="SHP-001", tracking_number="SF123456",
            idempotency_key="ship-001", actor=self.user,
        )
        second = ship_order(
            order=order, number="SHP-001", tracking_number="SF123456",
            idempotency_key="ship-001", actor=self.user,
        )
        self.assertEqual(first.pk, second.pk)
        balance.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(balance.on_hand, Decimal("6"))
        self.assertEqual(balance.reserved, Decimal("0"))
        self.assertEqual(order.status, SalesOrder.Status.SHIPPED)
        self.assertEqual(Shipment.objects.count(), 1)
        self.assertEqual(first.tracking_number, "SF123456")
        with self.assertRaises(ValidationError):
            ship_order(
                order=order, number="SHP-001", tracking_number="DIFFERENT",
                idempotency_key="ship-001", actor=self.user,
            )
        ledger = StockLedger.objects.filter(
            organization=self.organization, warehouse=self.warehouse, sku=self.sku
        )
        self.assertEqual(
            sum((entry.on_hand_delta for entry in ledger), Decimal("0")), balance.on_hand
        )
        self.assertEqual(
            sum((entry.reserved_delta for entry in ledger), Decimal("0")), balance.reserved
        )
        with self.assertRaises(ValidationError):
            ship_order(order=order, number="SHP-002", idempotency_key="ship-002", actor=self.user)
        self.assertEqual(Shipment.objects.count(), 1)
        other_order = SalesOrder.objects.create(
            organization=self.organization, number="SO-OTHER", warehouse=self.warehouse
        )
        with self.assertRaises(ValidationError):
            ship_order(
                order=other_order, number="SHP-OTHER", idempotency_key="ship-001", actor=self.user
            )

    def test_purchase_state_transitions_and_partial_receipt(self):
        supplier = Supplier.objects.create(
            organization=self.organization, code="SUP-02", name="Supplier 2"
        )
        purchase = PurchaseOrder.objects.create(
            organization=self.organization, number="PO-002", supplier=supplier,
            warehouse=self.warehouse,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=purchase, sku=self.sku, quantity_ordered="5", unit_cost="11"
        )
        with self.assertRaises(ValidationError):
            receive_purchase(
                organization=self.organization, purchase_order=purchase, number="RCV-DRAFT",
                lines=[{"purchase_line": line, "quantity": "1"}],
                idempotency_key="draft-receipt", actor=self.user,
            )
        self.assertFalse(Receipt.objects.exists())

        submit_purchase(purchase_order=purchase, actor=self.user)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseOrder.Status.SUBMITTED)
        self.assertEqual(
            submit_purchase(purchase_order=purchase, actor=self.user).status,
            PurchaseOrder.Status.SUBMITTED,
        )

        first = receive_purchase(
            organization=self.organization, purchase_order=purchase, number="RCV-002-A",
            lines=[{"purchase_line": line, "quantity": "2"}],
            idempotency_key="partial-a", actor=self.user,
        )
        replay = receive_purchase(
            organization=self.organization, purchase_order=purchase, number="IGNORED",
            lines=[{"purchase_line": line, "quantity": "2"}],
            idempotency_key="partial-a", actor=self.user,
        )
        self.assertEqual(first.pk, replay.pk)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseOrder.Status.PARTIAL)
        self.assertEqual(Receipt.objects.count(), 1)

        receive_purchase(
            organization=self.organization, purchase_order=purchase, number="RCV-002-B",
            lines=[{"purchase_line": line, "quantity": "3"}],
            idempotency_key="partial-b", actor=self.user,
        )
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, PurchaseOrder.Status.RECEIVED)
        with self.assertRaises(ValidationError):
            cancel_purchase(purchase_order=purchase, actor=self.user)
        cancellable = PurchaseOrder.objects.create(
            organization=self.organization, number="PO-CANCEL", supplier=supplier,
            warehouse=self.warehouse,
        )
        cancel_purchase(purchase_order=cancellable, actor=self.user)
        cancellable.refresh_from_db()
        self.assertEqual(cancellable.status, PurchaseOrder.Status.CANCELLED)

    def test_order_confirm_and_cancel_releases_reservations(self):
        adjust_inventory(
            organization=self.organization, warehouse=self.warehouse, sku=self.sku,
            delta="6", reason="opening", idempotency_key="cancel-opening", actor=self.user,
        )
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-CANCEL", warehouse=self.warehouse
        )
        SalesOrderLine.objects.create(order=order, sku=self.sku, quantity="4")
        confirm_order(order=order, actor=self.user)
        allocate_order(order=order, idempotency_key="cancel-allocation", actor=self.user)
        cancel_order(order=order, actor=self.user)

        order.refresh_from_db()
        balance = StockBalance.objects.get(warehouse=self.warehouse, sku=self.sku)
        reservation = StockReservation.objects.get(order_line__order=order)
        self.assertEqual(order.status, SalesOrder.Status.CANCELLED)
        self.assertEqual(balance.on_hand, Decimal("6"))
        self.assertEqual(balance.reserved, Decimal("0"))
        self.assertEqual(reservation.status, StockReservation.Status.RELEASED)
        self.assertEqual(
            StockLedger.objects.filter(event_type=StockLedger.Type.RELEASE).count(), 1
        )
        cancel_order(order=order, actor=self.user)
        self.assertEqual(
            StockLedger.objects.filter(event_type=StockLedger.Type.RELEASE).count(), 1
        )

    def test_shipment_rejects_allocated_order_without_reservations(self):
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-EMPTY", warehouse=self.warehouse,
            status=SalesOrder.Status.VERIFIED,
        )
        SalesOrderLine.objects.create(order=order, sku=self.sku, quantity="1")
        with self.assertRaises(ValidationError):
            ship_order(order=order, number="SHP-EMPTY", idempotency_key="empty", actor=self.user)
        self.assertFalse(Shipment.objects.filter(order=order).exists())

    def test_return_receipts_are_partial_and_idempotent(self):
        shipped_order = SalesOrder.objects.create(
            organization=self.organization, number="SO-RETURN", warehouse=self.warehouse,
            status=SalesOrder.Status.SHIPPED,
        )
        SalesOrderLine.objects.create(
            order=shipped_order, sku=self.sku, quantity="6", quantity_shipped="6"
        )
        return_order = ReturnOrder.objects.create(
            organization=self.organization, number="RET-001", warehouse=self.warehouse,
            original_order=shipped_order,
        )
        line = ReturnLine.objects.create(
            return_order=return_order, sku=self.sku, quantity_expected="5",
            condition=ReturnLine.Condition.RESTOCK,
        )
        first_quantities = [{"return_line": line, "quantity": "2"}]
        receive_return(
            return_order=return_order, quantities=first_quantities,
            idempotency_key="return-part-1", actor=self.user,
        )
        with self.assertRaises(ValidationError):
            receive_return(
                return_order=return_order,
                quantities=[{"return_line": line, "quantity": "1"}],
                idempotency_key="return-part-1", actor=self.user,
            )
        receive_return(
            return_order=return_order, quantities=first_quantities,
            idempotency_key="return-part-1", actor=self.user,
        )
        return_order.refresh_from_db()
        line.refresh_from_db()
        balance = StockBalance.objects.get(warehouse=self.warehouse, sku=self.sku)
        self.assertEqual(return_order.status, ReturnOrder.Status.PARTIAL)
        self.assertEqual(line.quantity_received, Decimal("2"))
        self.assertEqual(balance.on_hand, Decimal("2"))
        self.assertEqual(ReturnReceipt.objects.count(), 1)

        receive_return(
            return_order=return_order,
            quantities=[{"return_line": line, "quantity": "3"}],
            idempotency_key="return-part-2", actor=self.user,
        )
        return_order.refresh_from_db()
        balance.refresh_from_db()
        self.assertEqual(return_order.status, ReturnOrder.Status.RECEIVED)
        self.assertIsNotNone(return_order.received_at)
        self.assertEqual(balance.on_hand, Decimal("5"))
        self.assertEqual(ReturnReceipt.objects.count(), 2)
        with self.assertRaises(ValidationError):
            receive_return(
                return_order=return_order,
                quantities=[{"return_line": line, "quantity": "1"}],
                idempotency_key="return-after-complete", actor=self.user,
            )
        self.assertEqual(ReturnReceipt.objects.count(), 2)

        other_return = ReturnOrder.objects.create(
            organization=self.organization, number="RET-002", warehouse=self.warehouse,
            original_order=shipped_order,
        )
        other_line = ReturnLine.objects.create(
            return_order=other_return, sku=self.sku, quantity_expected="1"
        )
        with self.assertRaises(ValidationError):
            receive_return(
                return_order=other_return,
                quantities=[{"return_line": other_line, "quantity": "1"}],
                idempotency_key="return-part-1", actor=self.user,
            )
        self.assertEqual(ReturnReceipt.objects.count(), 2)

    def test_services_reject_cross_organization_inventory_references(self):
        other = Organization.objects.create(name="Other", slug="other-services")
        other_warehouse = Warehouse.objects.create(
            organization=other, code="OTHER", name="Other warehouse"
        )
        with self.assertRaises(ValidationError):
            adjust_inventory(
                organization=self.organization, warehouse=other_warehouse, sku=self.sku,
                delta="1", reason="invalid", idempotency_key="cross-org", actor=self.user,
            )
        self.assertFalse(StockLedger.objects.filter(idempotency_key="adjust:cross-org").exists())

    def test_stock_ledger_is_immutable(self):
        ledger = adjust_inventory(
            organization=self.organization, warehouse=self.warehouse, sku=self.sku,
            delta="1", reason="测试", idempotency_key="immutable", actor=self.user,
        )
        ledger.reason = "篡改"
        with self.assertRaises(ValidationError):
            ledger.save()
        with self.assertRaises(ValidationError):
            ledger.delete()
        with self.assertRaises(ValidationError):
            StockLedger.objects.filter(pk=ledger.pk).update(reason="批量篡改")
        with self.assertRaises(ValidationError):
            StockLedger.objects.filter(pk=ledger.pk).delete()

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.erp.models import (
    Organization,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    ReceiptLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentLine,
    SKU,
    StockBalance,
    Supplier,
    Warehouse,
)
from apps.erp.replenishment import (
    DemandVelocity,
    InventoryPosition,
    LeadTimeEstimate,
    ReplenishmentPolicy,
    RobustLeadSummary,
    calculate_replenishment,
    estimate_demand_velocity,
    estimate_lead_time,
    get_inventory_position,
    summarize_lead_times,
)


class ReplenishmentTests(TestCase):
    def setUp(self):
        self.as_of = timezone.now().replace(microsecond=0)
        self.organization = Organization.objects.create(
            name="Forecast Org", slug="forecast"
        )
        self.warehouse = Warehouse.objects.create(
            organization=self.organization,
            code="MY-01",
            name="Malaysia",
            country="MY",
        )
        self.other_warehouse = Warehouse.objects.create(
            organization=self.organization,
            code="SCHOOL",
            name="School",
        )
        self.product = Product.objects.create(
            organization=self.organization,
            name="Test product",
            status=Product.Status.ACTIVE,
        )
        self.sku = SKU.objects.create(
            organization=self.organization,
            product=self.product,
            code="SKU-FORECAST",
            cost="10",
        )
        self.supplier = Supplier.objects.create(
            organization=self.organization,
            code="SUP-01",
            name="Supplier",
        )

    def create_full_receipt_history(
        self, *, days: int, sequence: int, supplier=None, route: str = ""
    ):
        purchase = PurchaseOrder.objects.create(
            organization=self.organization,
            number=f"PO-HIST-{sequence}",
            supplier=supplier or self.supplier,
            warehouse=self.warehouse,
            status=PurchaseOrder.Status.RECEIVED,
            ordered_at=self.as_of - timedelta(days=days),
            notes=route,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=purchase,
            sku=self.sku,
            quantity_ordered="10",
            quantity_received="10",
            unit_cost="10",
        )
        receipt = Receipt.objects.create(
            organization=self.organization,
            number=f"RCV-HIST-{sequence}",
            purchase_order=purchase,
            warehouse=self.warehouse,
            status=Receipt.Status.COMPLETED,
            idempotency_key=f"receipt-history-{sequence}",
            received_at=self.as_of,
        )
        ReceiptLine.objects.create(
            receipt=receipt,
            purchase_line=line,
            sku=self.sku,
            quantity="10",
            unit_cost="10",
        )

    def create_shipment(
        self, *, warehouse, days_ago: int, quantity: str, sequence: int
    ):
        order = SalesOrder.objects.create(
            organization=self.organization,
            number=f"SO-{sequence}",
            warehouse=warehouse,
            status=SalesOrder.Status.SHIPPED,
        )
        order_line = SalesOrderLine.objects.create(
            order=order,
            sku=self.sku,
            quantity=quantity,
            quantity_shipped=quantity,
        )
        shipment = Shipment.objects.create(
            organization=self.organization,
            number=f"SHP-{sequence}",
            order=order,
            warehouse=warehouse,
            status=Shipment.Status.COMPLETED,
            idempotency_key=f"shipment-{sequence}",
            shipped_at=self.as_of - timedelta(days=days_ago),
        )
        ShipmentLine.objects.create(
            shipment=shipment,
            order_line=order_line,
            sku=self.sku,
            quantity=quantity,
        )

    def test_lead_time_uses_robust_full_receipt_p80(self):
        for sequence, days in enumerate((8, 10, 12, 200), start=1):
            self.create_full_receipt_history(days=days, sequence=sequence)

        estimate = estimate_lead_time(
            organization=self.organization,
            sku=self.sku,
            warehouse=self.warehouse,
            supplier=self.supplier,
            manual_lead_days=30,
            as_of=self.as_of,
        )

        self.assertEqual(estimate.full_receipt.sample_count, 3)
        self.assertEqual(estimate.full_receipt.excluded_count, 1)
        self.assertEqual(estimate.full_receipt.median_days, Decimal("10.0000"))
        self.assertEqual(estimate.full_receipt.p80_days, Decimal("12.0000"))
        self.assertEqual(estimate.selected_days, 12)
        self.assertEqual(estimate.source, "historical_full_receipt_p80")
        self.assertEqual(estimate.confidence, "medium")

    def test_lead_time_filters_supplier_and_explicit_route(self):
        other_supplier = Supplier.objects.create(
            organization=self.organization,
            code="SUP-02",
            name="Other supplier",
        )
        self.create_full_receipt_history(days=20, sequence=20, route="sea")
        self.create_full_receipt_history(days=5, sequence=21, route="air")
        self.create_full_receipt_history(
            days=2,
            sequence=22,
            supplier=other_supplier,
            route="sea",
        )

        estimate = estimate_lead_time(
            organization=self.organization,
            sku=self.sku,
            warehouse=self.warehouse,
            supplier=self.supplier,
            route="sea",
            route_resolver=lambda purchase: purchase.notes,
            as_of=self.as_of,
        )

        self.assertEqual(estimate.full_receipt.sample_count, 1)
        self.assertEqual(estimate.selected_days, 20)

    def test_lead_time_distinguishes_first_and_full_receipt(self):
        purchase = PurchaseOrder.objects.create(
            organization=self.organization,
            number="PO-PARTIAL",
            supplier=self.supplier,
            warehouse=self.warehouse,
            status=PurchaseOrder.Status.RECEIVED,
            ordered_at=self.as_of - timedelta(days=20),
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=purchase,
            sku=self.sku,
            quantity_ordered="10",
            quantity_received="10",
            unit_cost="10",
        )
        for sequence, (days_ago, quantity) in enumerate(
            ((15, "2"), (10, "8")), start=1
        ):
            receipt = Receipt.objects.create(
                organization=self.organization,
                number=f"RCV-PARTIAL-{sequence}",
                purchase_order=purchase,
                warehouse=self.warehouse,
                status=Receipt.Status.COMPLETED,
                idempotency_key=f"receipt-partial-{sequence}",
                received_at=self.as_of - timedelta(days=days_ago),
            )
            ReceiptLine.objects.create(
                receipt=receipt,
                purchase_line=line,
                sku=self.sku,
                quantity=quantity,
                unit_cost="10",
            )

        estimate = estimate_lead_time(
            organization=self.organization,
            sku=self.sku,
            warehouse=self.warehouse,
            as_of=self.as_of,
        )

        self.assertEqual(estimate.first_receipt.median_days, Decimal("5.0000"))
        self.assertEqual(estimate.full_receipt.median_days, Decimal("10.0000"))
        self.assertEqual(estimate.selected_days, 10)

    def test_no_lead_history_uses_explicit_manual_fallback(self):
        estimate = estimate_lead_time(
            organization=self.organization,
            sku=self.sku,
            warehouse=self.warehouse,
            manual_lead_days=21,
            as_of=self.as_of,
        )

        self.assertEqual(estimate.selected_days, 21)
        self.assertEqual(estimate.source, "manual_fallback")
        self.assertEqual(estimate.confidence, "low")
        self.assertTrue(any("没有可用历史" in reason for reason in estimate.reasons))

    def test_robust_summary_rejects_invalid_and_extreme_durations(self):
        summary = summarize_lead_times((-1, 8, 10, 12, 200, 500), max_valid_days=365)

        self.assertEqual(summary.sample_count, 3)
        self.assertEqual(summary.excluded_count, 3)
        self.assertEqual(summary.median_days, Decimal("10.0000"))
        self.assertEqual(summary.p80_days, Decimal("12.0000"))

    def test_weighted_velocity_uses_actual_shipments_and_isolates_warehouse(self):
        self.create_shipment(
            warehouse=self.warehouse, days_ago=2, quantity="14", sequence=1
        )
        self.create_shipment(
            warehouse=self.warehouse, days_ago=10, quantity="14", sequence=2
        )
        self.create_shipment(
            warehouse=self.warehouse, days_ago=20, quantity="30", sequence=3
        )
        self.create_shipment(
            warehouse=self.other_warehouse,
            days_ago=2,
            quantity="700",
            sequence=4,
        )

        demand = estimate_demand_velocity(
            organization=self.organization,
            sku=self.sku,
            warehouse=self.warehouse,
            as_of=self.as_of,
        )

        self.assertEqual(demand.quantity_7, Decimal("14.000"))
        self.assertEqual(demand.quantity_14, Decimal("28.000"))
        self.assertEqual(demand.quantity_30, Decimal("58.000"))
        self.assertEqual(demand.daily_7, Decimal("2.0000"))
        self.assertEqual(demand.daily_14, Decimal("2.0000"))
        self.assertEqual(demand.daily_30, Decimal("1.9333"))
        self.assertEqual(demand.daily_velocity, Decimal("1.9867"))
        self.assertEqual(demand.shipment_count, 3)

    def test_inventory_position_counts_only_target_warehouse_open_inbound(self):
        StockBalance.objects.create(
            organization=self.organization,
            warehouse=self.warehouse,
            sku=self.sku,
            on_hand="10",
            reserved="2",
        )
        StockBalance.objects.create(
            organization=self.organization,
            warehouse=self.other_warehouse,
            sku=self.sku,
            on_hand="100",
        )
        for sequence, (warehouse, status, ordered, received) in enumerate(
            (
                (self.warehouse, PurchaseOrder.Status.SUBMITTED, "20", "5"),
                (self.other_warehouse, PurchaseOrder.Status.SUBMITTED, "50", "0"),
                (self.warehouse, PurchaseOrder.Status.DRAFT, "90", "0"),
            ),
            start=1,
        ):
            purchase = PurchaseOrder.objects.create(
                organization=self.organization,
                number=f"PO-INBOUND-{sequence}",
                supplier=self.supplier,
                warehouse=warehouse,
                status=status,
            )
            PurchaseOrderLine.objects.create(
                purchase_order=purchase,
                sku=self.sku,
                quantity_ordered=ordered,
                quantity_received=received,
                unit_cost="10",
            )

        inventory = get_inventory_position(
            organization=self.organization,
            sku=self.sku,
            warehouse=self.warehouse,
        )

        self.assertEqual(inventory.on_hand, Decimal("10.000"))
        self.assertEqual(inventory.reserved, Decimal("2.000"))
        self.assertEqual(inventory.available, Decimal("8.000"))
        self.assertEqual(inventory.in_transit, Decimal("15.000"))
        self.assertEqual(inventory.inventory_position, Decimal("23.000"))
        self.assertEqual(inventory.open_purchase_count, 1)

    def test_calculation_rounds_up_to_moq_and_pack_size(self):
        forecast = calculate_replenishment(
            lead_time=self.lead(days=10, confidence="high"),
            demand=self.demand(daily="2", confidence="high"),
            inventory=self.inventory(available="20", in_transit="0"),
            policy=ReplenishmentPolicy(
                safety_days=Decimal("3"),
                review_cycle_days=Decimal("5"),
                target_days=Decimal("30"),
                moq=Decimal("70"),
                pack_size=Decimal("24"),
            ),
            as_of=self.as_of,
        )

        self.assertEqual(forecast.safety_stock_units, Decimal("6.000"))
        self.assertEqual(forecast.reorder_point, Decimal("36.000"))
        self.assertEqual(forecast.target_inventory_position, Decimal("86.000"))
        self.assertEqual(forecast.raw_order_quantity, Decimal("66.000"))
        self.assertEqual(forecast.suggested_order_quantity, Decimal("72.000"))
        self.assertTrue(forecast.needs_reorder)
        self.assertEqual(forecast.alert_level, "red")

    def test_confirmed_in_transit_can_prevent_duplicate_replenishment(self):
        forecast = calculate_replenishment(
            lead_time=self.lead(days=10),
            demand=self.demand(daily="2"),
            inventory=self.inventory(available="10", in_transit="30"),
            policy=ReplenishmentPolicy(
                safety_days=Decimal("3"),
                review_cycle_days=Decimal("5"),
                target_days=Decimal("30"),
            ),
            as_of=self.as_of,
        )

        self.assertEqual(forecast.inventory.inventory_position, Decimal("40"))
        self.assertFalse(forecast.needs_reorder)
        self.assertEqual(forecast.suggested_order_quantity, Decimal("0"))
        self.assertEqual(forecast.alert_level, "yellow")

    def test_zero_sales_does_not_invent_demand_or_stockout_date(self):
        forecast = calculate_replenishment(
            lead_time=self.lead(days=14),
            demand=self.demand(daily="0", confidence="low"),
            inventory=self.inventory(available="0", in_transit="0"),
            policy=ReplenishmentPolicy(),
            as_of=self.as_of,
        )

        self.assertFalse(forecast.needs_reorder)
        self.assertEqual(forecast.suggested_order_quantity, Decimal("0"))
        self.assertIsNone(forecast.projected_days_of_cover)
        self.assertIsNone(forecast.projected_stockout_date)
        self.assertIsNone(forecast.latest_order_date)
        self.assertEqual(forecast.confidence, "low")

    @staticmethod
    def lead(*, days: int, confidence: str = "medium") -> LeadTimeEstimate:
        empty = RobustLeadSummary(0, 0, None, None)
        return LeadTimeEstimate(
            selected_days=days,
            source="test",
            confidence=confidence,
            first_receipt=empty,
            full_receipt=empty,
            approximate_order_dates=0,
            reasons=(),
        )

    @staticmethod
    def demand(*, daily: str, confidence: str = "medium") -> DemandVelocity:
        velocity = Decimal(daily)
        return DemandVelocity(
            daily_velocity=velocity,
            daily_7=velocity,
            daily_14=velocity,
            daily_30=velocity,
            quantity_7=velocity * 7,
            quantity_14=velocity * 14,
            quantity_30=velocity * 30,
            shipment_count=0,
            active_days=0,
            confidence=confidence,
            reasons=(),
        )

    @staticmethod
    def inventory(*, available: str, in_transit: str) -> InventoryPosition:
        available_quantity = Decimal(available)
        inbound_quantity = Decimal(in_transit)
        return InventoryPosition(
            on_hand=available_quantity,
            reserved=Decimal("0"),
            available=available_quantity,
            in_transit=inbound_quantity,
            inventory_position=available_quantity + inbound_quantity,
            open_purchase_count=1 if inbound_quantity else 0,
            next_expected_at=None,
        )

"""Authoritative inbound inventory calculation for one warehouse/SKU.

The stage columns on ``StockBalance`` are maintained transactionally for fast
writes, but historical rows can predate those columns.  Read paths therefore
derive the business truth from the purchase/transfer documents and expose the
stored values separately for reconciliation.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q, Sum

from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseShipmentLine,
    Receipt,
    ReceiptLine,
    StockBalance,
    StockTransfer,
    StockTransferLine,
)


ZERO = Decimal("0")


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


@dataclass(frozen=True)
class InboundSnapshot:
    purchased_pending_shipment: Decimal
    in_transit: Decimal
    inbound_total: Decimal
    pending_sources: tuple[dict, ...]
    transit_sources: tuple[dict, ...]
    stored_pending_shipment: Decimal
    stored_in_transit: Decimal

    @property
    def has_balance_difference(self):
        return (
            self.purchased_pending_shipment != self.stored_pending_shipment
            or self.in_transit != self.stored_in_transit
        )


def calculate_inbound_snapshot(*, organization, warehouse, sku, balance=None):
    """Return source rows and totals using one shared business definition."""

    if balance is None:
        balance = StockBalance.objects.filter(
            organization=organization, warehouse=warehouse, sku=sku
        ).first()
    stored_pending = _decimal(getattr(balance, "purchased_pending_shipment", ZERO))
    stored_transit = _decimal(getattr(balance, "in_transit", ZERO))

    pending_sources = []
    purchase_lines = PurchaseOrderLine.objects.filter(
        purchase_order__organization=organization,
        purchase_order__warehouse=warehouse,
        purchase_order__status__in=(PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIAL),
        sku=sku,
    ).select_related("purchase_order")
    for line in purchase_lines:
        confirmed = (
            PurchaseShipmentLine.objects.filter(
                purchase_line=line,
                purchase_shipment__confirmed_at__isnull=False,
            ).aggregate(total=Sum("quantity_shipped"))["total"]
            or ZERO
        )
        direct_received = (
            ReceiptLine.objects.filter(
                purchase_line=line,
                receipt__status=Receipt.Status.COMPLETED,
            ).filter(
                Q(receipt__purchase_shipment__isnull=True)
                | Q(receipt__purchase_shipment__confirmed_at__isnull=True)
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        confirmed_received = (
            ReceiptLine.objects.filter(
                purchase_line=line,
                receipt__status=Receipt.Status.COMPLETED,
                receipt__purchase_shipment__confirmed_at__isnull=False,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        # Old imports may carry only the cumulative line field without receipt
        # events. Infer only the portion not already tied to confirmed shipments.
        inferred_direct_received = max(
            ZERO, _decimal(line.quantity_received) - _decimal(confirmed_received)
        )
        direct_received = max(_decimal(direct_received), inferred_direct_received)
        remaining = max(
            ZERO,
            _decimal(line.quantity_ordered)
            - _decimal(confirmed)
            - _decimal(line.quantity_unshipped_closed)
            - _decimal(direct_received),
        )
        if remaining:
            pending_sources.append({
                "source_type": "purchase",
                "source_stage": "pending_shipment",
                "source_number": line.purchase_order.number,
                "tracking_number": "",
                "planned_quantity": line.quantity_ordered,
                "received_quantity": line.quantity_received,
                "exception_closed_quantity": line.quantity_unshipped_closed,
                "remaining_quantity": remaining,
                "started_at": line.purchase_order.ordered_at,
                "expected_at": line.purchase_order.expected_at,
            })

    transit_sources = []
    shipment_lines = PurchaseShipmentLine.objects.filter(
        purchase_shipment__purchase_order__organization=organization,
        purchase_shipment__purchase_order__warehouse=warehouse,
        purchase_shipment__purchase_order__status__in=(
            PurchaseOrder.Status.SUBMITTED,
            PurchaseOrder.Status.PARTIAL,
        ),
        purchase_shipment__confirmed_at__isnull=False,
        purchase_line__sku=sku,
    ).select_related("purchase_shipment__purchase_order", "purchase_line")
    for line in shipment_lines:
        received = (
            ReceiptLine.objects.filter(
                receipt__status=Receipt.Status.COMPLETED,
                receipt__purchase_shipment=line.purchase_shipment,
                purchase_line=line.purchase_line,
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )
        remaining = max(
            ZERO,
            _decimal(line.quantity_shipped)
            - _decimal(received)
            - _decimal(line.quantity_exception_closed),
        )
        if remaining:
            transit_sources.append({
                "source_type": "purchase",
                "source_stage": "in_transit",
                "source_number": line.purchase_shipment.purchase_order.number,
                "tracking_number": line.purchase_shipment.tracking_number,
                "planned_quantity": line.quantity_shipped,
                "received_quantity": received,
                "exception_closed_quantity": line.quantity_exception_closed,
                "remaining_quantity": remaining,
                "started_at": line.purchase_shipment.confirmed_at,
                "expected_at": line.purchase_shipment.purchase_order.expected_at,
            })

    transfer_lines = StockTransferLine.objects.filter(
        transfer__organization=organization,
        transfer__destination_warehouse=warehouse,
        transfer__status__in=(
            StockTransfer.Status.IN_TRANSIT,
            StockTransfer.Status.PARTIALLY_RECEIVED,
        ),
        sku=sku,
    ).select_related("transfer").prefetch_related("transfer__packages")
    for line in transfer_lines:
        remaining = max(
            ZERO,
            _decimal(line.quantity)
            - _decimal(line.received_quantity)
            - _decimal(line.exception_closed_quantity),
        )
        if remaining:
            tracking = "、".join(
                value for value in line.transfer.packages.values_list("tracking_number", flat=True) if value
            )
            transit_sources.append({
                "source_type": "transfer",
                "source_stage": "in_transit",
                "source_number": line.transfer.number,
                "tracking_number": tracking,
                "planned_quantity": line.quantity,
                "received_quantity": line.received_quantity,
                "exception_closed_quantity": line.exception_closed_quantity,
                "remaining_quantity": remaining,
                "started_at": line.transfer.dispatched_at,
                "expected_at": None,
            })

    pending_total = sum((_decimal(item["remaining_quantity"]) for item in pending_sources), ZERO)
    transit_total = sum((_decimal(item["remaining_quantity"]) for item in transit_sources), ZERO)
    return InboundSnapshot(
        purchased_pending_shipment=pending_total,
        in_transit=transit_total,
        inbound_total=pending_total + transit_total,
        pending_sources=tuple(pending_sources),
        transit_sources=tuple(transit_sources),
        stored_pending_shipment=stored_pending,
        stored_in_transit=stored_transit,
    )

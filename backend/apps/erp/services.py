from copy import deepcopy
from decimal import Decimal
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from .models import (
    AuditLog,
    CompetitorProduct,
    CompetitorSnapshot,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    ReceiptLine,
    ReturnLine,
    ReturnOrder,
    ReturnReceipt,
    ReturnReceiptLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentLine,
    StockBalance,
    StockLedger,
    StockReservation,
    StockTransfer,
    StockTransferLine,
)


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _assert_organization(organization, **instances):
    """Reject corrupt or forged cross-organization domain references."""
    for label, instance in instances.items():
        if instance is None:
            continue
        instance_org_id = getattr(instance, "organization_id", None)
        if instance_org_id != organization.pk:
            raise ValidationError(f"{label} 不属于当前组织")


def _validate_warehouse_and_sku(organization, warehouse, sku=None):
    _assert_organization(organization, warehouse=warehouse)
    if sku is not None:
        _assert_organization(organization, sku=sku, product=sku.product)


def _assert_ledger_replay(
    existing, *, warehouse, sku, event_type, on_hand_delta, reserved_delta,
    reference_type, reference_id,
):
    expected = {
        "warehouse_id": warehouse.pk,
        "sku_id": sku.pk,
        "event_type": event_type,
        "on_hand_delta": _decimal(on_hand_delta),
        "reserved_delta": _decimal(reserved_delta),
        "reference_type": reference_type,
        "reference_id": str(reference_id),
    }
    if any(getattr(existing, field) != value for field, value in expected.items()):
        raise ValidationError("幂等键已用于不同的库存操作")
    return existing


def _normalized_line_payload(lines, *, line_key):
    return sorted(
        (
            str(item[line_key].pk),
            _decimal(item["quantity"]),
            _decimal(item.get("unit_cost", getattr(item[line_key], "unit_cost", 0))),
        )
        for item in lines
    )


def write_audit(*, organization, actor, action, instance, before=None, after=None, request_id=""):
    return AuditLog.objects.create(
        organization=organization,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        before=before or {},
        after=after or {},
        request_id=request_id,
    )


@transaction.atomic
def post_stock(
    *, organization, warehouse, sku, event_type, on_hand_delta=0, reserved_delta=0,
    reference_type, reference_id, idempotency_key, actor=None, reason="",
):
    """Atomically update the balance and append one immutable ledger row."""
    _validate_warehouse_and_sku(organization, warehouse, sku)
    existing = StockLedger.objects.filter(
        organization=organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        return _assert_ledger_replay(
            existing, warehouse=warehouse, sku=sku, event_type=event_type,
            on_hand_delta=on_hand_delta, reserved_delta=reserved_delta,
            reference_type=reference_type, reference_id=reference_id,
        )

    balance, _ = StockBalance.objects.select_for_update().get_or_create(
        organization=organization,
        warehouse=warehouse,
        sku=sku,
        defaults={"on_hand": Decimal("0"), "reserved": Decimal("0")},
    )
    # A concurrent first request may have committed while this request waited
    # for the balance lock. Re-check before applying any quantity delta.
    existing = StockLedger.objects.filter(
        organization=organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        return _assert_ledger_replay(
            existing, warehouse=warehouse, sku=sku, event_type=event_type,
            on_hand_delta=on_hand_delta, reserved_delta=reserved_delta,
            reference_type=reference_type, reference_id=reference_id,
        )
    new_on_hand = balance.on_hand + _decimal(on_hand_delta)
    new_reserved = balance.reserved + _decimal(reserved_delta)
    if new_on_hand < 0:
        raise ValidationError(f"SKU {sku.code} 库存不足")
    if new_reserved < 0:
        raise ValidationError(f"SKU {sku.code} 锁定库存不足")
    if new_reserved > new_on_hand:
        raise ValidationError(f"SKU {sku.code} 可用库存不足")

    balance.on_hand = new_on_hand
    balance.reserved = new_reserved
    balance.save(update_fields=["on_hand", "reserved", "updated_at"])
    return StockLedger.objects.create(
        organization=organization,
        warehouse=warehouse,
        sku=sku,
        event_type=event_type,
        on_hand_delta=_decimal(on_hand_delta),
        reserved_delta=_decimal(reserved_delta),
        on_hand_after=new_on_hand,
        reserved_after=new_reserved,
        reference_type=reference_type,
        reference_id=str(reference_id),
        idempotency_key=idempotency_key,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        reason=reason,
    )


@transaction.atomic
def dispatch_stock_transfer(*, transfer, idempotency_key, actor=None):
    """Post a draft transfer out of its source warehouse exactly once."""
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    expected_organization = transfer.organization
    transfer = StockTransfer.objects.select_for_update().select_related(
        "organization", "source_warehouse", "destination_warehouse"
    ).get(pk=transfer.pk, organization=expected_organization)
    _assert_organization(
        transfer.organization,
        source_warehouse=transfer.source_warehouse,
        destination_warehouse=transfer.destination_warehouse,
    )
    if transfer.status in {StockTransfer.Status.IN_TRANSIT, StockTransfer.Status.RECEIVED}:
        if transfer.dispatch_idempotency_key == idempotency_key:
            return transfer
        raise ValidationError("调拨单已经使用其他幂等键发出")
    if transfer.status != StockTransfer.Status.DRAFT:
        raise ValidationError("只有草稿调拨单可以发出")
    if transfer.source_warehouse_id == transfer.destination_warehouse_id:
        raise ValidationError("来源仓和目标仓不能相同")
    if not transfer.source_warehouse.active or not transfer.source_warehouse.can_ship:
        raise ValidationError("来源仓未启用或不允许出库")
    if not transfer.destination_warehouse.active or not transfer.destination_warehouse.can_receive:
        raise ValidationError("目标仓未启用或不允许收货")
    if StockTransfer.objects.filter(
        organization=transfer.organization,
        dispatch_idempotency_key=idempotency_key,
    ).exclude(pk=transfer.pk).exists():
        raise ValidationError("幂等键已被其他调拨单占用")

    lines = list(
        StockTransferLine.objects.select_for_update()
        .filter(transfer=transfer)
        .select_related("sku__product")
        .order_by("pk")
    )
    if not lines:
        raise ValidationError("调拨单没有明细")
    for line in lines:
        _assert_organization(
            transfer.organization, sku=line.sku, product=line.sku.product
        )
        StockBalance.objects.get_or_create(
            organization=transfer.organization,
            warehouse=transfer.destination_warehouse,
            sku=line.sku,
            defaults={"on_hand": Decimal("0"), "reserved": Decimal("0")},
        )
        post_stock(
            organization=transfer.organization,
            warehouse=transfer.source_warehouse,
            sku=line.sku,
            event_type=StockLedger.Type.TRANSFER_OUT,
            on_hand_delta=-line.quantity,
            reference_type="stock_transfer_line",
            reference_id=line.pk,
            idempotency_key=f"transfer-out:{transfer.pk}:{line.pk}",
            actor=actor,
            reason=f"调拨至 {transfer.destination_warehouse.name}",
        )
    transfer.status = StockTransfer.Status.IN_TRANSIT
    transfer.dispatch_idempotency_key = idempotency_key
    transfer.dispatched_at = timezone.now()
    transfer.dispatched_by = actor if getattr(actor, "is_authenticated", False) else None
    transfer.save(update_fields=[
        "status", "dispatch_idempotency_key", "dispatched_at", "dispatched_by", "updated_at",
    ])
    write_audit(
        organization=transfer.organization,
        actor=actor,
        action="stock_transfer.dispatch",
        instance=transfer,
        after={"idempotency_key": idempotency_key, "line_count": len(lines)},
    )
    return transfer


@transaction.atomic
def receive_stock_transfer(*, transfer, idempotency_key, actor=None):
    """Post an in-transit transfer into its destination warehouse exactly once."""
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    expected_organization = transfer.organization
    transfer = StockTransfer.objects.select_for_update().select_related(
        "organization", "source_warehouse", "destination_warehouse"
    ).get(pk=transfer.pk, organization=expected_organization)
    _assert_organization(
        transfer.organization,
        source_warehouse=transfer.source_warehouse,
        destination_warehouse=transfer.destination_warehouse,
    )
    if transfer.status == StockTransfer.Status.RECEIVED:
        if transfer.receive_idempotency_key == idempotency_key:
            return transfer
        raise ValidationError("调拨单已经使用其他幂等键收货")
    if transfer.status != StockTransfer.Status.IN_TRANSIT:
        raise ValidationError("只有调拨在途单可以收货")
    if not transfer.destination_warehouse.active or not transfer.destination_warehouse.can_receive:
        raise ValidationError("目标仓未启用或不允许收货")
    if StockTransfer.objects.filter(
        organization=transfer.organization,
        receive_idempotency_key=idempotency_key,
    ).exclude(pk=transfer.pk).exists():
        raise ValidationError("幂等键已被其他调拨收货占用")

    lines = list(
        StockTransferLine.objects.select_for_update()
        .filter(transfer=transfer)
        .select_related("sku__product")
        .order_by("pk")
    )
    if not lines:
        raise ValidationError("调拨单没有明细")
    for line in lines:
        _assert_organization(
            transfer.organization, sku=line.sku, product=line.sku.product
        )
        post_stock(
            organization=transfer.organization,
            warehouse=transfer.destination_warehouse,
            sku=line.sku,
            event_type=StockLedger.Type.TRANSFER_IN,
            on_hand_delta=line.quantity,
            reference_type="stock_transfer_line",
            reference_id=line.pk,
            idempotency_key=f"transfer-in:{transfer.pk}:{line.pk}",
            actor=actor,
            reason=f"从 {transfer.source_warehouse.name} 调拨收货",
        )
    transfer.status = StockTransfer.Status.RECEIVED
    transfer.receive_idempotency_key = idempotency_key
    transfer.received_at = timezone.now()
    transfer.received_by = actor if getattr(actor, "is_authenticated", False) else None
    transfer.save(update_fields=[
        "status", "receive_idempotency_key", "received_at", "received_by", "updated_at",
    ])
    write_audit(
        organization=transfer.organization,
        actor=actor,
        action="stock_transfer.receive",
        instance=transfer,
        after={"idempotency_key": idempotency_key, "line_count": len(lines)},
    )
    return transfer


@transaction.atomic
def cancel_stock_transfer(*, transfer, actor=None):
    expected_organization = transfer.organization
    transfer = StockTransfer.objects.select_for_update().select_related(
        "source_warehouse", "destination_warehouse"
    ).get(
        pk=transfer.pk, organization=expected_organization
    )
    if transfer.status == StockTransfer.Status.CANCELLED:
        return transfer
    if transfer.status == StockTransfer.Status.RECEIVED:
        raise ValidationError("已收货调拨单不能取消")
    if transfer.status not in {
        StockTransfer.Status.DRAFT,
        StockTransfer.Status.IN_TRANSIT,
    }:
        raise ValidationError("当前调拨状态不能取消")
    restored = transfer.status == StockTransfer.Status.IN_TRANSIT
    if restored:
        lines = list(
            StockTransferLine.objects.select_for_update()
            .filter(transfer=transfer)
            .select_related("sku__product")
            .order_by("pk")
        )
        if not lines:
            raise ValidationError("调拨单没有明细")
        for line in lines:
            _assert_organization(
                transfer.organization, sku=line.sku, product=line.sku.product
            )
            post_stock(
                organization=transfer.organization,
                warehouse=transfer.source_warehouse,
                sku=line.sku,
                event_type=StockLedger.Type.TRANSFER_CANCEL,
                on_hand_delta=line.quantity,
                reference_type="stock_transfer_line",
                reference_id=line.pk,
                idempotency_key=f"transfer-cancel:{transfer.pk}:{line.pk}",
                actor=actor,
                reason=f"撤回前往 {transfer.destination_warehouse.name} 的调拨",
            )
    transfer.status = StockTransfer.Status.CANCELLED
    transfer.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=transfer.organization,
        actor=actor,
        action="stock_transfer.cancel",
        instance=transfer,
        after={"restored_source_stock": restored},
    )
    return transfer


@transaction.atomic
def adjust_inventory(*, organization, warehouse, sku, delta, reason, idempotency_key, actor=None):
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    existing = StockLedger.objects.filter(
        organization=organization, idempotency_key=f"adjust:{idempotency_key}"
    ).first()
    if existing:
        _validate_warehouse_and_sku(organization, warehouse, sku)
        return _assert_ledger_replay(
            existing,
            warehouse=warehouse,
            sku=sku,
            event_type=StockLedger.Type.ADJUSTMENT,
            on_hand_delta=delta,
            reserved_delta=0,
            reference_type="inventory_adjustment",
            reference_id=idempotency_key,
        )
    ledger = post_stock(
        organization=organization,
        warehouse=warehouse,
        sku=sku,
        event_type=StockLedger.Type.ADJUSTMENT,
        on_hand_delta=delta,
        reference_type="inventory_adjustment",
        reference_id=idempotency_key,
        idempotency_key=f"adjust:{idempotency_key}",
        actor=actor,
        reason=reason,
    )
    if not AuditLog.objects.filter(
        organization=organization,
        action="inventory.adjust",
        object_type=ledger._meta.label_lower,
        object_id=str(ledger.pk),
    ).exists():
        write_audit(
            organization=organization,
            actor=actor,
            action="inventory.adjust",
            instance=ledger,
            before={
                "on_hand": str(ledger.on_hand_after - _decimal(delta)),
                "reserved": str(ledger.reserved_after),
            },
            after={
                "on_hand": str(ledger.on_hand_after),
                "reserved": str(ledger.reserved_after),
                "delta": str(delta),
                "reason": reason,
            },
        )
    return ledger


@transaction.atomic
def submit_purchase(*, purchase_order, actor=None):
    purchase_order = PurchaseOrder.objects.select_for_update().select_related(
        "organization", "supplier", "warehouse"
    ).get(pk=purchase_order.pk)
    _assert_organization(
        purchase_order.organization,
        supplier=purchase_order.supplier,
        warehouse=purchase_order.warehouse,
    )
    if (
        not purchase_order.supplier.active
        or not purchase_order.warehouse.active
        or not purchase_order.warehouse.can_receive
    ):
        raise ValidationError("采购单的供应商和收货仓库必须处于启用且可收货状态")
    if purchase_order.status == PurchaseOrder.Status.SUBMITTED:
        return purchase_order
    if purchase_order.status != PurchaseOrder.Status.DRAFT:
        raise ValidationError("只有草稿采购单可以提交")
    if not purchase_order.lines.exists():
        raise ValidationError("采购单没有明细")
    for line in purchase_order.lines.select_related("sku__product"):
        _assert_organization(
            purchase_order.organization, sku=line.sku, product=line.sku.product
        )
        if not line.sku.active or line.sku.product.status != line.sku.product.Status.ACTIVE:
            raise ValidationError(f"SKU {line.sku.code} 对应商品未启用")
        StockBalance.objects.get_or_create(
            organization=purchase_order.organization,
            warehouse=purchase_order.warehouse,
            sku=line.sku,
            defaults={"on_hand": Decimal("0"), "reserved": Decimal("0")},
        )
    purchase_order.status = PurchaseOrder.Status.SUBMITTED
    purchase_order.ordered_at = purchase_order.ordered_at or timezone.now()
    purchase_order.save(update_fields=["status", "ordered_at", "updated_at"])
    write_audit(
        organization=purchase_order.organization,
        actor=actor,
        action="purchase.submit",
        instance=purchase_order,
    )
    return purchase_order


@transaction.atomic
def cancel_purchase(*, purchase_order, actor=None):
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_order.pk)
    if purchase_order.status == PurchaseOrder.Status.CANCELLED:
        return purchase_order
    if purchase_order.status == PurchaseOrder.Status.RECEIVED:
        raise ValidationError("已全部收货的采购单不能取消")
    if purchase_order.status not in {
        PurchaseOrder.Status.DRAFT,
        PurchaseOrder.Status.SUBMITTED,
        PurchaseOrder.Status.PARTIAL,
    }:
        raise ValidationError("当前采购单状态不能取消")
    _assert_organization(
        purchase_order.organization,
        supplier=purchase_order.supplier,
        warehouse=purchase_order.warehouse,
    )
    purchase_order.status = PurchaseOrder.Status.CANCELLED
    purchase_order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=purchase_order.organization,
        actor=actor,
        action="purchase.cancel",
        instance=purchase_order,
    )
    return purchase_order


@transaction.atomic
def receive_purchase(*, organization, purchase_order, number, lines, idempotency_key, actor=None):
    _assert_organization(organization, purchase_order=purchase_order)
    purchase_order = PurchaseOrder.objects.select_for_update().select_related(
        "supplier", "warehouse"
    ).get(pk=purchase_order.pk, organization=organization)
    _assert_organization(
        organization, supplier=purchase_order.supplier, warehouse=purchase_order.warehouse
    )
    if not purchase_order.warehouse.active or not purchase_order.warehouse.can_receive:
        raise ValidationError("采购单的目标仓库未启用或不允许收货")
    # The PO lock serializes state changes; repeat the idempotency lookup only
    # after acquiring it so a concurrent successful receipt is observable.
    existing = Receipt.objects.filter(
        organization=organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.purchase_order_id != purchase_order.pk:
            raise ValidationError("幂等键已被其他采购收货占用")
        recorded = sorted(
            (str(line.purchase_line_id), line.quantity, line.unit_cost)
            for line in existing.lines.all()
        )
        if recorded != _normalized_line_payload(lines, line_key="purchase_line"):
            raise ValidationError("幂等键对应的采购收货明细不一致")
        return existing
    if purchase_order.status not in {
        PurchaseOrder.Status.SUBMITTED,
        PurchaseOrder.Status.PARTIAL,
    }:
        raise ValidationError("只有已提交或部分收货的采购单可以收货")
    if not lines:
        raise ValidationError("至少需要一条收货明细")

    receipt = Receipt.objects.create(
        organization=organization,
        number=number,
        purchase_order=purchase_order,
        warehouse=purchase_order.warehouse,
        idempotency_key=idempotency_key,
        status=Receipt.Status.DRAFT,
    )
    cost_changes = []
    for index, item in enumerate(lines):
        purchase_line = PurchaseOrderLine.objects.select_for_update().get(
            pk=item["purchase_line"].pk, purchase_order=purchase_order
        )
        _assert_organization(
            organization, sku=purchase_line.sku, product=purchase_line.sku.product
        )
        quantity = _decimal(item["quantity"])
        unit_cost = _decimal(item.get("unit_cost", purchase_line.unit_cost))
        remaining = purchase_line.quantity_ordered - purchase_line.quantity_received
        if quantity <= 0 or quantity > remaining:
            raise ValidationError(f"SKU {purchase_line.sku.code} 收货数量超出未收数量")
        receipt_line = ReceiptLine.objects.create(
            receipt=receipt,
            purchase_line=purchase_line,
            sku=purchase_line.sku,
            quantity=quantity,
            unit_cost=unit_cost,
        )
        post_stock(
            organization=organization,
            warehouse=purchase_order.warehouse,
            sku=purchase_line.sku,
            event_type=StockLedger.Type.RECEIPT,
            on_hand_delta=quantity,
            reference_type="receipt_line",
            reference_id=receipt_line.pk,
            idempotency_key=f"receipt:{idempotency_key}:{index}",
            actor=actor,
        )
        purchase_line.quantity_received += quantity
        purchase_line.save(update_fields=["quantity_received", "updated_at"])
        previous_cost = purchase_line.sku.cost
        purchase_line.sku.cost = unit_cost
        purchase_line.sku.save(update_fields=["cost", "updated_at"])
        if previous_cost != unit_cost:
            cost_changes.append({
                "sku": purchase_line.sku.code,
                "before": str(previous_cost),
                "after": str(unit_cost),
            })

    all_received = not purchase_order.lines.filter(quantity_received__lt=models.F("quantity_ordered")).exists()
    purchase_order.status = PurchaseOrder.Status.RECEIVED if all_received else PurchaseOrder.Status.PARTIAL
    purchase_order.save(update_fields=["status", "updated_at"])
    receipt.status = Receipt.Status.COMPLETED
    receipt.received_at = timezone.now()
    receipt.received_by = actor if getattr(actor, "is_authenticated", False) else None
    receipt.save(update_fields=["status", "received_at", "received_by", "updated_at"])
    write_audit(
        organization=organization,
        actor=actor,
        action="purchase.receive",
        instance=receipt,
        after={
            "purchase_order": str(purchase_order.pk),
            "line_count": len(lines),
            "cost_changes": cost_changes,
        },
    )
    return receipt


@transaction.atomic
def confirm_order(*, order, actor=None):
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(pk=order.pk)
    _assert_organization(order.organization, warehouse=order.warehouse)
    if not order.warehouse.active or not order.warehouse.can_ship:
        raise ValidationError("订单仓库未启用或不允许出库")
    if order.status == SalesOrder.Status.READY:
        return order
    if order.status != SalesOrder.Status.DRAFT:
        raise ValidationError("只有草稿订单可以确认")
    if not order.lines.exists():
        raise ValidationError("订单没有明细")
    for line in order.lines.select_related("sku__product"):
        _assert_organization(order.organization, sku=line.sku, product=line.sku.product)
        if not line.sku.active or line.sku.product.status != line.sku.product.Status.ACTIVE:
            raise ValidationError(f"SKU {line.sku.code} 对应商品未启用")
    order.status = SalesOrder.Status.READY
    order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=order.organization, actor=actor, action="order.confirm", instance=order
    )
    return order


@transaction.atomic
def cancel_order(*, order, actor=None):
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(pk=order.pk)
    _assert_organization(order.organization, warehouse=order.warehouse)
    if order.status == SalesOrder.Status.CANCELLED:
        return order
    if order.status == SalesOrder.Status.SHIPPED:
        raise ValidationError("已出库订单不能取消")
    if order.status not in {
        SalesOrder.Status.DRAFT,
        SalesOrder.Status.READY,
        SalesOrder.Status.ALLOCATED,
        SalesOrder.Status.PICKING,
        SalesOrder.Status.VERIFIED,
    }:
        raise ValidationError("当前订单状态不能取消")

    if order.status in {
        SalesOrder.Status.ALLOCATED,
        SalesOrder.Status.PICKING,
        SalesOrder.Status.VERIFIED,
    }:
        reservations = list(
            StockReservation.objects.select_for_update()
            .filter(order_line__order=order, status=StockReservation.Status.ACTIVE)
            .select_related("order_line", "sku__product", "warehouse")
        )
        if not reservations:
            raise ValidationError("已锁库订单缺少有效锁定记录")
        for reservation in reservations:
            _validate_warehouse_and_sku(order.organization, reservation.warehouse, reservation.sku)
            line = SalesOrderLine.objects.select_for_update().get(pk=reservation.order_line_id)
            if reservation.quantity > line.quantity_reserved:
                raise ValidationError("订单锁定数量不一致")
            post_stock(
                organization=order.organization,
                warehouse=reservation.warehouse,
                sku=reservation.sku,
                event_type=StockLedger.Type.RELEASE,
                reserved_delta=-reservation.quantity,
                reference_type="stock_reservation",
                reference_id=reservation.pk,
                idempotency_key=f"order-cancel:{order.pk}:{reservation.pk}",
                actor=actor,
                reason="取消订单释放锁定库存",
            )
            line.quantity_reserved -= reservation.quantity
            line.save(update_fields=["quantity_reserved", "updated_at"])
            reservation.status = StockReservation.Status.RELEASED
            reservation.save(update_fields=["status", "updated_at"])

    order.status = SalesOrder.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=order.organization, actor=actor, action="order.cancel", instance=order
    )
    return order


@transaction.atomic
def start_picking(*, order, actor=None):
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(pk=order.pk)
    _assert_organization(order.organization, warehouse=order.warehouse)
    if order.status in {SalesOrder.Status.PICKING, SalesOrder.Status.VERIFIED}:
        return order
    if order.status != SalesOrder.Status.ALLOCATED:
        raise ValidationError("只有已锁库订单可以开始拣货")
    if not StockReservation.objects.filter(
        order_line__order=order, status=StockReservation.Status.ACTIVE
    ).exists():
        raise ValidationError("订单缺少有效锁定记录")
    order.status = SalesOrder.Status.PICKING
    order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=order.organization, actor=actor, action="order.picking.start", instance=order
    )
    return order


@transaction.atomic
def verify_order(*, order, actor=None):
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(pk=order.pk)
    _assert_organization(order.organization, warehouse=order.warehouse)
    if order.status == SalesOrder.Status.VERIFIED:
        return order
    if order.status != SalesOrder.Status.PICKING:
        raise ValidationError("只有拣货中的订单可以复核")
    lines = list(order.lines.select_for_update())
    if not lines or any(
        line.quantity_reserved != line.quantity - line.quantity_shipped for line in lines
    ):
        raise ValidationError("订单锁定数量与待出库数量不一致")
    order.status = SalesOrder.Status.VERIFIED
    order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=order.organization, actor=actor, action="order.verify", instance=order
    )
    return order


@transaction.atomic
def allocate_order(*, order, idempotency_key, actor=None):
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(pk=order.pk)
    _assert_organization(order.organization, warehouse=order.warehouse)
    if order.status == SalesOrder.Status.ALLOCATED:
        lines = list(order.lines.select_for_update())
        expected_keys = {
            f"allocate:{idempotency_key}:{line.pk}"
            for line in lines
            if line.quantity_reserved > 0
        }
        actual_keys = set(
            StockReservation.objects.filter(
                order_line__order=order,
                status=StockReservation.Status.ACTIVE,
            ).values_list("idempotency_key", flat=True)
        )
        if expected_keys and actual_keys == expected_keys:
            return order
        raise ValidationError("订单已经使用其他幂等键完成锁库")
    if order.status != SalesOrder.Status.READY:
        raise ValidationError("只有待锁库订单可以锁定库存")
    if not order.lines.exists():
        raise ValidationError("订单没有明细")

    for line in order.lines.select_for_update().select_related("sku__product"):
        _assert_organization(order.organization, sku=line.sku, product=line.sku.product)
        quantity = line.quantity - line.quantity_shipped - line.quantity_reserved
        if quantity <= 0:
            continue
        line_key = f"allocate:{idempotency_key}:{line.pk}"
        post_stock(
            organization=order.organization,
            warehouse=order.warehouse,
            sku=line.sku,
            event_type=StockLedger.Type.RESERVE,
            reserved_delta=quantity,
            reference_type="sales_order_line",
            reference_id=line.pk,
            idempotency_key=line_key,
            actor=actor,
        )
        StockReservation.objects.create(
            organization=order.organization,
            order_line=line,
            warehouse=order.warehouse,
            sku=line.sku,
            quantity=quantity,
            idempotency_key=line_key,
        )
        line.quantity_reserved += quantity
        line.save(update_fields=["quantity_reserved", "updated_at"])
    order.status = SalesOrder.Status.ALLOCATED
    order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=order.organization, actor=actor, action="order.allocate", instance=order,
        after={"idempotency_key": idempotency_key},
    )
    return order


@transaction.atomic
def ship_order(*, order, number, idempotency_key, tracking_number="", actor=None):
    expected_organization = order.organization
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(
        pk=order.pk, organization=expected_organization
    )
    _assert_organization(order.organization, warehouse=order.warehouse)
    # Re-check only after locking the order to close the retry race.
    existing = Shipment.objects.filter(
        organization=order.organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.order_id != order.pk:
            raise ValidationError("幂等键已被其他出库单占用")
        if existing.tracking_number != tracking_number:
            raise ValidationError("幂等键对应的物流单号不一致")
        return existing
    if order.status != SalesOrder.Status.VERIFIED:
        raise ValidationError("只有已完成拣货复核的订单可以出库")
    lines = list(order.lines.select_for_update().select_related("sku__product"))
    if not lines or not any(line.quantity_reserved > 0 for line in lines):
        raise ValidationError("订单没有可出库的锁定库存")
    for line in lines:
        _assert_organization(order.organization, sku=line.sku, product=line.sku.product)
        remaining = line.quantity - line.quantity_shipped
        if remaining <= 0 or line.quantity_reserved != remaining:
            raise ValidationError(f"SKU {line.sku.code} 的锁定数量不足以完成出库")
    shipment = Shipment.objects.create(
        organization=order.organization,
        number=number,
        order=order,
        warehouse=order.warehouse,
        idempotency_key=idempotency_key,
        tracking_number=tracking_number,
        shipped_at=timezone.now(),
        shipped_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    for index, line in enumerate(lines):
        quantity = line.quantity_reserved
        if quantity <= 0:
            continue
        shipment_line = ShipmentLine.objects.create(
            shipment=shipment, order_line=line, sku=line.sku, quantity=quantity
        )
        post_stock(
            organization=order.organization,
            warehouse=order.warehouse,
            sku=line.sku,
            event_type=StockLedger.Type.SHIPMENT,
            on_hand_delta=-quantity,
            reserved_delta=-quantity,
            reference_type="shipment_line",
            reference_id=shipment_line.pk,
            idempotency_key=f"shipment:{idempotency_key}:{index}",
            actor=actor,
        )
        line.quantity_reserved = Decimal("0")
        line.quantity_shipped += quantity
        line.save(update_fields=["quantity_reserved", "quantity_shipped", "updated_at"])
        line.reservations.filter(status=StockReservation.Status.ACTIVE).update(status=StockReservation.Status.CONSUMED)
    order.status = SalesOrder.Status.SHIPPED
    order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=order.organization, actor=actor, action="order.ship", instance=shipment,
        after={"order": str(order.pk)},
    )
    return shipment


@transaction.atomic
def confirm_and_ship_order(
    *, order, idempotency_key, number="", tracking_number="", actor=None
):
    """Confirm, reserve and ship a complete order in one database transaction."""
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    expected_organization = order.organization
    order = SalesOrder.objects.select_for_update().select_related(
        "organization", "warehouse"
    ).get(pk=order.pk, organization=expected_organization)
    existing = Shipment.objects.filter(
        organization=order.organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.order_id != order.pk:
            raise ValidationError("幂等键已被其他订单的出库操作占用")
        if number and existing.number != number:
            raise ValidationError("幂等键对应的出库单号不一致")
        if tracking_number and existing.tracking_number != tracking_number:
            raise ValidationError("幂等键对应的物流单号不一致")
        return existing
    if order.status == SalesOrder.Status.CANCELLED:
        raise ValidationError("已取消订单不能确认出库")
    if order.status == SalesOrder.Status.SHIPPED:
        raise ValidationError("订单已由其他出库请求完成")

    if order.status == SalesOrder.Status.DRAFT:
        order = confirm_order(order=order, actor=actor)
    if order.status == SalesOrder.Status.READY:
        allocation_key = f"one-step-{sha256(idempotency_key.encode('utf-8')).hexdigest()}"
        order = allocate_order(
            order=order, idempotency_key=allocation_key, actor=actor
        )
    if order.status == SalesOrder.Status.ALLOCATED:
        order = start_picking(order=order, actor=actor)
    if order.status == SalesOrder.Status.PICKING:
        order = verify_order(order=order, actor=actor)
    if order.status != SalesOrder.Status.VERIFIED:
        raise ValidationError("当前订单状态不能执行一键确认出库")

    shipment_number = number.strip() if number else ""
    if not shipment_number:
        candidate = f"OUT-{order.number}"
        shipment_number = candidate if len(candidate) <= 60 else f"OUT-{order.pk.hex[:20]}"
    return ship_order(
        order=order,
        number=shipment_number,
        idempotency_key=idempotency_key,
        tracking_number=tracking_number,
        actor=actor,
    )


@transaction.atomic
def receive_return(*, return_order, quantities, idempotency_key, actor=None):
    expected_organization = return_order.organization
    return_order = ReturnOrder.objects.select_for_update().select_related(
        "organization", "warehouse", "original_order"
    ).get(pk=return_order.pk, organization=expected_organization)
    _assert_organization(
        return_order.organization,
        warehouse=return_order.warehouse,
        original_order=return_order.original_order,
    )
    if return_order.original_order is None:
        raise ValidationError("退货单必须关联已出库订单")
    if return_order.original_order.status != SalesOrder.Status.SHIPPED:
        raise ValidationError("只有已出库订单可以办理退货收货")
    if return_order.original_order.warehouse_id != return_order.warehouse_id:
        raise ValidationError("退货仓库必须与原订单出库仓一致")
    for return_line in return_order.lines.select_related("sku__product"):
        _assert_organization(
            return_order.organization,
            sku=return_line.sku,
            product=return_line.sku.product,
        )
        shipped = sum(
            (
                order_line.quantity_shipped
                for order_line in return_order.original_order.lines.filter(sku=return_line.sku)
            ),
            Decimal("0"),
        )
        requested = sum(
            (
                line.quantity_expected
                for line in ReturnLine.objects.filter(
                    return_order__original_order=return_order.original_order,
                    sku=return_line.sku,
                ).exclude(return_order__status=ReturnOrder.Status.REJECTED)
            ),
            Decimal("0"),
        )
        if shipped <= 0 or requested > shipped:
            raise ValidationError(f"SKU {return_line.sku.code} 的退货数量超过已出库数量")
    # The key is unique per organization. Re-check after the return-order lock
    # so retries cannot apply quantities twice.
    existing = ReturnReceipt.objects.filter(
        organization=return_order.organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.return_order_id != return_order.pk:
            raise ValidationError("幂等键已被其他退货收货占用")
        recorded = sorted(
            (str(line.return_line_id), line.quantity, Decimal("0"))
            for line in existing.lines.all()
        )
        if recorded != _normalized_line_payload(quantities, line_key="return_line"):
            raise ValidationError("幂等键对应的退货收货明细不一致")
        return return_order
    if return_order.status not in {ReturnOrder.Status.REQUESTED, ReturnOrder.Status.PARTIAL}:
        raise ValidationError("只有待收货或部分收货的退货单可以收货")
    if not quantities:
        raise ValidationError("至少需要一条退货收货明细")
    line_ids = [item["return_line"].pk for item in quantities]
    if len(line_ids) != len(set(line_ids)):
        raise ValidationError("同一退货明细不能在一次收货中重复")

    receipt = ReturnReceipt.objects.create(
        organization=return_order.organization,
        return_order=return_order,
        warehouse=return_order.warehouse,
        idempotency_key=idempotency_key,
        received_at=timezone.now(),
        received_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    for index, item in enumerate(quantities):
        line = ReturnLine.objects.select_for_update().select_related("sku__product").get(
            pk=item["return_line"].pk, return_order=return_order
        )
        _assert_organization(
            return_order.organization, sku=line.sku, product=line.sku.product
        )
        quantity = _decimal(item["quantity"])
        if quantity <= 0 or line.quantity_received + quantity > line.quantity_expected:
            raise ValidationError("退货收货数量不正确")
        receipt_line = ReturnReceiptLine.objects.create(
            receipt=receipt,
            return_line=line,
            sku=line.sku,
            quantity=quantity,
            condition=line.condition,
        )
        if line.condition == ReturnLine.Condition.RESTOCK:
            post_stock(
                organization=return_order.organization,
                warehouse=return_order.warehouse,
                sku=line.sku,
                event_type=StockLedger.Type.RETURN,
                on_hand_delta=quantity,
                reference_type="return_receipt_line",
                reference_id=receipt_line.pk,
                idempotency_key=f"return:{idempotency_key}:{index}",
                actor=actor,
            )
        line.quantity_received += quantity
        line.save(update_fields=["quantity_received", "updated_at"])
    all_received = not return_order.lines.filter(
        quantity_received__lt=models.F("quantity_expected")
    ).exists()
    return_order.status = (
        ReturnOrder.Status.RECEIVED if all_received else ReturnOrder.Status.PARTIAL
    )
    return_order.received_at = receipt.received_at if all_received else None
    return_order.save(update_fields=["status", "received_at", "updated_at"])
    write_audit(
        organization=return_order.organization,
        actor=actor,
        action="return.receive",
        instance=receipt,
        after={"return_order": str(return_order.pk), "completed": all_received},
    )
    return return_order


@transaction.atomic
def reject_return(*, return_order, actor=None):
    return_order = ReturnOrder.objects.select_for_update().select_related(
        "organization", "warehouse", "original_order"
    ).get(pk=return_order.pk)
    _assert_organization(
        return_order.organization,
        warehouse=return_order.warehouse,
        original_order=return_order.original_order,
    )
    if return_order.status == ReturnOrder.Status.REJECTED:
        return return_order
    if return_order.status != ReturnOrder.Status.REQUESTED:
        raise ValidationError("只有尚未收货的退货单可以拒绝")
    return_order.status = ReturnOrder.Status.REJECTED
    return_order.save(update_fields=["status", "updated_at"])
    write_audit(
        organization=return_order.organization,
        actor=actor,
        action="return.reject",
        instance=return_order,
    )
    return return_order


@transaction.atomic
def create_quick_sales_snapshot(*, product, sold_count, captured_at=None, actor=None):
    """Create a snapshot by changing only cumulative sales and inheriting all other facts."""
    expected_organization = product.organization
    product = CompetitorProduct.objects.select_for_update().get(
        pk=product.pk, organization=expected_organization
    )
    latest = (
        CompetitorSnapshot.objects.select_for_update()
        .filter(product=product)
        .order_by("-captured_at", "-created_at")
        .first()
    )
    if latest is None:
        raise ValidationError("该竞品还没有历史快照，请先录入一条完整快照")
    captured_at = captured_at or timezone.now()
    if CompetitorSnapshot.objects.filter(product=product, captured_at=captured_at).exists():
        raise ValidationError("该竞品在此时间已经有快照")
    snapshot = CompetitorSnapshot.objects.create(
        product=product,
        captured_at=captured_at,
        price=latest.price,
        sold_count=sold_count,
        rating=latest.rating,
        review_count=latest.review_count,
        availability=latest.availability,
        raw=deepcopy(latest.raw),
    )
    write_audit(
        organization=product.organization,
        actor=actor,
        action="competitor_snapshot.quick_sales",
        instance=snapshot,
        after={
            "product": str(product.pk),
            "sold_count": sold_count,
            "inherited_from": str(latest.pk),
        },
    )
    return snapshot

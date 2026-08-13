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
    PurchaseShipment,
    PurchaseShipmentLine,
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
    StockLedgerReversal,
    StockReservation,
    StockTransfer,
    StockTransferLine,
    StockTransferPackage,
    StockTransferPackageLine,
)


class WorkflowValidationError(ValidationError):
    """A validation failure that the API can return without losing its facts."""

    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload.get("detail", "业务校验失败"))


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


def _unmapped_order_line_error(order, line):
    return WorkflowValidationError({
        "code": "sku_unmapped",
        "detail": "SKU 未映射，不能锁库/出库",
        "order_number": order.number,
        "external_sku_code": line.external_sku_code or "",
    })


def _order_lines_or_raise(order, *, lock=False):
    queryset = order.lines
    if lock:
        queryset = queryset.select_for_update()
    lines = list(queryset.select_related("sku__product").order_by("pk"))
    if not lines:
        raise ValidationError("订单没有明细")
    for line in lines:
        if line.sku_id is None:
            raise _unmapped_order_line_error(order, line)
        _assert_organization(order.organization, sku=line.sku, product=line.sku.product)
        if not line.sku.active or line.sku.product.status != line.sku.product.Status.ACTIVE:
            raise ValidationError(f"SKU {line.sku.code} 对应商品未启用")
    return lines


def _order_stock_shortages(order, warehouse, lines):
    """Lock every required balance and return the complete order shortage list."""
    shortages = []
    for line in lines:
        balance, _ = StockBalance.objects.select_for_update().get_or_create(
            organization=order.organization,
            warehouse=warehouse,
            sku=line.sku,
            defaults={"on_hand": Decimal("0"), "reserved": Decimal("0")},
        )
        required = Decimal(line.quantity) - Decimal(line.quantity_shipped) - Decimal(line.quantity_reserved)
        available = Decimal(balance.on_hand) - Decimal(balance.reserved)
        if required > 0 and available < required:
            shortages.append({
                "sku": line.sku.code,
                "external_sku_code": line.external_sku_code or "",
                "required": str(required),
                "available": str(max(Decimal("0"), available)),
                "shortage": str(required - max(Decimal("0"), available)),
            })
    return shortages


def _raise_order_shortages(order, shortages):
    if shortages:
        raise WorkflowValidationError({
            "code": "inventory_shortage",
            "detail": "库存不足，整单不能锁库/出库",
            "order_number": order.number,
            "shortages": shortages,
        })


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
    pending_delta=0, in_transit_delta=0, reference_type, reference_id, idempotency_key, actor=None, reason="",
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

    pending = balance.purchased_pending_shipment + _decimal(pending_delta)
    transit = balance.in_transit + _decimal(in_transit_delta)
    if pending < 0 or transit < 0:
        raise ValidationError("在途或待发货数量不足")
    balance.on_hand = new_on_hand
    balance.reserved = new_reserved
    balance.purchased_pending_shipment = pending
    balance.in_transit = transit
    balance.save(update_fields=["on_hand", "reserved", "purchased_pending_shipment", "in_transit", "updated_at"])
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
def reserve_stock_transfer_draft(*, transfer, actor=None):
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk)
    if transfer.status != StockTransfer.Status.DRAFT:
        raise ValidationError("只有草稿调拨可以预占库存")
    for line in transfer.lines.select_for_update().select_related("sku__product"):
        StockBalance.objects.select_for_update().get_or_create(
            organization=transfer.organization, warehouse=transfer.source_warehouse, sku=line.sku,
            defaults={"on_hand": Decimal("0"), "reserved": Decimal("0")},
        )
        post_stock(
            organization=transfer.organization, warehouse=transfer.source_warehouse, sku=line.sku,
            event_type=StockLedger.Type.RESERVE, reserved_delta=line.quantity,
            reference_type="stock_transfer_line", reference_id=line.pk,
            idempotency_key=f"transfer-reserve:{transfer.pk}:{line.pk}", actor=actor,
        )
    # Preserve legacy create-and-dispatch callers while still giving every
    # transfer a real package allocation (tracking is intentionally optional).
    if not StockTransferPackage.objects.filter(transfer=transfer).exists():
        package = StockTransferPackage.objects.create(organization=transfer.organization, transfer=transfer)
        StockTransferPackageLine.objects.bulk_create([
            StockTransferPackageLine(package=package, sku=line.sku, quantity=line.quantity)
            for line in transfer.lines.all()
        ])
    write_audit(organization=transfer.organization, actor=actor, action="stock_transfer.reserve", instance=transfer, after={"line_count": transfer.lines.count()})
    return transfer


@transaction.atomic
def save_stock_transfer_packages(*, transfer, packages, actor=None):
    """Replace a draft transfer's package allocation without moving stock."""
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk, organization=transfer.organization)
    if transfer.status != StockTransfer.Status.DRAFT:
        raise ValidationError("只有草稿调拨单可以修改物流包 SKU 数量。")
    transfer_lines = {
        line.sku_id: line
        for line in StockTransferLine.objects.select_for_update().filter(transfer=transfer)
    }
    if not transfer_lines or not packages:
        raise ValidationError("调拨单必须包含明细和至少一个物流包。")
    prepared = []
    for package_data in packages:
        lines = package_data.get("lines") or []
        if not lines:
            raise ValidationError("每个物流包至少需要一条 SKU 数量。")
        seen = set()
        for item in lines:
            sku = item["sku"]
            if sku.pk not in transfer_lines or sku.pk in seen:
                raise ValidationError("物流包 SKU 必须属于调拨单且不可重复。")
            seen.add(sku.pk)
        prepared.append((str(package_data.get("tracking_number") or "").strip(), lines))
    StockTransferPackage.objects.filter(transfer=transfer).delete()
    for tracking_number, lines in prepared:
        package = StockTransferPackage.objects.create(
            organization=transfer.organization, transfer=transfer, tracking_number=tracking_number
        )
        StockTransferPackageLine.objects.bulk_create([
            StockTransferPackageLine(package=package, sku=item["sku"], quantity=item["quantity"])
            for item in lines
        ])
    write_audit(organization=transfer.organization, actor=actor, action="stock_transfer.packages.save", instance=transfer, after={"package_count": len(prepared)})
    return transfer


@transaction.atomic
def update_stock_transfer_package_tracking(*, transfer, packages, actor=None):
    """Tracking can be backfilled after dispatch while package quantities stay immutable."""
    transfer = StockTransfer.objects.select_for_update().get(pk=transfer.pk, organization=transfer.organization)
    if transfer.status == StockTransfer.Status.DRAFT:
        raise ValidationError("草稿调拨请使用完整物流包编辑。")
    stored = {str(item.pk): item for item in StockTransferPackage.objects.select_for_update().filter(transfer=transfer)}
    for item in packages:
        package = stored.get(str(item.get("id") or ""))
        if package is None or item.get("lines"):
            raise ValidationError("发货后只能补录当前物流包的物流单号。")
        package.tracking_number = str(item.get("tracking_number") or "").strip()
        package.save(update_fields=["tracking_number", "updated_at"])
    write_audit(organization=transfer.organization, actor=actor, action="stock_transfer.packages.tracking_update", instance=transfer)
    return transfer


def _assert_transfer_package_allocation(transfer, lines):
    packages = list(StockTransferPackage.objects.select_for_update().filter(transfer=transfer).prefetch_related("lines"))
    if not packages:
        raise ValidationError("确认发货前必须配置至少一个物流包。")
    planned = {line.sku_id: Decimal(line.quantity) for line in lines}
    allocated = {sku_id: Decimal("0") for sku_id in planned}
    for package in packages:
        for package_line in package.lines.all():
            if package_line.sku_id not in allocated:
                raise ValidationError("物流包包含不属于调拨单的 SKU。")
            allocated[package_line.sku_id] += Decimal(package_line.quantity)
    if any(allocated[sku_id] != quantity for sku_id, quantity in planned.items()):
        raise ValidationError("发货前每个 SKU 的物流包数量之和必须与调拨计划完全一致。")
    return packages


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
    # Service callers from earlier releases may create a draft directly instead
    # of via the viewset pre-reservation hook.  Give those legacy drafts one
    # explicit blank-tracking package so dispatch still validates an exact
    # package allocation rather than silently bypassing the package rule.
    if not StockTransferPackage.objects.filter(transfer=transfer).exists():
        package = StockTransferPackage.objects.create(organization=transfer.organization, transfer=transfer)
        StockTransferPackageLine.objects.bulk_create([
            StockTransferPackageLine(package=package, sku=line.sku, quantity=line.quantity)
            for line in lines
        ])
    packages = _assert_transfer_package_allocation(transfer, lines)
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
        source_balance = StockBalance.objects.select_for_update().get(
            organization=transfer.organization, warehouse=transfer.source_warehouse, sku=line.sku
        )
        reserved_release = min(Decimal(line.quantity), Decimal(source_balance.reserved or 0))
        post_stock(
            organization=transfer.organization,
            warehouse=transfer.source_warehouse,
            sku=line.sku,
            event_type=StockLedger.Type.TRANSFER_OUT,
            on_hand_delta=-line.quantity,
            reserved_delta=-reserved_release,
            reference_type="stock_transfer_line",
            reference_id=line.pk,
            idempotency_key=f"transfer-out:{transfer.pk}:{line.pk}",
            actor=actor,
            reason=f"调拨至 {transfer.destination_warehouse.name}",
        )
    for line in lines:
        post_stock(
            organization=transfer.organization, warehouse=transfer.destination_warehouse, sku=line.sku,
            event_type=StockLedger.Type.TRANSFER_TRANSIT, in_transit_delta=line.quantity,
            reference_type="stock_transfer_line", reference_id=line.pk,
            idempotency_key=f"transfer-transit:{transfer.pk}:{line.pk}", actor=actor,
            reason=f"调拨自 {transfer.source_warehouse.name} 在途",
        )
    transfer.status = StockTransfer.Status.IN_TRANSIT
    transfer.dispatch_idempotency_key = idempotency_key
    transfer.dispatched_at = timezone.now()
    transfer.dispatched_by = actor if getattr(actor, "is_authenticated", False) else None
    transfer.save(update_fields=[
        "status", "dispatch_idempotency_key", "dispatched_at", "dispatched_by", "updated_at",
    ])
    for package in packages:
        package.confirmed_at = transfer.dispatched_at
        package.save(update_fields=["confirmed_at", "updated_at"])
    write_audit(
        organization=transfer.organization,
        actor=actor,
        action="stock_transfer.dispatch",
        instance=transfer,
        after={"idempotency_key": idempotency_key, "line_count": len(lines)},
    )
    return transfer


@transaction.atomic
def receive_stock_transfer(*, transfer, idempotency_key, quantities=None, actor=None):
    """Receive all or part of an in-transit transfer exactly once per request."""
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
    from .models import StockTransferReceipt

    existing_receipt = StockTransferReceipt.objects.filter(
        organization=transfer.organization, idempotency_key=idempotency_key
    ).first()
    if existing_receipt:
        if existing_receipt.transfer_id == transfer.pk:
            return transfer
        raise ValidationError("幂等键已被其他调拨收货占用")
    if transfer.status not in {StockTransfer.Status.IN_TRANSIT, StockTransfer.Status.PARTIALLY_RECEIVED}:
        raise ValidationError("只有调拨在途或部分收货单可以收货")
    if not transfer.destination_warehouse.active or not transfer.destination_warehouse.can_receive:
        raise ValidationError("目标仓未启用或不允许收货")
    lines = list(
        StockTransferLine.objects.select_for_update()
        .filter(transfer=transfer)
        .select_related("sku__product")
        .order_by("pk")
    )
    if not lines:
        raise ValidationError("调拨单没有明细")
    requested = {str(key): _decimal(value) for key, value in (quantities or {}).items()}
    if requested and not set(requested).issubset({str(line.pk) for line in lines}):
        raise ValidationError("收货数量包含不属于当前调拨单的 SKU 明细")
    received_event = {}
    for line in lines:
        _assert_organization(
            transfer.organization, sku=line.sku, product=line.sku.product
        )
        remaining = line.quantity - line.received_quantity - line.exception_closed_quantity
        if requested and str(line.pk) not in requested:
            continue
        quantity = requested.get(str(line.pk), remaining)
        if quantity <= 0 or quantity > remaining:
            raise ValidationError("收货数量必须大于 0 且不能超过在途数量")
        post_stock(
            organization=transfer.organization,
            warehouse=transfer.destination_warehouse,
            sku=line.sku,
            event_type=StockLedger.Type.TRANSFER_IN,
            on_hand_delta=quantity,
            in_transit_delta=-quantity,
            reference_type="stock_transfer_receipt",
            reference_id=line.pk,
            idempotency_key=f"transfer-in:{transfer.pk}:{line.pk}:{idempotency_key}",
            actor=actor,
            reason=f"从 {transfer.source_warehouse.name} 调拨收货",
        )
        line.received_quantity += quantity
        line.save(update_fields=["received_quantity", "updated_at"])
        received_event[str(line.pk)] = str(quantity)
    fully_settled = all(line.received_quantity + line.exception_closed_quantity >= line.quantity for line in lines)
    has_exception = any(line.exception_closed_quantity > 0 for line in lines)
    transfer.status = StockTransfer.Status.COMPLETED_WITH_EXCEPTION if fully_settled and has_exception else (StockTransfer.Status.RECEIVED if fully_settled else StockTransfer.Status.PARTIALLY_RECEIVED)
    if fully_settled:
        transfer.receive_idempotency_key = idempotency_key
        transfer.received_at = timezone.now()
        transfer.received_by = actor if getattr(actor, "is_authenticated", False) else None
    transfer.save(update_fields=[
        "status", "receive_idempotency_key", "received_at", "received_by", "updated_at",
    ])
    StockTransferReceipt.objects.create(
        organization=transfer.organization,
        transfer=transfer,
        idempotency_key=idempotency_key,
        quantities=received_event,
        received_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    write_audit(
        organization=transfer.organization,
        actor=actor,
        action="stock_transfer.receive",
        instance=transfer,
        after={"idempotency_key": idempotency_key, "quantities": received_event, "fully_settled": fully_settled},
    )
    return transfer


@transaction.atomic
def close_stock_transfer_exception(*, transfer, quantities, reason, actor=None):
    """Close lost/damaged transfer quantities at the destination without restoring source stock."""
    if not str(reason or "").strip():
        raise ValidationError("关闭调拨在途异常必须填写原因")
    transfer = StockTransfer.objects.select_for_update().select_related(
        "organization", "destination_warehouse"
    ).get(pk=transfer.pk, organization=transfer.organization)
    if transfer.status not in {StockTransfer.Status.IN_TRANSIT, StockTransfer.Status.PARTIALLY_RECEIVED}:
        raise ValidationError("只有在途调拨可以关闭异常")
    lines = {str(line.pk): line for line in StockTransferLine.objects.select_for_update().select_related("sku").filter(transfer=transfer)}
    if not quantities:
        raise ValidationError("至少需要一条调拨异常明细")
    for line_id, raw_quantity in quantities.items():
        line = lines.get(str(line_id))
        if line is None:
            raise ValidationError("异常明细不属于当前调拨单")
        quantity = _decimal(raw_quantity)
        remaining = Decimal(line.quantity) - Decimal(line.received_quantity) - Decimal(line.exception_closed_quantity)
        if quantity <= 0 or quantity > remaining:
            raise ValidationError(f"SKU {line.sku.code} 异常关闭数量超过在途剩余")
        post_stock(
            organization=transfer.organization, warehouse=transfer.destination_warehouse, sku=line.sku,
            event_type=StockLedger.Type.TRANSFER_TRANSIT, in_transit_delta=-quantity,
            reference_type="stock_transfer_line", reference_id=line.pk,
            idempotency_key=f"transfer-exception-close:{transfer.pk}:{line.pk}:{line.received_quantity}", actor=actor,
            reason=reason,
        )
        line.exception_closed_quantity += quantity
        line.save(update_fields=["exception_closed_quantity", "updated_at"])
    settled_lines = list(StockTransferLine.objects.select_for_update().filter(transfer=transfer))
    fully_settled = all(line.received_quantity + line.exception_closed_quantity >= line.quantity for line in settled_lines)
    transfer.status = StockTransfer.Status.COMPLETED_WITH_EXCEPTION if fully_settled else StockTransfer.Status.PARTIALLY_RECEIVED
    transfer.exception_reason = reason
    transfer.save(update_fields=["status", "exception_reason", "updated_at"])
    write_audit(organization=transfer.organization, actor=actor, action="stock_transfer.transit.exception_close", instance=transfer, after={"reason": reason, "quantities": {str(key): str(value) for key, value in quantities.items()}})
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
    if transfer.status in {StockTransfer.Status.RECEIVED, StockTransfer.Status.PARTIALLY_RECEIVED, StockTransfer.Status.IN_TRANSIT}:
        raise ValidationError("已收货调拨单不能取消")
    if transfer.status not in {
        StockTransfer.Status.DRAFT,
    }:
        raise ValidationError("当前调拨状态不能取消")
    restored = False
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
    if transfer.status == StockTransfer.Status.DRAFT:
        for line in transfer.lines.select_for_update().select_related("sku"):
            post_stock(
                organization=transfer.organization, warehouse=transfer.source_warehouse, sku=line.sku,
                event_type=StockLedger.Type.RELEASE, reserved_delta=-line.quantity,
                reference_type="stock_transfer_line", reference_id=line.pk,
                idempotency_key=f"transfer-release:{transfer.pk}:{line.pk}", actor=actor,
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
def manual_stock_movement(*, organization, warehouse, sku, quantity, direction, reason="", idempotency_key, actor=None):
    """Post an auditable manual inbound/outbound movement without allowing negative stock."""
    if direction not in {"inbound", "outbound"}:
        raise ValidationError("手动库存操作方向无效")
    quantity = _decimal(quantity)
    if quantity <= 0:
        raise ValidationError("手动出入库数量必须大于 0")
    _validate_warehouse_and_sku(organization, warehouse, sku)
    if direction == "outbound" and not warehouse.can_ship:
        raise ValidationError("当前仓库未开放出库")
    if direction == "inbound" and not warehouse.can_receive:
        raise ValidationError("当前仓库未开放收货")
    event_type = StockLedger.Type.MANUAL_INBOUND if direction == "inbound" else StockLedger.Type.MANUAL_OUTBOUND
    delta = quantity if direction == "inbound" else -quantity
    key = f"manual-{direction}:{idempotency_key}"
    existing = StockLedger.objects.filter(organization=organization, idempotency_key=key).first()
    if existing:
        return _assert_ledger_replay(
            existing, warehouse=warehouse, sku=sku, event_type=event_type, on_hand_delta=delta,
            reserved_delta=0, reference_type="manual_stock_movement", reference_id=idempotency_key,
        )
    ledger = post_stock(
        organization=organization, warehouse=warehouse, sku=sku, event_type=event_type,
        on_hand_delta=delta, reference_type="manual_stock_movement", reference_id=idempotency_key,
        idempotency_key=key, actor=actor, reason=reason or "",
    )
    write_audit(
        organization=organization, actor=actor, action=f"inventory.manual_{direction}", instance=ledger,
        after={"quantity": str(quantity), "reason": reason or ""},
    )
    return ledger


@transaction.atomic
def reverse_stock_ledger(*, organization, ledger, reason="", actor=None):
    """Reverse eligible manual adjustments while retaining both immutable ledger entries."""
    ledger = StockLedger.objects.select_for_update().select_related("warehouse", "sku").get(
        pk=ledger.pk, organization=organization
    )
    if ledger.event_type not in {
        StockLedger.Type.ADJUSTMENT,
        StockLedger.Type.MANUAL_INBOUND,
        StockLedger.Type.MANUAL_OUTBOUND,
    }:
        raise ValidationError("只有手动入库、手动出库或库存调整流水可直接撤回；采购收货和订单出库请通过原业务单据处理")
    if StockLedgerReversal.objects.filter(original_ledger=ledger).exists():
        raise ValidationError("该库存流水已撤回，不能重复操作")
    reverse_key = f"ledger-reversal:{ledger.pk}"
    reversal_ledger = post_stock(
        organization=organization, warehouse=ledger.warehouse, sku=ledger.sku,
        event_type=StockLedger.Type.REVERSAL, on_hand_delta=-ledger.on_hand_delta,
        reserved_delta=-ledger.reserved_delta, reference_type="stock_ledger_reversal", reference_id=ledger.pk,
        idempotency_key=reverse_key, actor=actor, reason=reason or f"撤回流水 {ledger.pk}",
    )
    reversal = StockLedgerReversal.objects.create(
        original_ledger=ledger, reversal_ledger=reversal_ledger, reason=reason or "",
        reversed_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    write_audit(
        organization=organization, actor=actor, action="inventory.ledger_reverse", instance=reversal,
        before={"ledger": str(ledger.pk), "on_hand_delta": str(ledger.on_hand_delta)},
        after={"reversal_ledger": str(reversal_ledger.pk), "reason": reason or ""},
    )
    return reversal


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
        pending = max(Decimal("0"), Decimal(line.quantity_ordered) - Decimal(line.quantity_received or 0))
        if pending:
            post_stock(
                organization=purchase_order.organization, warehouse=purchase_order.warehouse, sku=line.sku,
                event_type=StockLedger.Type.PURCHASE_PENDING, pending_delta=pending,
                reference_type="purchase_order_line", reference_id=line.pk,
                idempotency_key=f"purchase-pending:{purchase_order.pk}:{line.pk}", actor=actor,
                reason="采购提交，待发货",
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
    # A submitted purchase contributes to one of two inventory stages:
    # unconfirmed quantity is pending shipment, while confirmed packages are
    # in transit.  Cancelling the remaining purchase must close both stages;
    # changing only the PO status leaves stale quantities in StockBalance.
    if purchase_order.status in {PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIAL}:
        lines = list(
            PurchaseOrderLine.objects.select_for_update()
            .select_related("sku")
            .filter(purchase_order=purchase_order)
        )
        for line in lines:
            confirmed_lines = list(
                PurchaseShipmentLine.objects.select_for_update()
                .select_related("purchase_shipment")
                .filter(
                    purchase_line=line,
                    purchase_shipment__confirmed_at__isnull=False,
                )
            )
            confirmed_total = sum(
                (Decimal(item.quantity_shipped) for item in confirmed_lines),
                Decimal("0"),
            )
            direct_received = (
                ReceiptLine.objects.filter(
                    purchase_line=line,
                    receipt__status=Receipt.Status.COMPLETED,
                ).filter(
                    models.Q(receipt__purchase_shipment__isnull=True)
                    | models.Q(receipt__purchase_shipment__confirmed_at__isnull=True)
                ).aggregate(total=models.Sum("quantity"))["total"]
                or Decimal("0")
            )
            pending_remaining = max(
                Decimal("0"),
                Decimal(line.quantity_ordered)
                - Decimal(line.quantity_unshipped_closed)
                - confirmed_total
                - Decimal(direct_received),
            )
            if pending_remaining:
                post_stock(
                    organization=purchase_order.organization,
                    warehouse=purchase_order.warehouse,
                    sku=line.sku,
                    event_type=StockLedger.Type.PURCHASE_PENDING,
                    pending_delta=-pending_remaining,
                    reference_type="purchase_order_line",
                    reference_id=line.pk,
                    idempotency_key=f"purchase-cancel-pending:{purchase_order.pk}:{line.pk}",
                    actor=actor,
                    reason="取消采购单，关闭未发货数量",
                )
                line.quantity_unshipped_closed += pending_remaining
                line.save(update_fields=["quantity_unshipped_closed", "updated_at"])

            for shipment_line in confirmed_lines:
                received = (
                    ReceiptLine.objects.filter(
                        purchase_line=line,
                        receipt__status=Receipt.Status.COMPLETED,
                        receipt__purchase_shipment=shipment_line.purchase_shipment,
                    ).aggregate(total=models.Sum("quantity"))["total"]
                    or Decimal("0")
                )
                transit_remaining = max(
                    Decimal("0"),
                    Decimal(shipment_line.quantity_shipped)
                    - Decimal(shipment_line.quantity_exception_closed)
                    - Decimal(received),
                )
                if not transit_remaining:
                    continue
                post_stock(
                    organization=purchase_order.organization,
                    warehouse=purchase_order.warehouse,
                    sku=line.sku,
                    event_type=StockLedger.Type.PURCHASE_TRANSIT,
                    in_transit_delta=-transit_remaining,
                    reference_type="purchase_shipment_line",
                    reference_id=shipment_line.pk,
                    idempotency_key=f"purchase-cancel-transit:{purchase_order.pk}:{shipment_line.pk}",
                    actor=actor,
                    reason="取消采购单，关闭采购在途数量",
                )
                shipment_line.quantity_exception_closed += transit_remaining
                shipment_line.save(update_fields=["quantity_exception_closed", "updated_at"])

        purchase_order.shipments.filter(
            confirmed_at__isnull=False,
            closed_at__isnull=True,
        ).update(
            closed_at=timezone.now(),
            closed_reason="采购单已取消",
            updated_at=timezone.now(),
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


def _purchase_audit_snapshot(purchase_order):
    return {
        "number": purchase_order.number,
        "supplier_id": str(purchase_order.supplier_id),
        "warehouse_id": str(purchase_order.warehouse_id),
        "purchaser_id": str(purchase_order.purchaser_id) if purchase_order.purchaser_id else None,
        "expected_at": purchase_order.expected_at.isoformat() if purchase_order.expected_at else None,
        "extra_cost": str(purchase_order.extra_cost),
        "lines": [
            {
                "sku": line.sku.code,
                "ordered": str(line.quantity_ordered),
                "received": str(line.quantity_received),
                "cost": str(line.unit_cost),
            }
            for line in purchase_order.lines.select_related("sku").order_by("created_at", "id")
        ],
        "shipments": [
            {
                "id": str(shipment.pk),
                "tracking_number": shipment.tracking_number,
                "lines": [
                    {"sku": item.purchase_line.sku.code, "quantity": str(item.quantity_shipped)}
                    for item in shipment.lines.select_related("purchase_line__sku").order_by("created_at", "id")
                ],
            }
            for shipment in purchase_order.shipments.prefetch_related("lines__purchase_line__sku").order_by("created_at", "id")
        ],
    }


def purchase_order_for_update_queryset():
    """Lock only the purchase order and its non-nullable joins.

    PostgreSQL rejects ``FOR UPDATE`` when Django adds a LEFT OUTER JOIN for the
    nullable purchaser relation.  Keeping that relation out of this locking
    query preserves the row lock without attempting to lock the nullable side
    of an outer join.
    """
    return PurchaseOrder.objects.select_for_update().select_related(
        "organization", "supplier", "warehouse"
    )


@transaction.atomic
def edit_purchase(*, purchase_order, data, actor=None):
    """Edit only the unreceived part of an open purchase order.

    Receipt rows and stock ledgers are never changed here.  The guards make
    changes safe even when an operator edits a partially received PO.
    """
    purchase_order = purchase_order_for_update_queryset().get(pk=purchase_order.pk)
    if purchase_order.status not in {
        PurchaseOrder.Status.DRAFT,
        PurchaseOrder.Status.SUBMITTED,
        PurchaseOrder.Status.PARTIAL,
    }:
        raise ValidationError("只有草稿、已下单或部分收货的采购单可以编辑。")
    before = _purchase_audit_snapshot(purchase_order)
    organization = purchase_order.organization
    for key in ("supplier", "warehouse", "purchaser"):
        value = data.get(key)
        if value is not None:
            _assert_organization(organization, **{key: value}) if key != "purchaser" else None
    if data.get("warehouse") and data["warehouse"].pk != purchase_order.warehouse_id and purchase_order.receipts.exists():
        raise ValidationError("已有收货记录，不能修改收货仓库。")

    for field in ("number", "supplier", "warehouse", "purchaser", "currency", "extra_cost", "ordered_at", "expected_at", "notes"):
        if field in data and (data[field] is not None or field in {"purchaser", "ordered_at", "expected_at"}):
            setattr(purchase_order, field, data[field])

    existing_lines = {
        str(line.sku_id): line
        for line in PurchaseOrderLine.objects.select_for_update().select_related("sku").filter(purchase_order=purchase_order)
    }
    desired_skus = set()
    for item in data["lines"]:
        sku = item["sku"]
        _assert_organization(organization, sku=sku, product=sku.product)
        desired_skus.add(str(sku.pk))
        line = existing_lines.get(str(sku.pk))
        ordered = _decimal(item["quantity_ordered"])
        if line:
            if ordered < line.quantity_received:
                raise ValidationError(f"SKU {sku.code} 的采购数量不能低于已收货数量。")
            line.quantity_ordered = ordered
            line.unit_cost = _decimal(item["unit_cost"])
            line.save(update_fields=["quantity_ordered", "unit_cost", "updated_at"])
        else:
            PurchaseOrderLine.objects.create(
                purchase_order=purchase_order,
                sku=sku,
                quantity_ordered=ordered,
                unit_cost=_decimal(item["unit_cost"]),
            )
    for sku_id, line in existing_lines.items():
        if sku_id not in desired_skus:
            if line.quantity_received > 0 or line.shipment_lines.exists():
                raise ValidationError(f"SKU {line.sku.code} 已有关联收货或物流包裹，不能从采购单移除。")
            line.delete()

    lines_by_sku = {
        str(line.sku_id): line
        for line in PurchaseOrderLine.objects.select_for_update().select_related("sku").filter(purchase_order=purchase_order)
    }
    existing_shipments = {
        str(shipment.pk): shipment
        for shipment in PurchaseShipment.objects.select_for_update().filter(purchase_order=purchase_order)
    }
    desired_shipment_ids = set()
    for shipment_data in data.get("shipments", []):
        shipment = existing_shipments.get(str(shipment_data.get("id", "")))
        if shipment is None:
            shipment = PurchaseShipment.objects.filter(
                purchase_order=purchase_order,
                tracking_number=shipment_data["tracking_number"].strip(),
            ).first()
        if shipment is None:
            shipment = PurchaseShipment.objects.create(
                purchase_order=purchase_order,
                tracking_number=shipment_data["tracking_number"].strip(),
            )
        else:
            shipment.tracking_number = shipment_data["tracking_number"].strip()
            shipment.save(update_fields=["tracking_number", "updated_at"])
        desired_shipment_ids.add(str(shipment.pk))
        shipment_lines = {
            str(item.purchase_line.sku_id): item
            for item in PurchaseShipmentLine.objects.select_for_update().select_related("purchase_line").filter(purchase_shipment=shipment)
        }
        desired_shipment_skus = set()
        for item in shipment_data.get("lines", []):
            sku_id = str(item["sku"].pk)
            line = lines_by_sku.get(sku_id)
            if line is None:
                raise ValidationError("物流包裹含有不属于采购单的 SKU。")
            desired_shipment_skus.add(sku_id)
            allocation = _decimal(item["quantity_shipped"])
            receipt_quantity = sum(
                (receipt_line.quantity for receipt in shipment.receipts.all() for receipt_line in receipt.lines.filter(purchase_line=line)),
                Decimal("0"),
            )
            if allocation < receipt_quantity:
                raise ValidationError(f"物流单 {shipment.tracking_number} 的 {line.sku.code} 不能低于该包裹已收货数量。")
            ship_line = shipment_lines.get(sku_id)
            if ship_line:
                ship_line.quantity_shipped = allocation
                ship_line.save(update_fields=["quantity_shipped", "updated_at"])
            else:
                PurchaseShipmentLine.objects.create(
                    purchase_shipment=shipment, purchase_line=line, quantity_shipped=allocation
                )
        for sku_id, ship_line in shipment_lines.items():
            if sku_id not in desired_shipment_skus:
                if shipment.receipts.filter(lines__purchase_line=ship_line.purchase_line).exists():
                    raise ValidationError("已收货的物流包裹明细不能删除。")
                ship_line.delete()
    for shipment_id, shipment in existing_shipments.items():
        if shipment_id not in desired_shipment_ids:
            if shipment.receipts.exists():
                continue  # preserve received package history even if it is omitted from an edit form
            shipment.delete()

    for line in PurchaseOrderLine.objects.select_for_update().filter(purchase_order=purchase_order):
        assigned = sum(
            PurchaseShipmentLine.objects.filter(purchase_line=line).values_list("quantity_shipped", flat=True), Decimal("0")
        )
        if assigned > line.quantity_ordered:
            raise ValidationError(f"SKU {line.sku.code} 的所有物流包裹数量不能超过采购数量。")
    purchase_order.save()
    write_audit(
        organization=organization,
        actor=actor,
        action="purchase.edit",
        instance=purchase_order,
        before=before,
        after=_purchase_audit_snapshot(purchase_order),
    )
    return purchase_order


@transaction.atomic
def confirm_purchase_shipment(*, purchase_shipment, actor=None):
    """Confirm one editable purchase batch and move only its quantities to transit."""
    purchase_shipment = PurchaseShipment.objects.select_for_update().select_related(
        "purchase_order__organization", "purchase_order__warehouse"
    ).get(pk=purchase_shipment.pk)
    purchase_order = PurchaseOrder.objects.select_for_update().get(pk=purchase_shipment.purchase_order_id)
    if purchase_shipment.confirmed_at is not None:
        return purchase_shipment
    if purchase_order.status not in {PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIAL}:
        raise ValidationError("只有已提交采购单可以确认本批发货")
    lines = list(PurchaseShipmentLine.objects.select_for_update().select_related("purchase_line__sku__product").filter(
        purchase_shipment=purchase_shipment
    ))
    if not lines:
        raise ValidationError("发货批次必须至少包含一个 SKU")
    for shipment_line in lines:
        purchase_line = shipment_line.purchase_line
        already_confirmed = PurchaseShipmentLine.objects.filter(
            purchase_line=purchase_line, purchase_shipment__confirmed_at__isnull=False,
        ).aggregate(total=models.Sum("quantity_shipped"))["total"] or Decimal("0")
        remaining = Decimal(purchase_line.quantity_ordered) - Decimal(purchase_line.quantity_unshipped_closed) - Decimal(already_confirmed)
        if shipment_line.quantity_shipped <= 0 or shipment_line.quantity_shipped > remaining:
            raise ValidationError(f"SKU {purchase_line.sku.code} 本批发货数量超过未发货数量")
        post_stock(
            organization=purchase_order.organization, warehouse=purchase_order.warehouse, sku=purchase_line.sku,
            event_type=StockLedger.Type.PURCHASE_TRANSIT,
            pending_delta=-shipment_line.quantity_shipped, in_transit_delta=shipment_line.quantity_shipped,
            reference_type="purchase_shipment_line", reference_id=shipment_line.pk,
            idempotency_key=f"purchase-shipment-confirm:{purchase_shipment.pk}:{shipment_line.pk}", actor=actor,
            reason="确认采购发货批次",
        )
    purchase_shipment.confirmed_at = timezone.now()
    purchase_shipment.confirmed_by = actor if getattr(actor, "is_authenticated", False) else None
    purchase_shipment.save(update_fields=["confirmed_at", "confirmed_by", "updated_at"])
    write_audit(
        organization=purchase_order.organization, actor=actor, action="purchase.shipment.confirm",
        instance=purchase_shipment, after={"purchase_order": str(purchase_order.pk), "line_count": len(lines)},
    )
    return purchase_shipment


@transaction.atomic
def close_purchase_unshipped(*, purchase_order, quantities, reason, actor=None):
    purchase_order = PurchaseOrder.objects.select_for_update().select_related("organization", "warehouse").get(pk=purchase_order.pk)
    if purchase_order.status not in {PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIAL}:
        raise ValidationError("只有已提交采购单可以关闭未发货数量")
    if not str(reason or "").strip():
        raise ValidationError("关闭未发货数量必须填写原因")
    for item in quantities:
        line = PurchaseOrderLine.objects.select_for_update().select_related("sku").get(
            pk=item["purchase_line"].pk, purchase_order=purchase_order
        )
        confirmed = PurchaseShipmentLine.objects.filter(
            purchase_line=line, purchase_shipment__confirmed_at__isnull=False,
        ).aggregate(total=models.Sum("quantity_shipped"))["total"] or Decimal("0")
        quantity = _decimal(item["quantity"])
        remaining = Decimal(line.quantity_ordered) - Decimal(confirmed) - Decimal(line.quantity_unshipped_closed)
        if quantity <= 0 or quantity > remaining:
            raise ValidationError(f"SKU {line.sku.code} 关闭数量超过未发货数量")
        post_stock(
            organization=purchase_order.organization, warehouse=purchase_order.warehouse, sku=line.sku,
            event_type=StockLedger.Type.PURCHASE_PENDING, pending_delta=-quantity,
            reference_type="purchase_order_line", reference_id=line.pk,
            idempotency_key=f"purchase-unshipped-close:{purchase_order.pk}:{line.pk}:{line.quantity_unshipped_closed}", actor=actor,
            reason=reason,
        )
        line.quantity_unshipped_closed += quantity
        line.save(update_fields=["quantity_unshipped_closed", "updated_at"])
    write_audit(organization=purchase_order.organization, actor=actor, action="purchase.unshipped.close", instance=purchase_order, after={"reason": reason})
    return purchase_order


@transaction.atomic
def close_purchase_transit_exception(*, purchase_shipment, quantities, reason, actor=None):
    purchase_shipment = PurchaseShipment.objects.select_for_update().select_related("purchase_order__organization", "purchase_order__warehouse").get(pk=purchase_shipment.pk)
    if purchase_shipment.confirmed_at is None:
        raise ValidationError("未确认发货批次不能关闭在途异常")
    if not str(reason or "").strip():
        raise ValidationError("关闭在途异常必须填写原因")
    lines = {str(line.purchase_line_id): line for line in PurchaseShipmentLine.objects.select_for_update().select_related("purchase_line__sku").filter(purchase_shipment=purchase_shipment)}
    for item in quantities:
        shipment_line = lines.get(str(item["purchase_line"].pk))
        if shipment_line is None:
            raise ValidationError("异常 SKU 不属于当前发货批次")
        received = sum((receipt_line.quantity for receipt in purchase_shipment.receipts.all() for receipt_line in receipt.lines.filter(purchase_line=shipment_line.purchase_line)), Decimal("0"))
        quantity = _decimal(item["quantity"])
        remaining = Decimal(shipment_line.quantity_shipped) - received - Decimal(shipment_line.quantity_exception_closed)
        if quantity <= 0 or quantity > remaining:
            raise ValidationError(f"SKU {shipment_line.purchase_line.sku.code} 异常关闭数量超过在途剩余")
        post_stock(
            organization=purchase_shipment.purchase_order.organization, warehouse=purchase_shipment.purchase_order.warehouse, sku=shipment_line.purchase_line.sku,
            event_type=StockLedger.Type.PURCHASE_TRANSIT, in_transit_delta=-quantity,
            reference_type="purchase_shipment_line", reference_id=shipment_line.pk,
            idempotency_key=f"purchase-transit-close:{purchase_shipment.pk}:{shipment_line.pk}:{shipment_line.quantity_exception_closed}", actor=actor,
            reason=reason,
        )
        shipment_line.quantity_exception_closed += quantity
        shipment_line.save(update_fields=["quantity_exception_closed", "updated_at"])
    purchase_shipment.closed_at = timezone.now()
    purchase_shipment.closed_reason = reason
    purchase_shipment.save(update_fields=["closed_at", "closed_reason", "updated_at"])
    write_audit(organization=purchase_shipment.purchase_order.organization, actor=actor, action="purchase.transit.exception_close", instance=purchase_shipment, after={"reason": reason})
    return purchase_shipment


@transaction.atomic
def receive_purchase(*, organization, purchase_order, number, lines, idempotency_key, purchase_shipment=None, actor=None):
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
        if existing.purchase_shipment_id != (purchase_shipment.pk if purchase_shipment else None):
            raise ValidationError("幂等键对应的物流单号不一致")
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
    if purchase_shipment is not None:
        if purchase_shipment.purchase_order_id != purchase_order.pk:
            raise ValidationError("物流单号不属于当前采购单。")
        purchase_shipment = PurchaseShipment.objects.select_for_update().get(pk=purchase_shipment.pk)

    receipt = Receipt.objects.create(
        organization=organization,
        number=number,
        purchase_order=purchase_order,
        purchase_shipment=purchase_shipment,
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
        if purchase_shipment is not None:
            shipment_allocations = PurchaseShipmentLine.objects.filter(
                purchase_shipment=purchase_shipment,
            )
            allocated = shipment_allocations.filter(
                purchase_line=purchase_line,
            ).values_list("quantity_shipped", flat=True).first()
            if shipment_allocations.exists() and allocated is None:
                raise ValidationError(f"SKU {purchase_line.sku.code} 未分配到该物流单号，不能在此包裹收货")
            if allocated is not None:
                received_in_package = sum(
                    (line.quantity for receipt in purchase_shipment.receipts.exclude(pk=receipt.pk) for line in receipt.lines.filter(purchase_line=purchase_line)),
                    Decimal("0"),
                )
                if quantity > allocated - received_in_package:
                    raise ValidationError(f"SKU {purchase_line.sku.code} 的本次收货超过该物流单的已分配数量。")
        receipt_line = ReceiptLine.objects.create(
            receipt=receipt,
            purchase_line=purchase_line,
            sku=purchase_line.sku,
            quantity=quantity,
            unit_cost=unit_cost,
        )
        balance = StockBalance.objects.select_for_update().filter(
            organization=organization,
            warehouse=purchase_order.warehouse,
            sku=purchase_line.sku,
        ).first()
        pending_release = Decimal("0")
        transit_release = Decimal("0")
        if balance is not None:
            if purchase_shipment is not None and purchase_shipment.confirmed_at is not None:
                transit_release = min(quantity, Decimal(balance.in_transit or 0))
            else:
                pending_release = min(quantity, Decimal(balance.purchased_pending_shipment or 0))
        post_stock(
            organization=organization,
            warehouse=purchase_order.warehouse,
            sku=purchase_line.sku,
            event_type=StockLedger.Type.RECEIPT,
            on_hand_delta=quantity,
            pending_delta=-pending_release,
            in_transit_delta=-transit_release,
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
    if order.warehouse_id is None:
        raise ValidationError("订单出库前必须人工指定仓库")
    _assert_organization(order.organization, warehouse=order.warehouse)
    if not order.warehouse.active or not order.warehouse.can_ship:
        raise ValidationError("订单仓库未启用或不允许出库")
    if order.status == SalesOrder.Status.READY:
        return order
    if order.status != SalesOrder.Status.DRAFT:
        raise ValidationError("只有草稿订单可以确认")
    _order_lines_or_raise(order, lock=True)
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

    lines = list(SalesOrderLine.objects.select_for_update().filter(order=order).order_by("pk"))
    reservations = list(
        StockReservation.objects.select_for_update()
        .filter(order_line__order=order, status=StockReservation.Status.ACTIVE)
        .select_related("order_line", "sku__product", "warehouse")
        .order_by("pk")
    )
    reserved_by_line = {
        line.pk: sum(
            (reservation.quantity for reservation in reservations if reservation.order_line_id == line.pk),
            Decimal("0"),
        )
        for line in lines
    }
    inconsistent = [
        {
            "order_line": str(line.pk),
            "sku": line.sku.code if line.sku_id else line.external_sku_code,
            "line_reserved": str(line.quantity_reserved),
            "active_reservations": str(reserved_by_line[line.pk]),
        }
        for line in lines
        if Decimal(line.quantity_reserved) != reserved_by_line[line.pk]
    ]
    for reservation in reservations:
        if (
            reservation.order_line.order_id != order.pk
            or reservation.sku_id != reservation.order_line.sku_id
            or reservation.warehouse_id != order.warehouse_id
        ):
            inconsistent.append({
                "reservation": str(reservation.pk),
                "detail": "锁库记录的订单行、SKU 或仓库与订单不一致",
            })
    if inconsistent:
        raise WorkflowValidationError({
            "code": "reservation_inconsistent",
            "detail": "订单锁库数据不一致，已停止取消且未改动库存，请按诊断明细排查",
            "order_number": order.number,
            "inconsistencies": inconsistent,
        })

    for reservation in reservations:
        _validate_warehouse_and_sku(order.organization, reservation.warehouse, reservation.sku)
        line = reservation.order_line
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
    order.fulfillment_override = "erp_cancelled"
    order.erp_cancelled_at = timezone.now()
    order.erp_cancelled_by = actor if getattr(actor, "is_authenticated", False) else None
    order.save(update_fields=["status", "fulfillment_override", "erp_cancelled_at", "erp_cancelled_by", "updated_at"])
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
    if order.warehouse_id is None:
        raise ValidationError("请先人工选择仓库后再锁定库存")
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
    lines = _order_lines_or_raise(order, lock=True)
    if order.status != SalesOrder.Status.READY:
        raise ValidationError("只有待锁库订单可以锁定库存")
    _raise_order_shortages(order, _order_stock_shortages(order, order.warehouse, lines))

    for line in lines:
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
def confirm_and_ship_or_shortage(
    *, order, idempotency_key, number="", tracking_number="", actor=None
):
    """Ship a complete order or keep the untouched draft with shortage facts."""
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    expected_organization = order.organization
    order = SalesOrder.objects.select_for_update().select_related(
        "organization", "warehouse"
    ).get(pk=order.pk, organization=expected_organization)
    if order.warehouse_id is None:
        raise ValidationError("订单出库前必须指定仓库")
    existing = Shipment.objects.filter(
        organization=order.organization, idempotency_key=idempotency_key
    ).first()
    if existing:
        if existing.order_id != order.pk:
            raise ValidationError("幂等键已被其他订单的出库操作占用")
        return order, existing, []
    lines = _order_lines_or_raise(order, lock=True)
    shortages = _order_stock_shortages(order, order.warehouse, lines)
    if shortages:
        return order, None, shortages
    shipment = confirm_and_ship_order(
        order=order,
        idempotency_key=idempotency_key,
        number=number,
        tracking_number=tracking_number,
        actor=actor,
    )
    order.refresh_from_db()
    return order, shipment, []


@transaction.atomic
def restore_order_fulfillment(*, order, actor=None):
    """Re-enable ERP fulfilment without recreating a prior warehouse reservation."""
    order = SalesOrder.objects.select_for_update().get(pk=order.pk, organization=order.organization)
    if order.status != SalesOrder.Status.CANCELLED or order.fulfillment_override != "erp_cancelled":
        raise ValidationError("只有 ERP 人工取消的订单可以恢复履约。")
    if StockReservation.objects.filter(order_line__order=order, status=StockReservation.Status.ACTIVE).exists():
        raise ValidationError("恢复履约前订单不应存在有效锁库记录，请先排查历史库存数据。")
    order.status = SalesOrder.Status.READY
    order.warehouse = None
    order.fulfillment_override = "normal"
    order.save(update_fields=["status", "warehouse", "fulfillment_override", "updated_at"])
    write_audit(organization=order.organization, actor=actor, action="order.fulfillment.restore", instance=order)
    return order


@transaction.atomic
def assign_order_warehouse(*, order, warehouse, idempotency_key, actor=None):
    """Select a warehouse and reserve the entire order in one all-or-nothing step."""
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    organization = order.organization
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(
        pk=order.pk, organization=organization
    )
    _assert_organization(order.organization, warehouse=warehouse)
    if not warehouse.active or not warehouse.can_ship:
        raise ValidationError("所选仓库未启用或不允许出库")
    if order.status in {SalesOrder.Status.SHIPPED, SalesOrder.Status.CANCELLED, SalesOrder.Status.PICKING, SalesOrder.Status.VERIFIED}:
        raise ValidationError("当前订单状态不能选择仓库")
    if order.status == SalesOrder.Status.ALLOCATED:
        if order.warehouse_id == warehouse.pk:
            return order
        raise ValidationError("已锁库订单请使用更换仓库")
    lines = _order_lines_or_raise(order, lock=True)
    _raise_order_shortages(order, _order_stock_shortages(order, warehouse, lines))
    order.warehouse = warehouse
    if order.status == SalesOrder.Status.DRAFT:
        order.status = SalesOrder.Status.READY
    order.save(update_fields=["warehouse", "status", "updated_at"])
    # Allocation is deliberately performed only after every line is proven available.
    order = allocate_order(order=order, idempotency_key=idempotency_key, actor=actor)
    write_audit(
        organization=order.organization, actor=actor, action="order.warehouse.assign", instance=order,
        after={"warehouse": str(warehouse.pk), "idempotency_key": idempotency_key},
    )
    return order


@transaction.atomic
def change_order_warehouse(*, order, warehouse, idempotency_key, actor=None):
    """Move an active order reservation without ever leaving it half-reserved."""
    if not idempotency_key:
        raise ValidationError("幂等键不能为空")
    organization = order.organization
    order = SalesOrder.objects.select_for_update().select_related("organization", "warehouse").get(
        pk=order.pk, organization=organization
    )
    _assert_organization(order.organization, warehouse=warehouse)
    if Shipment.objects.filter(order=order).exists() or order.status in {SalesOrder.Status.SHIPPED, SalesOrder.Status.PICKING, SalesOrder.Status.VERIFIED}:
        raise ValidationError("订单已进入拣货或已出库，不能更换仓库")
    if order.warehouse_id is None:
        return assign_order_warehouse(order=order, warehouse=warehouse, idempotency_key=idempotency_key, actor=actor)
    if order.warehouse_id == warehouse.pk:
        return order
    if order.status != SalesOrder.Status.ALLOCATED:
        return assign_order_warehouse(order=order, warehouse=warehouse, idempotency_key=idempotency_key, actor=actor)
    if not warehouse.active or not warehouse.can_ship:
        raise ValidationError("所选仓库未启用或不允许出库")
    lines = _order_lines_or_raise(order, lock=True)
    # Validate and lock the destination before touching the original reservation.
    _raise_order_shortages(order, _order_stock_shortages(order, warehouse, lines))
    reservations = list(StockReservation.objects.select_for_update().filter(
        order_line__order=order, status=StockReservation.Status.ACTIVE
    ).select_related("order_line", "sku"))
    if len(reservations) != len([line for line in lines if line.quantity_reserved > 0]):
        raise ValidationError("订单缺少有效锁库记录")
    for reservation in reservations:
        post_stock(
            organization=order.organization, warehouse=reservation.warehouse, sku=reservation.sku,
            event_type=StockLedger.Type.RELEASE, reserved_delta=-reservation.quantity,
            reference_type="stock_reservation", reference_id=reservation.pk,
            idempotency_key=f"order-change-release:{idempotency_key}:{reservation.pk}", actor=actor,
            reason="更换订单出库仓释放旧锁库",
        )
        reservation.status = StockReservation.Status.RELEASED
        reservation.save(update_fields=["status", "updated_at"])
        line = next(line for line in lines if line.pk == reservation.order_line_id)
        line.quantity_reserved -= reservation.quantity
        line.save(update_fields=["quantity_reserved", "updated_at"])
    order.warehouse = warehouse
    order.status = SalesOrder.Status.READY
    order.save(update_fields=["warehouse", "status", "updated_at"])
    order = allocate_order(order=order, idempotency_key=idempotency_key, actor=actor)
    write_audit(
        organization=order.organization, actor=actor, action="order.warehouse.change", instance=order,
        after={"warehouse": str(warehouse.pk), "idempotency_key": idempotency_key},
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
    lines = _order_lines_or_raise(order, lock=True)
    if not lines or not any(line.quantity_reserved > 0 for line in lines):
        raise ValidationError("订单没有可出库的锁定库存")
    for line in lines:
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

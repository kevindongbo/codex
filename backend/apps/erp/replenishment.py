"""Explainable replenishment forecasting for a SKU in one warehouse.

The module deliberately keeps policy inputs outside the database.  Warehouses can
therefore start using the forecast before route, MOQ or pack-size fields are added
to the data model.  Query functions collect the facts; ``calculate_replenishment``
is a pure function that applies the policy.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from statistics import median
from typing import Callable, Iterable, Sequence

from django.db.models import Q
from django.utils import timezone

from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    ReceiptLine,
    Shipment,
    ShipmentLine,
    StockBalance,
    StockTransfer,
    StockTransferLine,
)


ZERO = Decimal("0")
RATE_QUANTUM = Decimal("0.0001")
QUANTITY_QUANTUM = Decimal("0.001")
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _decimal(value: object, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


def _rate(value: Decimal) -> Decimal:
    return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)


def _nonnegative(name: str, value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _as_aware(value: datetime | None) -> datetime:
    result = value or timezone.now()
    if timezone.is_naive(result):
        return timezone.make_aware(result, timezone.get_current_timezone())
    return result


def _as_date(value: date | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value or timezone.localdate()


def _nearest_rank(values: Sequence[Decimal], percentile: Decimal) -> Decimal | None:
    """Return a nearest-rank percentile, a conservative and explainable P80."""

    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(float(percentile * len(ordered))))
    return ordered[rank - 1]


@dataclass(frozen=True)
class RobustLeadSummary:
    sample_count: int
    excluded_count: int
    median_days: Decimal | None
    p80_days: Decimal | None


def summarize_lead_times(
    values: Iterable[Decimal | int | float], *, max_valid_days: Decimal | int = 365
) -> RobustLeadSummary:
    """Summarize lead times after removing invalid values and gross outliers.

    Values outside 0..``max_valid_days`` are invalid.  With four or more valid
    samples a median absolute deviation filter removes observations farther than
    three MADs (with a two-day minimum tolerance) from the median.  Median and P80
    are both returned so callers can show how the selected lead time was derived.
    """

    maximum = _nonnegative("max_valid_days", _decimal(max_valid_days))
    raw = [_decimal(value) for value in values]
    valid = [value for value in raw if ZERO <= value <= maximum]
    excluded = len(raw) - len(valid)

    filtered = valid
    if len(valid) >= 4:
        center = _decimal(median(valid))
        deviations = [abs(value - center) for value in valid]
        mad = _decimal(median(deviations))
        tolerance = max(Decimal("2"), mad * Decimal("3"))
        filtered = [value for value in valid if abs(value - center) <= tolerance]
        excluded += len(valid) - len(filtered)

    if not filtered:
        return RobustLeadSummary(0, excluded, None, None)

    return RobustLeadSummary(
        sample_count=len(filtered),
        excluded_count=excluded,
        median_days=_rate(_decimal(median(filtered))),
        p80_days=_rate(_nearest_rank(filtered, Decimal("0.80")) or ZERO),
    )


@dataclass(frozen=True)
class LeadTimeEstimate:
    selected_days: int
    source: str
    confidence: str
    first_receipt: RobustLeadSummary
    full_receipt: RobustLeadSummary
    approximate_order_dates: int
    reasons: tuple[str, ...]


def _route_value(purchase_order: PurchaseOrder, resolver: Callable | None) -> object:
    if resolver is not None:
        return resolver(purchase_order)
    for attribute in ("route", "route_code", "shipping_route"):
        value = getattr(purchase_order, attribute, None)
        if value not in (None, ""):
            return getattr(value, "code", value)
    return None


def estimate_lead_time(
    *,
    organization,
    sku,
    warehouse,
    supplier=None,
    route: object | None = None,
    route_resolver: Callable[[PurchaseOrder], object] | None = None,
    manual_lead_days: Decimal | int | float = 14,
    as_of: datetime | None = None,
    lookback_days: int = 730,
    max_valid_days: Decimal | int = 365,
) -> LeadTimeEstimate:
    """Estimate order-to-first/full-receipt time for one SKU and destination.

    ``route_resolver`` makes route filtering usable without requiring a route field
    on ``PurchaseOrder``.  If no resolver is supplied, common optional attributes
    are read through ``getattr`` for forward compatibility.
    """

    manual = _nonnegative("manual_lead_days", _decimal(manual_lead_days))
    current_time = _as_aware(as_of)
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")

    lines = PurchaseOrderLine.objects.filter(
        purchase_order__organization=organization,
        purchase_order__warehouse=warehouse,
        sku=sku,
    ).select_related("purchase_order")
    if supplier is not None:
        lines = lines.filter(purchase_order__supplier=supplier)
    lines = lines.filter(
        Q(purchase_order__ordered_at__gte=current_time - timedelta(days=lookback_days))
        | Q(
            purchase_order__ordered_at__isnull=True,
            purchase_order__created_at__gte=current_time
            - timedelta(days=lookback_days),
        )
    )

    selected_lines = []
    route_attribute_missing = False
    for line in lines:
        purchase_order = line.purchase_order
        if route is not None:
            found_route = _route_value(purchase_order, route_resolver)
            if found_route is None:
                route_attribute_missing = True
                continue
            if str(getattr(found_route, "pk", found_route)) != str(
                getattr(route, "pk", route)
            ):
                continue
        selected_lines.append(line)

    line_by_purchase = {line.purchase_order_id: line for line in selected_lines}
    receipt_events: dict[object, list[tuple[datetime, Decimal]]] = defaultdict(list)
    if line_by_purchase:
        receipt_lines = ReceiptLine.objects.filter(
            receipt__purchase_order_id__in=line_by_purchase,
            receipt__organization=organization,
            receipt__warehouse=warehouse,
            receipt__status=Receipt.Status.COMPLETED,
            receipt__received_at__isnull=False,
            receipt__received_at__lte=current_time,
            sku=sku,
        ).select_related("receipt")
        for receipt_line in receipt_lines:
            receipt_events[receipt_line.receipt.purchase_order_id].append(
                (receipt_line.receipt.received_at, _decimal(receipt_line.quantity))
            )

    first_durations: list[Decimal] = []
    full_durations: list[Decimal] = []
    approximate_order_dates = 0
    for purchase_id, line in line_by_purchase.items():
        events = sorted(receipt_events.get(purchase_id, ()), key=lambda item: item[0])
        if not events:
            continue
        ordered_at = line.purchase_order.ordered_at
        if ordered_at is None:
            ordered_at = line.purchase_order.created_at
            approximate_order_dates += 1
        ordered_at = _as_aware(ordered_at)

        first_at = events[0][0]
        first_durations.append(
            Decimal(str((first_at - ordered_at).total_seconds())) / Decimal("86400")
        )
        cumulative = ZERO
        for received_at, quantity in events:
            cumulative += quantity
            if cumulative >= _decimal(line.quantity_ordered):
                full_durations.append(
                    Decimal(str((received_at - ordered_at).total_seconds()))
                    / Decimal("86400")
                )
                break

    first = summarize_lead_times(first_durations, max_valid_days=max_valid_days)
    full = summarize_lead_times(full_durations, max_valid_days=max_valid_days)
    reasons: list[str] = []

    if full.sample_count:
        chosen = full.p80_days or full.median_days or manual
        source = "historical_full_receipt_p80"
        if full.sample_count >= 8:
            confidence = "high"
        elif full.sample_count >= 3:
            confidence = "medium"
        else:
            confidence = "low"
            reasons.append("完整收货样本少于 3 个，预测可信度较低")
        reasons.append(
            f"采用 {full.sample_count} 个完整收货样本的 P80；中位数为 {full.median_days} 天"
        )
    elif first.sample_count:
        chosen = first.p80_days or first.median_days or manual
        source = "historical_first_receipt_p80"
        confidence = "low"
        reasons.append("没有完整收货样本，暂用首次收货 P80，可能低估全量到货周期")
    else:
        chosen = manual
        source = "manual_fallback"
        confidence = "low"
        reasons.append(f"没有可用历史收货样本，使用人工默认周期 {manual} 天")

    excluded = first.excluded_count + full.excluded_count
    if excluded:
        reasons.append(f"已排除 {excluded} 个无效或异常周期样本")
    if approximate_order_dates:
        reasons.append(
            f"{approximate_order_dates} 个采购单缺少下单时间，使用创建时间近似"
        )
    if route is not None and route_attribute_missing:
        reasons.append("部分采购单没有路线信息，未纳入本路线统计")

    return LeadTimeEstimate(
        selected_days=max(0, math.ceil(float(chosen))),
        source=source,
        confidence=confidence,
        first_receipt=first,
        full_receipt=full,
        approximate_order_dates=approximate_order_dates,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class DemandVelocity:
    daily_velocity: Decimal
    daily_7: Decimal
    daily_14: Decimal
    daily_30: Decimal
    quantity_7: Decimal
    quantity_14: Decimal
    quantity_30: Decimal
    shipment_count: int
    active_days: int
    confidence: str
    reasons: tuple[str, ...]
    daily_stddev: Decimal = ZERO


def estimate_demand_velocity(
    *,
    organization,
    sku,
    warehouse,
    as_of: datetime | None = None,
    weights: Sequence[Decimal | int | float] = (
        Decimal("0.50"),
        Decimal("0.30"),
        Decimal("0.20"),
    ),
) -> DemandVelocity:
    """Calculate weighted 7/14/30-day velocity from completed shipment lines."""

    if len(weights) != 3:
        raise ValueError("weights must contain values for 7, 14 and 30 days")
    normalized_weights = tuple(
        _nonnegative("weight", _decimal(value)) for value in weights
    )
    weight_total = sum(normalized_weights, ZERO)
    if weight_total <= 0:
        raise ValueError("weights must have a positive sum")
    normalized_weights = tuple(value / weight_total for value in normalized_weights)

    current_time = _as_aware(as_of)
    oldest = current_time - timedelta(days=30)
    lines = list(
        ShipmentLine.objects.filter(
            shipment__organization=organization,
            shipment__warehouse=warehouse,
            shipment__status=Shipment.Status.COMPLETED,
            shipment__shipped_at__gte=oldest,
            shipment__shipped_at__lte=current_time,
            sku=sku,
        )
        .select_related("shipment")
        .order_by("shipment__shipped_at")
    )

    quantities: dict[int, Decimal] = {}
    for days in (7, 14, 30):
        threshold = current_time - timedelta(days=days)
        quantities[days] = sum(
            (
                _decimal(line.quantity)
                for line in lines
                if line.shipment.shipped_at >= threshold
            ),
            ZERO,
        )
    daily_7 = quantities[7] / Decimal("7")
    daily_14 = quantities[14] / Decimal("14")
    daily_30 = quantities[30] / Decimal("30")
    velocity = (
        daily_7 * normalized_weights[0]
        + daily_14 * normalized_weights[1]
        + daily_30 * normalized_weights[2]
    )

    shipment_ids = {line.shipment_id for line in lines}
    active_dates = {
        timezone.localtime(line.shipment.shipped_at).date() for line in lines
    }
    daily_quantities = {current_time.date() - timedelta(days=offset): ZERO for offset in range(30)}
    for line in lines:
        day = timezone.localtime(line.shipment.shipped_at).date()
        if day in daily_quantities:
            daily_quantities[day] += _decimal(line.quantity)
    daily_values = list(daily_quantities.values())
    daily_average = sum(daily_values, ZERO) / Decimal(len(daily_values))
    variance = sum(((value - daily_average) ** 2 for value in daily_values), ZERO) / Decimal(len(daily_values))
    daily_stddev = _rate(Decimal(str(math.sqrt(float(variance)))))
    reasons: list[str] = [
        "日速度按近 7/14/30 日实际出库加权计算（默认权重 50%/30%/20%）"
    ]
    if not lines:
        confidence = "low"
        reasons.append("近 30 天没有实际出库记录，无法从历史判断需求")
    else:
        history_days = (current_time - lines[0].shipment.shipped_at).days
        if history_days >= 28 and len(active_dates) >= 10:
            confidence = "high"
        elif history_days >= 13 and len(active_dates) >= 3:
            confidence = "medium"
        else:
            confidence = "low"
            reasons.append("出库覆盖天数或活跃销售天数较少，速度预测可信度较低")

    return DemandVelocity(
        daily_velocity=_rate(velocity),
        daily_7=_rate(daily_7),
        daily_14=_rate(daily_14),
        daily_30=_rate(daily_30),
        quantity_7=_quantity(quantities[7]),
        quantity_14=_quantity(quantities[14]),
        quantity_30=_quantity(quantities[30]),
        shipment_count=len(shipment_ids),
        active_days=len(active_dates),
        daily_stddev=daily_stddev,
        confidence=confidence,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class InventoryPosition:
    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    in_transit: Decimal
    inventory_position: Decimal
    open_purchase_count: int
    next_expected_at: datetime | None


def get_inventory_position(*, organization, sku, warehouse) -> InventoryPosition:
    """Read inventory and confirmed open inbound for exactly one warehouse."""

    balance = StockBalance.objects.filter(
        organization=organization, warehouse=warehouse, sku=sku
    ).first()
    on_hand = _decimal(getattr(balance, "on_hand", ZERO))
    reserved = _decimal(getattr(balance, "reserved", ZERO))
    available = max(ZERO, on_hand - reserved)

    open_lines = list(
        PurchaseOrderLine.objects.filter(
            purchase_order__organization=organization,
            purchase_order__warehouse=warehouse,
            purchase_order__status__in=(
                PurchaseOrder.Status.SUBMITTED,
                PurchaseOrder.Status.PARTIAL,
            ),
            sku=sku,
        ).select_related("purchase_order")
    )
    # Python subtraction keeps this compatible if either quantity later becomes a
    # computed property rather than a concrete database field.
    remaining_by_purchase: dict[object, Decimal] = defaultdict(lambda: ZERO)
    expected_by_purchase: dict[object, datetime | None] = {}
    for line in open_lines:
        remaining = max(
            ZERO, _decimal(line.quantity_ordered) - _decimal(line.quantity_received)
        )
        if remaining:
            remaining_by_purchase[line.purchase_order_id] += remaining
            expected_by_purchase[line.purchase_order_id] = getattr(
                line.purchase_order, "expected_at", None
            )
    purchase_in_transit = sum(remaining_by_purchase.values(), ZERO)
    transfer_in_transit = sum(
        StockTransferLine.objects.filter(
            transfer__organization=organization,
            transfer__destination_warehouse=warehouse,
            transfer__status=StockTransfer.Status.IN_TRANSIT,
            sku=sku,
        ).values_list("quantity", flat=True),
        ZERO,
    )
    in_transit = purchase_in_transit + transfer_in_transit
    expected_dates = [
        value for value in expected_by_purchase.values() if value is not None
    ]

    return InventoryPosition(
        on_hand=_quantity(on_hand),
        reserved=_quantity(reserved),
        available=_quantity(available),
        in_transit=_quantity(in_transit),
        inventory_position=_quantity(available + in_transit),
        open_purchase_count=len(remaining_by_purchase),
        next_expected_at=min(expected_dates) if expected_dates else None,
    )


@dataclass(frozen=True)
class ReplenishmentPolicy:
    safety_days: Decimal = Decimal("7")
    review_cycle_days: Decimal = Decimal("7")
    target_days: Decimal = Decimal("30")
    moq: Decimal = ZERO
    pack_size: Decimal = Decimal("1")
    manual_lead_days: Decimal = Decimal("14")
    safety_stock_units: Decimal | None = None
    service_level_factor: Decimal = Decimal("1.65")
    initial_safety_reference: Decimal = ZERO
    initial_reference_shipment_count: int = 3


@dataclass(frozen=True)
class ReplenishmentForecast:
    as_of: date
    lead_time: LeadTimeEstimate
    demand: DemandVelocity
    inventory: InventoryPosition
    safety_stock_units: Decimal
    reorder_point: Decimal
    target_inventory_position: Decimal
    raw_order_quantity: Decimal
    suggested_order_quantity: Decimal
    needs_reorder: bool
    alert_level: str
    available_days_of_cover: Decimal | None
    projected_days_of_cover: Decimal | None
    available_stockout_date: date | None
    projected_stockout_date: date | None
    latest_order_date: date | None
    confidence: str
    reasons: tuple[str, ...]


def _days_of_cover(quantity: Decimal, daily_velocity: Decimal) -> Decimal | None:
    if daily_velocity <= 0:
        return None
    return (quantity / daily_velocity).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _stockout_date(
    quantity: Decimal, daily_velocity: Decimal, forecast_date: date
) -> date | None:
    if daily_velocity <= 0:
        return None
    days = max(0, math.ceil(float(quantity / daily_velocity)))
    return forecast_date + timedelta(days=days)


def _round_order_quantity(
    quantity: Decimal, moq: Decimal, pack_size: Decimal
) -> Decimal:
    if quantity <= 0:
        return ZERO
    required = max(quantity, moq)
    packs = (required / pack_size).to_integral_value(rounding=ROUND_CEILING)
    return _quantity(packs * pack_size)


def _combined_confidence(*values: str) -> str:
    return min(values, key=lambda value: CONFIDENCE_ORDER.get(value, 0))


def calculate_replenishment(
    *,
    lead_time: LeadTimeEstimate,
    demand: DemandVelocity,
    inventory: InventoryPosition,
    policy: ReplenishmentPolicy | None = None,
    as_of: date | datetime | None = None,
) -> ReplenishmentForecast:
    """Apply an inventory policy without performing database access."""

    policy = policy or ReplenishmentPolicy()
    safety_days = _nonnegative("safety_days", _decimal(policy.safety_days))
    review_days = _nonnegative("review_cycle_days", _decimal(policy.review_cycle_days))
    target_days = _nonnegative("target_days", _decimal(policy.target_days))
    moq = _nonnegative("moq", _decimal(policy.moq))
    pack_size = _decimal(policy.pack_size)
    if pack_size <= 0:
        raise ValueError("pack_size must be positive")

    forecast_date = _as_date(as_of)
    velocity = max(ZERO, _decimal(demand.daily_velocity))
    lead_days = Decimal(lead_time.selected_days)
    day_based_safety = velocity * safety_days
    service_level_factor = _nonnegative("service_level_factor", _decimal(policy.service_level_factor))
    volatility_safety = demand.daily_stddev * Decimal(str(math.sqrt(float(lead_days + review_days)))) * service_level_factor
    manual_safety = _nonnegative(
        "safety_stock_units", _decimal(policy.safety_stock_units, ZERO)
    )
    initial_reference = _nonnegative("initial_safety_reference", _decimal(policy.initial_safety_reference))
    initial_safety = initial_reference if demand.shipment_count < policy.initial_reference_shipment_count else ZERO
    safety_units = max(day_based_safety, volatility_safety, manual_safety, initial_safety)

    reorder_point = velocity * (lead_days + review_days) + safety_units
    effective_target_days = max(target_days, review_days)
    target_position = velocity * (lead_days + effective_target_days) + safety_units
    position = max(ZERO, _decimal(inventory.inventory_position))
    needs_reorder = position <= reorder_point and target_position > position
    raw_quantity = max(ZERO, target_position - position) if needs_reorder else ZERO
    suggested = _round_order_quantity(raw_quantity, moq, pack_size)

    if needs_reorder:
        alert_level = "red"
    elif velocity > 0 and position <= reorder_point + velocity * review_days:
        alert_level = "yellow"
    else:
        alert_level = "green"

    available_cover = _days_of_cover(inventory.available, velocity)
    projected_cover = _days_of_cover(inventory.inventory_position, velocity)
    available_stockout = _stockout_date(inventory.available, velocity, forecast_date)
    projected_stockout = _stockout_date(
        inventory.inventory_position, velocity, forecast_date
    )
    latest_order_date = None
    if projected_stockout is not None:
        risk_buffer = math.ceil(float(lead_days + safety_days))
        latest_order_date = projected_stockout - timedelta(days=risk_buffer)

    reasons = list(lead_time.reasons) + list(demand.reasons)
    reasons.append(
        "库存位置 = 可用库存 + 已确认在途；补货点 = 日速度 ×（采购周期 + 检查周期）+ 安全库存"
    )
    reasons.append(
        f"安全库存同时考虑覆盖天数和销量波动（近 30 天日波动 {demand.daily_stddev}，服务系数 {service_level_factor}）"
    )
    if initial_safety > ZERO:
        reasons.append("出库历史不足，暂以首次录入的安全库存作为参考；后续会自动切换为销量与波动计算")
    if inventory.in_transit > 0:
        reasons.append(f"库存位置已计入 {inventory.in_transit} 件已确认在途")
    if needs_reorder:
        reasons.append(
            f"库存位置 {inventory.inventory_position} 已达到补货点 {_quantity(reorder_point)}"
        )
    elif velocity <= 0:
        reasons.append("当前预测日速度为 0；除非设置了人工安全库存，否则不建议自动采购")
    if suggested > raw_quantity and raw_quantity > 0:
        reasons.append(f"建议量已按 MOQ {moq} 和整箱数 {pack_size} 向上取整")

    return ReplenishmentForecast(
        as_of=forecast_date,
        lead_time=lead_time,
        demand=demand,
        inventory=inventory,
        safety_stock_units=_quantity(safety_units),
        reorder_point=_quantity(reorder_point),
        target_inventory_position=_quantity(target_position),
        raw_order_quantity=_quantity(raw_quantity),
        suggested_order_quantity=suggested,
        needs_reorder=needs_reorder,
        alert_level=alert_level,
        available_days_of_cover=available_cover,
        projected_days_of_cover=projected_cover,
        available_stockout_date=available_stockout,
        projected_stockout_date=projected_stockout,
        latest_order_date=latest_order_date,
        confidence=_combined_confidence(lead_time.confidence, demand.confidence),
        reasons=tuple(reasons),
    )


def build_replenishment_forecast(
    *,
    organization,
    sku,
    warehouse,
    supplier=None,
    route: object | None = None,
    route_resolver: Callable[[PurchaseOrder], object] | None = None,
    policy: ReplenishmentPolicy | None = None,
    as_of: datetime | None = None,
    weights: Sequence[Decimal | int | float] = (Decimal("0.50"), Decimal("0.30"), Decimal("0.20")),
) -> ReplenishmentForecast:
    """Build a complete, explainable forecast from current ERP records."""

    policy = policy or ReplenishmentPolicy()
    current_time = _as_aware(as_of)
    lead_time = estimate_lead_time(
        organization=organization,
        sku=sku,
        warehouse=warehouse,
        supplier=supplier,
        route=route,
        route_resolver=route_resolver,
        manual_lead_days=policy.manual_lead_days,
        as_of=current_time,
    )
    demand = estimate_demand_velocity(
        organization=organization,
        sku=sku,
        warehouse=warehouse,
        as_of=current_time,
        weights=weights,
    )
    inventory = get_inventory_position(
        organization=organization,
        sku=sku,
        warehouse=warehouse,
    )
    policy = ReplenishmentPolicy(
        safety_days=policy.safety_days,
        review_cycle_days=policy.review_cycle_days,
        target_days=policy.target_days,
        moq=policy.moq,
        pack_size=policy.pack_size,
        manual_lead_days=policy.manual_lead_days,
        safety_stock_units=policy.safety_stock_units,
        service_level_factor=policy.service_level_factor,
        initial_safety_reference=policy.initial_safety_reference or _decimal(getattr(sku, "safety_stock", ZERO)),
        initial_reference_shipment_count=policy.initial_reference_shipment_count,
    )
    return calculate_replenishment(
        lead_time=lead_time,
        demand=demand,
        inventory=inventory,
        policy=policy,
        as_of=current_time,
    )

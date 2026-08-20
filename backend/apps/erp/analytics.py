"""Read-only, organization-scoped ERP analytics.

The functions only aggregate authoritative ERP facts.  Missing monetary facts
remain ``None`` instead of being inferred from catalogue prices.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from .models import (
    OwnStore,
    ReturnReceipt,
    ReturnReceiptLine,
    SalesOrder,
    SalesOrderLine,
    Shipment,
    ShipmentLine,
    SKU,
    StockBalance,
    StockLedger,
)


ZERO = Decimal("0")


def _decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _quantity(value):
    return str(_decimal(value).quantize(Decimal("0.001")))


def _money_or_none(value, has_source):
    return str(_decimal(value).quantize(Decimal("0.01"))) if has_source else None


def report_window(*, start=None, end=None, days=30, now=None):
    try:
        report_zone = ZoneInfo(settings.TIME_ZONE)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError(f"系统报表时区配置无效：{settings.TIME_ZONE}") from exc
    local_now = (now or timezone.now()).astimezone(report_zone)
    try:
        end_date = date.fromisoformat(end) if end else local_now.date()
        start_date = date.fromisoformat(start) if start else end_date - timedelta(days=int(days) - 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD，days 必须为正整数") from exc
    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")
    if (end_date - start_date).days > 366:
        raise ValueError("单次报表区间不能超过 367 天")
    start_at = datetime.combine(start_date, time.min, tzinfo=report_zone)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=report_zone)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "start_at": start_at,
        "end_at": end_at,
        "timezone": str(report_zone),
    }


def _warehouse_filter(queryset, warehouse_ids, field="warehouse_id"):
    if warehouse_ids is None:
        return queryset
    return queryset.filter(**{f"{field}__in": warehouse_ids})


def _normalized_store_name(value):
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def _store_lookup(stores):
    grouped = defaultdict(list)
    for store in stores:
        grouped[_normalized_store_name(store.name)].append(store)
    return {key: rows[0] for key, rows in grouped.items() if key and len(rows) == 1}


def _filter_orders_by_store(queryset, organization, store_id):
    if not store_id:
        return queryset
    selected = OwnStore.objects.filter(organization=organization, pk=store_id).first()
    if selected is None:
        raise ValueError("店铺不存在或不属于当前组织")
    stores = list(OwnStore.objects.filter(organization=organization))
    lookup = _store_lookup(stores)
    if lookup.get(_normalized_store_name(selected.name)) != selected:
        return queryset.none()
    matching_ids = [
        row["pk"]
        for row in queryset.values("pk", "store")
        if lookup.get(_normalized_store_name(row["store"])) == selected
    ]
    return queryset.filter(pk__in=matching_ids)


def _overview_counts(*, organization, window, warehouse_ids, store_id=None):
    orders = SalesOrder.objects.filter(
        organization=organization,
        ordered_at__gte=window["start_at"],
        ordered_at__lt=window["end_at"],
    )
    orders = _warehouse_filter(orders, warehouse_ids)
    orders = _filter_orders_by_store(orders, organization, store_id)
    lines = SalesOrderLine.objects.filter(order__in=orders)
    units = lines.aggregate(total=Sum("quantity"))["total"] or ZERO
    priced_lines = lines.filter(unit_price__gt=0)
    priced = priced_lines.exists()
    gmv_expression = ExpressionWrapper(
        F("quantity") * F("unit_price"),
        output_field=DecimalField(max_digits=24, decimal_places=4),
    )
    gmv = priced_lines.aggregate(total=Sum(gmv_expression))["total"] or ZERO

    shipments = Shipment.objects.filter(
        organization=organization,
        shipped_at__gte=window["start_at"],
        shipped_at__lt=window["end_at"],
    )
    shipments = _warehouse_filter(shipments, warehouse_ids)
    if store_id:
        shipments = shipments.filter(order_id__in=orders.values("pk"))
    shipped_units = ShipmentLine.objects.filter(shipment__in=shipments).aggregate(total=Sum("quantity"))["total"] or ZERO

    returns = ReturnReceipt.objects.filter(
        organization=organization,
        received_at__gte=window["start_at"],
        received_at__lt=window["end_at"],
    )
    returns = _warehouse_filter(returns, warehouse_ids)
    if store_id:
        returns = returns.filter(return_order__original_order_id__in=orders.values("pk"))
    return_lines = ReturnReceiptLine.objects.filter(receipt__in=returns)
    return_units = return_lines.aggregate(total=Sum("quantity"))["total"] or ZERO
    refund_expression = ExpressionWrapper(
        F("quantity") * F("return_line__unit_refund"),
        output_field=DecimalField(max_digits=24, decimal_places=4),
    )
    priced_refunds = return_lines.filter(return_line__unit_refund__gt=0)
    refund_known = priced_refunds.exists()
    refund = priced_refunds.aggregate(total=Sum(refund_expression))["total"] or ZERO

    cancelled = SalesOrder.objects.filter(
        organization=organization,
        erp_cancelled_at__gte=window["start_at"],
        erp_cancelled_at__lt=window["end_at"],
    )
    cancelled = _warehouse_filter(cancelled, warehouse_ids)
    cancelled = _filter_orders_by_store(cancelled, organization, store_id)

    attributed_return_units = ZERO
    sale_shipment_keys = set(
        ShipmentLine.objects.filter(shipment__in=shipments).values_list("shipment__order_id", "sku_id")
    )
    if sale_shipment_keys:
        for row in ReturnReceiptLine.objects.filter(
            receipt__organization=organization,
            receipt__return_order__original_order_id__in={key[0] for key in sale_shipment_keys},
        ).values("receipt__return_order__original_order_id", "sku_id").annotate(total=Sum("quantity")):
            if (row["receipt__return_order__original_order_id"], row["sku_id"]) in sale_shipment_keys:
                attributed_return_units += _decimal(row["total"])

    return {
        "order_count": orders.count(),
        "sales_units": _quantity(units),
        "shipped_order_count": shipments.values("order_id").distinct().count(),
        "shipped_units": _quantity(shipped_units),
        "shortage_order_count": orders.filter(status__in=(SalesOrder.Status.DRAFT, SalesOrder.Status.READY)).count(),
        "cancelled_order_count": cancelled.count(),
        "return_units": _quantity(return_units),
        "return_units_period_occurrence": _quantity(return_units),
        "return_units_attributed_to_sales_period": _quantity(attributed_return_units),
        "gmv": _money_or_none(gmv, priced),
        "sales_revenue": _money_or_none(gmv, priced),
        "refund_amount": _money_or_none(refund, refund_known),
        "profit": None,
        "monetary_data_available": priced,
    }


def overview_payload(*, organization, warehouse_ids, start=None, end=None, days=30, now=None, store_id=None):
    window = report_window(start=start, end=end, days=days, now=now)
    counts = _overview_counts(
        organization=organization, window=window, warehouse_ids=warehouse_ids, store_id=store_id
    )
    top_shipments = ShipmentLine.objects.filter(
        shipment__organization=organization,
        shipment__shipped_at__gte=window["start_at"],
        shipment__shipped_at__lt=window["end_at"],
    )
    top_shipments = _warehouse_filter(top_shipments, warehouse_ids, "shipment__warehouse_id")
    if store_id:
        selected_orders = SalesOrder.objects.filter(organization=organization)
        selected_orders = _filter_orders_by_store(selected_orders, organization, store_id)
        top_shipments = top_shipments.filter(shipment__order_id__in=selected_orders.values("pk"))
    top_skus = list(
        top_shipments.values("sku_id", "sku__code", "sku__product__name")
        .annotate(quantity=Sum("quantity"))
        .order_by("-quantity")[:10]
    )
    balances = StockBalance.objects.filter(organization=organization)
    balances = _warehouse_filter(balances, warehouse_ids)
    risks = balances.filter(on_hand__lte=F("reserved")).count()
    report_zone = ZoneInfo(window["timezone"])
    dates = [window["start_date"] + timedelta(days=offset) for offset in range((window["end_date"] - window["start_date"]).days + 1)]
    sales_trend = {day: {"date": day.isoformat(), "orders": 0, "sales_units": ZERO, "shipped_units": ZERO} for day in dates}
    period_orders = SalesOrder.objects.filter(
        organization=organization, ordered_at__gte=window["start_at"], ordered_at__lt=window["end_at"]
    )
    period_orders = _warehouse_filter(period_orders, warehouse_ids)
    period_orders = _filter_orders_by_store(period_orders, organization, store_id)
    for order in period_orders.prefetch_related("lines"):
        day = order.ordered_at.astimezone(report_zone).date()
        sales_trend[day]["orders"] += 1
        sales_trend[day]["sales_units"] += sum((_decimal(line.quantity) for line in order.lines.all()), ZERO)
    period_shipments = Shipment.objects.filter(
        organization=organization, shipped_at__gte=window["start_at"], shipped_at__lt=window["end_at"]
    )
    period_shipments = _warehouse_filter(period_shipments, warehouse_ids)
    if store_id:
        period_shipments = period_shipments.filter(order_id__in=period_orders.values("pk"))
    for shipment in period_shipments.prefetch_related("lines"):
        day = shipment.shipped_at.astimezone(report_zone).date()
        sales_trend[day]["shipped_units"] += sum((_decimal(line.quantity) for line in shipment.lines.all()), ZERO)
    trend_rows = [
        {**row, "sales_units": _quantity(row["sales_units"]), "shipped_units": _quantity(row["shipped_units"])}
        for row in sales_trend.values()
    ]
    status_trend = [
        {
            "status": row["status"], "count": row["count"],
        }
        for row in period_orders.values("status").annotate(count=Count("id")).order_by("status")
    ]
    recent_exceptions = [
        {"type": "shortage", "order": order.number, "occurred_at": (order.ordered_at or order.created_at).isoformat()}
        for order in period_orders.filter(status__in=(SalesOrder.Status.DRAFT, SalesOrder.Status.READY)).order_by("-ordered_at")[:10]
    ]
    recent_exceptions += [
        {"type": "erp_cancelled", "order": order.number, "occurred_at": order.erp_cancelled_at.isoformat()}
        for order in SalesOrder.objects.filter(
            organization=organization, erp_cancelled_at__gte=window["start_at"], erp_cancelled_at__lt=window["end_at"]
        ).order_by("-erp_cancelled_at")[:10]
    ]
    return {
        "period": {
            "start": window["start_date"].isoformat(),
            "end": window["end_date"].isoformat(),
            "timezone": window["timezone"],
            "end_inclusive": True,
        },
        "metrics": counts,
        "top_skus": [
            {
                "sku": str(row["sku_id"]),
                "sku_code": row["sku__code"],
                "product_name": row["sku__product__name"],
                "shipped_units": _quantity(row["quantity"]),
            }
            for row in top_skus
        ],
        "sales_trend": trend_rows,
        "order_status_trend": status_trend,
        "recent_exceptions": sorted(recent_exceptions, key=lambda item: item["occurred_at"], reverse=True)[:20],
        "current_snapshot": {"stock_risk_sku_count": risks, "generated_at": timezone.now().isoformat()},
        "sources": ["erp_orders", "erp_shipments", "erp_returns", "current_stock_balances"],
    }


def stores_payload(*, organization, warehouse_ids, start=None, end=None, days=30, now=None, store_id=None):
    window = report_window(start=start, end=end, days=days, now=now)
    all_stores = list(OwnStore.objects.filter(organization=organization).order_by("name", "id"))
    stores = all_stores
    if store_id:
        stores = [store for store in stores if str(store.pk) == str(store_id)]
        if not stores:
            raise ValueError("店铺不存在或不属于当前组织")
    lookup = _store_lookup(all_stores)
    orders = SalesOrder.objects.filter(
        organization=organization,
        ordered_at__gte=window["start_at"],
        ordered_at__lt=window["end_at"],
    ).prefetch_related("lines")
    orders = list(_warehouse_filter(orders, warehouse_ids))
    groups = defaultdict(list)
    for order in orders:
        matched = lookup.get(_normalized_store_name(order.store))
        groups[str(matched.pk) if matched else "unlinked"].append(order)

    result = []
    for store in [*stores, None]:
        key = str(store.pk) if store else "unlinked"
        grouped_orders = groups.get(key, [])
        if store is None and not grouped_orders:
            continue
        order_ids = [order.pk for order in grouped_orders]
        lines = SalesOrderLine.objects.filter(order_id__in=order_ids)
        units = lines.aggregate(total=Sum("quantity"))["total"] or ZERO
        priced = lines.filter(unit_price__gt=0).exists()
        gmv_expression = ExpressionWrapper(
            F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=24, decimal_places=4)
        )
        gmv = lines.filter(unit_price__gt=0).aggregate(total=Sum(gmv_expression))["total"] or ZERO
        shipped_lines = ShipmentLine.objects.filter(
            shipment__order_id__in=order_ids,
            shipment__shipped_at__gte=window["start_at"],
            shipment__shipped_at__lt=window["end_at"],
        )
        occurrence_returns = ReturnReceiptLine.objects.filter(
            receipt__organization=organization,
            receipt__received_at__gte=window["start_at"],
            receipt__received_at__lt=window["end_at"],
            receipt__return_order__original_order_id__in=order_ids,
        )
        return_units = occurrence_returns.aggregate(total=Sum("quantity"))["total"] or ZERO
        refund_expression = ExpressionWrapper(
            F("quantity") * F("return_line__unit_refund"), output_field=DecimalField(max_digits=24, decimal_places=4)
        )
        known_refunds = occurrence_returns.filter(return_line__unit_refund__gt=0)
        refund_known = known_refunds.exists()
        refund = known_refunds.aggregate(total=Sum(refund_expression))["total"] or ZERO
        result.append({
            "store": str(store.pk) if store else None,
            "store_name": store.name if store else "未关联店铺",
            "linked": store is not None,
            "order_count": len(grouped_orders),
            "sales_units": _quantity(units),
            "shipped_units": _quantity(shipped_lines.aggregate(total=Sum("quantity"))["total"] or ZERO),
            "shortage_order_count": sum(order.status in (SalesOrder.Status.DRAFT, SalesOrder.Status.READY) for order in grouped_orders),
            "cancelled_order_count": sum(order.status == SalesOrder.Status.CANCELLED for order in grouped_orders),
            "return_units": _quantity(return_units),
            "gmv": _money_or_none(gmv, priced),
            "sales_revenue": _money_or_none(gmv, priced),
            "refund_amount": _money_or_none(refund, refund_known),
            "profit": None,
            "data_source": "erp",
        })
    return {
        "period": {"start": window["start_date"].isoformat(), "end": window["end_date"].isoformat(), "timezone": window["timezone"]},
        "stores": result,
        "generated_at": timezone.now().isoformat(),
    }


def skus_payload(*, organization, warehouse_ids, start=None, end=None, days=30, now=None, query="", limit=200, store_id=None, sku_id=None):
    window = report_window(start=start, end=end, days=days, now=now)
    skus = SKU.objects.filter(organization=organization).select_related("product")
    if sku_id:
        skus = skus.filter(pk=sku_id)
        if not skus.exists():
            raise ValueError("SKU 不存在或不属于当前组织")
    if query:
        from django.db.models import Q
        skus = skus.filter(Q(code__icontains=query) | Q(product__name__icontains=query))
    skus = list(skus.order_by("code")[:limit])
    sku_ids = [sku.pk for sku in skus]

    shipment_rows = ShipmentLine.objects.filter(
        shipment__organization=organization,
        shipment__shipped_at__gte=window["start_at"],
        shipment__shipped_at__lt=window["end_at"],
        sku_id__in=sku_ids,
    )
    shipment_rows = _warehouse_filter(shipment_rows, warehouse_ids, "shipment__warehouse_id")
    if store_id:
        store_orders = SalesOrder.objects.filter(organization=organization)
        store_orders = _filter_orders_by_store(store_orders, organization, store_id)
        shipment_rows = shipment_rows.filter(shipment__order_id__in=store_orders.values("pk"))
    shipped = {row["sku_id"]: row["total"] for row in shipment_rows.values("sku_id").annotate(total=Sum("quantity"))}
    shipment_keys = set(shipment_rows.values_list("shipment__order_id", "sku_id"))
    returned = defaultdict(lambda: ZERO)
    if shipment_keys:
        original_order_ids = {order_id for order_id, _sku_id in shipment_keys}
        for return_line in ReturnReceiptLine.objects.filter(
            receipt__organization=organization,
            receipt__return_order__original_order_id__in=original_order_ids,
            sku_id__in=sku_ids,
        ).values("receipt__return_order__original_order_id", "sku_id").annotate(total=Sum("quantity")):
            key = (return_line["receipt__return_order__original_order_id"], return_line["sku_id"])
            if key in shipment_keys:
                returned[return_line["sku_id"]] += _decimal(return_line["total"])

    manual_rows = StockLedger.objects.filter(
        organization=organization,
        sku_id__in=sku_ids,
        event_type=StockLedger.Type.MANUAL_OUTBOUND,
        occurred_at__gte=window["start_at"],
        occurred_at__lt=window["end_at"],
        on_hand_delta__lt=0,
        reversal__isnull=True,
    )
    manual_rows = _warehouse_filter(manual_rows, warehouse_ids)
    if store_id:
        manual_rows = manual_rows.none()
    manual = {row["sku_id"]: -row["total"] for row in manual_rows.values("sku_id").annotate(total=Sum("on_hand_delta"))}

    balance_rows = StockBalance.objects.filter(organization=organization, sku_id__in=sku_ids)
    balance_rows = _warehouse_filter(balance_rows, warehouse_ids)
    balances = {
        row["sku_id"]: row
        for row in balance_rows.values("sku_id").annotate(
            on_hand=Sum("on_hand"), reserved=Sum("reserved"), in_transit=Sum("in_transit")
        )
    }
    rows = []
    period_days = Decimal((window["end_date"] - window["start_date"]).days + 1)
    for sku in skus:
        order_outbound = _decimal(shipped.get(sku.pk))
        manual_outbound = _decimal(manual.get(sku.pk))
        return_quantity = returned[sku.pk]
        net = max(ZERO, order_outbound + manual_outbound - return_quantity)
        balance = balances.get(sku.pk, {})
        on_hand = _decimal(balance.get("on_hand"))
        reserved = _decimal(balance.get("reserved"))
        available = max(ZERO, on_hand - reserved)
        daily = net / period_days
        rows.append({
            "sku": str(sku.pk), "sku_code": sku.code, "product_name": sku.product.name,
            "order_outbound": _quantity(order_outbound), "manual_outbound": _quantity(manual_outbound),
            "returns_at_original_sale_date": _quantity(return_quantity), "net_sales": _quantity(net),
            "daily_average": str(daily.quantize(Decimal("0.0001"))),
            "on_hand": _quantity(on_hand), "reserved": _quantity(reserved),
            "available": _quantity(available), "in_transit": _quantity(balance.get("in_transit")),
            "days_of_cover": str((available / daily).quantize(Decimal("0.1"))) if daily > 0 else None,
        })
    return {
        "period": {"start": window["start_date"].isoformat(), "end": window["end_date"].isoformat(), "timezone": window["timezone"]},
        "results": rows,
        "generated_at": timezone.now().isoformat(),
    }

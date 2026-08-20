"""Auditable TikTok Shop Malaysia profit estimation.

The calculator uses only versioned local rules.  It never calls a third-party
calculator at runtime and it never treats buyer-paid shipping as seller income.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .profit_category_data import CATEGORY_ROWS
from .profit_category_taxonomy import CATEGORY_TAXONOMY, iter_taxonomy_leaves
from .profit_shipping_rates import (
    MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE,
    MALAYSIA_CROSS_BORDER_MAX_G,
    MALAYSIA_CROSS_BORDER_RATE_VERSION,
    MALAYSIA_CROSS_BORDER_SOURCE,
    MALAYSIA_STANDARD_BUYER_SHIPPING_EFFECTIVE_DATE,
    MALAYSIA_STANDARD_BUYER_SHIPPING_RATE_VERSION,
    MALAYSIA_STANDARD_BUYER_SHIPPING_SOURCE,
    malaysia_cross_border_shipping,
    malaysia_standard_buyer_shipping,
)


MONEY = Decimal("0.01")
PERCENT = Decimal("100")
RULE_EFFECTIVE_DATE = date(2026, 8, 2)
RULE_VERSION = "MY-TTS-2026-08-05-v6"
COMMISSION_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=6907739532281602&lang=en"
)
TRANSACTION_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=10013511&lang=en"
)
SUPPORT_FEE_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=7992113007347457&lang=en"
)
AFFILIATE_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=6837846988539650&lang=en"
)
LVG_TAX_SOURCE = (
    "https://mysst.customs.gov.my/assets/document/Industry%20Guides/GI/"
    "Guide%20on%20Low%20Value%20Goods_Draft.pdf"
)
SHIPPING_CALCULATION_SOURCE = MALAYSIA_CROSS_BORDER_SOURCE
SHIPPING_SOURCE = MALAYSIA_CROSS_BORDER_SOURCE


def decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def money(value) -> Decimal:
    return decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def rate_amount(base: Decimal, rate: Decimal) -> Decimal:
    return money(base * rate / PERCENT)


def percentage(amount: Decimal, base: Decimal) -> Decimal:
    return money(amount / base * PERCENT) if base else Decimal("0.00")


@dataclass(frozen=True)
class CategoryRule:
    code: str
    industry: str
    level_one: str
    level_two: str
    marketplace_bxp: Decimal
    marketplace_standard: Decimal
    mall_bxp: Decimal
    mall_standard: Decimal
    support_fee_exempt: bool = False

    @property
    def label(self) -> str:
        return " / ".join((self.industry, self.level_one, self.level_two))

    def rate(self, shop_identity: str, bxp: bool) -> Decimal:
        if shop_identity == "mall":
            return self.mall_bxp if bxp else self.mall_standard
        return self.marketplace_bxp if bxp else self.marketplace_standard


CATEGORY_RULES = {
    row[0]: CategoryRule(
        code=row[0],
        industry=row[1],
        level_one=row[2],
        level_two=row[3],
        marketplace_bxp=Decimal(row[4]),
        marketplace_standard=Decimal(row[5]),
        mall_bxp=Decimal(row[6]),
        mall_standard=Decimal(row[7]),
        support_fee_exempt=row[8],
    )
    for row in CATEGORY_ROWS
}

# The public commission table stops at a fee-bearing category group.  The ERP
# exposes the operator's two complete three-level trees and inherits the
# official rate from each leaf's mapped TikTok fee group.
for root_label, group_label, code, label, parent_code in iter_taxonomy_leaves():
    CATEGORY_RULES[code] = replace(
        CATEGORY_RULES[parent_code],
        code=code,
        industry=root_label,
        level_one=group_label,
        level_two=label,
    )

LEGACY_CATEGORY_ALIASES = {
    "womens_bags": "bag-womens-womens-tote-bags",
    "fashion_accessories": "fashion-fashion-accessories-clothes-accessories",
    "peripherals_accessories": "electronics-phones-and-electronics-tablet-and-computer-accessories",
    "home_supplies": "lifestyle-home-supplies-home-decor",
    "beauty_skincare": "fmcg-beauty-and-personal-care-skincare",
    "musical_instruments": "lifestyle-toys-and-hobbies-musical-instruments-and-accessories",
    "essential_food": "fmcg-food-and-beverages-staples-and-cooking-essentials",
}

TRANSACTION_RATE = Decimal("3.78")
BXP_RATE = Decimal("4.86")
BXP_FEE_CAP = Decimal("54.00")
PLATFORM_SUPPORT_FEE = Decimal("0.54")
LVG_RATE = Decimal("10.00")
LVG_LIMIT = Decimal("500.00")


def resolve_category(code: str) -> CategoryRule:
    return CATEGORY_RULES[LEGACY_CATEGORY_ALIASES.get(code, code)]


def category_config():
    return [
        {
            "code": rule.code,
            "label": rule.label,
            "path": [rule.industry, rule.level_one, rule.level_two],
            "support_fee_exempt": rule.support_fee_exempt,
            "rates": {
                "marketplace_bxp": str(rule.marketplace_bxp),
                "marketplace_standard": str(rule.marketplace_standard),
                "mall_bxp": str(rule.mall_bxp),
                "mall_standard": str(rule.mall_standard),
            },
        }
        for rule in CATEGORY_RULES.values()
    ]


def category_tree():
    return [
        {
            "label": root["label"],
            "children": [
                {
                    "label": group["label"],
                    "children": [
                        {"code": code, "label": label}
                        for code, label in group["children"]
                    ],
                }
                for group in root["children"]
            ],
        }
        for root in CATEGORY_TAXONOMY
    ]


def shipping_estimate(weight_g: Decimal) -> tuple[int, Decimal]:
    """Compatibility wrapper returning rounded grams and merchant cost."""
    return malaysia_cross_border_shipping(weight_g)


def inclusive_lvg_tax(item_price: Decimal, seller_type: str) -> Decimal:
    """Return the tax component already included in a tax-inclusive price."""
    if seller_type != "cross_border" or item_price > LVG_LIMIT:
        return Decimal("0.00")
    return money(item_price * LVG_RATE / (PERCENT + LVG_RATE))


def advertising_cost(item_revenue: Decimal, item: dict, usd_per_myr: Decimal) -> Decimal:
    """Return the pre-rebate ad cost in MYR without guessing missing inputs."""
    cost_type = item.get("ad_cost_type", "none")
    value = decimal(item.get("ad_cost_value"))
    if value <= 0 or cost_type == "none":
        return Decimal("0.00")
    if cost_type == "roi":
        return money(item_revenue / value)
    if cost_type == "cpa_usd":
        return money(value / usd_per_myr)
    if cost_type == "ratio":
        return rate_amount(item_revenue, value)
    return Decimal("0.00")


def advertising_costs(
    item_revenue: Decimal,
    item: dict,
    usd_per_myr: Decimal,
    global_rebate_percent: Decimal,
) -> dict:
    """Calculate one SKU's auditable advertising amounts.

    ``None`` is the only inheritance marker.  An explicit zero override must
    therefore remain distinguishable from a missing override.  The gross cost
    is rounded by the existing advertising conversion first, then rebate and
    payable amounts are rounded at the SKU boundary before order aggregation.
    """
    override = item.get("advertising_rebate_percent_override")
    if override is None:
        rebate_percent = decimal(global_rebate_percent)
        rebate_source = "global"
    else:
        rebate_percent = decimal(override)
        rebate_source = "sku_override"
    rebate_percent = min(PERCENT, max(Decimal("0"), rebate_percent))

    before_rebate = advertising_cost(item_revenue, item, usd_per_myr)
    has_ad_input = before_rebate > 0
    rebate_amount = rate_amount(before_rebate, rebate_percent) if has_ad_input else Decimal("0.00")
    # Subtract the rounded rebate from the rounded gross cost so every SKU and
    # the order total reconcile to the cent even at half-cent boundaries.
    actual_cost = money(before_rebate - rebate_amount) if has_ad_input else Decimal("0.00")

    if not has_ad_input:
        true_roi = None
        true_roi_status = "unavailable"
    elif actual_cost == 0:
        true_roi = "Infinity"
        true_roi_status = "infinite"
    else:
        true_roi = str(money(item_revenue / actual_cost))
        true_roi_status = "available"

    cost_type = item.get("ad_cost_type", "none")
    value = decimal(item.get("ad_cost_value"))
    true_cpa_usd = None
    if has_ad_input and cost_type == "cpa_usd":
        true_cpa_usd = str(money(value * (PERCENT - rebate_percent) / PERCENT))

    return {
        "has_ad_input": has_ad_input,
        "advertising_cost_before_rebate": before_rebate,
        "advertising_rebate_percent": rebate_percent,
        "advertising_rebate_source": rebate_source,
        "advertising_rebate_amount": rebate_amount,
        "advertising_cost": actual_cost,
        "original_roi": str(value) if has_ad_input and cost_type == "roi" else None,
        "original_cpa_usd": str(value) if has_ad_input and cost_type == "cpa_usd" else None,
        "true_roi": true_roi,
        "true_roi_status": true_roi_status,
        "true_cpa_usd": true_cpa_usd,
    }


def _allocate_order_support_fee(items: list[dict], delivered: bool) -> list[Decimal]:
    """Allocate one delivered-order fee without creating or losing a cent.

    TikTok charges this fee once per order.  The calculator is SKU-oriented, so
    the displayed line items receive a revenue-proportional allocation and the
    highest-revenue SKU receives the rounding remainder.
    """
    allocations = [Decimal("0.00") for _ in items]
    eligible = [index for index, item in enumerate(items) if not item["support_fee_exempt"]]
    if not delivered or not eligible:
        return allocations
    eligible_revenue = sum((items[index]["item_price"] for index in eligible), Decimal("0"))
    if eligible_revenue <= 0:
        allocations[eligible[0]] = PLATFORM_SUPPORT_FEE
        return allocations
    remaining = PLATFORM_SUPPORT_FEE
    # Every non-tail allocation is rounded independently; the deterministic
    # tail keeps the order total exactly RM0.54.
    ordered = sorted(eligible, key=lambda index: (-items[index]["item_price"], index))
    for index in ordered[1:]:
        allocated = money(PLATFORM_SUPPORT_FEE * items[index]["item_price"] / eligible_revenue)
        allocations[index] = allocated
        remaining -= allocated
    allocations[ordered[0]] = money(remaining)
    return allocations


def _calculate_profit_v5(payload: dict) -> dict:
    shop_identity = payload.get("shop_identity", "marketplace")
    seller_type = payload.get("seller_type", "cross_border")
    bxp = bool(payload.get("bxp", False))
    delivered = bool(payload.get("delivered", True))
    cny_per_myr = decimal(payload.get("cny_per_myr", "1"))
    usd_per_myr = decimal(payload.get("usd_per_myr", "0.235"))
    commission_adjustment = decimal(payload.get("commission_adjustment", "0.00"))
    customer_refund = money(payload.get("customer_refund", 0))
    items = payload["items"]

    support_inputs = []
    for item in items:
        rule = resolve_category(item["category_code"])
        support_inputs.append({
            "item_price": money(item["item_price"]),
            "support_fee_exempt": rule.support_fee_exempt,
        })
    support_allocations = _allocate_order_support_fee(support_inputs, delivered)

    fee_totals = {
        "product_cost": Decimal("0"),
        "seller_shipping_cost": Decimal("0"),
        "platform_commission": Decimal("0"),
        "transaction_fee": Decimal("0"),
        "affiliate_commission": Decimal("0"),
        "bxp_fee": Decimal("0"),
        "platform_support_fee": Decimal("0"),
        "advertising_cost": Decimal("0"),
    }
    bases = {
        "commission": Decimal("0"),
        "commission_weighted_rate": Decimal("0"),
        "transaction": Decimal("0"),
        "affiliate": Decimal("0"),
        "affiliate_weighted_rate": Decimal("0"),
    }
    sales_revenue = Decimal("0")
    buyer_shipping_total = Decimal("0")
    tax_total = Decimal("0")
    item_results = []
    has_ad_cost = False
    has_manual_commission_rate = False

    for item_index, item in enumerate(items):
        item_price = money(item["item_price"])
        weight_g = decimal(item["weight_g"])
        product_cost_cny = decimal(item.get("product_cost_cny", 0))
        affiliate_rate = decimal(item.get("affiliate_rate", 0))
        buyer_shipping_fee = money(item.get("buyer_shipping_fee", 0))
        rounded_weight_g, estimated_shipping = malaysia_cross_border_shipping(weight_g)
        seller_shipping_cost = (
            money(estimated_shipping)
            if seller_type == "cross_border"
            else Decimal("0.00")
        )
        product_tax = inclusive_lvg_tax(item_price, seller_type)
        affiliate_base = max(Decimal("0"), item_price - product_tax)
        # A buyer-paid freight amount is not revenue and cannot offset seller
        # logistics.  It only expands the payment-fee base, while refunds
        # reduce that base at order level below.
        transaction_base = money(item_price + buyer_shipping_fee)

        rule = resolve_category(item["category_code"])
        official_commission_rate = rule.rate(shop_identity, bxp)
        manual_commission_rate = item.get("manual_commission_rate")
        if manual_commission_rate is not None:
            manual_commission_rate = decimal(manual_commission_rate)
            has_manual_commission_rate = True
        if official_commission_rate is None and manual_commission_rate is None:
            raise ValueError("所选三级类目没有官方佣金率，请在费用明细中手动填写类目佣金率。")
        system_commission_rate = (
            min(PERCENT, max(Decimal("0"), official_commission_rate + commission_adjustment))
            if official_commission_rate is not None
            else None
        )
        applied_commission_rate = (
            manual_commission_rate
            if manual_commission_rate is not None
            else system_commission_rate
        )
        bxp_fee = (
            min(rate_amount(item_price, BXP_RATE), BXP_FEE_CAP)
            if bxp
            else Decimal("0.00")
        )
        support_fee = support_allocations[item_index]
        item_ad_cost = advertising_cost(item_price, item, usd_per_myr)
        has_ad_cost = has_ad_cost or item_ad_cost > 0
        line_fees = {
            "product_cost": money(product_cost_cny / cny_per_myr),
            "seller_shipping_cost": seller_shipping_cost,
            "platform_commission": rate_amount(item_price, applied_commission_rate),
            "transaction_fee": rate_amount(transaction_base, TRANSACTION_RATE),
            "affiliate_commission": rate_amount(affiliate_base, affiliate_rate),
            "bxp_fee": bxp_fee,
            "platform_support_fee": support_fee,
            "advertising_cost": item_ad_cost,
        }

        sales_revenue += item_price
        buyer_shipping_total += buyer_shipping_fee
        tax_total += product_tax
        bases["commission"] += item_price
        bases["commission_weighted_rate"] += item_price * applied_commission_rate
        bases["transaction"] += transaction_base
        bases["affiliate"] += affiliate_base
        bases["affiliate_weighted_rate"] += affiliate_base * affiliate_rate
        for key, value in line_fees.items():
            fee_totals[key] += value

        item_results.append({
            "sku_name": item.get("sku_name") or "SKU",
            "category": rule.label,
            "category_code": rule.code,
            "weight_g": str(weight_g),
            "rounded_weight_g": rounded_weight_g,
            "shipping_tier_g": rounded_weight_g,
            "buyer_shipping_fee": str(buyer_shipping_fee),
            "seller_shipping_cost": str(seller_shipping_cost),
            "shipping_estimate": str(money(estimated_shipping)),
            "product_tax": str(product_tax),
            "revenue": str(item_price),
            "commission_base": str(item_price),
            "transaction_base": str(transaction_base),
            "affiliate_base": str(money(affiliate_base)),
            "official_commission_rate": (
                str(official_commission_rate)
                if official_commission_rate is not None
                else None
            ),
            "system_commission_rate": (
                str(system_commission_rate)
                if system_commission_rate is not None
                else None
            ),
            "commission_rate": str(applied_commission_rate),
            "commission_rate_source": (
                "manual" if manual_commission_rate is not None else "official_adjusted"
            ),
            "affiliate_rate": str(affiliate_rate),
            "ad_cost_type": item.get("ad_cost_type", "none"),
            "ad_cost_value": str(decimal(item.get("ad_cost_value"))),
            "fees": {key: str(money(value)) for key, value in line_fees.items()},
        })

    # Refunds have no SKU identity in this trial calculator.  Keep the
    # allocation deterministic by reducing the total payment base after all
    # SKU lines were rounded, and expose it in the returned basis.
    bases["transaction"] = max(Decimal("0.00"), money(bases["transaction"] - customer_refund))
    fee_totals["transaction_fee"] = rate_amount(bases["transaction"], TRANSACTION_RATE)
    sales_revenue = money(sales_revenue)
    buyer_shipping_total = money(buyer_shipping_total)
    revenue = sales_revenue
    tax_total = money(tax_total)
    fee_totals = {key: money(value) for key, value in fee_totals.items()}
    advertising_cost_total = fee_totals["advertising_cost"]
    costs_before_ads = money(
        sum(
            (
                value
                for key, value in fee_totals.items()
                if key != "advertising_cost"
            ),
            Decimal("0"),
        )
    )
    gross_profit = money(revenue - costs_before_ads)
    gross_margin = percentage(gross_profit, revenue)
    net_profit = money(gross_profit - advertising_cost_total) if has_ad_cost else None
    net_margin = percentage(net_profit, revenue) if net_profit is not None else None
    total_costs = money(costs_before_ads + advertising_cost_total)
    break_even_roi = money(revenue / gross_profit) if gross_profit > 0 else None
    break_even_cpa_usd = money(gross_profit * usd_per_myr)
    platform_fee_total = money(
        fee_totals["platform_commission"]
        + fee_totals["transaction_fee"]
        + fee_totals["bxp_fee"]
        + fee_totals["platform_support_fee"]
    )
    estimated_platform_payout = money(
        revenue
        - platform_fee_total
        - fee_totals["affiliate_commission"]
        - fee_totals["seller_shipping_cost"]
    )
    amount_summary = {
        "sales_revenue": str(sales_revenue),
        "buyer_shipping_revenue": str(buyer_shipping_total),
        "settlement_revenue": str(revenue),
        "platform_fees": str(platform_fee_total),
        "affiliate_commission": str(fee_totals["affiliate_commission"]),
        "logistics_cost": str(fee_totals["seller_shipping_cost"]),
        "estimated_platform_payout": str(estimated_platform_payout),
        "product_cost": str(fee_totals["product_cost"]),
        "gross_profit": str(gross_profit),
        "advertising_cost": str(advertising_cost_total),
        "net_profit": str(net_profit) if net_profit is not None else None,
        "net_margin": str(net_margin) if net_margin is not None else None,
    }

    weighted_commission_rate = (
        bases["commission_weighted_rate"] / bases["commission"]
        if bases["commission"]
        else None
    )
    weighted_affiliate_rate = (
        bases["affiliate_weighted_rate"] / bases["affiliate"]
        if bases["affiliate"]
        else None
    )

    def row(key, label, amount, kind, base, group, *, rate=None, **extra):
        item = {
            "key": key,
            "label": label,
            "amount": str(money(amount)),
            "kind": kind,
            "base": base,
            "group": group,
            "share": str(percentage(decimal(amount), revenue)),
            "rate": str(money(rate)) if rate is not None else None,
        }
        item.update(extra)
        return item

    rows = [
        row("sales_revenue", "商品售价合计", sales_revenue, "income", "各 SKU 售价合计；买家运费不计入收入", "收入"),
        row("product_cost", "商品采购成本", fee_totals["product_cost"], "cost", "人民币采购成本 ÷ 汇率", "商品"),
        row(
            "seller_shipping_cost",
            "商家运费（系统估算）",
            fee_totals["seller_shipping_cost"],
            "cost",
            "跨境：各 SKU 包装后重量向上取整至 10g 后分别计费；本土：0",
            "物流",
            source=MALAYSIA_CROSS_BORDER_SOURCE,
            source_detail="包装后重量向上取整至10g",
            effective_date=MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE,
        ),
        row(
            "buyer_shipping_fee",
            "买家运费（手动，默认 0）",
            buyer_shipping_total,
            "reference",
            "不计入收入及物流成本；仅加入支付交易手续费基数",
            "物流",
            editable=True,
            exclude_from_group_total=True,
        ),
        row(
            "platform_commission",
            "类目佣金",
            fee_totals["platform_commission"],
            "fee",
            "商品售价（卖家折扣固定为 0）",
            "平台代扣",
            rate=weighted_commission_rate,
            editable=True,
            rate_source=(
                "manual"
                if has_manual_commission_rate
                else "official_adjusted"
            ),
            source=COMMISSION_SOURCE,
            effective_date="2026-06-06",
        ),
        row(
            "transaction_fee",
            "支付交易手续费",
            fee_totals["transaction_fee"],
            "fee",
            "商品售价 + 买家运费 - 客户退款",
            "平台代扣",
            rate=TRANSACTION_RATE,
            source=TRANSACTION_SOURCE,
            effective_date="2026-02-15",
        ),
        row(
            "bxp_fee",
            "BXP 增值服务费",
            fee_totals["bxp_fee"],
            "fee",
            "商品售价；每件最高 RM54",
            "平台代扣",
            rate=BXP_RATE if bxp else Decimal("0"),
            source=COMMISSION_SOURCE,
            effective_date="2025-09-13",
        ),
        row(
            "platform_support_fee",
            "每件平台支持费",
            fee_totals["platform_support_fee"],
            "fee",
            "每个已送达订单收取 RM0.54；按 SKU 商品售价比例分摊，最高售价 SKU 承担舍入尾差",
            "平台代扣",
            source=SUPPORT_FEE_SOURCE,
            effective_date="2026-02-15",
        ),
        row(
            "affiliate_commission",
            "达人推广佣金",
            fee_totals["affiliate_commission"],
            "fee",
            "含税售价 − 自动拆分的 LVG 商品税",
            "推广代扣",
            rate=weighted_affiliate_rate,
            source=AFFILIATE_SOURCE,
            effective_date="2026-02-19",
        ),
        row(
            "lvg_product_tax",
            "LVG 商品税（售价内含）",
            tax_total,
            "info",
            "跨境且税前货值 ≤ RM500：含税售价 × 10/110；仅展示，不重复扣除",
            "税费",
            rate=LVG_RATE if seller_type == "cross_border" else Decimal("0"),
            source=LVG_TAX_SOURCE,
            effective_date="2024-01-01",
        ),
        row(
            "advertising_cost",
            "实际广告投入",
            advertising_cost_total,
            "cost",
            "仅在填写实际 ROI、CPA 或广告费占比后计入",
            "广告投放",
        ),
    ]

    group_business_order = {
        "收入": 0,
        "商品": 1,
        "物流": 2,
        "平台代扣": 3,
        "推广代扣": 4,
        "税费": 5,
        "广告投放": 6,
    }
    item_business_order = {item["key"]: index for index, item in enumerate(rows)}
    groups = []
    for group_name in group_business_order:
        group_items = [item for item in rows if item["group"] == group_name]
        if not group_items:
            continue
        included = [item for item in group_items if not item.get("exclude_from_group_total")]
        group_amount = money(sum((decimal(item["amount"]) for item in included), Decimal("0")))
        group_kind = "income" if group_name == "收入" else ("info" if group_name == "税费" else "cost")
        group_items.sort(
            key=lambda item: (
                decimal(item["amount"]) == 0,
                -abs(decimal(item["amount"])),
                item_business_order[item["key"]],
            )
        )
        groups.append({
            "key": group_name,
            "label": group_name,
            "kind": group_kind,
            "amount": str(group_amount),
            "share": str(percentage(group_amount, revenue)),
            "items": group_items,
            "business_order": group_business_order[group_name],
        })

    income_group = next(group for group in groups if group["key"] == "收入")
    remaining_groups = [group for group in groups if group["key"] != "收入"]
    remaining_groups.sort(
        key=lambda group: (
            decimal(group["amount"]) == 0,
            -abs(decimal(group["share"])),
            group["business_order"],
        )
    )
    breakdown_groups = [income_group, *remaining_groups]
    for group in breakdown_groups:
        group.pop("business_order", None)
    breakdown = [item for group in breakdown_groups for item in group["items"]]

    warnings = [
        "跨境商家运费按上传的马来西亚价目表估算：每个 SKU 的包装后重量分别向上取整至 10g；本土发货为 0。",
        "买家运费默认 0，可在费用明细中临时修改；它不增加收入、不抵扣商家运费，只进入支付交易手续费基数。",
        "LVG 10% 已包含在售价中，本页只拆分展示税额，不再次扣作卖家成本。",
        "类目佣金默认使用官方名义佣金加本次试算的调试百分点；手动佣金率优先，清空后自动恢复。",
        "结果不含临时补贴、活动减免、退款调整或税前货值超过 RM500 后可能发生的进口税费。",
    ]
    if not has_ad_cost:
        warnings.append("尚未填写实际广告数据；当前展示广告前毛利，不生成净利润和净利率。")
    if any(decimal(item["item_price"]) > LVG_TAX_INCLUSIVE_LIMIT for item in items) and seller_type == "cross_border":
        warnings.append("存在税前货值超过 RM500 的商品：不适用 LVG 规则；进口税费需要 HS 编码和海关估值，本页未猜测计入。")

    return {
        "currency": "MYR",
        "revenue": str(revenue),
        "total_costs": str(total_costs),
        "costs_before_ads": str(costs_before_ads),
        "advertising_cost": str(advertising_cost_total),
        "gross_profit": str(gross_profit),
        "gross_margin": str(gross_margin),
        "net_profit": str(net_profit) if net_profit is not None else None,
        "net_margin": str(net_margin) if net_margin is not None else None,
        "has_ad_cost": has_ad_cost,
        "profit": str(gross_profit),
        "profit_rate": str(gross_margin),
        "break_even_cpa": str(gross_profit),
        "break_even_cpa_usd": str(break_even_cpa_usd),
        "break_even_roi": str(break_even_roi) if break_even_roi is not None else None,
        "break_even_roas": str(break_even_roi) if break_even_roi is not None else None,
        "items": item_results,
        "breakdown": breakdown,
        "breakdown_groups": breakdown_groups,
        "amount_summary": amount_summary,
        "commission_adjustment": str(commission_adjustment),
        "customer_refund": str(customer_refund),
        "shipping_rate_version": MALAYSIA_CROSS_BORDER_RATE_VERSION,
        "shipping_max_weight_g": str(MALAYSIA_CROSS_BORDER_MAX_G),
        "rule_version": RULE_VERSION,
        "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "warnings": warnings,
    }


def calculate_profit(payload: dict) -> dict:
    """Calculate a Malaysia profit trial using one server-side settlement model.

    The browser submits inputs only.  This function is the single authority for
    freight, tax, fees, settlement and profit totals.
    """
    shop_identity = payload.get("shop_identity", "marketplace")
    seller_type = payload.get("seller_type", "cross_border")
    bxp = bool(payload.get("bxp", False))
    delivered = bool(payload.get("delivered", True))
    cny_per_myr = decimal(payload.get("cny_per_myr", "1"))
    usd_per_myr = decimal(payload.get("usd_per_myr", "0.235"))
    commission_adjustment = decimal(payload.get("commission_adjustment", "0"))
    transaction_fee_adjustment = decimal(payload.get("transaction_fee_adjustment", "0"))
    advertising_rebate_percent = min(
        PERCENT,
        max(Decimal("0"), decimal(payload.get("advertising_rebate_percent", "0"))),
    )
    official_transaction_rate = TRANSACTION_RATE
    applied_transaction_rate = max(Decimal("0"), official_transaction_rate + transaction_fee_adjustment)
    customer_refund = money(payload.get("customer_refund", 0))
    buyer_pays_shipping = bool(payload.get("buyer_pays_shipping", False))
    buyer_shipping_region = payload.get("buyer_shipping_region", "west_malaysia")
    buyer_shipping_total = (
        money(malaysia_standard_buyer_shipping(buyer_shipping_region))
        if buyer_pays_shipping and seller_type == "cross_border"
        else Decimal("0.00")
    )
    items = payload["items"]

    support_inputs = []
    for item in items:
        rule = resolve_category(item["category_code"])
        support_inputs.append({"item_price": money(item["item_price"]), "support_fee_exempt": rule.support_fee_exempt})
    support_allocations = _allocate_order_support_fee(support_inputs, delivered)

    fee_totals = {key: Decimal("0") for key in (
        "product_cost", "seller_shipping_cost", "platform_commission", "transaction_fee",
        "affiliate_commission", "bxp_fee", "platform_support_fee", "lvg_product_tax",
        "other_platform_settlement_fee", "advertising_cost_before_rebate",
        "advertising_rebate_amount", "advertising_cost",
    )}
    bases = {"commission": Decimal("0"), "commission_weighted_rate": Decimal("0"), "affiliate": Decimal("0"), "affiliate_weighted_rate": Decimal("0")}
    sales_revenue = Decimal("0")
    item_results = []
    has_ad_cost = False
    ad_attributed_revenue = Decimal("0")
    cpa_true_values = []
    ad_input_types = []
    has_manual_commission_rate = False

    for index, item in enumerate(items):
        item_price = money(item["item_price"])
        weight_g = decimal(item["weight_g"])
        rounded_weight_g, estimated_shipping = malaysia_cross_border_shipping(weight_g)
        seller_shipping = money(estimated_shipping) if seller_type == "cross_border" else Decimal("0.00")
        product_tax = inclusive_lvg_tax(item_price, seller_type)
        affiliate_base = max(Decimal("0"), item_price - product_tax)
        rule = resolve_category(item["category_code"])
        official_rate = rule.rate(shop_identity, bxp)
        manual_rate = item.get("manual_commission_rate")
        if manual_rate is not None:
            manual_rate = decimal(manual_rate)
            has_manual_commission_rate = True
        if official_rate is None and manual_rate is None:
            raise ValueError("所选三级类目没有官方佣金率，请在费用明细中手动填写类目佣金率。")
        system_rate = min(PERCENT, max(Decimal("0"), official_rate + commission_adjustment)) if official_rate is not None else None
        commission_rate = manual_rate if manual_rate is not None else system_rate
        ad = advertising_costs(
            item_price, item, usd_per_myr, advertising_rebate_percent
        )
        if ad["has_ad_input"]:
            has_ad_cost = True
            ad_attributed_revenue += item_price
            ad_input_types.append(item.get("ad_cost_type", "none"))
            if ad["true_cpa_usd"] is not None:
                cpa_true_values.append(decimal(ad["true_cpa_usd"]))
        line_fees = {
            "product_cost": money(decimal(item.get("product_cost_cny", 0)) / cny_per_myr),
            "seller_shipping_cost": seller_shipping,
            "platform_commission": rate_amount(item_price, commission_rate),
            # The order-level fee is assigned after its one shared basis is known.
            "transaction_fee": Decimal("0.00"),
            "affiliate_commission": rate_amount(affiliate_base, decimal(item.get("affiliate_rate", 0))),
            "bxp_fee": min(rate_amount(item_price, BXP_RATE), BXP_FEE_CAP) if bxp else Decimal("0.00"),
            "platform_support_fee": support_allocations[index],
            "lvg_product_tax": product_tax,
            "other_platform_settlement_fee": Decimal("0.00"),
            "advertising_cost_before_rebate": ad["advertising_cost_before_rebate"],
            "advertising_rebate_amount": ad["advertising_rebate_amount"],
            "advertising_cost": ad["advertising_cost"],
        }
        sales_revenue += item_price
        bases["commission"] += item_price
        bases["commission_weighted_rate"] += item_price * commission_rate
        bases["affiliate"] += affiliate_base
        bases["affiliate_weighted_rate"] += affiliate_base * decimal(item.get("affiliate_rate", 0))
        for key, value in line_fees.items():
            fee_totals[key] += value
        item_results.append({
            "sku_name": item.get("sku_name") or "SKU", "category": rule.label, "category_code": rule.code,
            "weight_g": str(weight_g), "rounded_weight_g": rounded_weight_g, "shipping_tier_g": rounded_weight_g,
            "buyer_shipping_fee": str(buyer_shipping_total if index == 0 else Decimal("0.00")),
            "transaction_base": str(money(item_price + (buyer_shipping_total if index == 0 else Decimal("0.00")))),
            "seller_shipping_cost": str(seller_shipping), "shipping_estimate": str(money(estimated_shipping)),
            "product_tax": str(product_tax),
            "lvg_status": "applied" if product_tax else ("outside_range" if seller_type == "cross_border" and item_price > LVG_LIMIT else "not_applicable"),
            "revenue": str(item_price), "commission_base": str(item_price),
            "affiliate_base": str(money(affiliate_base)),
            "official_commission_rate": str(official_rate) if official_rate is not None else None,
            "system_commission_rate": str(system_rate) if system_rate is not None else None,
            "commission_rate": str(commission_rate),
            "commission_rate_source": "manual" if manual_rate is not None else "official_adjusted",
            "affiliate_rate": str(decimal(item.get("affiliate_rate", 0))),
            "ad_cost_type": item.get("ad_cost_type", "none"), "ad_cost_value": str(decimal(item.get("ad_cost_value"))),
            "advertising_cost_before_rebate": str(ad["advertising_cost_before_rebate"]),
            "advertising_rebate_percent": str(money(ad["advertising_rebate_percent"])),
            "advertising_rebate_source": ad["advertising_rebate_source"],
            "advertising_rebate_amount": str(ad["advertising_rebate_amount"]),
            "advertising_cost": str(ad["advertising_cost"]),
            "original_roi": ad["original_roi"],
            "original_cpa_usd": ad["original_cpa_usd"],
            "true_roi": ad["true_roi"],
            "true_roi_status": ad["true_roi_status"],
            "true_cpa_usd": ad["true_cpa_usd"],
            "fees": {key: str(money(value)) for key, value in line_fees.items()},
        })

    sales_revenue = money(sales_revenue)
    transaction_base = max(Decimal("0"), money(sales_revenue + buyer_shipping_total - customer_refund))
    fee_totals["transaction_fee"] = rate_amount(transaction_base, applied_transaction_rate)
    # Transaction fees are priced at order level.  Keep the per-SKU response
    # reconcilable without multiplying the charge: show the full order fee on
    # the deterministic first row.
    if item_results:
        item_results[0]["fees"]["transaction_fee"] = str(fee_totals["transaction_fee"])
    fee_totals = {key: money(value) for key, value in fee_totals.items()}

    item_cost_keys = (
        "product_cost", "seller_shipping_cost", "platform_commission",
        "transaction_fee", "affiliate_commission", "bxp_fee",
        "platform_support_fee", "lvg_product_tax",
        "other_platform_settlement_fee",
    )
    for item_result in item_results:
        item_revenue = decimal(item_result["revenue"])
        item_costs_before_ads = money(sum(
            (decimal(item_result["fees"].get(key, "0")) for key in item_cost_keys),
            Decimal("0"),
        ))
        item_gross_profit = money(item_revenue - item_costs_before_ads)
        item_actual_ad_cost = decimal(item_result["advertising_cost"])
        item_net_profit = (
            money(item_gross_profit - item_actual_ad_cost)
            if item_result["true_roi_status"] != "unavailable"
            else None
        )
        item_result.update({
            "costs_before_ads": str(item_costs_before_ads),
            "gross_profit": str(item_gross_profit),
            "gross_margin": str(percentage(item_gross_profit, item_revenue)),
            "net_profit": str(item_net_profit) if item_net_profit is not None else None,
            "net_margin": (
                str(percentage(item_net_profit, item_revenue))
                if item_net_profit is not None else None
            ),
        })
    platform_fee_total = money(sum((fee_totals[key] for key in ("platform_commission", "transaction_fee", "bxp_fee", "platform_support_fee", "other_platform_settlement_fee")), Decimal("0")))
    total_fees = money(platform_fee_total + fee_totals["affiliate_commission"] + fee_totals["lvg_product_tax"] + fee_totals["seller_shipping_cost"])
    settlement_amount = money(sales_revenue - total_fees)
    costs_before_ads = money(total_fees + fee_totals["product_cost"])
    gross_profit = money(sales_revenue - costs_before_ads)
    gross_margin = percentage(gross_profit, sales_revenue)
    advertising_cost_before_rebate_total = fee_totals["advertising_cost_before_rebate"]
    advertising_rebate_amount_total = fee_totals["advertising_rebate_amount"]
    advertising_cost_total = fee_totals["advertising_cost"]
    costs_after_ads = money(costs_before_ads + advertising_cost_total) if has_ad_cost else None
    net_profit = money(sales_revenue - costs_after_ads) if costs_after_ads is not None else None
    net_margin = percentage(net_profit, sales_revenue) if net_profit is not None else None
    if not has_ad_cost:
        true_roi = None
        true_roi_status = "unavailable"
    elif advertising_cost_total == 0:
        true_roi = "Infinity"
        true_roi_status = "infinite"
    else:
        true_roi = str(money(ad_attributed_revenue / advertising_cost_total))
        true_roi_status = "available"
    true_cpa_usd = None
    if ad_input_types and all(value == "cpa_usd" for value in ad_input_types):
        true_cpa_usd = str(money(sum(cpa_true_values, Decimal("0")) / len(cpa_true_values)))
    weighted_commission_rate = bases["commission_weighted_rate"] / bases["commission"] if bases["commission"] else None
    weighted_affiliate_rate = bases["affiliate_weighted_rate"] / bases["affiliate"] if bases["affiliate"] else None

    def row(key, label, amount, kind, base, group, *, rate=None, **extra):
        value = money(amount)
        result = {"key": key, "label": label, "amount": str(value), "kind": kind, "base": base, "group": group,
                  "share": str(percentage(value, sales_revenue)), "rate": str(money(rate)) if rate is not None else None}
        result.update(extra)
        return result

    rows = [
        row("sales_revenue", "商品售价合计", sales_revenue, "income", "所有 SKU 商品售价合计；买家运费不计入收入", "收入"),
        row("product_cost", "商品采购成本", fee_totals["product_cost"], "cost", "人民币采购成本 ÷ MYR/CNY 汇率", "商品"),
        row("seller_shipping_cost", "商家运费（系统估算）", fee_totals["seller_shipping_cost"], "cost", "跨境按每个 SKU 包装重量向上取整至 10g；本土为 RM0", "物流", source=MALAYSIA_CROSS_BORDER_SOURCE, source_detail="包装后重量向上取整至10g", effective_date=MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE),
        row("buyer_shipping_fee", "买家运费（订单 Standard）", buyer_shipping_total, "reference", "按订单只计算一次；不计入收入或物流小计，只加入交易手续费基数", "物流", exclude_from_group_total=True, source=MALAYSIA_STANDARD_BUYER_SHIPPING_SOURCE, effective_date=MALAYSIA_STANDARD_BUYER_SHIPPING_EFFECTIVE_DATE),
        row("platform_commission", "类目佣金", fee_totals["platform_commission"], "fee", "商品售价", "平台代扣", rate=weighted_commission_rate, editable=True, rate_source="manual" if has_manual_commission_rate else "official_adjusted", source=COMMISSION_SOURCE),
        row("transaction_fee", "支付交易手续费", fee_totals["transaction_fee"], "fee", "商品售价 + 买家运费 - 客户退款", "平台代扣", rate=applied_transaction_rate, official_rate=str(official_transaction_rate), adjustment=str(transaction_fee_adjustment), source=TRANSACTION_SOURCE),
        row("bxp_fee", "BXP 增值服务费", fee_totals["bxp_fee"], "fee", "商品售价；每件最高 RM54", "平台代扣", rate=BXP_RATE if bxp else Decimal("0"), source=COMMISSION_SOURCE),
        row("platform_support_fee", "每单平台支持费", fee_totals["platform_support_fee"], "fee", "每个已送达订单收取 RM0.54，按 SKU 分摊", "平台代扣", source=SUPPORT_FEE_SOURCE),
        row("affiliate_commission", "达人推广佣金", fee_totals["affiliate_commission"], "fee", "含税售价 − 自动拆分的 LVG 商品税", "推广代扣", rate=weighted_affiliate_rate, source=AFFILIATE_SOURCE),
        row("lvg_product_tax", "LVG 商品税（售价内含）", fee_totals["lvg_product_tax"], "fee", "跨境且单件原始售价 ≤ RM500：售价 × 10/110；已在售价内含但作为结算扣费计入一次", "税费", rate=LVG_RATE if seller_type == "cross_border" else Decimal("0"), source=LVG_TAX_SOURCE),
        row("advertising_cost_before_rebate", "返点前广告成本", advertising_cost_before_rebate_total, "reference", "按 ROI、CPA 或广告占比换算；逐 SKU 舍入后汇总", "广告投放", exclude_from_group_total=True),
        row("advertising_rebate_amount", "广告返点金额", advertising_rebate_amount_total, "reference", "返点前广告成本 × 每个 SKU 的有效返点比例", "广告投放", exclude_from_group_total=True),
        row("advertising_cost", "实际广告投入", advertising_cost_total, "cost", "返点前广告成本 − 广告返点金额", "广告投放"),
    ]
    business_order = {"收入": 0, "商品": 1, "物流": 2, "平台代扣": 3, "推广代扣": 4, "税费": 5, "广告投放": 6}
    item_order = {item["key"]: index for index, item in enumerate(rows)}
    groups = []
    for group_name, order in business_order.items():
        group_items = [item for item in rows if item["group"] == group_name]
        included = [item for item in group_items if not item.get("exclude_from_group_total")]
        amount = money(sum((decimal(item["amount"]) for item in included), Decimal("0")))
        group_items.sort(key=lambda item: (decimal(item["amount"]) == 0, -abs(decimal(item["amount"])), item_order[item["key"]]))
        groups.append({"key": group_name, "label": group_name, "kind": "income" if group_name == "收入" else "cost", "amount": str(amount), "share": str(percentage(amount, sales_revenue)), "items": group_items, "business_order": order})
    income, *remaining = groups
    remaining.sort(key=lambda group: (decimal(group["amount"]) == 0, -abs(decimal(group["share"])), group["business_order"]))
    breakdown_groups = [income, *remaining]
    for group in breakdown_groups:
        group.pop("business_order", None)

    return {
        "currency": "MYR", "revenue": str(sales_revenue), "total_fees": str(total_fees), "settlement_amount": str(settlement_amount),
        "total_costs": str(costs_after_ads) if costs_after_ads is not None else str(costs_before_ads), "costs_before_ads": str(costs_before_ads),
        "costs_after_ads": str(costs_after_ads) if costs_after_ads is not None else None,
        "advertising_cost_before_rebate": str(advertising_cost_before_rebate_total),
        "advertising_rebate_percent": str(money(advertising_rebate_percent)),
        "advertising_rebate_amount": str(advertising_rebate_amount_total),
        "advertising_cost": str(advertising_cost_total),
        "true_roi": true_roi, "true_roi_status": true_roi_status,
        "true_cpa_usd": true_cpa_usd,
        "gross_profit": str(gross_profit), "gross_margin": str(gross_margin), "net_profit": str(net_profit) if net_profit is not None else None,
        "net_margin": str(net_margin) if net_margin is not None else None, "has_ad_cost": has_ad_cost, "profit": str(gross_profit), "profit_rate": str(gross_margin),
        "break_even_cpa": str(gross_profit), "break_even_cpa_usd": str(money(gross_profit * usd_per_myr)), "break_even_roi": str(money(sales_revenue / gross_profit)) if gross_profit > 0 else None,
        "items": item_results, "breakdown_groups": breakdown_groups, "breakdown": [item for group in breakdown_groups for item in group["items"]],
        "amount_summary": {"total_revenue": str(sales_revenue), "total_fees": str(total_fees), "settlement_amount": str(settlement_amount), "costs_before_ads": str(costs_before_ads), "gross_profit": str(gross_profit), "gross_margin": str(gross_margin), "advertising_cost_before_rebate": str(advertising_cost_before_rebate_total), "advertising_rebate_amount": str(advertising_rebate_amount_total), "advertising_cost": str(advertising_cost_total), "true_roi": true_roi, "true_roi_status": true_roi_status, "true_cpa_usd": true_cpa_usd, "costs_after_ads": str(costs_after_ads) if costs_after_ads is not None else None, "net_profit": str(net_profit) if net_profit is not None else None, "net_margin": str(net_margin) if net_margin is not None else None},
        "shipping": {"buyer_pays_shipping": buyer_pays_shipping, "buyer_shipping_region": buyer_shipping_region, "buyer_shipping_amount": str(buyer_shipping_total), "buyer_shipping_rate_version": MALAYSIA_STANDARD_BUYER_SHIPPING_RATE_VERSION},
        "transaction_fee": {"official_rate": str(money(official_transaction_rate)), "adjustment": str(money(transaction_fee_adjustment)), "applied_rate": str(money(applied_transaction_rate)), "base": str(transaction_base), "amount": str(fee_totals["transaction_fee"])},
        "commission_adjustment": str(commission_adjustment), "customer_refund": str(customer_refund),
        "shipping_rate_version": MALAYSIA_CROSS_BORDER_RATE_VERSION, "shipping_max_weight_g": str(MALAYSIA_CROSS_BORDER_MAX_G), "rule_version": RULE_VERSION, "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "warnings": [],
    }

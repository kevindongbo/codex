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
    malaysia_cross_border_shipping,
)


MONEY = Decimal("0.01")
PERCENT = Decimal("100")
RULE_EFFECTIVE_DATE = date(2026, 8, 2)
RULE_VERSION = "MY-TTS-2026-08-02-v5"
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
LVG_TAX_INCLUSIVE_LIMIT = money(LVG_LIMIT * (PERCENT + LVG_RATE) / PERCENT)


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
    tax_exclusive_value = item_price * PERCENT / (PERCENT + LVG_RATE)
    if seller_type != "cross_border" or tax_exclusive_value > LVG_LIMIT:
        return Decimal("0.00")
    return money(item_price * LVG_RATE / (PERCENT + LVG_RATE))


def advertising_cost(item_revenue: Decimal, item: dict, usd_per_myr: Decimal) -> Decimal:
    """Return optional actual ad cost in MYR without guessing missing inputs."""
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


def calculate_profit(payload: dict) -> dict:
    shop_identity = payload.get("shop_identity", "marketplace")
    seller_type = payload.get("seller_type", "cross_border")
    bxp = bool(payload.get("bxp", False))
    delivered = bool(payload.get("delivered", True))
    cny_per_myr = decimal(payload.get("cny_per_myr", "1"))
    usd_per_myr = decimal(payload.get("usd_per_myr", "0.235"))
    commission_adjustment = decimal(payload.get("commission_adjustment", "1.00"))
    manual_commission_rate = payload.get("manual_commission_rate")
    if manual_commission_rate is not None:
        manual_commission_rate = decimal(manual_commission_rate)
    items = payload["items"]

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

    for item in items:
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
        transaction_base = money(item_price + buyer_shipping_fee)

        rule = resolve_category(item["category_code"])
        official_commission_rate = rule.rate(shop_identity, bxp)
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
        support_fee = (
            PLATFORM_SUPPORT_FEE
            if delivered and not rule.support_fee_exempt
            else Decimal("0.00")
        )
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
            rate_source="manual" if manual_commission_rate is not None else "official_adjusted",
            source=COMMISSION_SOURCE,
            effective_date="2026-06-06",
        ),
        row(
            "transaction_fee",
            "支付交易手续费",
            fee_totals["transaction_fee"],
            "fee",
            "商品售价 + 买家运费",
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
            "每个 SKU 收取 RM0.54；指定基础类目自动豁免",
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
                item["key"] == "buyer_shipping_fee",
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
        "manual_commission_rate": (
            str(manual_commission_rate)
            if manual_commission_rate is not None
            else None
        ),
        "shipping_rate_version": MALAYSIA_CROSS_BORDER_RATE_VERSION,
        "shipping_max_weight_g": str(MALAYSIA_CROSS_BORDER_MAX_G),
        "rule_version": RULE_VERSION,
        "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "warnings": warnings,
    }

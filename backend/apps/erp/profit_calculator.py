"""TikTok Shop Malaysia profit calculation.

The module deliberately separates three concepts:
- official_auto: versioned rule-table estimate;
- manual_override: user supplied rate used for estimates only;
- actual_settlement: TikTok settlement amount, which always wins for settled orders.

Money is calculated with Decimal and rounded per fee line before aggregation.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from .profit_category_data import CATEGORY_ROWS
from .profit_category_taxonomy import CATEGORY_TAXONOMY, iter_taxonomy_leaves

MONEY = Decimal("0.01")
PERCENT = Decimal("100")
RULE_EFFECTIVE_DATE = date(2026, 7, 1)
COMMISSION_SOURCE = "https://seller-my.tiktok.com/university/essay?knowledge_id=6907739532281602&lang=en"
TRANSACTION_SOURCE = "https://seller-my.tiktok.com/university/essay?knowledge_id=10013511&lang=en"
SUPPORT_FEE_SOURCE = "https://seller-my.tiktok.com/university/essay?knowledge_id=7992113007347457&lang=en"
AFFILIATE_SOURCE = "https://seller-my.tiktok.com/university/essay?knowledge_id=6837846988539650&lang=en"
SHIPPING_SOURCE = "东南亚跨境物流运费价格表20260515"
SHIPPING_CALCULATION_SOURCE = SHIPPING_SOURCE
LVG_TAX_SOURCE = "https://mysst.customs.gov.my/assets/document/Industry%20Guides/GI/Guide%20on%20Low%20Value%20Goods_Draft.pdf"

TRANSACTION_RATE = Decimal("3.78")
BXP_RATE = Decimal("4.86")
BXP_FEE_CAP = Decimal("54.00")
PLATFORM_SUPPORT_FEE = Decimal("0.54")
LVG_RATE = Decimal("10.00")
LVG_LIMIT = Decimal("500.00")
CROSS_BORDER_PER_10G = Decimal("0.15")
WEST_MALAYSIA_LAST_MILE = Decimal("2.90")
EAST_MALAYSIA_LAST_MILE = Decimal("8.00")


def decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def money(value) -> Decimal:
    return decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def rate_amount(base: Decimal, rate: Decimal) -> Decimal:
    return money(decimal(base) * decimal(rate) / PERCENT)


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
    def label(self):
        return " / ".join((self.industry, self.level_one, self.level_two))

    def rate(self, shop_identity, bxp):
        if shop_identity == "mall":
            return self.mall_bxp if bxp else self.mall_standard
        return self.marketplace_bxp if bxp else self.marketplace_standard


CATEGORY_RULES = {
    row[0]: CategoryRule(
        code=row[0], industry=row[1], level_one=row[2], level_two=row[3],
        marketplace_bxp=Decimal(row[4]), marketplace_standard=Decimal(row[5]),
        mall_bxp=Decimal(row[6]), mall_standard=Decimal(row[7]),
        support_fee_exempt=row[8],
    )
    for row in CATEGORY_ROWS
}
for root_label, group_label, code, label, parent_code in iter_taxonomy_leaves():
    CATEGORY_RULES[code] = replace(
        CATEGORY_RULES[parent_code], code=code, industry=root_label,
        level_one=group_label, level_two=label,
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


def resolve_category(code):
    return CATEGORY_RULES[LEGACY_CATEGORY_ALIASES.get(code, code)]


def category_config():
    return [{
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
    } for rule in CATEGORY_RULES.values()]


def category_tree():
    return [{
        "label": root["label"],
        "children": [{
            "label": group["label"],
            "children": [{"code": code, "label": label} for code, label in group["children"]],
        } for group in root["children"]],
    } for root in CATEGORY_TAXONOMY]


def inclusive_lvg_tax(item_price, seller_type):
    tax_exclusive = decimal(item_price) * PERCENT / (PERCENT + LVG_RATE)
    if seller_type != "cross_border" or tax_exclusive > LVG_LIMIT:
        return Decimal("0.00")
    return money(decimal(item_price) * LVG_RATE / (PERCENT + LVG_RATE))


def shipping_estimate(weight_g, region="west_malaysia"):
    """Return chargeable grams and complete merchant cross-border logistics cost."""
    grams = max(Decimal("10"), decimal(weight_g))
    units = int((grams / Decimal("10")).to_integral_value(rounding=ROUND_CEILING))
    chargeable_g = units * 10
    last_mile = EAST_MALAYSIA_LAST_MILE if region == "east_malaysia" else WEST_MALAYSIA_LAST_MILE
    return chargeable_g, money(Decimal(units) * CROSS_BORDER_PER_10G + last_mile)


def advertising_cost(total_revenue, item, usd_per_myr):
    cost_type = item.get("ad_cost_type", "none")
    value = decimal(item.get("ad_cost_value"))
    if value <= 0 or cost_type == "none":
        return Decimal("0.00")
    if cost_type == "roi":
        return money(total_revenue / value)
    if cost_type == "cpa_usd":
        return money(value / usd_per_myr)
    if cost_type == "ratio":
        return rate_amount(total_revenue, value)
    return Decimal("0.00")


def _applied_rate(item, payload, key, official_rate):
    """Resolve estimate rate. Per-item override beats top-level override beats official."""
    item_value = item.get(key)
    payload_value = payload.get(key)
    if item_value not in (None, ""):
        return decimal(item_value), "manual_override"
    if payload_value not in (None, ""):
        return decimal(payload_value), "manual_override"
    return decimal(official_rate), "official_auto"


def _actual(item, key):
    value = item.get(key)
    return None if value in (None, "") else money(abs(decimal(value)))


def calculate_profit(payload):
    shop_identity = payload.get("shop_identity", "marketplace")
    seller_type = payload.get("seller_type", "cross_border")
    bxp = bool(payload.get("bxp", False))
    cny_per_myr = decimal(payload.get("cny_per_myr", "1"))
    usd_per_myr = decimal(payload.get("usd_per_myr", "0.235"))
    destination_region = payload.get("destination_region", "west_malaysia")

    totals = {key: Decimal("0") for key in (
        "product_cost", "seller_shipping_cost", "platform_commission",
        "transaction_fee", "affiliate_commission", "bxp_fee", "advertising_cost",
    )}
    sales_revenue = Decimal("0")
    tax_total = Decimal("0")
    support_exemptions = []
    item_results = []
    has_ad_cost = False

    for item in payload["items"]:
        item_price = money(item["item_price"])
        buyer_shipping = money(item.get("buyer_shipping_paid", 0))
        weight_g = decimal(item["weight_g"])
        rule = resolve_category(item["category_code"])
        official_commission_rate = rule.rate(shop_identity, bxp)
        commission_rate, commission_rate_source = _applied_rate(item, payload, "commission_rate_override", official_commission_rate)
        transaction_rate, transaction_rate_source = _applied_rate(item, payload, "transaction_rate_override", TRANSACTION_RATE)
        bxp_rate, bxp_rate_source = _applied_rate(item, payload, "bxp_rate_override", BXP_RATE)
        affiliate_rate, affiliate_rate_source = _applied_rate(item, payload, "affiliate_rate_override", item.get("affiliate_rate", 0))

        product_tax = inclusive_lvg_tax(item_price, seller_type)
        affiliate_base = max(Decimal("0"), item_price - product_tax)
        chargeable_g, table_shipping = shipping_estimate(weight_g, item.get("destination_region", destination_region))
        estimated_shipping = table_shipping if seller_type == "cross_border" else Decimal("0.00")

        actual_commission = _actual(item, "actual_platform_commission")
        actual_transaction = _actual(item, "actual_transaction_fee")
        actual_bxp = _actual(item, "actual_bxp_fee")
        actual_affiliate = _actual(item, "actual_affiliate_commission")
        actual_shipping = _actual(item, "actual_seller_shipping_cost")

        commission_amount = actual_commission if actual_commission is not None else rate_amount(item_price, commission_rate)
        transaction_base = money(item_price + buyer_shipping)
        transaction_amount = actual_transaction if actual_transaction is not None else rate_amount(transaction_base, transaction_rate)
        estimated_bxp = min(rate_amount(item_price, bxp_rate), BXP_FEE_CAP) if bxp else Decimal("0.00")
        bxp_amount = actual_bxp if actual_bxp is not None else estimated_bxp
        affiliate_amount = actual_affiliate if actual_affiliate is not None else rate_amount(affiliate_base, affiliate_rate)
        shipping_amount = actual_shipping if actual_shipping is not None else estimated_shipping
        ad_amount = advertising_cost(item_price, item, usd_per_myr)
        has_ad_cost = has_ad_cost or ad_amount > 0

        line = {
            "product_cost": money(decimal(item.get("product_cost_cny", 0)) / cny_per_myr),
            "seller_shipping_cost": money(shipping_amount),
            "platform_commission": money(commission_amount),
            "transaction_fee": money(transaction_amount),
            "affiliate_commission": money(affiliate_amount),
            "bxp_fee": money(bxp_amount),
            "advertising_cost": money(ad_amount),
        }
        for key, value in line.items():
            totals[key] += value
        sales_revenue += item_price
        tax_total += product_tax
        support_exemptions.append(rule.support_fee_exempt)

        item_results.append({
            "sku_name": item.get("sku_name") or "SKU",
            "category": rule.label,
            "weight_g": str(weight_g),
            "chargeable_weight_g": chargeable_g,
            "buyer_shipping_fee": str(buyer_shipping),
            "seller_shipping_cost": str(line["seller_shipping_cost"]),
            "shipping_estimate": str(estimated_shipping),
            "product_tax": str(product_tax),
            "revenue": str(item_price),
            "commission_base": str(item_price),
            "transaction_base": str(transaction_base),
            "affiliate_base": str(money(affiliate_base)),
            "commission_rate": str(commission_rate),
            "official_commission_rate": str(official_commission_rate),
            "commission_rate_source": "actual_settlement" if actual_commission is not None else commission_rate_source,
            "transaction_rate": str(transaction_rate),
            "transaction_rate_source": "actual_settlement" if actual_transaction is not None else transaction_rate_source,
            "bxp_rate": str(bxp_rate if bxp else Decimal("0")),
            "bxp_rate_source": "actual_settlement" if actual_bxp is not None else bxp_rate_source,
            "affiliate_rate": str(affiliate_rate),
            "affiliate_rate_source": "actual_settlement" if actual_affiliate is not None else affiliate_rate_source,
            "fees": {key: str(value) for key, value in line.items()},
        })

    sales_revenue = money(sales_revenue)
    totals = {key: money(value) for key, value in totals.items()}
    support_override = payload.get("platform_support_fee_override")
    support_fee = (
        money(support_override) if support_override not in (None, "")
        else Decimal("0.00") if not payload.get("delivered", True) or all(support_exemptions)
        else PLATFORM_SUPPORT_FEE
    )
    actual_support = payload.get("actual_platform_support_fee")
    if actual_support not in (None, ""):
        support_fee = money(abs(decimal(actual_support)))

    platform_fee_total = money(totals["platform_commission"] + totals["transaction_fee"] + totals["bxp_fee"] + support_fee)
    estimated_platform_payout = money(sales_revenue - platform_fee_total - totals["affiliate_commission"] - totals["seller_shipping_cost"])
    gross_profit = money(estimated_platform_payout - totals["product_cost"])
    net_profit = money(gross_profit - totals["advertising_cost"]) if has_ad_cost else None
    gross_margin = money(gross_profit / sales_revenue * PERCENT) if sales_revenue else Decimal("0")
    net_margin = money(net_profit / sales_revenue * PERCENT) if net_profit is not None and sales_revenue else None
    total_costs = money(platform_fee_total + totals["affiliate_commission"] + totals["seller_shipping_cost"] + totals["product_cost"] + totals["advertising_cost"])

    def row(key, label, amount, kind, base, group, rate=None, source_type="rule_estimate", source=None):
        return {
            "key": key, "label": label, "amount": str(money(amount)), "kind": kind,
            "base": base, "group": group,
            "share": str(money(decimal(amount) / sales_revenue * PERCENT)) if sales_revenue else "0.00",
            "rate": str(rate) if rate is not None else None,
            "source_type": source_type, "source": source,
            "effective_date": str(RULE_EFFECTIVE_DATE),
        }

    any_actual = lambda field: any(item.get(field) not in (None, "") for item in payload["items"])
    breakdown = [
        row("sales_revenue", "商品售价合计 / 总收入", sales_revenue, "income", "各 SKU 商家折扣后售价合计", "收入"),
        row("product_cost", "商品采购成本", totals["product_cost"], "cost", "人民币采购成本 ÷ 汇率", "商品"),
        row("seller_shipping_cost", "商家承担物流费用", totals["seller_shipping_cost"], "cost", "本土发货 RM0；跨境优先实际扣费，否则按 10g 价卡 + 当地派送", "物流", source_type="actual_settlement" if any_actual("actual_seller_shipping_cost") else "shipping_table_estimate", source=SHIPPING_SOURCE),
        row("platform_commission", "类目佣金", totals["platform_commission"], "fee", "商品折后售价", "平台代扣", source_type="actual_settlement" if any_actual("actual_platform_commission") else "rule_estimate", source=COMMISSION_SOURCE),
        row("transaction_fee", "支付交易手续费", totals["transaction_fee"], "fee", "商品折后售价 + 买家支付运费（买家运费不计入总收入）", "平台代扣", source_type="actual_settlement" if any_actual("actual_transaction_fee") else "rule_estimate", source=TRANSACTION_SOURCE),
        row("bxp_fee", "BXP 增值服务费", totals["bxp_fee"], "fee", "商品折后售价；每件最高 RM54", "平台代扣", source_type="actual_settlement" if any_actual("actual_bxp_fee") else "rule_estimate", source=COMMISSION_SOURCE),
        row("platform_support_fee", "每单平台支持费", support_fee, "fee", "已妥投订单固定费用，可手动覆盖", "平台代扣", source_type="actual_settlement" if actual_support not in (None, "") else "rule_estimate", source=SUPPORT_FEE_SOURCE),
        row("affiliate_commission", "达人推广佣金", totals["affiliate_commission"], "fee", "含税售价 − LVG 商品税", "推广代扣", source_type="actual_settlement" if any_actual("actual_affiliate_commission") else "rule_estimate", source=AFFILIATE_SOURCE),
        row("lvg_product_tax", "LVG 商品税（售价内含）", tax_total, "info", "仅说明，不重复扣除", "税费说明", rate=LVG_RATE, source=LVG_TAX_SOURCE),
        row("advertising_cost", "实际广告投入", totals["advertising_cost"], "cost", "仅在填写后计入", "广告投放"),
    ]

    warnings = [
        "规则试算使用自动费率或手动覆盖费率；已结算订单应填写 TikTok 实际扣费金额，实际金额优先且不会反写官方费率。",
        "理论佣金与实际佣金不一致时，应核对 TikTok 真实类目、店铺类型、BXP 状态、规则生效日期、折扣分摊、退款和费用调整；系统不得仅凭金额反推并覆盖官方费率。",
        "总收入只等于商品折后售价。买家支付运费仅可能进入交易手续费基数，不作为营业收入。",
    ]

    return {
        "currency": "MYR",
        "revenue": str(sales_revenue),
        "total_costs": str(total_costs),
        "costs_before_ads": str(money(total_costs - totals["advertising_cost"])),
        "advertising_cost": str(totals["advertising_cost"]),
        "gross_profit": str(gross_profit),
        "gross_margin": str(gross_margin),
        "net_profit": str(net_profit) if net_profit is not None else None,
        "net_margin": str(net_margin) if net_margin is not None else None,
        "has_ad_cost": has_ad_cost,
        "profit": str(gross_profit),
        "profit_rate": str(gross_margin),
        "break_even_cpa": str(gross_profit),
        "break_even_cpa_usd": str(money(gross_profit * usd_per_myr)),
        "break_even_roi": str(money(sales_revenue / gross_profit)) if gross_profit > 0 else None,
        "break_even_roas": str(money(sales_revenue / gross_profit)) if gross_profit > 0 else None,
        "items": item_results,
        "breakdown": breakdown,
        "amount_summary": {
            "sales_revenue": str(sales_revenue),
            "buyer_shipping_revenue": "0.00",
            "settlement_revenue": str(sales_revenue),
            "platform_fees": str(platform_fee_total),
            "affiliate_commission": str(totals["affiliate_commission"]),
            "logistics_cost": str(totals["seller_shipping_cost"]),
            "estimated_platform_payout": str(estimated_platform_payout),
            "product_cost": str(totals["product_cost"]),
            "gross_profit": str(gross_profit),
            "advertising_cost": str(totals["advertising_cost"]),
            "net_profit": str(net_profit) if net_profit is not None else None,
            "net_margin": str(net_margin) if net_margin is not None else None,
        },
        "rule_version": "MY-TTS-2026-07-31-v5",
        "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "warnings": warnings,
    }

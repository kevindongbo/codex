"""Auditable TikTok Shop Malaysia profit estimation.

All percentages and shipping tiers are versioned locally from primary sources.
The calculator never calls a third-party calculator at runtime.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from .profit_category_data import CATEGORY_ROWS


MONEY = Decimal("0.01")
PERCENT = Decimal("100")
RULE_EFFECTIVE_DATE = date(2026, 5, 13)
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
SHIPPING_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=7753788005828354&lang=en"
)
SHIPPING_CALCULATION_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=10014116&lang=en"
)
LVG_TAX_SOURCE = (
    "https://mysst.customs.gov.my/assets/document/Industry%20Guides/GI/"
    "Guide%20on%20Low%20Value%20Goods_Draft.pdf"
)


def decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def money(value) -> Decimal:
    return decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def rate_amount(base: Decimal, rate: Decimal) -> Decimal:
    return money(base * rate / PERCENT)


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

# Preserve payload compatibility with the first calculator release.
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
LVG_LIMIT = Decimal("500.00")  # Tax-exclusive sale value defined by Customs.
LVG_TAX_INCLUSIVE_LIMIT = money(LVG_LIMIT * (PERCENT + LVG_RATE) / PERCENT)

# Median of all 256 origin/destination routes in TikTok Shop Malaysia's
# official Standard Delivery Rate Card effective 2026-05-13.  Weight is
# rounded up to the next kg, matching the published rate-card tiers.
STANDARD_SHIPPING_MEDIAN = {
    1: Decimal("2.90"), 2: Decimal("2.90"), 3: Decimal("3.50"),
    4: Decimal("4.20"), 5: Decimal("5.00"), 6: Decimal("6.00"),
    7: Decimal("7.00"), 8: Decimal("8.00"), 9: Decimal("9.00"),
    10: Decimal("10.00"), 11: Decimal("11.00"), 12: Decimal("12.00"),
    13: Decimal("13.00"), 14: Decimal("14.00"), 15: Decimal("15.00"),
}


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
    tree = []
    industries = {}
    for rule in CATEGORY_RULES.values():
        industry = industries.get(rule.industry)
        if industry is None:
            industry = {"label": rule.industry, "children": []}
            industries[rule.industry] = industry
            tree.append(industry)
        level_one = next(
            (item for item in industry["children"] if item["label"] == rule.level_one),
            None,
        )
        if level_one is None:
            level_one = {"label": rule.level_one, "children": []}
            industry["children"].append(level_one)
        level_one["children"].append({"code": rule.code, "label": rule.level_two})
    return tree


def shipping_estimate(weight_g: Decimal) -> tuple[int, Decimal]:
    tier = int((weight_g / Decimal("1000")).to_integral_value(rounding=ROUND_CEILING))
    tier = max(1, tier)
    if tier > 15:
        raise ValueError("标准配送费率表仅覆盖 15kg 以内商品。")
    return tier, STANDARD_SHIPPING_MEDIAN[tier]


def inclusive_lvg_tax(item_price: Decimal, seller_type: str) -> Decimal:
    """Return the tax component already included in a tax-inclusive price."""
    tax_exclusive_value = item_price * PERCENT / (PERCENT + LVG_RATE)
    if seller_type != "cross_border" or tax_exclusive_value > LVG_LIMIT:
        return Decimal("0.00")
    return money(item_price * LVG_RATE / (PERCENT + LVG_RATE))


def calculate_profit(payload: dict) -> dict:
    shop_identity = payload.get("shop_identity", "marketplace")
    seller_type = payload.get("seller_type", "cross_border")
    bxp = bool(payload.get("bxp", False))
    cny_per_myr = decimal(payload.get("cny_per_myr", "1"))
    usd_per_myr = decimal(payload.get("usd_per_myr", "0.235"))
    items = payload["items"]

    fee_totals = {
        "product_cost": Decimal("0"),
        "seller_shipping_cost": Decimal("0"),
        "platform_commission": Decimal("0"),
        "transaction_fee": Decimal("0"),
        "affiliate_commission": Decimal("0"),
        "bxp_fee": Decimal("0"),
    }
    sales_revenue = Decimal("0")
    buyer_shipping_total = Decimal("0")
    tax_total = Decimal("0")
    item_results = []
    support_exemptions = []

    for item in items:
        item_price = decimal(item["item_price"])
        weight_g = decimal(item["weight_g"])
        product_cost_cny = decimal(item.get("product_cost_cny", 0))
        affiliate_rate = decimal(item.get("affiliate_rate", 0))
        shipping_tier, shipping_fee = shipping_estimate(weight_g)
        product_tax = inclusive_lvg_tax(item_price, seller_type)
        affiliate_base = max(Decimal("0"), item_price - product_tax)

        rule = resolve_category(item["category_code"])
        commission_rate = rule.rate(shop_identity, bxp)
        bxp_fee = min(rate_amount(item_price, BXP_RATE), BXP_FEE_CAP) if bxp else Decimal("0.00")
        line_fees = {
            "product_cost": money(product_cost_cny / cny_per_myr),
            "seller_shipping_cost": money(shipping_fee),
            "platform_commission": rate_amount(item_price, commission_rate),
            "transaction_fee": rate_amount(item_price + shipping_fee, TRANSACTION_RATE),
            "affiliate_commission": rate_amount(affiliate_base, affiliate_rate),
            "bxp_fee": bxp_fee,
        }

        sales_revenue += item_price
        buyer_shipping_total += shipping_fee
        tax_total += product_tax
        support_exemptions.append(rule.support_fee_exempt)
        for key, value in line_fees.items():
            fee_totals[key] += value

        item_results.append({
            "sku_name": item.get("sku_name") or "SKU",
            "category": rule.label,
            "weight_g": str(weight_g),
            "shipping_tier_kg": shipping_tier,
            "buyer_shipping_fee": str(money(shipping_fee)),
            "seller_shipping_cost": str(money(shipping_fee)),
            "product_tax": str(product_tax),
            "revenue": str(money(item_price + shipping_fee)),
            "commission_base": str(money(item_price)),
            "transaction_base": str(money(item_price + shipping_fee)),
            "affiliate_base": str(money(affiliate_base)),
            "commission_rate": str(commission_rate),
            "affiliate_rate": str(affiliate_rate),
            "fees": {key: str(money(value)) for key, value in line_fees.items()},
        })

    sales_revenue = money(sales_revenue)
    buyer_shipping_total = money(buyer_shipping_total)
    revenue = money(sales_revenue + buyer_shipping_total)
    support_fee = (
        Decimal("0.00")
        if not payload.get("delivered", True) or all(support_exemptions)
        else PLATFORM_SUPPORT_FEE
    )
    fee_totals = {key: money(value) for key, value in fee_totals.items()}
    total_costs = money(sum(fee_totals.values(), Decimal("0")) + support_fee)
    profit = money(revenue - total_costs)
    profit_rate = money(profit / revenue * PERCENT) if revenue else Decimal("0.00")
    break_even_roi = money(revenue / profit) if profit > 0 else None
    break_even_cpa_usd = money(profit * usd_per_myr)

    breakdown = [
        {"key": "sales_revenue", "label": "商品销售收入", "amount": str(sales_revenue), "kind": "income", "base": "商品售价"},
        {"key": "buyer_shipping_fee", "label": "买家支付运费（自动）", "amount": str(buyer_shipping_total), "kind": "income", "base": "重量向上取整至 kg 档 · 官方全国线路中位数", "source": SHIPPING_SOURCE, "effective_date": "2026-05-13"},
        {"key": "product_cost", "label": "商品成本", "amount": str(fee_totals["product_cost"]), "kind": "cost", "base": "人民币成本 ÷ 汇率"},
        {"key": "seller_shipping_cost", "label": "卖家承担运费（自动）", "amount": str(fee_totals["seller_shipping_cost"]), "kind": "cost", "base": "重量向上取整至 kg 档 · 官方全国线路中位数", "source": SHIPPING_CALCULATION_SOURCE, "effective_date": "2026-05-13"},
        {"key": "platform_commission", "label": "平台佣金", "amount": str(fee_totals["platform_commission"]), "kind": "fee", "base": "商品售价（卖家折扣固定为 0）", "source": COMMISSION_SOURCE, "effective_date": "2026-06-06"},
        {"key": "transaction_fee", "label": "交易手续费", "amount": str(fee_totals["transaction_fee"]), "kind": "fee", "base": "商品售价 + 买家运费", "rate": str(TRANSACTION_RATE), "source": TRANSACTION_SOURCE, "effective_date": "2026-02-15"},
        {"key": "affiliate_commission", "label": "达人佣金", "amount": str(fee_totals["affiliate_commission"]), "kind": "fee", "base": "含税售价 − 自动拆分的 LVG 商品税", "source": AFFILIATE_SOURCE, "effective_date": "2026-02-19"},
        {"key": "lvg_product_tax", "label": "LVG 商品税（自动识别）", "amount": str(money(tax_total)), "kind": "info", "base": "跨境且税前货值 ≤ RM500：含税售价 × 10/110；不重复计入卖家成本", "rate": str(LVG_RATE) if seller_type == "cross_border" else "0", "source": LVG_TAX_SOURCE, "effective_date": "2024-01-01"},
        {"key": "bxp_fee", "label": "BXP 服务费", "amount": str(fee_totals["bxp_fee"]), "kind": "fee", "base": "商品售价；每件最高 RM54", "rate": str(BXP_RATE) if bxp else "0", "source": COMMISSION_SOURCE, "effective_date": "2025-09-13"},
        {"key": "platform_support_fee", "label": "平台支持费", "amount": str(support_fee), "kind": "fee", "base": "每个已妥投订单一次；指定基础类目自动豁免", "source": SUPPORT_FEE_SOURCE, "effective_date": "2026-02-15"},
    ]

    warnings = [
        "运费只根据重量估算：采用 TikTok Shop 马来西亚官方标准配送费率表的全国线路中位数；实际费用仍会受寄出州、收件州、体积重和物流商复称影响。",
        "LVG 10% 为买家税，平台代收代缴；本页仅从含税售价中拆分税额用于达人佣金基数，不将其重复扣作卖家成本。",
        "结果按正常平台费率估算，不含临时补贴、活动减免、退款调整、广告花费或税前货值超过 RM500 后可能发生的进口税费。",
    ]
    if any(decimal(item["item_price"]) > LVG_TAX_INCLUSIVE_LIMIT for item in items) and seller_type == "cross_border":
        warnings.append("存在税前货值超过 RM500 的商品：不适用 LVG 规则；进口税费需要 HS 编码和海关估值，本页未猜测计入。")

    return {
        "currency": "MYR",
        "revenue": str(revenue),
        "total_costs": str(total_costs),
        "profit": str(profit),
        "profit_rate": str(profit_rate),
        "break_even_cpa": str(profit),
        "break_even_cpa_usd": str(break_even_cpa_usd),
        "break_even_roi": str(break_even_roi) if break_even_roi is not None else None,
        "break_even_roas": str(break_even_roi) if break_even_roi is not None else None,
        "items": item_results,
        "breakdown": breakdown,
        "rule_version": "MY-TTS-2026-07-28-v2",
        "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "warnings": warnings,
    }

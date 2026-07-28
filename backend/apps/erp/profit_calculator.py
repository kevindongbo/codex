"""Deterministic TikTok Shop Malaysia profit estimation.

The calculator deliberately uses :class:`~decimal.Decimal` end to end and
returns every fee base so a seller can reconcile the estimate against Seller
Center.  Rule constants are versioned here instead of being fetched from a
third-party calculator at runtime.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("0.01")
PERCENT = Decimal("100")
RULE_EFFECTIVE_DATE = date(2026, 2, 15)
COMMISSION_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=6907739532281602&lang=en"
)
TRANSACTION_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=10013511&lang=ms-MY"
)
SUPPORT_FEE_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=7992113007347457&lang=en"
)
AFFILIATE_SOURCE = (
    "https://seller-my.tiktok.com/university/essay?"
    "knowledge_id=6837846988539650&role=1"
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
    label: str
    marketplace_bxp: Decimal
    marketplace_standard: Decimal
    mall_bxp: Decimal
    mall_standard: Decimal

    def rate(self, shop_identity: str, bxp: bool) -> Decimal:
        if shop_identity == "mall":
            return self.mall_bxp if bxp else self.mall_standard
        return self.marketplace_bxp if bxp else self.marketplace_standard


# Frequently used categories in the current ERP.  A custom category remains
# available for any Seller Center sub-category not listed here; its rate must
# be entered explicitly rather than guessed.
CATEGORY_RULES = {
    rule.code: rule
    for rule in (
        CategoryRule("womens_bags", "女包 / 箱包", Decimal("10.26"), Decimal("14.58"), Decimal("13.50"), Decimal("17.82")),
        CategoryRule("fashion_accessories", "时尚配饰", Decimal("10.26"), Decimal("14.58"), Decimal("13.50"), Decimal("17.82")),
        CategoryRule("peripherals_accessories", "电脑外设与配件", Decimal("7.02"), Decimal("11.34"), Decimal("10.26"), Decimal("14.58")),
        CategoryRule("home_supplies", "家居日用品", Decimal("8.10"), Decimal("12.42"), Decimal("11.34"), Decimal("15.66")),
        CategoryRule("beauty_skincare", "美妆与护肤", Decimal("10.80"), Decimal("15.12"), Decimal("14.04"), Decimal("18.36")),
        CategoryRule("musical_instruments", "乐器与配件", Decimal("7.02"), Decimal("11.34"), Decimal("10.26"), Decimal("14.58")),
        CategoryRule("essential_food", "基础食品（免佣类目）", Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
    )
}

TRANSACTION_RATE = Decimal("3.78")
BXP_RATE = Decimal("4.86")
PLATFORM_SUPPORT_FEE = Decimal("0.54")  # SST inclusive, once per delivered order.


def category_config():
    return [
        {
            "code": rule.code,
            "label": rule.label,
            "rates": {
                "marketplace_bxp": str(rule.marketplace_bxp),
                "marketplace_standard": str(rule.marketplace_standard),
                "mall_bxp": str(rule.mall_bxp),
                "mall_standard": str(rule.mall_standard),
            },
        }
        for rule in CATEGORY_RULES.values()
    ]


def calculate_profit(payload: dict) -> dict:
    shop_identity = payload.get("shop_identity", "marketplace")
    bxp = bool(payload.get("bxp", False))
    exchange_rate = decimal(payload.get("cny_per_myr", "1"))
    items = payload["items"]

    fee_totals = {
        "product_cost": Decimal("0"),
        "seller_shipping_cost": Decimal("0"),
        "platform_commission": Decimal("0"),
        "transaction_fee": Decimal("0"),
        "affiliate_commission": Decimal("0"),
        "bxp_fee": Decimal("0"),
        "other_cost": Decimal("0"),
        "ad_spend": Decimal("0"),
    }
    revenue = Decimal("0")
    item_results = []

    for item in items:
        quantity = decimal(item.get("quantity", 1))
        item_price = decimal(item["item_price"])
        seller_discount = decimal(item.get("seller_discount", 0))
        platform_discount = decimal(item.get("platform_discount", 0))
        product_tax = decimal(item.get("product_tax", 0))
        buyer_shipping_fee = decimal(item.get("buyer_shipping_fee", 0))
        product_cost_cny = decimal(item.get("product_cost_cny", 0))
        seller_shipping_cost = decimal(item.get("seller_shipping_cost", 0))
        affiliate_rate = decimal(item.get("affiliate_rate", 0))
        other_cost = decimal(item.get("other_cost", 0))
        ad_spend = decimal(item.get("ad_spend", 0))

        commission_base = max(Decimal("0"), item_price - seller_discount)
        transaction_base = max(Decimal("0"), commission_base + buyer_shipping_fee)
        affiliate_base = max(
            Decimal("0"),
            item_price - seller_discount - platform_discount - product_tax,
        )
        line_revenue = transaction_base * quantity

        category_code = item.get("category_code")
        if category_code == "custom":
            commission_rate = decimal(item["custom_commission_rate"])
            category_label = item.get("category_label") or "自定义类目"
        else:
            rule = CATEGORY_RULES[category_code]
            commission_rate = rule.rate(shop_identity, bxp)
            category_label = rule.label

        line_fees = {
            "product_cost": money(product_cost_cny / exchange_rate * quantity),
            "seller_shipping_cost": money(seller_shipping_cost * quantity),
            "platform_commission": rate_amount(commission_base * quantity, commission_rate),
            "transaction_fee": rate_amount(transaction_base * quantity, TRANSACTION_RATE),
            "affiliate_commission": rate_amount(affiliate_base * quantity, affiliate_rate),
            "bxp_fee": rate_amount(commission_base * quantity, BXP_RATE) if bxp else Decimal("0.00"),
            "other_cost": money(other_cost * quantity),
            "ad_spend": money(ad_spend * quantity),
        }
        revenue += line_revenue
        for key, value in line_fees.items():
            fee_totals[key] += value

        item_results.append({
            "sku_name": item.get("sku_name") or "SKU",
            "category": category_label,
            "quantity": str(quantity),
            "revenue": str(money(line_revenue)),
            "commission_base": str(money(commission_base * quantity)),
            "transaction_base": str(money(transaction_base * quantity)),
            "affiliate_base": str(money(affiliate_base * quantity)),
            "commission_rate": str(commission_rate),
            "affiliate_rate": str(affiliate_rate),
            "fees": {key: str(money(value)) for key, value in line_fees.items()},
        })

    revenue = money(revenue)
    support_fee = PLATFORM_SUPPORT_FEE if payload.get("delivered", True) else Decimal("0.00")
    fee_totals = {key: money(value) for key, value in fee_totals.items()}
    total_costs = money(sum(fee_totals.values(), Decimal("0")) + support_fee)
    profit = money(revenue - total_costs)
    contribution_before_ads = money(profit + fee_totals["ad_spend"])
    profit_rate = money(profit / revenue * PERCENT) if revenue else Decimal("0.00")
    break_even_roas = (
        money(revenue / contribution_before_ads)
        if contribution_before_ads > 0
        else None
    )

    breakdown = [
        {"key": "revenue", "label": "结算收入", "amount": str(revenue), "kind": "income", "base": "商品售价 - 卖家折扣 + 买家支付运费"},
        {"key": "product_cost", "label": "商品成本", "amount": str(fee_totals["product_cost"]), "kind": "cost", "base": "人民币成本 ÷ 汇率"},
        {"key": "seller_shipping_cost", "label": "卖家承担运费", "amount": str(fee_totals["seller_shipping_cost"]), "kind": "cost", "base": "商家输入"},
        {"key": "platform_commission", "label": "平台佣金", "amount": str(fee_totals["platform_commission"]), "kind": "fee", "base": "商品售价 - 卖家折扣", "source": COMMISSION_SOURCE, "effective_date": "2025-09-13"},
        {"key": "transaction_fee", "label": "交易手续费", "amount": str(fee_totals["transaction_fee"]), "kind": "fee", "base": "售价 - 卖家折扣 + 买家运费", "rate": str(TRANSACTION_RATE), "source": TRANSACTION_SOURCE, "effective_date": str(RULE_EFFECTIVE_DATE)},
        {"key": "affiliate_commission", "label": "达人佣金", "amount": str(fee_totals["affiliate_commission"]), "kind": "fee", "base": "售价 - 卖家折扣 - 平台优惠 - 商品税", "source": AFFILIATE_SOURCE, "effective_date": "2026-02-19"},
        {"key": "bxp_fee", "label": "BXP 服务费", "amount": str(fee_totals["bxp_fee"]), "kind": "fee", "base": "售价 - 卖家折扣", "rate": str(BXP_RATE) if bxp else "0", "source": COMMISSION_SOURCE, "effective_date": "2025-09-13"},
        {"key": "platform_support_fee", "label": "平台支持费", "amount": str(support_fee), "kind": "fee", "base": "每个已妥投订单一次", "source": SUPPORT_FEE_SOURCE, "effective_date": str(RULE_EFFECTIVE_DATE)},
        {"key": "other_cost", "label": "其他成本", "amount": str(fee_totals["other_cost"]), "kind": "cost", "base": "商家输入"},
        {"key": "ad_spend", "label": "广告花费", "amount": str(fee_totals["ad_spend"]), "kind": "cost", "base": "商家输入"},
    ]

    return {
        "currency": "MYR",
        "revenue": str(revenue),
        "total_costs": str(total_costs),
        "profit": str(profit),
        "profit_rate": str(profit_rate),
        "break_even_cpa": str(contribution_before_ads),
        "break_even_roas": str(break_even_roas) if break_even_roas is not None else None,
        "items": item_results,
        "breakdown": breakdown,
        "rule_version": "MY-TTS-2026-07-28",
        "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "warnings": [
            "结果为正常平台费率估算，不含临时补贴、免佣、退款调整或商家自行申报税费。",
            "平台支持费按一个已妥投订单计一次；多件商品同单时不会重复扣除。",
        ],
    }

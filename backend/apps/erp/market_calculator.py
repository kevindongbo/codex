"""US/MX scenario calculator: Decimal money, explicit evidence, no guessed tariffs.

Official category IDs, shop tax status and carrier rate cards are not available
in this installation. They remain blocked; confirmed merchant scenarios can be
calculated without pretending that a manual quote is an official rate card.
"""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from hashlib import sha256
import json

from rest_framework import serializers

CURRENCIES = {"MY": "MYR", "US": "USD", "MX": "MXN"}
RULE_VERSION = "camera-scenario-2026-10-27-v1"
SOURCES = {
    "US": "https://seller-us.tiktok.com/university/essay?knowledge_id=5988482086864682",
    "MX": "https://seller-mx.tiktok.com/university/essay?knowledge_id=309514093152016",
    "MX_SFP": "https://seller-mx.tiktok.com/university/essay?knowledge_id=4397124533274384&lang=en",
}
CATEGORIES = [("home_security", "家用安防摄像头"), ("surveillance_system", "监控摄像头／监控套装"), ("video_doorbell", "可视门铃")]
ZERO = Decimal("0")


def money(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def amounts(**kwargs):
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in kwargs.items()}


def allocation(total, weights):
    """Stable cent residuals; all allocations sum to exactly total."""
    total = money(total)
    denominator = sum(weights)
    if not denominator:
        weights = [Decimal(1)] * len(weights)
        denominator = sum(weights)
    raw = [total * w / denominator for w in weights]
    values = [v.quantize(Decimal("0.01"), rounding=ROUND_DOWN) for v in raw]
    cents = int((total - sum(values)) * 100)
    order = sorted(range(len(values)), key=lambda i: (-(raw[i] - values[i]), i))
    for idx in order[:cents]:
        values[idx] += Decimal("0.01")
    return values


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("必须为对象")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "不支持的字段" for key in sorted(unknown)})
        return super().to_internal_value(data)


def amount(required=True, **kwargs):
    return serializers.DecimalField(max_digits=14, decimal_places=4, min_value=ZERO, required=required, **kwargs)


def percent(required=True, **kwargs):
    return serializers.DecimalField(max_digits=7, decimal_places=4, min_value=ZERO, max_value=Decimal(100), required=required, **kwargs)


class ItemInput(StrictSerializer):
    client_item_id = serializers.CharField(max_length=80)
    sku_id = serializers.UUIDField(required=False, allow_null=True)
    sku_name = serializers.CharField(max_length=120)
    category_mapping_id = serializers.CharField(max_length=80)
    quantity = serializers.IntegerField(min_value=1, max_value=10000)
    unit_price = amount()
    seller_discount = amount(False, default=ZERO)  # Per unit, same currency.
    platform_discount = amount(False, default=ZERO)
    product_cost_cny = amount(False, allow_null=True)
    first_leg_cost_cny = amount(False, allow_null=True)
    affiliate_rate = percent(False, allow_null=True)
    commission_rate = percent(False, allow_null=True)
    commission_source = serializers.CharField(max_length=200, required=False, allow_blank=True)
    # Import/warehouse/materials/returns not included in shipping quote; per unit.
    other_cost = amount(False, allow_null=True)
    other_cost_source = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tax_expense = amount(False, allow_null=True)  # Nonrecoverable cost; per unit.
    tax_withholding = amount(False, allow_null=True)  # Payout only, not a second cost.
    tax_source = serializers.CharField(max_length=200, required=False, allow_blank=True)
    # Optional actual ad input. Empty => no net profit.
    ad_mode = serializers.ChoiceField(choices=["none", "cpa_usd", "roi", "percent"], default="none")
    ad_value = amount(False, allow_null=True)

    def validate(self, attrs):
        if attrs["seller_discount"] > attrs["unit_price"] or attrs["platform_discount"] > attrs["unit_price"] - attrs["seller_discount"]:
            raise serializers.ValidationError("折扣不能超过商品售价")
        if attrs["ad_mode"] != "none" and attrs.get("ad_value") is None:
            raise serializers.ValidationError("填写实际广告数据后才能计算净利润")
        if attrs["ad_mode"] == "roi" and not attrs.get("ad_value"):
            raise serializers.ValidationError("实际ROI必须大于0")
        if attrs["ad_mode"] == "percent" and attrs["ad_value"] > 100:
            raise serializers.ValidationError("广告占比不能超过100%")
        return attrs


class PackageItem(StrictSerializer):
    client_item_id = serializers.CharField(max_length=80)
    quantity = serializers.IntegerField(min_value=1, max_value=10000)


class Weight(StrictSerializer):
    value = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"))
    unit = serializers.ChoiceField(choices=["g", "kg", "lb", "oz"])


class Dimensions(StrictSerializer):
    length = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"))
    width = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"))
    height = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"))
    unit = serializers.ChoiceField(choices=["cm", "in"])


class PackageInput(StrictSerializer):
    client_package_id = serializers.CharField(max_length=80)
    items = PackageItem(many=True, allow_empty=False)
    weight = Weight()
    dimensions = Dimensions()
    battery_profile = serializers.ChoiceField(choices=["plug_in_no_battery", "built_in", "removable", "unknown"])


class CalculationInput(StrictSerializer):
    schema_version = serializers.IntegerField(min_value=2, max_value=2)
    country = serializers.ChoiceField(choices=["US", "MX"])
    currency = serializers.ChoiceField(choices=["USD", "MXN"])
    store_id = serializers.UUIDField(required=False, allow_null=True)
    seller_program = serializers.CharField(max_length=40)
    fulfillment_service = serializers.ChoiceField(choices=["seller_shipping", "platform_label_standard", "platform_collection", "platform_warehouse"])
    items = ItemInput(many=True, allow_empty=False)
    packages = PackageInput(many=True, allow_empty=False)
    shipping_quote_id = serializers.UUIDField(required=False, allow_null=True)
    exchange_rate_set_id = serializers.UUIDField(required=False, allow_null=True)
    buyer_shipping = amount(False, default=ZERO)
    retained_shipping = amount(False, default=ZERO)
    subsidy = amount(False, default=ZERO)
    subsidy_source = serializers.CharField(max_length=200, required=False, allow_blank=True)
    sfp = serializers.BooleanField(default=False)
    sfp_confirmed = serializers.BooleanField(default=False)
    mx_fee_units_confirmed = serializers.BooleanField(default=False)
    # Price net of seller-remitted product IVA; referral base remains inclusive.
    product_tax_in_price = amount(False, default=ZERO)
    checkout_sales_tax = amount(False, default=ZERO)  # Pass-through, never revenue.
    fees_confirmed = serializers.BooleanField(default=False)

    def validate(self, attrs):
        country = attrs["country"]
        if attrs["currency"] != CURRENCIES[country]:
            raise serializers.ValidationError({"currency": "国家与币种不一致"})
        if len(attrs["items"]) > 100 or len(attrs["packages"]) > 100:
            raise serializers.ValidationError("单次最多100个SKU和包裹")
        if attrs["fulfillment_service"] == "platform_warehouse" and country == "MX":
            raise serializers.ValidationError({"fulfillment_service": "墨西哥平台仓尚未核验，当前不可用"})
        if attrs["sfp"] and country != "MX":
            raise serializers.ValidationError({"sfp": "SFP仅适用于墨西哥已开通店铺"})
        if country == "US" and attrs["product_tax_in_price"]:
            raise serializers.ValidationError("美国商品输入为税外价；销售税填写checkout_sales_tax")
        ids = [i["client_item_id"] for i in attrs["items"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("商品标识重复")
        package_ids = [p["client_package_id"] for p in attrs["packages"]]
        if len(set(package_ids)) != len(package_ids):
            raise serializers.ValidationError("包裹标识重复")
        expected = Counter({i["client_item_id"]: i["quantity"] for i in attrs["items"]})
        actual = Counter()
        for p in attrs["packages"]:
            for item in p["items"]:
                actual[item["client_item_id"]] += item["quantity"]
        if actual != expected:
            raise serializers.ValidationError({"packages": "包裹数量必须恰好匹配商品，不能重复或漏装"})
        for i in attrs["items"]:
            if i["category_mapping_id"] not in [country + ":" + key for key, _ in CATEGORIES]:
                raise serializers.ValidationError({"category_mapping_id": "摄像头类目不属于当前国家"})
        if attrs["retained_shipping"] > attrs["buyer_shipping"]:
            raise serializers.ValidationError("商家保留运费不能超过买家支付运费")
        if attrs["subsidy"] and not attrs.get("subsidy_source"):
            raise serializers.ValidationError("补贴须填写来源，不得预设平台补贴")
        return attrs


def package_metrics(package):
    factors = {"g": Decimal(1), "kg": Decimal(1000), "lb": Decimal("453.59237"), "oz": Decimal("28.349523125")}
    weight_g = package["weight"]["value"] * factors[package["weight"]["unit"]]
    d = package["dimensions"]
    factor = Decimal("2.54") if d["unit"] == "in" else Decimal(1)
    dims = [d[k] * factor for k in ("length", "width", "height")]
    return amounts(package_id=package["client_package_id"], actual_weight_g=weight_g,
                   length_cm=dims[0], width_cm=dims[1], height_cm=dims[2],
                   billed_weight=None, note="人工报价已含计费重；未导入官方价卡，不猜体积重除数")


def quote_binding(data):
    return digest({k: data.get(k) for k in ("country", "currency", "store_id", "seller_program", "fulfillment_service", "packages")})


def calculate(data, rates, quote):
    missing = []
    if not rates:
        missing.append("exchange_rate_set_id：请保存当前市场的汇率快照")
    if not quote:
        missing.append("shipping_quote_id：请填写有来源的当地履约报价")
    if not data["fees_confirmed"]:
        missing.append("fees_confirmed：确认佣金、税务及其他费用口径")
    if data["sfp"] and not data["sfp_confirmed"]:
        missing.append("sfp_confirmed：确认已开通SFP，补贴须另填实际值")
    if data["country"] == "MX" and not data["mx_fee_units_confirmed"]:
        missing.append("mx_fee_units_confirmed：确认本次交易的MXN6按件费用适用")
    for item in data["items"]:
        for field in ("product_cost_cny", "first_leg_cost_cny", "affiliate_rate", "commission_rate", "other_cost", "tax_expense", "tax_withholding"):
            if item.get(field) is None:
                missing.append(item["sku_name"] + "：" + field + "未填写（确认无费用可明确填0）")
        for field in ("commission_source", "other_cost_source", "tax_source"):
            if not item.get(field):
                missing.append(item["sku_name"] + "：" + field + "来源待填写")
    if any(p["battery_profile"] == "unknown" for p in data["packages"]):
        missing.append("电池运输属性未知")
    context = {"rule_version": RULE_VERSION, "rule_hash": digest({"version": RULE_VERSION, "sources": SOURCES}),
               "rate_hash": rates.content_hash if rates else None, "quote_hash": quote.content_hash if quote else None,
               "input_hash": digest(data)}
    result = {"schema_version": 2, "country": data["country"], "currency": data["currency"],
              "mode": "merchant_scenario", "calculation_status": "partial" if missing else "complete",
              "context": context, "context_hash": digest(context), "missing_inputs": missing,
              "sources": SOURCES, "packages": [package_metrics(p) for p in data["packages"]],
              "warnings": ["商家确认情景：类目官方末级ID和店铺资格尚未核验；人工佣金／报价不是官方自动匹配价表。",
                           "税务费用与代扣按已填写依据估算；代扣仅影响预计平台回款，不能再重复扣减利润。"],
              "gross_profit": None, "gross_margin": None, "net_profit": None, "net_margin": None,
              "break_even_roi": None, "break_even_cpa": None, "platform_payout": None, "items": []}
    if missing:
        return result
    # Snapshot rates are base currency -> CNY/USD. Same rate set for all lines.
    cny, usd = Decimal(rates.payload["cny_per_base"]), Decimal(rates.payload["usd_per_base"])
    items = data["items"]
    sales = [money((i["unit_price"] - i["seller_discount"]) * i["quantity"]) for i in items]
    product_taxes = allocation(data["product_tax_in_price"], sales)
    if any(s < t for s, t in zip(sales, product_taxes)):
        raise serializers.ValidationError("价内税不能超过商品金额")
    fee_shipping = allocation(data["buyer_shipping"], sales)
    retained = allocation(data["retained_shipping"], sales)
    subsidies = allocation(data["subsidy"], sales)
    shipping_allocations = [ZERO for _ in items]
    for package, line in zip(data["packages"], quote.payload["lines"]):
        weights = []
        indexes = []
        for packed in package["items"]:
            idx = next(idx for idx, i in enumerate(items) if i["client_item_id"] == packed["client_item_id"])
            indexes.append(idx)
            weights.append((items[idx]["unit_price"] - items[idx]["seller_discount"]) * packed["quantity"])
        if not sum(weights):
            weights = [Decimal(p["quantity"]) for p in package["items"]]
        for idx, value in zip(indexes, allocation(Decimal(line["amount"]), weights)):
            shipping_allocations[idx] += value
    for idx, item in enumerate(items):
        qty = item["quantity"]
        net_sales = sales[idx] - product_taxes[idx]
        fee_base = sales[idx] + fee_shipping[idx]  # US tax is separate checkout input.
        commission = money(fee_base * item["commission_rate"] / 100)
        fixed = money(Decimal(6) * qty) if data["country"] == "MX" else ZERO
        sfp = money(min((sales[idx] / qty) * Decimal(".08"), Decimal(40)) * qty) if data["sfp"] else ZERO
        affiliate = money(net_sales * item["affiliate_rate"] / 100)
        product_cost = money(item["product_cost_cny"] * qty / cny)
        head = money(item["first_leg_cost_cny"] * qty / cny)
        other = money(item["other_cost"] * qty)
        tax = money(item["tax_expense"] * qty)
        withheld = money(item["tax_withholding"] * qty)
        shipping = money(shipping_allocations[idx])
        revenue = net_sales + retained[idx] + subsidies[idx]
        gross = money(revenue - product_cost - head - other - tax - shipping - commission - fixed - sfp - affiliate)
        platform_shipping = shipping if quote.payload["payment_channel"] == "platform" else ZERO
        # Price component remitted to government is not seller payout.
        payout = money(revenue - commission - fixed - sfp - affiliate - withheld - platform_shipping)
        ad = None
        if item["ad_mode"] == "cpa_usd":
            ad = money(item["ad_value"] * qty / usd)
        elif item["ad_mode"] == "roi":
            ad = money(net_sales / item["ad_value"])
        elif item["ad_mode"] == "percent":
            ad = money(net_sales * item["ad_value"] / 100)
        net = money(gross - ad) if ad is not None else None
        fees = [("商品成本", product_cost, "商家输入CNY / 汇率快照"), ("头程成本", head, "商家每件确认分摊"),
                ("其他落地／仓储／耗材／退货成本", other, item["other_cost_source"]),
                ("当地履约", shipping, quote.payload["source"]), ("平台佣金", commission, item["commission_source"]),
                ("售出固定费", fixed, SOURCES["MX"] if fixed else "本市场不适用"),
                ("SFP服务费", sfp, SOURCES["MX_SFP"] if sfp else "未参加"),
                ("达人佣金", affiliate, "商家确认"), ("不可抵扣税费", tax, item["tax_source"])]
        result["items"].append(amounts(client_item_id=item["client_item_id"], sku_name=item["sku_name"], quantity=qty,
            sales=net_sales, revenue=revenue, platform_payout=payout, tax_withholding=withheld,
            gross_profit=gross, gross_margin=money(gross / net_sales * 100) if net_sales else None,
            break_even_roi=money(net_sales / gross) if gross > 0 and net_sales > 0 else None,
            break_even_cpa=money(gross / qty), advertising_cost=ad, net_profit=net,
            net_margin=money(net / net_sales * 100) if net is not None and net_sales else None,
            fee_base=fee_base, fees=[{"label": label, "amount": str(value), "source": source} for label, value, source in fees]))
    sales_total = sum(Decimal(i["sales"]) for i in result["items"])
    gross = sum(Decimal(i["gross_profit"]) for i in result["items"])
    net = sum(Decimal(i["net_profit"]) for i in result["items"]) if all(i["net_profit"] is not None for i in result["items"]) else None
    result.update(amounts(sales=sales_total, gross_profit=gross,
        gross_margin=money(gross / sales_total * 100) if sales_total else None,
        net_profit=net, net_margin=money(net / sales_total * 100) if net is not None and sales_total else None,
        break_even_roi=money(sales_total / gross) if gross > 0 and sales_total > 0 else None,
        break_even_cpa=money(gross / sum(i["quantity"] for i in items)),
        platform_payout=sum(Decimal(i["platform_payout"]) for i in result["items"])))
    return result

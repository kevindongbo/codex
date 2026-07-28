from decimal import Decimal

from rest_framework import serializers

from .profit_calculator import CATEGORY_RULES


class ProfitItemSerializer(serializers.Serializer):
    sku_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    category_code = serializers.ChoiceField(choices=tuple(CATEGORY_RULES) + ("custom",))
    category_label = serializers.CharField(required=False, allow_blank=True, max_length=120)
    custom_commission_rate = serializers.DecimalField(required=False, max_digits=6, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"))
    quantity = serializers.DecimalField(required=False, default=Decimal("1"), max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    item_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    seller_discount = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    platform_discount = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    product_tax = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    buyer_shipping_fee = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    product_cost_cny = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    seller_shipping_cost = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    affiliate_rate = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=6, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"))
    other_cost = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    ad_spend = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))

    def validate(self, attrs):
        if attrs["seller_discount"] > attrs["item_price"]:
            raise serializers.ValidationError({"seller_discount": "卖家折扣不能超过商品售价。"})
        if attrs["category_code"] == "custom" and "custom_commission_rate" not in attrs:
            raise serializers.ValidationError({"custom_commission_rate": "自定义类目必须填写 Seller Center 显示的佣金费率。"})
        return attrs


class ProfitCalculationSerializer(serializers.Serializer):
    country = serializers.ChoiceField(choices=("MY",), default="MY")
    shop_identity = serializers.ChoiceField(choices=("marketplace", "mall"), default="marketplace")
    bxp = serializers.BooleanField(required=False, default=False)
    delivered = serializers.BooleanField(required=False, default=True)
    cny_per_myr = serializers.DecimalField(max_digits=12, decimal_places=6, min_value=Decimal("0.000001"))
    items = ProfitItemSerializer(many=True, allow_empty=False)

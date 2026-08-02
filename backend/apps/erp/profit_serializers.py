from decimal import Decimal

from rest_framework import serializers

from .profit_calculator import CATEGORY_RULES, LEGACY_CATEGORY_ALIASES


class ProfitItemSerializer(serializers.Serializer):
    sku_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    category_code = serializers.ChoiceField(
        choices=tuple(CATEGORY_RULES) + tuple(LEGACY_CATEGORY_ALIASES)
    )
    weight_g = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("1"),
        max_value=None,
    )
    item_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"))
    product_cost_cny = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=14, decimal_places=2, min_value=Decimal("0"))
    affiliate_rate = serializers.DecimalField(required=False, default=Decimal("0"), max_digits=6, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"))
    buyer_shipping_fee = serializers.DecimalField(
        required=False,
        default=Decimal("0"),
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0"),
    )
    ad_cost_type = serializers.ChoiceField(
        choices=("none", "roi", "cpa_usd", "ratio"),
        required=False,
        default="none",
    )
    ad_cost_value = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=14,
        decimal_places=4,
        min_value=Decimal("0"),
    )
    manual_commission_rate = serializers.DecimalField(
        required=False,
        allow_null=True,
        default=None,
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
    )

    def validate_weight_g(self, value):
        if value > Decimal("30000"):
            raise serializers.ValidationError("超过当前运费价表范围")
        return value


class ProfitCalculationSerializer(serializers.Serializer):
    country = serializers.ChoiceField(choices=("MY",), default="MY")
    seller_type = serializers.ChoiceField(choices=("cross_border", "local"), default="cross_border")
    shop_identity = serializers.ChoiceField(choices=("marketplace", "mall"), default="marketplace")
    bxp = serializers.BooleanField(required=False, default=False)
    delivered = serializers.BooleanField(required=False, default=True)
    commission_adjustment = serializers.DecimalField(
        required=False,
        default=Decimal("0.00"),
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("-100"),
        max_value=Decimal("100"),
    )
    customer_refund = serializers.DecimalField(
        required=False,
        default=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0"),
    )
    cny_per_myr = serializers.DecimalField(max_digits=12, decimal_places=6, min_value=Decimal("0.000001"))
    usd_per_myr = serializers.DecimalField(
        required=False,
        default=Decimal("0.235000"),
        max_digits=12,
        decimal_places=6,
        min_value=Decimal("0.000001"),
    )
    items = ProfitItemSerializer(many=True, allow_empty=False)

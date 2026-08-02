"""Versioned Malaysia cross-border shipping estimates for the profit calculator.

The May 15, 2026 price list supplied by the operator charges RM0.15 for every
started 10 grams and covers packaged weights up to 30,000 grams.  Keeping this
rule in a small backend module makes updates reviewable and prevents the web
page from reading an operator spreadsheet at runtime.
"""

from decimal import Decimal, ROUND_CEILING


MALAYSIA_CROSS_BORDER_RATE_VERSION = "MY-CB-2026-05-15"
MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE = "2026-05-15"
MALAYSIA_CROSS_BORDER_SOURCE = "马来西亚跨境价目表"
MALAYSIA_CROSS_BORDER_STEP_G = Decimal("10")
MALAYSIA_CROSS_BORDER_STEP_PRICE = Decimal("0.15")
MALAYSIA_CROSS_BORDER_MAX_G = Decimal("30000")


def malaysia_cross_border_shipping(weight_g: Decimal) -> tuple[int, Decimal]:
    """Return rounded packaged weight and merchant-paid shipping in MYR."""
    if weight_g <= 0:
        raise ValueError("包装后重量必须大于 0g。")
    if weight_g > MALAYSIA_CROSS_BORDER_MAX_G:
        raise ValueError("当前马来西亚跨境价目表仅覆盖 30,000g 以内商品，请拆单或更新运费配置。")
    steps = int(
        (weight_g / MALAYSIA_CROSS_BORDER_STEP_G).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    rounded_weight_g = steps * int(MALAYSIA_CROSS_BORDER_STEP_G)
    return rounded_weight_g, MALAYSIA_CROSS_BORDER_STEP_PRICE * steps

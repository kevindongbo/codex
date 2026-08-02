"""Versioned Malaysia cross-border shipping estimates for the profit calculator.

The May 15, 2026 operator price list charges RM0.15 for every started 10 grams
of the cross-border segment and covers packaged weights up to 30,000 grams.
The last-mile West/East Malaysia charges in the source sheet are deliberately
not included: this calculator only estimates the merchant-paid cross-border
leg.  Keeping the converted rule here makes updates reviewable and prevents
the web page from reading an operator spreadsheet at runtime.
"""

from decimal import Decimal, ROUND_CEILING


MALAYSIA_CROSS_BORDER_RATE_VERSION = "MY-CB-2026-05-15"
MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE = "2026-05-15"
MALAYSIA_CROSS_BORDER_SOURCE = "马来西亚跨境价目表"
MALAYSIA_CROSS_BORDER_SOURCE_FILE = "东南亚跨境物流运费价格表20260515(1).xlsx"
MALAYSIA_CROSS_BORDER_STEP_G = Decimal("10")
MALAYSIA_CROSS_BORDER_STEP_PRICE = Decimal("0.15")
MALAYSIA_CROSS_BORDER_MAX_G = Decimal("30000")


def malaysia_cross_border_shipping(weight_g: Decimal) -> tuple[int, Decimal]:
    """Return rounded packaged weight and merchant-paid shipping in MYR."""
    if weight_g <= 0:
        raise ValueError("包装后重量必须大于 0g。")
    if weight_g > MALAYSIA_CROSS_BORDER_MAX_G:
        raise ValueError("超过当前运费价表范围")
    steps = int(
        (weight_g / MALAYSIA_CROSS_BORDER_STEP_G).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    rounded_weight_g = steps * int(MALAYSIA_CROSS_BORDER_STEP_G)
    return rounded_weight_g, MALAYSIA_CROSS_BORDER_STEP_PRICE * steps

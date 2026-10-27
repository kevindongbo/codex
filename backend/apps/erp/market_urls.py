from django.urls import path
from . import market_views as v

urlpatterns = [path("markets/", v.markets), path("config/", v.config),
    path("sku-profiles/<uuid:sku_id>/", v.sku_profile),
    path("working-config/", v.working), path("strategies/", v.strategies),
    path("strategies/<uuid:strategy_id>/", v.strategies), path("strategies/<uuid:strategy_id>/activate/", v.activate),
    path("exchange-rates/", v.exchange), path("shipping-quotes/", v.shipping_quote),
    path("calculate/", v.calculation), path("plans/", v.plans), path("plans/save/", v.save_plan),
    path("plans/<uuid:snapshot_id>/", v.plans)]

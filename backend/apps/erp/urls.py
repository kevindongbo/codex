from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("organizations", views.OrganizationViewSet, basename="organization")
router.register("memberships", views.MembershipViewSet, basename="membership")
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("products", views.ProductViewSet, basename="product")
router.register("product-images", views.ProductImageViewSet, basename="product-image")
router.register("media-assets", views.UploadedMediaAssetViewSet, basename="media-asset")
router.register("skus", views.SKUViewSet, basename="sku")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("purchase-orders", views.PurchaseOrderViewSet, basename="purchase-order")
router.register("receipts", views.ReceiptViewSet, basename="receipt")
router.register("stock-balances", views.StockBalanceViewSet, basename="stock-balance")
router.register("stock-ledger", views.StockLedgerViewSet, basename="stock-ledger")
router.register("stock-transfers", views.StockTransferViewSet, basename="stock-transfer")
router.register(
    "replenishment-policies",
    views.ReplenishmentPolicyViewSet,
    basename="replenishment-policy",
)
router.register("replenishment-settings", views.ReplenishmentSettingsViewSet, basename="replenishment-settings")
router.register("orders", views.SalesOrderViewSet, basename="order")
router.register("shipments", views.ShipmentViewSet, basename="shipment")
router.register("returns", views.ReturnOrderViewSet, basename="return")
router.register("competitors", views.CompetitorProductViewSet, basename="competitor")
router.register("competitor-snapshots", views.CompetitorSnapshotViewSet, basename="competitor-snapshot")
router.register("audit-logs", views.AuditLogViewSet, basename="audit-log")
router.register("local-imports", views.LocalImportViewSet, basename="local-import")
router.register("tiktok-shop-connections", views.TikTokShopConnectionViewSet, basename="tiktok-shop-connection")
router.register("ai-providers", views.AIProviderConfigViewSet, basename="ai-provider")
router.register("ai-invocations", views.AIInvocationLogViewSet, basename="ai-invocation")
router.register("ai-recommendations", views.AIRecommendationViewSet, basename="ai-recommendation")

urlpatterns = [
    path("health/", views.health, name="health"),
    path("sync/version/", views.sync_version, name="sync-version"),
    path("auth/me/", views.me, name="me"),
    path("integrations/tiktok-shop/callback/", views.tiktok_shop_oauth_callback, name="tiktok-shop-oauth-callback"),
    path("media-assets/<uuid:pk>/content/", views.media_asset_content, name="media-asset-content"),
    path("alphashop-config/", views.AlphaShopConfigurationView.as_view(), name="alphashop-config"),
    path("alphashop-config/test/", views.AlphaShopConfigurationTestView.as_view(), name="alphashop-config-test"),
    path("product-selection/status/", views.ProductSelectionStatusView.as_view(), name="product-selection-status"),
    path("product-selection/keywords/", views.ProductSelectionKeywordView.as_view(), name="product-selection-keywords"),
    path("product-selection/report/", views.ProductSelectionReportView.as_view(), name="product-selection-report"),
    path("internal-accounts/", views.internal_accounts, name="internal-accounts"),
    path("internal-accounts/<uuid:membership_id>/", views.internal_account_detail, name="internal-account-detail"),
    path("purchase-members/", views.purchase_members, name="purchase-members"),
    path(
        "replenishment/recommendations/",
        views.replenishment_recommendations,
        name="replenishment-recommendations",
    ),
    path("replenishment/batch-policy/", views.replenishment_batch_policy, name="replenishment-batch-policy"),
    path("replenishment/recompute/", views.replenishment_recompute, name="replenishment-recompute"),
    path("", include(router.urls)),
]

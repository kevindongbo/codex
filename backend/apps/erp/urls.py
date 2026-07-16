from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("organizations", views.OrganizationViewSet, basename="organization")
router.register("memberships", views.MembershipViewSet, basename="membership")
router.register("warehouses", views.WarehouseViewSet, basename="warehouse")
router.register("products", views.ProductViewSet, basename="product")
router.register("product-images", views.ProductImageViewSet, basename="product-image")
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
router.register("orders", views.SalesOrderViewSet, basename="order")
router.register("shipments", views.ShipmentViewSet, basename="shipment")
router.register("returns", views.ReturnOrderViewSet, basename="return")
router.register("competitors", views.CompetitorProductViewSet, basename="competitor")
router.register("competitor-snapshots", views.CompetitorSnapshotViewSet, basename="competitor-snapshot")
router.register("audit-logs", views.AuditLogViewSet, basename="audit-log")
router.register("local-imports", views.LocalImportViewSet, basename="local-import")

urlpatterns = [
    path("health/", views.health, name="health"),
    path("uploads/product-images/", views.upload_product_image, name="product-image-upload"),
    path("uploads/product-images/<str:filename>/", views.serve_product_image, name="product-image-file"),
    path("sync/version/", views.sync_version, name="sync-version"),
    path("auth/me/", views.me, name="me"),
    path("internal-accounts/", views.internal_accounts, name="internal-accounts"),
    path("internal-accounts/<uuid:membership_id>/", views.internal_account_detail, name="internal-account-detail"),
    path(
        "replenishment/recommendations/",
        views.replenishment_recommendations,
        name="replenishment-recommendations",
    ),
    path("", include(router.urls)),
]

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.erp.models import (
    AuditLog, CompetitorProduct, CompetitorSnapshot, LocalImport, Membership, Organization,
    Product, ProductImage, PurchaseOrder, ReplenishmentPolicy, ReturnOrder, SalesOrder,
    SalesOrderLine, Shipment, SKU, StockBalance, StockLedger, StockTransfer,
    Supplier, Warehouse,
)


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="api-user", password="test-pass-123")
        self.organization = Organization.objects.create(name="东铂", slug="api-dongbo")
        Membership.objects.create(
            organization=self.organization, user=self.user, role=Membership.Role.ADMIN
        )
        self.client = APIClient()

    def test_health_is_public_and_checks_database(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_jwt_login(self):
        response = self.client.post(
            "/api/auth/token/", {"username": "api-user", "password": "test-pass-123"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        self.assertIn("refresh", response.json())

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["username"], "api-user")
        self.assertEqual(me.data["memberships"][0]["organization"]["name"], "东铂")

    def test_organization_scope_and_role_header(self):
        self.client.force_authenticate(self.user)
        create = self.client.post(
            "/api/warehouses/",
            {"code": "CN-01", "name": "深圳仓", "country": "CN"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertEqual(create.status_code, 201, create.data)
        self.assertTrue(Warehouse.objects.filter(organization=self.organization, code="CN-01").exists())
        duplicate = self.client.post(
            "/api/warehouses/",
            {"code": "CN-01", "name": "重复仓", "country": "CN"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        self.assertIn(duplicate.status_code, {400, 409})

        other = Organization.objects.create(name="其他公司", slug="other")
        denied = self.client.get("/api/warehouses/", HTTP_X_ORGANIZATION_ID=str(other.pk))
        self.assertEqual(denied.status_code, 403)

    def test_creating_organization_bootstraps_default_warehouse(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/organizations/",
            {"name": "新团队", "slug": "new-team", "active": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        created = Organization.objects.get(pk=response.data["id"])
        self.assertTrue(
            Warehouse.objects.filter(
                organization=created, code="DEFAULT", name="默认仓", active=True
            ).exists()
        )
        self.assertTrue(
            Membership.objects.filter(
                organization=created, user=self.user, role=Membership.Role.ADMIN
            ).exists()
        )

    def test_team_frontend_fields_and_linked_monitoring_profile_round_trip(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        product = self.client.post(
            "/api/products/",
            {
                "name": "团队商品", "seller": "Dongbo MY", "market": "MY",
                "sales_currency": "MYR", "monitoring_enabled": True,
                "source_url": "https://example.com/product",
            },
            format="json", **headers,
        )
        self.assertEqual(product.status_code, 201, product.data)
        competitor = self.client.post(
            "/api/competitors/",
            {
                "name": "团队商品监控", "linked_product": product.data["id"],
                "kind": "direct", "platform": "own", "market": "MY",
                "url": "https://example.com/product", "image_url": "https://example.com/image.jpg",
                "currency": "MYR", "active": True,
            },
            format="json", **headers,
        )

        self.assertEqual(competitor.status_code, 201, competitor.data)
        saved_product = Product.objects.get(pk=product.data["id"])
        saved_profile = CompetitorProduct.objects.get(pk=competitor.data["id"])
        self.assertEqual(saved_product.seller, "Dongbo MY")
        self.assertEqual(saved_product.sales_currency, "MYR")
        self.assertTrue(saved_product.monitoring_enabled)
        self.assertEqual(saved_profile.linked_product, saved_product)
        self.assertEqual(saved_profile.market, "MY")

    def test_viewer_cannot_modify_or_delete_organization(self):
        viewer = get_user_model().objects.create_user(username="viewer", password="test-pass-123")
        Membership.objects.create(
            organization=self.organization, user=viewer, role=Membership.Role.VIEWER
        )
        self.client.force_authenticate(viewer)

        update = self.client.patch(
            f"/api/organizations/{self.organization.pk}/", {"active": False}, format="json"
        )
        destroy = self.client.delete(f"/api/organizations/{self.organization.pk}/")

        self.assertEqual(update.status_code, 403)
        self.assertEqual(destroy.status_code, 403)
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.active)

    def test_last_admin_is_protected_and_membership_changes_are_audited(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        admin_membership = Membership.objects.get(
            organization=self.organization, user=self.user
        )
        demote = self.client.patch(
            f"/api/memberships/{admin_membership.pk}/",
            {"role": Membership.Role.VIEWER}, format="json", **headers,
        )
        remove = self.client.delete(
            f"/api/memberships/{admin_membership.pk}/", **headers
        )
        self.assertEqual(demote.status_code, 400)
        self.assertEqual(remove.status_code, 400)

        second_user = get_user_model().objects.create_user(
            username="second-admin", password="test-pass-123"
        )
        created = self.client.post(
            "/api/memberships/",
            {"user_id": second_user.pk, "role": Membership.Role.ADMIN, "active": True},
            format="json", **headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(
            AuditLog.objects.filter(
                organization=self.organization, action="membership.create"
            ).exists()
        )

    def test_related_objects_cannot_cross_organization_on_create_or_patch(self):
        self.client.force_authenticate(self.user)
        other = Organization.objects.create(name="其他公司", slug="tenant-other")
        other_product = Product.objects.create(organization=other, name="其他商品")
        other_supplier = Supplier.objects.create(
            organization=other, code="OTHER-SUP", name="其他供应商"
        )
        own_product = Product.objects.create(organization=self.organization, name="本组织商品")
        image = ProductImage.objects.create(
            product=own_product, url="https://example.com/own.jpg", position=0
        )

        create_sku = self.client.post(
            "/api/skus/",
            {"product": str(other_product.pk), "code": "CROSS-001", "cost": "1.00"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        patch_image = self.client.patch(
            f"/api/product-images/{image.pk}/",
            {"product": str(other_product.pk)},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )
        patch_product = self.client.patch(
            f"/api/products/{own_product.pk}/",
            {"default_supplier": str(other_supplier.pk)},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )

        self.assertEqual(create_sku.status_code, 400)
        self.assertEqual(patch_image.status_code, 400)
        self.assertEqual(patch_product.status_code, 400)
        self.assertFalse(SKU.objects.filter(organization=self.organization, code="CROSS-001").exists())
        image.refresh_from_db()
        self.assertEqual(image.product_id, own_product.pk)

    def test_sku_can_be_created_without_optional_barcode(self):
        self.client.force_authenticate(self.user)
        product = Product.objects.create(
            organization=self.organization, name="无条码商品"
        )

        response = self.client.post(
            "/api/skus/",
            {"product": str(product.pk), "code": "NO-BARCODE-001", "cost": "18.50"},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["barcode"], "")

    def test_invalid_nested_purchase_does_not_leave_parent_record(self):
        self.client.force_authenticate(self.user)
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="CN-02", name="东莞仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="SUP-01", name="供应商"
        )
        other = Organization.objects.create(name="另一租户", slug="po-other")
        other_product = Product.objects.create(organization=other, name="其他商品")
        other_sku = SKU.objects.create(
            organization=other, product=other_product, code="OTHER-SKU", cost="5"
        )

        response = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-CROSS",
                "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk),
                "currency": "CNY",
                "lines": [{
                    "sku": str(other_sku.pk), "quantity_ordered": "2", "unit_cost": "5"
                }],
            },
            format="json",
            HTTP_X_ORGANIZATION_ID=str(self.organization.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(PurchaseOrder.objects.filter(number="PO-CROSS").exists())

    def test_product_activation_requires_link_image_sku_and_cost(self):
        self.client.force_authenticate(self.user)
        product = Product.objects.create(organization=self.organization, name="待完善商品")
        SKU.objects.create(
            organization=self.organization, product=product, code="DRAFT-SKU", cost="0"
        )
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}

        incomplete = self.client.post(f"/api/products/{product.pk}/activate/", **headers)
        self.assertEqual(incomplete.status_code, 400)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.DRAFT)

        product.source_url = "https://example.com/product"
        product.save(update_fields=["source_url", "updated_at"])
        ProductImage.objects.create(
            product=product, url="https://example.com/product.jpg", position=0
        )
        sku = product.skus.get()
        sku.cost = "12.50"
        sku.save(update_fields=["cost", "updated_at"])

        activated = self.client.post(f"/api/products/{product.pk}/activate/", **headers)
        self.assertEqual(activated.status_code, 200, activated.data)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.ACTIVE)

    def test_purchase_and_order_actions_enforce_state_and_release_stock(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="FLOW-WH", name="流程仓"
        )
        supplier = Supplier.objects.create(
            organization=self.organization, code="FLOW-SUP", name="流程供应商"
        )
        product = Product.objects.create(
            organization=self.organization, name="流程商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="FLOW-SKU", cost="8"
        )

        purchase = self.client.post(
            "/api/purchase-orders/",
            {
                "number": "PO-FLOW", "supplier": str(supplier.pk),
                "warehouse": str(warehouse.pk), "currency": "CNY",
                "lines": [{"sku": str(sku.pk), "quantity_ordered": "3", "unit_cost": "8"}],
            },
            format="json", **headers,
        )
        self.assertEqual(purchase.status_code, 201, purchase.data)
        purchase_id = purchase.data["id"]
        submitted = self.client.post(f"/api/purchase-orders/{purchase_id}/submit/", **headers)
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], PurchaseOrder.Status.SUBMITTED)
        self.assertEqual(submitted.data["in_transit_quantity"], "3.000")
        balances = self.client.get("/api/stock-balances/", **headers)
        self.assertEqual(balances.status_code, 200)
        self.assertEqual(balances.data["results"][0]["on_hand"], "0.000")
        self.assertEqual(balances.data["results"][0]["in_transit"], 3)

        adjusted = self.client.post(
            "/api/stock-balances/adjust/",
            {
                "warehouse": str(warehouse.pk), "sku": str(sku.pk), "delta": "5",
                "reason": "测试期初库存", "idempotency_key": "api-flow-opening",
            },
            format="json", **headers,
        )
        self.assertEqual(adjusted.status_code, 201, adjusted.data)

        order = self.client.post(
            "/api/orders/",
            {
                "number": "SO-FLOW", "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "3", "unit_price": "20"}],
            },
            format="json", **headers,
        )
        self.assertEqual(order.status_code, 201, order.data)
        order_id = order.data["id"]
        confirmed = self.client.post(f"/api/orders/{order_id}/confirm/", **headers)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

        other_warehouse = Warehouse.objects.create(
            organization=self.organization, code="OTHER-WH", name="其他仓"
        )
        frozen = self.client.patch(
            f"/api/orders/{order_id}/", {"warehouse": str(other_warehouse.pk)},
            format="json", **headers,
        )
        self.assertEqual(frozen.status_code, 400)

        allocated = self.client.post(
            f"/api/orders/{order_id}/allocate/",
            {"idempotency_key": "api-flow-allocate"}, format="json", **headers,
        )
        self.assertEqual(allocated.status_code, 200, allocated.data)
        picking = self.client.post(f"/api/orders/{order_id}/start-picking/", **headers)
        self.assertEqual(picking.status_code, 200, picking.data)
        self.assertEqual(picking.data["status"], SalesOrder.Status.PICKING)
        verified = self.client.post(f"/api/orders/{order_id}/verify/", **headers)
        self.assertEqual(verified.status_code, 200, verified.data)
        self.assertEqual(verified.data["status"], SalesOrder.Status.VERIFIED)
        cancelled = self.client.post(f"/api/orders/{order_id}/cancel/", **headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], SalesOrder.Status.CANCELLED)
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.reserved, 0)

    def test_return_must_reference_shipped_quantity_and_support_partial_receipt(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="RETURN-WH", name="退货仓"
        )
        product = Product.objects.create(organization=self.organization, name="退货商品")
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="RETURN-SKU", cost="10"
        )
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-RETURN-API", warehouse=warehouse,
            status=SalesOrder.Status.SHIPPED,
        )
        SalesOrderLine.objects.create(
            order=order, sku=sku, quantity="2", quantity_shipped="2", unit_price="20"
        )

        excessive = self.client.post(
            "/api/returns/",
            {
                "number": "RET-TOO-MUCH", "original_order": str(order.pk),
                "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity_expected": "3", "condition": "restock"}],
            },
            format="json", **headers,
        )
        self.assertEqual(excessive.status_code, 400)

        rejected = self.client.post(
            "/api/returns/",
            {
                "number": "RET-REJECT", "original_order": str(order.pk),
                "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity_expected": "1", "condition": "restock"}],
            },
            format="json", **headers,
        )
        self.assertEqual(rejected.status_code, 201, rejected.data)
        rejected_result = self.client.post(
            f"/api/returns/{rejected.data['id']}/reject/", **headers
        )
        self.assertEqual(rejected_result.status_code, 200)
        self.assertEqual(rejected_result.data["status"], ReturnOrder.Status.REJECTED)

        created = self.client.post(
            "/api/returns/",
            {
                "number": "RET-API", "original_order": str(order.pk),
                "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity_expected": "2", "condition": "restock"}],
            },
            format="json", **headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        return_id = created.data["id"]
        line_id = created.data["lines"][0]["id"]
        partial = self.client.post(
            f"/api/returns/{return_id}/receive/",
            {"idempotency_key": "return-api-1", "lines": [{"return_line": line_id, "quantity": "1"}]},
            format="json", **headers,
        )
        self.assertEqual(partial.status_code, 200, partial.data)
        self.assertEqual(partial.data["status"], ReturnOrder.Status.PARTIAL)
        self.assertEqual(len(partial.data["receipts"]), 1)

    def test_receive_from_order_is_atomic_and_idempotent(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="RETURN-COMBO", name="组合退货仓"
        )
        product = Product.objects.create(organization=self.organization, name="组合退货商品")
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="RETURN-COMBO-SKU", cost="10"
        )
        order = SalesOrder.objects.create(
            organization=self.organization, number="SO-RETURN-COMBO", warehouse=warehouse,
            status=SalesOrder.Status.SHIPPED,
        )
        SalesOrderLine.objects.create(
            order=order, sku=sku, quantity="2", quantity_shipped="2", unit_price="20"
        )
        payload = {
            "idempotency_key": "return-combo-key",
            "number": "RET-COMBO", "original_order": str(order.pk),
            "warehouse": str(warehouse.pk), "reason": "完好退回",
            "lines": [{
                "sku": str(sku.pk), "quantity_expected": "2",
                "condition": "restock", "unit_refund": "0",
            }],
        }

        first = self.client.post(
            "/api/returns/receive-from-order/", payload, format="json", **headers
        )
        repeated = self.client.post(
            "/api/returns/receive-from-order/", payload, format="json", **headers
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(first.data["id"], repeated.data["id"])
        self.assertEqual(ReturnOrder.objects.filter(number="RET-COMBO").count(), 1)
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.on_hand, 2)

    def test_local_backup_preview_and_commit_import_catalog_snapshot_and_opening_stock(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="DEFAULT", name="默认仓"
        )
        source = {
            "version": 5,
            "products": [
                {
                    "id": "local-own", "name": "本店商品", "kind": "own", "sku": "LOCAL-001",
                    "seller": "Dongbo", "market": "MY", "salesCurrency": "MYR",
                    "costCurrency": "CNY", "standardCost": 12.5, "safetyStock": 3,
                    "defaultSupplier": "迁移供应商", "status": "active",
                    "productUrl": "https://example.com/own", "purchaseUrl": "https://example.com/buy",
                    "image": "https://example.com/own.jpg", "monitoringEnabled": False,
                },
                {
                    "id": "local-competitor", "name": "竞品", "kind": "direct", "sku": "",
                    "seller": "Other", "market": "MY", "salesCurrency": "MYR", "status": "active",
                    "productUrl": "https://example.com/competitor",
                    "image": "https://example.com/competitor.jpg", "monitoringEnabled": True,
                },
            ],
            "snapshots": [{
                "id": "local-snapshot", "productId": "local-competitor",
                "at": "2026-07-15T00:00:00Z", "price": 19.9, "sold": 10,
                "rating": 4.8, "reviews": 5, "lowReviews": 1, "shopRating": 4.7,
            }],
            "inventoryBalances": [{
                "productId": "local-own", "onHand": 7, "reserved": 0,
            }],
            "purchaseOrders": [{"id": "archived-po"}],
            "salesOrders": [], "returns": [], "inventoryMovements": [],
        }

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "local-import-test",
            },
            format="json", **headers,
        )
        repeated = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "local-import-test",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["ready"])
        self.assertEqual(preview.data["summary"]["products"], 2)
        self.assertTrue(any("历史采购" in item for item in preview.data["warnings"]))
        self.assertEqual(committed.status_code, 201, committed.data)
        self.assertEqual(repeated.status_code, 201, repeated.data)
        self.assertEqual(committed.data["id"], repeated.data["id"])
        self.assertEqual(LocalImport.objects.count(), 1)
        self.assertEqual(Product.objects.filter(organization=self.organization).count(), 1)
        self.assertEqual(CompetitorProduct.objects.filter(organization=self.organization).count(), 1)
        self.assertEqual(CompetitorSnapshot.objects.count(), 1)
        sku = SKU.objects.get(organization=self.organization, code="LOCAL-001")
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=sku).on_hand, 7)

    def _local_import_source(self, *, products=None, snapshots=None, balances=None):
        return {
            "version": 5,
            "products": products or [],
            "snapshots": snapshots or [],
            "inventoryBalances": balances or [],
            "purchaseOrders": [],
            "salesOrders": [],
            "returns": [],
            "inventoryMovements": [],
        }

    def test_local_import_sanitizes_unsafe_urls_and_keeps_product_draft(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-URL", name="导入仓"
        )
        source = self._local_import_source(products=[
            {
                "id": "unsafe-own", "name": "不安全链接商品", "kind": "own",
                "sku": "UNSAFE-001", "standardCost": "10", "status": "active",
                "productUrl": "https://user:secret@example.com/item",
                "purchaseUrl": "javascript:alert(1)",
                "image": "http://example.com/not-shared.jpg",
            },
            {
                "id": "unsafe-competitor", "name": "无效竞品", "kind": "direct",
                "productUrl": "javascript:alert(1)",
                "image": "https://example.com/competitor.jpg",
            },
        ])

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "unsafe-url-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["ready"])
        self.assertEqual(committed.status_code, 201, committed.data)
        product = Product.objects.get(organization=self.organization)
        self.assertEqual(product.status, Product.Status.DRAFT)
        self.assertEqual(product.source_url, "")
        self.assertEqual(product.purchase_url, "")
        self.assertFalse(product.images.exists())
        self.assertFalse(CompetitorProduct.objects.filter(organization=self.organization).exists())

    def test_local_import_rejects_malformed_source_without_partial_rows(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-BAD", name="校验仓"
        )
        source = self._local_import_source(
            products=[{"id": None, "name": None, "kind": "own", "sku": None}],
            snapshots=[{"id": "bad-snapshot", "productId": None, "at": "not-a-date"}],
            balances=[{"productId": None, "onHand": 1, "reserved": 0}],
        )

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "bad-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["ready"])
        self.assertEqual(committed.status_code, 400, committed.data)
        self.assertFalse(Product.objects.filter(organization=self.organization).exists())
        self.assertFalse(LocalImport.objects.filter(organization=self.organization).exists())

    def test_local_import_rolls_back_catalog_when_opening_stock_fails(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-ROLLBACK", name="回滚仓"
        )
        source = self._local_import_source(
            products=[{
                "id": "rollback-own", "name": "回滚商品", "kind": "own",
                "sku": "ROLLBACK-001", "standardCost": "8", "status": "active",
                "productUrl": "https://example.com/rollback",
                "image": "https://example.com/rollback.jpg",
                "defaultSupplier": "回滚供应商",
            }],
            balances=[{"productId": "rollback-own", "onHand": 2, "reserved": 0}],
        )

        with patch(
            "apps.erp.local_imports.adjust_inventory",
            side_effect=DjangoValidationError("模拟库存过账失败"),
        ):
            response = self.client.post(
                "/api/local-imports/commit/",
                {
                    "warehouse": str(warehouse.pk), "source": source,
                    "idempotency_key": "rollback-import",
                },
                format="json", **headers,
            )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Product.objects.filter(organization=self.organization).exists())
        self.assertFalse(Supplier.objects.filter(organization=self.organization).exists())
        self.assertFalse(LocalImport.objects.filter(organization=self.organization).exists())

    def test_local_import_idempotency_is_warehouse_bound_and_keys_fit_database(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-IDEM-A", name="幂等仓 A"
        )
        other_warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-IDEM-B", name="幂等仓 B"
        )
        source = self._local_import_source(
            products=[{
                "id": "idem-own", "name": "幂等商品", "kind": "own",
                "sku": "IDEM-001", "standardCost": "5", "status": "active",
                "productUrl": "https://example.com/idem",
                "image": "https://example.com/idem.jpg",
            }],
            balances=[{"productId": "idem-own", "onHand": 1, "reserved": 0}],
        )
        idempotency_key = "k" * 160

        too_long = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "x" * 161,
            },
            format="json", **headers,
        )
        first = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": idempotency_key,
            },
            format="json", **headers,
        )
        wrong_warehouse = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(other_warehouse.pk), "source": source,
                "idempotency_key": idempotency_key,
            },
            format="json", **headers,
        )

        self.assertEqual(too_long.status_code, 400, too_long.data)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(wrong_warehouse.status_code, 400, wrong_warehouse.data)
        ledger = StockLedger.objects.get(organization=self.organization)
        self.assertLessEqual(len(ledger.reference_id), 64)
        self.assertLessEqual(len(ledger.idempotency_key), 160)
        report = LocalImport.objects.get(organization=self.organization)
        with self.assertRaises(DjangoValidationError):
            report.delete()
        with self.assertRaises(DjangoValidationError):
            LocalImport.objects.filter(pk=report.pk).update(status="completed")

    def test_local_import_write_actions_require_manager_role(self):
        viewer = get_user_model().objects.create_user(
            username="import-viewer", password="test-pass-123"
        )
        Membership.objects.create(
            organization=self.organization, user=viewer, role=Membership.Role.VIEWER
        )
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-VIEW", name="只读仓"
        )
        self.client.force_authenticate(viewer)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        source = self._local_import_source()

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "viewer-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 403)
        self.assertEqual(committed.status_code, 403)

    def test_local_import_blocks_open_documents_and_reserved_stock(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-OPEN", name="开放单据仓"
        )
        source = self._local_import_source(
            products=[{
                "id": "open-own", "name": "开放单据商品", "kind": "own",
                "sku": "OPEN-001", "standardCost": "5", "status": "active",
                "productUrl": "https://example.com/open",
                "image": "https://example.com/open.jpg",
            }],
            balances=[{"productId": "open-own", "onHand": 3, "reserved": 1}],
        )
        source.update({
            "purchaseOrders": [{"id": "po-open", "status": "transit"}],
            "salesOrders": [{"id": "so-open", "status": "picking"}],
            "returns": [{"id": "ret-open", "status": "partial"}],
            "reservations": [{"id": "res-open", "status": "active"}],
        })

        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source},
            format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "open-state-import",
            },
            format="json", **headers,
        )

        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["ready"])
        self.assertTrue(any("锁定库存" in error for error in preview.data["errors"]))
        self.assertTrue(any("未完成采购单" in error for error in preview.data["errors"]))
        self.assertTrue(any("未完成订单" in error for error in preview.data["errors"]))
        self.assertTrue(any("未完成退货单" in error for error in preview.data["errors"]))
        self.assertEqual(committed.status_code, 400, committed.data)
        self.assertFalse(LocalImport.objects.filter(organization=self.organization).exists())

    def test_custom_warehouse_types_and_replenishment_policy_are_tenant_scoped(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        created_ids = []
        for code, name, warehouse_type, country, timezone_name in [
            ("MY", "马来仓", "overseas", "my", "Asia/Kuala_Lumpur"),
            ("FWD", "货代仓", "forwarder", "CN", "Asia/Shanghai"),
            ("SCHOOL", "学校仓", "school", "CN", "Asia/Shanghai"),
        ]:
            response = self.client.post(
                "/api/warehouses/",
                {
                    "code": code, "name": name, "warehouse_type": warehouse_type,
                    "country": country, "timezone": timezone_name,
                    "address": {"city": "测试城市"},
                    "contact": {"name": "仓管", "phone": "123"},
                    "can_receive": True, "can_ship": code != "FWD",
                },
                format="json", **headers,
            )
            self.assertEqual(response.status_code, 201, response.data)
            created_ids.append(response.data["id"])
        self.assertEqual(Warehouse.objects.filter(organization=self.organization).count(), 3)
        malaysia = Warehouse.objects.get(pk=created_ids[0])
        self.assertEqual(malaysia.country, "MY")
        self.assertEqual(malaysia.warehouse_type, Warehouse.Type.OVERSEAS)
        self.assertEqual(malaysia.timezone, "Asia/Kuala_Lumpur")

        product = Product.objects.create(
            organization=self.organization, name="补货商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="REPLENISH-SKU", cost="8"
        )
        policy = self.client.post(
            "/api/replenishment-policies/",
            {
                "warehouse": str(malaysia.pk), "sku": str(sku.pk),
                "lead_time_override": 12, "review_cycle_days": 7, "target_days": 35,
                "min_order_qty": "10", "pack_size": "5",
                "safety_stock_override": "8",
            },
            format="json", **headers,
        )
        self.assertEqual(policy.status_code, 201, policy.data)
        self.assertEqual(ReplenishmentPolicy.objects.get().lead_time_override, 12)

        other = Organization.objects.create(name="策略其他组织", slug="policy-other")
        other_warehouse = Warehouse.objects.create(
            organization=other, code="OTHER", name="其他仓"
        )
        cross_org = self.client.post(
            "/api/replenishment-policies/",
            {
                "warehouse": str(other_warehouse.pk), "sku": str(sku.pk),
                "review_cycle_days": 7, "target_days": 30,
                "min_order_qty": "1", "pack_size": "1",
            },
            format="json", **headers,
        )
        self.assertEqual(cross_org.status_code, 400)
        self.assertEqual(ReplenishmentPolicy.objects.count(), 1)

    def test_stock_transfer_api_tracks_in_transit_and_prevents_reposting(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        source = Warehouse.objects.create(
            organization=self.organization, code="TRANSFER-SRC", name="学校仓",
            warehouse_type=Warehouse.Type.SCHOOL,
        )
        destination = Warehouse.objects.create(
            organization=self.organization, code="TRANSFER-DST", name="马来仓",
            warehouse_type=Warehouse.Type.OVERSEAS, country="MY",
        )
        product = Product.objects.create(
            organization=self.organization, name="调拨商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="TRANSFER-SKU", cost="10"
        )
        opening = self.client.post(
            "/api/stock-balances/adjust/",
            {
                "warehouse": str(source.pk), "sku": str(sku.pk), "delta": "6",
                "reason": "调拨测试期初", "idempotency_key": "api-transfer-opening",
            },
            format="json", **headers,
        )
        self.assertEqual(opening.status_code, 201, opening.data)
        created = self.client.post(
            "/api/stock-transfers/",
            {
                "number": "TR-API-001", "source_warehouse": str(source.pk),
                "destination_warehouse": str(destination.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "4"}],
            },
            format="json", **headers,
        )
        self.assertEqual(created.status_code, 201, created.data)
        transfer_id = created.data["id"]
        first_dispatch = self.client.post(
            f"/api/stock-transfers/{transfer_id}/dispatch/",
            {"idempotency_key": "api-dispatch-001"}, format="json", **headers,
        )
        replay_dispatch = self.client.post(
            f"/api/stock-transfers/{transfer_id}/dispatch/",
            {"idempotency_key": "api-dispatch-001"}, format="json", **headers,
        )
        wrong_replay = self.client.post(
            f"/api/stock-transfers/{transfer_id}/dispatch/",
            {"idempotency_key": "api-dispatch-other"}, format="json", **headers,
        )
        self.assertEqual(first_dispatch.status_code, 200, first_dispatch.data)
        self.assertEqual(replay_dispatch.status_code, 200, replay_dispatch.data)
        self.assertEqual(wrong_replay.status_code, 400)
        self.assertEqual(first_dispatch.data["status"], StockTransfer.Status.IN_TRANSIT)
        self.assertEqual(StockBalance.objects.get(warehouse=source, sku=sku).on_hand, 2)
        destination_balance = StockBalance.objects.get(warehouse=destination, sku=sku)
        balances = self.client.get("/api/stock-balances/", **headers)
        destination_row = next(
            row for row in balances.data["results"]
            if row["id"] == str(destination_balance.pk)
        )
        self.assertEqual(destination_row["in_transit"], 4)
        recommendations = self.client.get(
            f"/api/replenishment/recommendations/?warehouse={destination.pk}", **headers
        )
        self.assertEqual(recommendations.status_code, 200, recommendations.data)
        self.assertEqual(recommendations.data[0]["inventory"]["in_transit"], 4)
        refused_delete = self.client.delete(
            f"/api/stock-transfers/{transfer_id}/", **headers
        )
        self.assertEqual(refused_delete.status_code, 400)

        first_receive = self.client.post(
            f"/api/stock-transfers/{transfer_id}/receive/",
            {"idempotency_key": "api-receive-001"}, format="json", **headers,
        )
        replay_receive = self.client.post(
            f"/api/stock-transfers/{transfer_id}/receive/",
            {"idempotency_key": "api-receive-001"}, format="json", **headers,
        )
        self.assertEqual(first_receive.status_code, 200, first_receive.data)
        self.assertEqual(replay_receive.status_code, 200, replay_receive.data)
        destination_balance.refresh_from_db()
        self.assertEqual(destination_balance.on_hand, 4)
        self.assertEqual(
            StockLedger.objects.filter(event_type=StockLedger.Type.TRANSFER_OUT).count(), 1
        )
        self.assertEqual(
            StockLedger.objects.filter(event_type=StockLedger.Type.TRANSFER_IN).count(), 1
        )

    def test_replenishment_recommendations_apply_policy_and_scope_warehouse(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="RECOMMEND", name="建议仓"
        )
        product = Product.objects.create(
            organization=self.organization, name="建议商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="REC-SKU", cost="6"
        )
        policy = ReplenishmentPolicy.objects.create(
            organization=self.organization, warehouse=warehouse, sku=sku,
            lead_time_override=12, review_cycle_days=7, target_days=30,
            min_order_qty="10", pack_size="5", safety_stock_override="5",
        )
        inactive_product = Product.objects.create(
            organization=self.organization, name="停用商品", status=Product.Status.INACTIVE
        )
        SKU.objects.create(
            organization=self.organization, product=inactive_product,
            code="INACTIVE-REC", cost="2",
        )

        response = self.client.get(
            f"/api/replenishment/recommendations/?warehouse={warehouse.pk}", **headers
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        recommendation = response.data[0]
        self.assertEqual(recommendation["sku"], str(sku.pk))
        self.assertEqual(recommendation["policy"], str(policy.pk))
        self.assertEqual(recommendation["lead_time"]["selected_days"], 12)
        self.assertEqual(recommendation["suggested_order_quantity"], 10)
        self.assertTrue(recommendation["needs_reorder"])
        self.assertEqual(recommendation["alert_level"], "red")

        other = Organization.objects.create(name="建议其他组织", slug="recommend-other")
        other_warehouse = Warehouse.objects.create(
            organization=other, code="OTHER-REC", name="其他建议仓"
        )
        denied = self.client.get(
            f"/api/replenishment/recommendations/?warehouse={other_warehouse.pk}",
            **headers,
        )
        self.assertEqual(denied.status_code, 400)

    def test_confirm_and_ship_api_is_atomic_and_idempotent(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="ONE-STEP", name="一键出库仓"
        )
        product = Product.objects.create(
            organization=self.organization, name="一键商品", status=Product.Status.ACTIVE
        )
        sku = SKU.objects.create(
            organization=self.organization, product=product, code="ONE-STEP-SKU", cost="9"
        )
        StockBalance.objects.create(
            organization=self.organization, warehouse=warehouse, sku=sku, on_hand="5"
        )
        order = self.client.post(
            "/api/orders/",
            {
                "number": "SO-ONE-STEP-API", "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "3", "unit_price": "20"}],
            },
            format="json", **headers,
        )
        self.assertEqual(order.status_code, 201, order.data)
        payload = {
            "idempotency_key": "confirm-ship-api-001", "tracking_number": "MY123"
        }
        first = self.client.post(
            f"/api/orders/{order.data['id']}/confirm-and-ship/",
            payload, format="json", **headers,
        )
        replay = self.client.post(
            f"/api/orders/{order.data['id']}/confirm-and-ship/",
            payload, format="json", **headers,
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(first.data["id"], replay.data["id"])
        self.assertEqual(Shipment.objects.count(), 1)
        self.assertEqual(StockBalance.objects.get(warehouse=warehouse, sku=sku).on_hand, 2)

        shortage = self.client.post(
            "/api/orders/",
            {
                "number": "SO-SHORTAGE-API", "warehouse": str(warehouse.pk),
                "lines": [{"sku": str(sku.pk), "quantity": "3", "unit_price": "20"}],
            },
            format="json", **headers,
        )
        failed = self.client.post(
            f"/api/orders/{shortage.data['id']}/confirm-and-ship/",
            {"idempotency_key": "confirm-ship-shortage"}, format="json", **headers,
        )
        self.assertEqual(failed.status_code, 400, failed.data)
        self.assertEqual(
            SalesOrder.objects.get(pk=shortage.data["id"]).status, SalesOrder.Status.DRAFT
        )
        balance = StockBalance.objects.get(warehouse=warehouse, sku=sku)
        self.assertEqual(balance.on_hand, 2)
        self.assertEqual(balance.reserved, 0)

    def test_quick_sales_api_inherits_latest_snapshot_and_requires_history(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        competitor = CompetitorProduct.objects.create(
            organization=self.organization, name="快照竞品", url="https://example.com/quick"
        )
        missing = self.client.post(
            "/api/competitor-snapshots/quick-sales/",
            {"product": str(competitor.pk), "sold_count": 11}, format="json", **headers,
        )
        self.assertEqual(missing.status_code, 400)
        original = CompetitorSnapshot.objects.create(
            product=competitor, captured_at="2026-07-14T08:00:00Z", price="29.90",
            sold_count=10, rating="4.70", review_count=20,
            availability="available", raw={"low_reviews": 2, "shop_rating": 4.8},
        )
        quick = self.client.post(
            "/api/competitor-snapshots/quick-sales/",
            {"product": str(competitor.pk), "sold_count": 15}, format="json", **headers,
        )
        self.assertEqual(quick.status_code, 201, quick.data)
        self.assertEqual(quick.data["sold_count"], 15)
        self.assertEqual(quick.data["price"], "29.9000")
        self.assertEqual(quick.data["rating"], "4.70")
        self.assertEqual(quick.data["review_count"], 20)
        self.assertEqual(quick.data["availability"], "available")
        self.assertEqual(quick.data["raw"], original.raw)

    def test_local_import_preview_accepts_version_six(self):
        self.client.force_authenticate(self.user)
        headers = {"HTTP_X_ORGANIZATION_ID": str(self.organization.pk)}
        warehouse = Warehouse.objects.create(
            organization=self.organization, code="IMPORT-V6", name="第六版导入仓"
        )
        source = self._local_import_source()
        source["version"] = 6
        preview = self.client.post(
            "/api/local-imports/validate/",
            {"warehouse": str(warehouse.pk), "source": source}, format="json", **headers,
        )
        committed = self.client.post(
            "/api/local-imports/commit/",
            {
                "warehouse": str(warehouse.pk), "source": source,
                "idempotency_key": "version-six-import",
            },
            format="json", **headers,
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["ready"])
        self.assertEqual(preview.data["summary"]["source_version"], 6)
        self.assertEqual(committed.status_code, 201, committed.data)
        self.assertEqual(committed.data["source_version"], 6)

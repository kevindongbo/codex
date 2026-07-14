from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.erp.models import (
    AuditLog, Membership, Organization, Product, ProductImage, PurchaseOrder, ReturnOrder,
    SalesOrder, SalesOrderLine, SKU, StockBalance, Supplier, Warehouse,
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

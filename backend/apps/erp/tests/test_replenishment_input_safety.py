from decimal import Decimal

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from apps.erp.models import Membership, Organization, Product, SKU, SKUReplenishmentProfile, Warehouse, ReplenishmentAIJob


class ReplenishmentInputSafetyTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Input safety", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.user = get_user_model().objects.create_user(username="input-safety")
        self.membership = Membership.objects.create(organization=self.organization, user=self.user, role=Membership.Role.ADMIN)
        self.warehouse = Warehouse.objects.create(organization=self.organization, code="SAFE", name="Safe")
        product = Product.objects.create(organization=self.organization, name="Safe", status=Product.Status.ACTIVE)
        self.sku = SKU.objects.create(organization=self.organization, product=product, code="SAFE", safety_stock=5)
        self.profile = SKUReplenishmentProfile.objects.create(organization=self.organization, sku=self.sku, primary_warehouse=self.warehouse)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.client.raise_request_exception = False

    def batch(self, fields, **extra):
        return self.client.post('/api/replenishment/batch-policy/', {
            'sku_ids': [str(self.sku.pk)], 'warehouse': str(self.warehouse.pk), 'fields': fields, **extra,
        }, format='json')

    def test_invalid_numeric_parameters_are_400_and_never_write(self):
        for field, value in [('pack_size', 'NaN'), ('pack_size', 'Infinity'), ('pack_size', '1e100'),
                             ('pack_size', '1.2345'), ('target_coverage_days', 1.5),
                             ('safety_stock', '-1'), ('safety_stock', 'Infinity')]:
            with self.subTest(field=field, value=value):
                response = self.batch({field: value})
                self.assertEqual(response.status_code, 400)
                self.profile.refresh_from_db()
                self.sku.refresh_from_db()
                self.assertEqual(self.profile.target_coverage_days, 30)
                self.assertIsNone(self.profile.pack_size)
                self.assertEqual(self.sku.safety_stock, Decimal('5'))

    def test_invalid_identifiers_are_400(self):
        for payload in [{'sku_ids': ['not-a-uuid']}, {'sku_ids': str(self.sku.pk)}, {'warehouse': 'bad'}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.batch({'pack_size': 6}, **payload).status_code, 400)
        self.assertEqual(self.batch({'primary_warehouse': 'bad'}).status_code, 400)
        self.assertEqual(self.client.post('/api/replenishment/recompute/', {'warehouse': 'bad'}, format='json').status_code, 400)

    def test_recompute_and_profile_changes_require_warehouse_access(self):
        self.membership.role = Membership.Role.BUYER
        self.membership.save()
        self.assertEqual(self.batch({'pack_size': 6}).status_code, 403)
        response = self.client.post('/api/replenishment/recompute/', {'warehouse': str(self.warehouse.pk)}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReplenishmentAIJob.objects.exists())
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.pack_size)
        self.membership.authorized_warehouses.add(self.warehouse)
        self.assertEqual(self.batch({'pack_size': 6}).status_code, 200)

    def test_nullable_fields_and_valid_precision_remain_supported(self):
        response = self.batch({'target_coverage_days': '', 'min_order_qty': None, 'pack_size': '6.125'})
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.target_coverage_days)
        self.assertIsNone(self.profile.min_order_qty)
        self.assertEqual(self.profile.pack_size, Decimal('6.125'))

    def test_authorized_request_warehouse_cannot_hide_unauthorized_primary_warehouse(self):
        other = Warehouse.objects.create(organization=self.organization, code='OTHER', name='Other')
        self.membership.role = Membership.Role.BUYER
        self.membership.save()
        self.membership.authorized_warehouses.add(other)
        self.assertEqual(self.batch({'pack_size': 6}, warehouse=str(other.pk)).status_code, 403)
        self.assertEqual(self.batch({'primary_warehouse': str(self.warehouse.pk)}, warehouse=str(other.pk)).status_code, 403)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.pack_size)
        self.assertEqual(self.profile.primary_warehouse_id, self.warehouse.pk)

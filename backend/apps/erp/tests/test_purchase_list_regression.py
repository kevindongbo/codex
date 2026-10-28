from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.erp.models import Organization, PurchaseOrder
from apps.erp.serializers import PurchaseOrderSerializer


class PurchaseListInitializationTests(SimpleTestCase):
    def setUp(self):
        self.context = {"view": SimpleNamespace(organization=Organization())}

    def test_nonempty_paginated_list_initializes_without_reading_single_order(self):
        serializer = PurchaseOrderSerializer([PurchaseOrder(purchaser_id=1)], many=True, context=self.context)
        self.assertIn("purchaser", serializer.child.fields)

    def test_queryset_initialization_does_not_evaluate_database(self):
        serializer = PurchaseOrderSerializer(PurchaseOrder.objects.all(), many=True, context=self.context)
        self.assertIn("purchaser", serializer.child.fields)

    def test_single_order_keeps_original_purchaser_eligible(self):
        serializer = PurchaseOrderSerializer(PurchaseOrder(purchaser_id=123), context=self.context)
        self.assertIn("123", str(serializer.fields["purchaser"].queryset.query))

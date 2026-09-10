from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PurchaseTrackingMigrationTests(TransactionTestCase):
    before = [('erp', '0036_stock_transfer_exception_close_idempotency')]
    after = [('erp', '0037_purchase_domestic_international_tracking')]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        self.migrate(self.after)
        super().tearDown()

    def test_upgrade_preserves_legacy_and_old_code_writes_and_reverse_is_guarded(self):
        old = self.migrate(self.before)
        org = old.get_model('erp', 'Organization').objects.create(name='Migration QA', slug='migration-qa')
        warehouse = old.get_model('erp', 'Warehouse').objects.create(organization_id=org.pk, name='QA', code='QA')
        supplier = old.get_model('erp', 'Supplier').objects.create(organization_id=org.pk, name='QA', code='QA')
        order = old.get_model('erp', 'PurchaseOrder').objects.create(organization_id=org.pk, warehouse_id=warehouse.pk, supplier_id=supplier.pk, number='QA')
        old_package = old.get_model('erp', 'PurchaseShipment').objects.create(purchase_order_id=order.pk, tracking_number='LEGACY')
        new = self.migrate(self.after)
        model = new.get_model('erp', 'PurchaseShipment')
        package = model.objects.get(pk=old_package.pk)
        self.assertEqual(package.tracking_number, 'LEGACY')
        self.assertEqual(package.domestic_tracking_number, '')
        self.assertEqual(package.international_tracking_number, '')
        # Old application can insert without knowledge of the two new columns.
        old.get_model('erp', 'PurchaseShipment').objects.create(purchase_order_id=order.pk, tracking_number='OLD-CODE')
        package.international_tracking_number = 'INT'
        package.save()
        with self.assertRaisesRegex(RuntimeError, 'preserve the new logistics data'):
            self.migrate(self.before)
        package.international_tracking_number = ''
        package.save()
        reverted = self.migrate(self.before)
        self.assertEqual(reverted.get_model('erp', 'PurchaseShipment').objects.get(pk=old_package.pk).tracking_number, 'LEGACY')
        self.migrate(self.after)

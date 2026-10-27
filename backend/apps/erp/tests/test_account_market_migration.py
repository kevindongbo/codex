from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class AccountMarketMigrationTests(TransactionTestCase):
    def test_old_disabled_accounts_and_myr_prices_survive_additive_migration(self):
        from unittest.mock import patch
        from django.db.migrations.operations.special import RunPython
        # Only in the isolated migration test, allow rolling the freshly empty
        # test schema back to the old state. Production cannot reverse 0039.
        guard = patch.object(RunPython, 'reversible', property(lambda operation: True))
        guard.start()
        self.addCleanup(guard.stop)
        executor = MigrationExecutor(connection)
        migration = executor.loader.get_migration('erp', '0039_account_departure_market_v2')
        for operation in migration.operations:
            if isinstance(operation, RunPython) and operation.reverse_code is None:
                operation.reverse_code = RunPython.noop
        executor.migrate([("erp", "0038_course_work_scheduling")])
        try:
            old = executor.loader.project_state([("erp", "0038_course_work_scheduling")]).apps
            User = old.get_model("auth", "User")
            Org = old.get_model("erp", "Organization")
            user = User.objects.create(username="inactive-history", is_active=False)
            org = Org.objects.create(name="迁移组织", slug="migration-market")
            membership = old.get_model("erp", "Membership").objects.create(organization=org, user=user, active=False, role="admin")
            product = old.get_model("erp", "Product").objects.create(organization=org, name="原商品")
            sku = old.get_model("erp", "SKU").objects.create(organization=org, product=product, code="OLD-SKU")
            Store = old.get_model("erp", "OwnStore")
            Listing = old.get_model("erp", "StoreProduct")
            known = Store.objects.create(organization=org, name="MY", market="马来西亚")
            unknown = Store.objects.create(organization=org, name="旧店", market="未明确的市场")
            conflict = Store.objects.create(organization=org, name="美国旧MYR价", market="美国")
            ids = [Listing.objects.create(organization=org, sku=sku, store=s, sale_price_myr="79.90", commission_override_percent="0").pk for s in (known, unknown, conflict)]
            executor = MigrationExecutor(connection)
            executor.migrate([("erp", "0040_market_price_backfill")])
            new = executor.loader.project_state([("erp", "0040_market_price_backfill")]).apps
            member = new.get_model("erp", "Membership").objects.get(pk=membership.pk)
            self.assertEqual((member.employment_status, member.active, member.revision), ("employed", False, 1))
            NewStore = new.get_model("erp", "OwnStore")
            self.assertEqual(NewStore.objects.get(pk=known.pk).country_code, "MY")
            self.assertEqual(NewStore.objects.get(pk=unknown.pk).country_code, "")
            self.assertEqual(NewStore.objects.get(pk=conflict.pk).country_code, "")
            for listing in new.get_model("erp", "StoreProduct").objects.filter(pk__in=ids):
                self.assertEqual(str(listing.sale_price_myr), "79.90")
                self.assertEqual(str(listing.price_amount), "79.90")
                self.assertEqual((listing.currency, listing.country, str(listing.commission_override_percent)), ("MYR", "MY", "0.00"))
            self.assertFalse(get_user_model().objects.get(pk=user.pk).is_active)
        finally:
            MigrationExecutor(connection).migrate([("erp", "0040_market_price_backfill")])

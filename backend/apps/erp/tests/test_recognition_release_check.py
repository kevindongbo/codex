"""Release preflight is read-only and does not stand in for a vision API run."""
from io import StringIO
from unittest.mock import patch

from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings

from apps.erp.management.commands import check_recognition_store_release as release


@override_settings(SCHEDULING_ENABLED=True, SCHEDULING_RECOGNITION_HOURLY_LIMIT=60)
class RecognitionReleaseCheckTests(SimpleTestCase):
    def use_patch(self, patcher):
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def setUp(self):
        self.output = StringIO()
        self.command = release.Command(stdout=self.output)
        self.connection = self.use_patch(patch.object(release, 'connection'))
        self.connection.vendor = 'postgresql'
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.return_value = (True,)
        self.serializer = self.use_patch(patch.object(release, 'StoreProductSerializer'))
        self.serializer.return_value.data = []
        self.store_query = self.use_patch(patch.object(release.StoreProduct.objects, 'select_related'))
        self.providers = self.use_patch(patch.object(release.AIProviderConfig.objects, 'filter'))
        self.providers.return_value.count.return_value = 1
        self.terms = self.use_patch(patch.object(release.ScheduleTerm.objects, 'filter'))
        self.terms.return_value.count.return_value = 1

    def test_checks_each_table_privilege_using_only_select_statements(self):
        self.command.handle()
        expected = [(model._meta.db_table, privilege)
            for model, privileges in release.REQUIRED_TABLE_PRIVILEGES for privilege in privileges]
        actual = []
        for call in self.cursor.execute.call_args_list:
            sql, parameters = call.args
            self.assertEqual(sql, 'SELECT has_table_privilege(current_user, %s, %s)')
            actual.append(tuple(parameters))
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), sum(len(privileges) for model, privileges in release.REQUIRED_TABLE_PRIVILEGES))
        self.assertNotIn((release.TimetableEvidence._meta.db_table, 'DELETE'), actual)
        self.assertNotIn((release.AIInvocationLog._meta.db_table, 'DELETE'), actual)
        self.assertNotIn((release.AuditLog._meta.db_table, 'DELETE'), actual)
        self.serializer.return_value.save.assert_not_called()
        self.store_query.assert_called_once_with('store', 'sku')
        self.assertIn('TABLE PRIVILEGES OK', self.output.getvalue())
        self.assertIn('No paid API calls or data writes', self.output.getvalue())
        self.assertIn('real image recognition still requires', self.output.getvalue())

    def test_missing_single_write_privilege_fails_even_if_other_privileges_exist(self):
        table = release.SKU._meta.db_table
        def result():
            parameters = self.cursor.execute.call_args.args[1]
            return (parameters != [table, 'UPDATE'],)
        self.cursor.fetchone.side_effect = result
        with self.assertRaisesMessage(CommandError, f'{table}: UPDATE'):
            self.command.handle()
        self.serializer.assert_not_called()
        self.assertNotIn('TABLE PRIVILEGES OK', self.output.getvalue())

    def test_invalid_raw_budget_fails_before_database_access(self):
        for budget in (0, -1, True, False, 1.5, '60', None):
            with self.subTest(budget=budget), self.settings(SCHEDULING_RECOGNITION_HOURLY_LIMIT=budget):
                with self.assertRaisesMessage(CommandError, '必须为正整数'):
                    self.command.handle()
        self.connection.cursor.assert_not_called()
        self.serializer.assert_not_called()

    def test_database_privilege_lookup_error_is_an_explicit_command_failure(self):
        self.cursor.execute.side_effect = DatabaseError('missing relation')
        with self.assertRaisesMessage(CommandError, '无法只读核验 PostgreSQL 表权限'):
            self.command.handle()
        self.serializer.assert_not_called()

    def test_non_postgresql_does_not_claim_postgresql_privileges_are_verified(self):
        self.connection.vendor = 'sqlite'
        self.command.handle()
        self.connection.cursor.assert_not_called()
        self.assertIn('TABLE PRIVILEGES NOT CHECKED', self.output.getvalue())
        self.assertNotIn('TABLE PRIVILEGES OK', self.output.getvalue())

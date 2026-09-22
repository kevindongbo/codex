import io
import tempfile
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings


@skipUnless(connection.vendor == 'postgresql', 'Release preflight targets PostgreSQL')
@override_settings(SCHEDULING_ENABLED=True)
class SchedulingReleaseTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        setting = override_settings(SCHEDULING_PRIVATE_ROOT=self.directory.name)
        setting.enable()
        self.addCleanup(setting.disable)

    def test_migrated_database_passes_without_disclosing_connection(self):
        output = io.StringIO()
        call_command('check_scheduling_release', expect_migrated=True, stdout=output)
        self.assertIn('checks passed', output.getvalue())
        self.assertNotIn('postgresql://', output.getvalue())

    def test_unrelated_pending_migration_rejected(self):
        target = 'apps.erp.management.commands.check_scheduling_release.MigrationExecutor'
        with patch(target) as executor:
            executor.return_value.migration_plan.return_value = [(SimpleNamespace(app_label='erp', name='0037'), False)]
            with self.assertRaisesMessage(CommandError, 'Unrelated migrations'):
                call_command('check_scheduling_release')

    def test_public_media_root_rejected(self):
        with override_settings(MEDIA_ROOT=self.directory.name):
            with self.assertRaisesMessage(CommandError, 'outside public media'):
                call_command('check_scheduling_release')

    def test_disabled_flag_rejected(self):
        with override_settings(SCHEDULING_ENABLED=False):
            with self.assertRaisesMessage(CommandError, 'disabled'):
                call_command('check_scheduling_release')

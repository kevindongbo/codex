import io
from unittest import skipUnless
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from apps.erp.models import Organization, ProfitCalculationStrategy


@skipUnless(connection.vendor == 'postgresql', 'Production checks target PostgreSQL')
class OptimizationReleaseTests(TestCase):
    def test_serialization_checks_do_not_disclose_strategy_values(self):
        org = Organization.objects.create(name='Release', slug='optimization-release')
        ProfitCalculationStrategy.objects.create(organization=org, name='private-test-name', config={'country':'MY'})
        output = io.StringIO()
        call_command('check_erp_optimization_release', stdout=output)
        self.assertIn('checks passed (1 records)', output.getvalue())
        self.assertNotIn('private-test-name', output.getvalue())
        self.assertNotIn('country', output.getvalue())

    def test_missing_right_stops_release(self):
        target = 'apps.erp.management.commands.check_erp_optimization_release.connection'
        with patch(target) as db:
            db.vendor = 'postgresql'
            db.cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
            with self.assertRaisesMessage(CommandError, 'needs SELECT'):
                call_command('check_erp_optimization_release')

    def test_bad_strategy_stops_without_rewriting_it(self):
        org = Organization.objects.create(name='Release', slug='bad-strategy')
        record = ProfitCalculationStrategy.objects.create(organization=org, name='bad-private', config={'advertising_rebate_percent':'not-a-number'})
        with self.assertRaisesMessage(CommandError, 'cannot be serialized'):
            call_command('check_erp_optimization_release')
        record.refresh_from_db()
        self.assertEqual(record.config['advertising_rebate_percent'], 'not-a-number')

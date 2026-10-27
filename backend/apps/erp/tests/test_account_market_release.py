from io import StringIO
import importlib.util
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from apps.erp.models import Membership, Organization, MarketSnapshot


class AccountMarketReleaseTests(TestCase):
    def test_preflight_and_inventory_are_read_only_and_do_not_print_people(self):
        org = Organization.objects.create(name="private-org", slug="release-test")
        user = get_user_model().objects.create_user(username="private-person")
        Membership.objects.create(organization=org, user=user)
        output = StringIO()
        counts = (Membership.objects.count(), MarketSnapshot.objects.count())
        call_command("check_account_market_release", stdout=output)
        self.assertIn("SYNTHETIC CALCULATION OK", output.getvalue())
        self.assertNotIn("private-person", output.getvalue())
        self.assertNotIn("private-org", output.getvalue())
        self.assertEqual(counts, (Membership.objects.count(), MarketSnapshot.objects.count()))
        root = Path(__file__).resolve().parents[4]
        spec = importlib.util.spec_from_file_location("release_helper_test", root / "deploy/account-market-check.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        before = helper.inventory()
        self.assertEqual(before, helper.inventory())
        self.assertEqual(before["members"]["count"], 1)
        self.assertNotIn("private-person", str(before))

    def test_invalid_departed_user_blocks_release_without_changing_records(self):
        org = Organization.objects.create(name="release", slug="invalid-release-test")
        user = get_user_model().objects.create_user(username="invalid-departed", is_active=True)
        member = Membership.objects.create(organization=org, user=user, active=False, employment_status="departed")
        with self.assertRaisesMessage(CommandError, "离职人员仍启用"):
            call_command("check_account_market_release")
        member.refresh_from_db()
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(member.active)

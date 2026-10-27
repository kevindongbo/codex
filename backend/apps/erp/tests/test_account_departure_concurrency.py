from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless
from unittest.mock import patch
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, close_old_connections, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from apps.erp.authentication import InternalJWTAuthentication, issue_refresh
from apps.erp.models import AuditLog, Membership, Organization


@skipUnless(connection.vendor == "postgresql", "Real PostgreSQL row locks required")
class AccountDepartureConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="并发", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.owner = get_user_model().objects.create_user(username="owner", is_superuser=True)
        self.user = get_user_model().objects.create_user(username="child")
        self.member = Membership.objects.create(organization=self.org, user=self.user, role="admin")
        self.url = f"/api/internal-accounts/{self.member.pk}/archive/"

    def archive(self, key):
        close_old_connections()
        try:
            c = APIClient()
            c.force_authenticate(self.owner)
            return c.post(self.url, {"revision": 1}, format="json", HTTP_IDEMPOTENCY_KEY=key)
        finally:
            close_old_connections()

    def test_concurrent_retry_has_one_audit_and_generation(self):
        key = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.archive, key) for _ in range(2)]
            results = [f.result(timeout=15) for f in futures]
        self.assertEqual([r.status_code for r in results], [200, 200], [r.data for r in results])
        self.assertEqual(results[0].data, results[1].data)
        self.assertEqual(AuditLog.objects.filter(action="account.archive").count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.account_security.auth_version, 1)

    def test_write_waiting_behind_archive_rechecks_authentication(self):
        access = str(issue_refresh(self.user).access_token)
        entered = Event()
        original = InternalJWTAuthentication.get_user
        def observed(authentication, token):
            entered.set()
            return original(authentication, token)
        def write():
            close_old_connections()
            try:
                c = APIClient()
                c.credentials(HTTP_AUTHORIZATION="Bearer " + access)
                return c.post("/api/profit-calculator/calculate/", {}, format="json").status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(InternalJWTAuthentication, "get_user", observed):
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                pending = pool.submit(write)
                self.assertTrue(entered.wait(5))
                c = APIClient()
                c.force_authenticate(self.owner)
                r = c.post(self.url, {"revision": 1}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
                self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(pending.result(timeout=15), 401)

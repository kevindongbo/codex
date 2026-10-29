import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.erp.models import Organization, Membership, MarketSnapshot, MarketWorkspace
from .test_market_v2 import MarketV2Tests


@override_settings(MARKET_MX_ENABLED=False)
class MexicoPausedTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="测试", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.owner = get_user_model().objects.create_user(username="owner", is_superuser=True)
        Membership.objects.create(organization=self.org, user=self.owner, role="admin")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.base = "/api/profit-calculator/v2/"

    def test_no_new_mexico_activity_but_history_stays_readable(self):
        saved = MarketSnapshot.objects.create(organization=self.org, created_by=self.owner, country="MX", currency="MXN",
            kind="plan", plan_key=uuid.uuid4(), version=1, name="历史墨西哥方案", content_hash="old",
            payload={"result": {"gross_profit": "294.00"}})
        workspace = MarketWorkspace.objects.create(organization=self.org, country="MX", config={"country":"MX","currency":"MXN"})
        markets = self.client.get(self.base + "markets/").data["markets"]
        self.assertEqual([m["code"] for m in markets], ["MY", "US"])
        self.assertEqual(self.client.get(self.base + "config/?country=MX").status_code, 404)
        data = MarketV2Tests().data("MX")
        requests = [("working-config/?country=MX", {"revision":1,"config":{}}, "put"),
                    ("exchange-rates/", {"country":"MX"}, "post"),
                    ("shipping-quotes/", {"country":"MX"}, "post"),
                    ("calculate/", data, "post"),
                    ("plans/save/", {"input":data}, "post")]
        for path, payload, method in requests:
            response = getattr(self.client, method)(self.base+path,payload,format="json",HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(response.status_code,400,path)
            self.assertIn("墨西哥试算已暂停",str(response.data))
        history=self.client.get(self.base+f"plans/{saved.pk}/?country=MX")
        self.assertEqual(history.status_code,200)
        self.assertEqual(history.data["payload"]["result"]["gross_profit"],"294.00")
        workspace.refresh_from_db()
        self.assertEqual(workspace.config,{"country":"MX","currency":"MXN"})
        self.assertEqual(MarketSnapshot.objects.count(),1)

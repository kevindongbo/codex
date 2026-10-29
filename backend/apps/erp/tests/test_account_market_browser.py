"""Real browser -> HTTP -> Django -> isolated PostgreSQL -> reload."""
import os
from pathlib import Path
import subprocess
from unittest import skipUnless
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.http import HttpResponse
from django.test import LiveServerTestCase, override_settings
from django.urls import path
from config.urls import urlpatterns as production_patterns
from apps.erp.authentication import issue_refresh
from apps.erp.models import Membership, Organization, Warehouse, MarketSnapshot, ExchangeRateSnapshot
from django.utils import timezone

ROOT = Path(__file__).resolve().parents[4]
FILES = {"index.html": "text/html", **{x: "text/javascript" for x in ["app.js", "team.js", "market-profit.js", "profit-calculator.js", "runtime-config.js", "scheduling.js"]},
         "styles.css": "text/css", "scheduling.css": "text/css"}


def asset(request, name):
    if name not in {"dongbo-erp-mark.png", "dongbo-erp-logo.png", "og-dongbo-crossborder.png", "dongbo-mark.svg"}:
        return HttpResponse(status=404)
    return HttpResponse((ROOT / "assets" / name).read_bytes(), content_type="image/svg+xml" if name.endswith("svg") else "image/png")


def page(request, name="index.html"):
    if name == "favicon.ico":
        return HttpResponse(status=204)
    if name not in FILES:
        return HttpResponse(status=404)
    content = (ROOT / name).read_text(encoding="utf-8")
    if name == "index.html":
        content = content.replace("<head>", '<head><script>window.DONGBO_CONFIG={mode:"team",apiBase:"/api"};</script>')
    return HttpResponse(content, content_type=FILES[name])


urlpatterns = [path("assets/<str:name>", asset), path("", page), path("<str:name>", page), *production_patterns]


@skipUnless(connection.vendor == "postgresql" and os.environ.get("NODE_EXECUTABLE"), "Requires PostgreSQL and browser runtime")
@override_settings(ROOT_URLCONF=__name__, SCHEDULING_ENABLED=False)
class AccountMarketBrowserTests(LiveServerTestCase):
    def test_accounts_and_market_scenarios_save_and_reload(self):
        org = Organization.objects.create(name="E2E", slug=settings.INTERNAL_ORGANIZATION_SLUG)
        owner = get_user_model().objects.create_user(username="owner", is_superuser=True)
        Membership.objects.create(organization=org, user=owner, role="admin")
        user = get_user_model().objects.create_user(username="departed-example")
        member = Membership.objects.create(organization=org, user=user, display_name="离职测试人员", role="admin")
        wh = Warehouse.objects.create(organization=org, code="E2E", name="测试仓库")
        ExchangeRateSnapshot.objects.create(organization=org, effective_date=timezone.localdate(), fetched_at=timezone.now(), myr_cny="1.68", myr_usd=".235", source="synthetic", is_current=True)
        env = dict(os.environ, MARKET_TEST_URL=self.live_server_url, MARKET_TEST_REFRESH=str(issue_refresh(owner)),
                   MARKET_TEST_ORG=str(org.pk), MARKET_TEST_WH=str(wh.pk), MARKET_TEST_MEMBER=str(member.pk))
        completed = subprocess.run([os.environ["NODE_EXECUTABLE"], str(ROOT / "tests/browser/account-market-live.test.mjs")],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        member.refresh_from_db()
        self.assertEqual((member.employment_status, member.active, member.permissions), ("employed", False, ["view"]))
        plans = MarketSnapshot.objects.filter(kind="plan")
        self.assertEqual(plans.count(), 1)
        self.assertEqual(set(plans.values_list("country", flat=True)), {"US"})
        self.assertEqual(plans.get(country="US").payload["result"]["gross_profit"], "53.00")

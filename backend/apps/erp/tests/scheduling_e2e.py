"""Opt-in real HTTP/PostgreSQL/browser/worker test; only vision transport mocked.

Run: manage.py test apps.erp.tests.scheduling_e2e --noinput
Requires NODE_EXECUTABLE, Playwright and CODEX_NODE_MODULES when not installed locally.
"""
import base64
import io
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
from unittest import skipUnless
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, connections, close_old_connections
from django.http import HttpResponse
from django.test import LiveServerTestCase, override_settings
from django.urls import path
from config.urls import urlpatterns as production_patterns
from apps.erp.models import Organization, Membership, AIProviderConfig
from apps.erp.scheduling_models import ScheduleTerm, MemberWeekPlan, TimetableEvidence, TimetableRecognitionJob, ScheduleOverride
from apps.erp.scheduling_services import monday, today
from apps.erp.timetable_recognition import run_one_job, candidate_grid
from datetime import timedelta
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]


def fixture_page(request):
    html = '<button id="scheduleNav" hidden>排班</button><button data-schedule-page="board">工作安排</button><button data-schedule-page="evidence">原始凭证</button><main id="module-scheduling"><div id="schedulingRoot"></div></main>'
    return HttpResponse('<meta charset="utf-8"><style>' + (ROOT / 'scheduling.css').read_text(encoding='utf-8') + '</style>' + html + '<script>' + (ROOT / 'scheduling.js').read_text(encoding='utf-8') + '</script>')


urlpatterns = [path('__scheduling_test__/', fixture_page), *production_patterns]


@skipUnless(connection.vendor == 'postgresql', 'Real scheduling E2E requires PostgreSQL')
@override_settings(ROOT_URLCONF=__name__, SCHEDULING_ENABLED=True, OWNER_EMAIL_VERIFICATION_REQUIRED=False)
class SchedulingEndToEndTests(LiveServerTestCase):
    def test_browser_upload_worker_confirm_leave_and_privacy(self):
        with tempfile.TemporaryDirectory() as private, override_settings(SCHEDULING_PRIVATE_ROOT=private):
            org = Organization.objects.create(name='E2E', slug=settings.INTERNAL_ORGANIZATION_SLUG)
            password = secrets.token_urlsafe(32)
            member = get_user_model().objects.create_user(username='schedule-e2e-member', password=password)
            other = get_user_model().objects.create_user(username='schedule-e2e-other', password=password)
            for user in (member, other):
                Membership.objects.create(organization=org, user=user, role=Membership.Role.VIEWER, display_name=user.username)
            provider = AIProviderConfig.objects.create(organization=org, name='fixture-only', api_base_url='https://example.invalid/v1', model_name='fixture', api_key_encrypted='')
            term = ScheduleTerm.objects.create(organization=org, name='E2E term', first_monday=monday(today())+timedelta(days=7), recognition_provider=provider)
            png = io.BytesIO()
            Image.new('RGB', (20, 20), 'white').save(png, format='PNG')
            env = dict(os.environ, SCHEDULING_TEST_URL=self.live_server_url, SCHEDULING_TEST_PASSWORD=password,
                       SCHEDULING_TEST_IMAGE=base64.b64encode(png.getvalue()).decode(), SCHEDULING_TEST_ORG=str(org.pk), SCHEDULING_TEST_USER=str(member.pk))
            stop, failures = threading.Event(), []
            def worker():
                close_old_connections()
                try:
                    while not stop.wait(.2):
                        run_one_job()
                except Exception as exc:
                    failures.append(type(exc).__name__)
                finally:
                    connections.close_all()
            grid = candidate_grid({'courses':[{'day':1, 'start_period':1, 'end_period':2, 'course_name':'Private fixture course'}]}, term.periods)
            with patch('apps.erp.timetable_recognition.invoke_vision', return_value=grid):
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                try:
                    result = subprocess.run([os.environ.get('NODE_EXECUTABLE', 'node'), str(ROOT/'tests/browser/scheduling-live.test.mjs')], env=env, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
                finally:
                    stop.set(); thread.join(timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(failures)
            self.assertEqual(TimetableRecognitionJob.objects.get().status, 'succeeded')
            self.assertEqual(TimetableEvidence.objects.count(), 1)
            self.assertEqual(MemberWeekPlan.objects.count(), 1)
            self.assertEqual(ScheduleOverride.objects.count(), 12)
            self.assertEqual(MemberWeekPlan.objects.get().confirmed_grid[0][0]['status'], 'class')

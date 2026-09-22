import io
import tempfile
import uuid
from datetime import date, timedelta
from unittest.mock import patch
from unittest import skipUnless

from PIL import Image
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from rest_framework.test import APIClient
from apps.erp.models import Organization, Membership, AIProviderConfig
from apps.erp.scheduling_models import ScheduleTerm, MemberWeekPlan, WorkScheduleCell, ScheduleOverride


@override_settings(SCHEDULING_ENABLED=True)
class SchedulingTests(TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.files = override_settings(SCHEDULING_PRIVATE_ROOT=self.root.name)
        self.files.enable()
        self.addCleanup(self.files.disable)
        self.org = Organization.objects.create(name='Team', slug=settings.INTERNAL_ORGANIZATION_SLUG)
        self.owner = get_user_model().objects.create_user(username='owner', is_superuser=True)
        self.member = get_user_model().objects.create_user(username='member')
        self.other = get_user_model().objects.create_user(username='other')
        for user in (self.member, self.other):
            Membership.objects.create(organization=self.org, user=user, role=Membership.Role.VIEWER)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.start = date(2035, 1, 1)
        self.term = self.send('terms/', {'name': 'Term', 'first_monday': str(self.start), 'week_count': 20}).data
        self.client.force_authenticate(self.member)

    def send(self, path, data, method='post', key=None):
        return getattr(self.client, method)('/api/scheduling/' + path, data, format='json', HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))

    def draft(self, complete=True):
        image = io.BytesIO()
        Image.new('RGB', (10, 10), 'white').save(image, format='PNG')
        response = self.client.post('/api/scheduling/evidence/', {'file': SimpleUploadedFile('test.png', image.getvalue(), content_type='image/png')}, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        evidence = response.data['results'][0]
        response = self.send('imports/', {'term_id': self.term['id'], 'evidence_id': evidence['id'], 'selected_weeks': [1, 2]})
        self.assertEqual(response.status_code, 201, response.data)
        draft = response.data
        grid = [[{'status': 'free' if complete else 'unknown', 'course_name': ''} for _ in range(12)] for _ in range(7)]
        grid[0][0] = {'status': 'class', 'course_name': 'Private course'}
        response = self.send('imports/' + draft['id'] + '/', {'revision': draft['revision'], 'draft_grid': grid}, 'patch')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data, evidence

    def confirm(self, draft, replace=False, key=None):
        return self.send('imports/' + draft['id'] + '/confirm/', {'revision': draft['revision'], 'expected_week_revisions': draft['expected_week_revisions'], 'replace_existing': replace}, key=key)

    def test_confirm_full_weeks_idempotency_and_weekend(self):
        draft, _ = self.draft()
        key = str(uuid.uuid4())
        first = self.confirm(draft, key=key)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(self.confirm(draft, key=key).data, first.data)
        self.assertEqual(MemberWeekPlan.objects.count(), 2)
        self.assertEqual(WorkScheduleCell.objects.count(), 168)
        self.assertEqual(WorkScheduleCell.objects.get(date=self.start, period=1).effective_status, 'class')
        self.assertEqual(WorkScheduleCell.objects.get(date=self.start + timedelta(days=5), period=1).effective_status, 'work')
        self.assertEqual(WorkScheduleCell.objects.get(date=self.start + timedelta(days=6), period=1).effective_status, 'rest')

    def test_unknown_cannot_publish(self):
        draft, _ = self.draft(False)
        self.assertEqual(self.confirm(draft).status_code, 400)
        self.assertFalse(WorkScheduleCell.objects.exists())

    def test_private_evidence_and_shared_board(self):
        draft, evidence = self.draft()
        self.confirm(draft)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(evidence['content_url']).status_code, 404)
        self.assertEqual(self.client.get('/api/scheduling/imports/' + draft['id'] + '/').status_code, 404)
        board = self.client.get('/api/scheduling/board/?week_start=' + str(self.start))
        self.assertEqual(board.status_code, 200)
        self.assertNotIn('Private course', str(board.data))
        self.assertNotIn('private_file', str(board.data))

    def test_member_reason_required_and_recompute_preserves_leave(self):
        draft, _ = self.draft()
        self.confirm(draft)
        day = str(self.start)
        payload = {'dates': [day], 'periods': [2], 'status': 'leave', 'reason': '', 'expected_revisions': {day + ':2': 1}}
        self.assertEqual(self.send('adjustments/', payload).status_code, 400)
        payload['reason'] = '私密请假原因'
        result = self.send('adjustments/', payload)
        self.assertEqual(result.status_code, 200, result.data)
        revised, _ = self.draft()
        self.assertEqual(self.confirm(revised, replace=True).status_code, 200)
        self.assertEqual(WorkScheduleCell.objects.get(date=self.start, period=2).effective_status, 'leave')
        self.client.force_authenticate(self.other)
        board = self.client.get('/api/scheduling/board/?week_start=' + day).data
        self.assertNotIn('私密请假原因', str(board))
        self.assertIn('leave', str(board))
        self.client.force_authenticate(self.member)
        row = ScheduleOverride.objects.get()
        self.assertEqual(self.send('adjustments/' + str(row.pk) + '/revoke/', {'revision': row.revision, 'reason': '恢复上班'}).status_code, 200)
        self.assertEqual(WorkScheduleCell.objects.get(date=self.start, period=2).effective_status, 'work')

    def test_admin_force_optional_annotation_and_member_cannot_override(self):
        draft, _ = self.draft()
        self.confirm(draft)
        self.client.force_authenticate(self.owner)
        payload = {'target_user': self.member.pk, 'dates': [str(self.start)], 'periods': [1], 'status': 'work', 'show_annotation': False, 'expected_revisions': {str(self.start) + ':1': 1}}
        self.assertEqual(self.send('adjustments/', payload).status_code, 409)
        payload['force'] = True
        self.assertEqual(self.send('adjustments/', payload).status_code, 200)
        self.assertFalse(ScheduleOverride.objects.get().show_annotation)
        self.client.force_authenticate(self.member)
        payload.update(status='leave', reason='去办理业务', expected_revisions={str(self.start) + ':1': 2})
        self.assertEqual(self.send('adjustments/', payload).status_code, 403)

    def test_stale_revision_and_atomic_replacement(self):
        draft, _ = self.draft()
        self.confirm(draft)
        revised, _ = self.draft()
        revised['expected_week_revisions'][str(self.start)] = 0
        self.assertEqual(self.confirm(revised, replace=True).status_code, 409)
        self.assertEqual(list(MemberWeekPlan.objects.values_list('revision', flat=True)), [1, 1])

    def test_twenty_weeks_then_single_week_replacement(self):
        draft, _ = self.draft()
        draft = self.send('imports/' + draft['id'] + '/', {'revision': draft['revision'], 'selected_weeks': list(range(1,21))}, 'patch').data
        self.assertEqual(self.confirm(draft).status_code, 200)
        self.assertEqual(WorkScheduleCell.objects.count(), 20 * 84)
        revised, _ = self.draft()
        revised = self.send('imports/' + revised['id'] + '/', {'revision': revised['revision'], 'selected_weeks': [4], 'weekend_day': 'sun'}, 'patch').data
        self.assertEqual(self.confirm(revised, replace=True).status_code, 200)
        self.assertEqual(MemberWeekPlan.objects.filter(revision=1).count(), 19)
        self.assertEqual(MemberWeekPlan.objects.get(week_index=4).weekend_day, 'sun')

    def test_admin_config_and_archive_revision(self):
        draft, _ = self.draft()
        self.assertEqual(self.send('imports/' + draft['id'] + '/archive/', {}).status_code, 409)
        self.assertEqual(self.send('imports/' + draft['id'] + '/archive/', {'revision': draft['revision']}).status_code, 200)
        self.assertEqual(self.send('terms/', {}).status_code, 403)
        self.client.force_authenticate(self.owner)
        provider = AIProviderConfig.objects.create(organization=self.org, name='vision', api_base_url='https://example.com', model_name='vision')
        result = self.send('terms/' + self.term['id'] + '/', {'recognition_provider_id': str(provider.pk)}, 'patch')
        self.assertEqual(result.status_code, 200, result.data)

    @override_settings(SCHEDULING_ENABLED=False)
    def test_disabled_context_does_not_query_new_tables(self):
        with patch.object(ScheduleTerm.objects, 'filter', side_effect=AssertionError('must not query')):
            response = self.client.get('/api/scheduling/context/')
        self.assertFalse(response.data['enabled'])
        self.assertEqual(self.client.get('/api/scheduling/board/').status_code, 404)


@override_settings(SCHEDULING_ENABLED=True)
@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock concurrency test')
class SchedulingConcurrencyTests(TransactionTestCase):
    setUp = SchedulingTests.setUp
    send = SchedulingTests.send
    draft = SchedulingTests.draft

    @skipUnlessDBFeature('has_select_for_update')
    def test_overlapping_confirmations_one_wins_without_partial_write(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections, connections
        first, _ = self.draft()
        second, _ = self.draft()
        barrier = Barrier(2)
        def publish(draft):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=self.member.pk))
                barrier.wait(timeout=10)
                return client.post('/api/scheduling/imports/' + draft['id'] + '/confirm/', {'revision': draft['revision'], 'expected_week_revisions': draft['expected_week_revisions'], 'replace_existing': True}, format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())).status_code
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(publish, (first, second)))
        self.assertEqual(sorted(responses), [200,409])
        self.assertEqual(MemberWeekPlan.objects.count(), 2)
        self.assertEqual(WorkScheduleCell.objects.count(), 168)

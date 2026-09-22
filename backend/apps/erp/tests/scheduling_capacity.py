"""Opt-in synthetic capacity test; run against a disposable PostgreSQL test DB."""
import time
from datetime import date, timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from apps.erp.models import Organization, Membership
from apps.erp.scheduling_models import ScheduleTerm, ScheduleParticipant, WorkScheduleCell


@override_settings(SCHEDULING_ENABLED=True)
class CapacityTest(TestCase):
    def test_100_people_20_weeks(self):
        org = Organization.objects.create(name='Capacity', slug=settings.INTERNAL_ORGANIZATION_SLUG)
        users = get_user_model().objects.bulk_create([get_user_model()(username=f'capacity-{i}') for i in range(100)])
        start = date(2035,1,1)
        ScheduleTerm.objects.create(organization=org,name='Capacity',first_monday=start)
        Membership.objects.bulk_create([Membership(organization=org,user=u,role=Membership.Role.VIEWER) for u in users])
        ScheduleParticipant.objects.bulk_create([ScheduleParticipant(organization=org,user=u,effective_from=start) for u in users])
        for week in range(20):
            WorkScheduleCell.objects.bulk_create([
                WorkScheduleCell(organization=org,owner=u,date=start+timedelta(days=week*7+d),period=p,
                    base_status='work',effective_status='work',period_start='08:20',period_end='09:05')
                for u in users for d in range(7) for p in range(1,13)
            ],batch_size=1000)
        client=APIClient()
        client.force_authenticate(users[0])
        samples=[]
        for _ in range(10):
            begin=time.perf_counter()
            result=client.get('/api/scheduling/board/?week_start=2035-01-01')
            samples.append(time.perf_counter()-begin)
            self.assertEqual(result.status_code,200)
            self.assertEqual(len(result.data['cells']),84)
            self.assertTrue(all(c['counts']['work']==100 for c in result.data['cells']))
        p95=sorted(samples)[-1]
        print(f'Capacity: 168000 cells, 10 board requests, conservative P95={p95:.3f}s')
        self.assertLess(p95,2.0)

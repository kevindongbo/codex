"""Scheduling API: shared board, private sources, owner-only administration."""
import hashlib
import io
import os
import uuid
import warnings
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import FileResponse
from rest_framework.generics import get_object_or_404
from django.db import transaction
from django.utils import timezone
from PIL import Image
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import Membership, Organization, AIProviderConfig
from .permissions import is_owner
from .scheduling_permissions import SchedulePermission
from .scheduling_models import (ScheduleTerm, ScheduleParticipant, TimetableEvidence, TimetableImport,
    TimetableRecognitionJob, MemberWeekPlan, MemberWeekPlanVersion, WorkScheduleCell, ScheduleOverride, default_periods)
from . import scheduling_services as service


def term_json(t):
    return dict(id=str(t.pk), name=t.name, first_monday=str(t.first_monday), week_count=t.week_count,
        timezone=t.timezone, periods=t.periods, locked_at=t.locked_at.isoformat() if t.locked_at else None,
        recognition_provider_id=str(t.recognition_provider_id) if t.recognition_provider_id else None)

def evidence_json(e):
    return dict(id=str(e.pk), owner_id=e.owner_id, original_name=e.original_name, sha256=e.sha256,
        size=e.size, content_type=e.content_type, uploaded_at=e.created_at.isoformat(), created_at=e.created_at.isoformat(),
        pixel_width=e.pixel_width, pixel_height=e.pixel_height, content_url=f'/api/scheduling/evidence/{e.pk}/content/')

def import_json(i):
    expected = {}
    weeks = [i.term.first_monday+timedelta(weeks=w-1) for w in i.selected_weeks]
    current = {p.week_start: p.revision for p in MemberWeekPlan.objects.filter(organization=i.organization, owner=i.owner, week_start__in=weeks)}
    for w in weeks:
        expected[str(w)] = current.get(w, 0)
    job = i.jobs.order_by('-created_at').first()
    return dict(id=str(i.pk), owner_id=i.owner_id, term_id=str(i.term_id), evidence_id=str(i.evidence_id), state=i.state,
        draft_grid=i.draft_grid, selected_weeks=i.selected_weeks, weekend_day=i.weekend_day, revision=i.revision,
        expected_week_revisions=expected, created_at=i.created_at.isoformat(), job=job_json(job) if job else None)

def job_json(j):
    return dict(id=str(j.pk), import_id=str(j.timetable_import_id), status=j.status, attempts=j.attempts,
        sanitized_error=j.sanitized_error, candidate_grid=j.candidate_grid, input_revision=j.input_revision,
        warnings=j.recognition_warnings)

def plan_json(p):
    return dict(id=str(p.pk), owner_id=p.owner_id, term_id=str(p.term_id), week_start=str(p.week_start), week_index=p.week_index,
        confirmed_grid=p.confirmed_grid, weekend_day=p.weekend_day, evidence_id=str(p.evidence_id), revision=p.revision)


class ScheduleAPI(APIView):
    permission_classes = [SchedulePermission]
    operation = ''

    def owner(self, raw=None):
        if raw is None or str(raw) == str(self.request.user.pk):
            return self.request.user
        if not is_owner(self.request.user):
            raise PermissionDenied('只能操作本人数据')
        person = get_object_or_404(get_user_model(), pk=raw, is_active=True)
        if not person.is_superuser and not Membership.objects.filter(organization=self.organization, user=person, active=True).exists():
            raise PermissionDenied('成员不属于本组织')
        return person

    def private(self, model, pk):
        query = model.objects.filter(organization=self.organization)
        if not is_owner(self.request.user):
            query = query.filter(owner=self.request.user)
        return get_object_or_404(query, pk=pk)

    def admin(self):
        if not is_owner(self.request.user):
            raise PermissionDenied('仅超级管理员可操作')

    def run_mutation(self, callback):
        if not isinstance(self.request.data, dict):
            raise ValidationError('请求必须为JSON对象')
        for field in ('expected_week_revisions', 'expected_revisions'):
            if field in self.request.data and not isinstance(self.request.data[field], dict):
                raise ValidationError(f'{field}必须为版本映射')
        for field in ('dates', 'week_starts'):
            if field in self.request.data and not isinstance(self.request.data[field], list):
                raise ValidationError(f'{field}必须为数组')
        for field in ('reason', 'name'):
            if field in self.request.data and not isinstance(self.request.data[field], str):
                raise ValidationError(f'{field}必须为文字')
        for field in ('force', 'show_annotation', 'replace_existing', 'historical_correction'):
            if field in self.request.data and type(self.request.data[field]) is not bool:
                raise ValidationError(f'{field}必须为布尔值')
        return service.mutate(self.organization, self.request.user, self.request.headers.get('Idempotency-Key'),
            {'path': self.request.path, 'data': self.request.data}, callback)

    def get(self, request, pk=None):
        org, op = self.organization, self.operation
        if op == 'context':
            if not getattr(settings, 'SCHEDULING_ENABLED', False):
                return Response({'enabled': False, 'user': {'id': request.user.pk, 'is_superuser': is_owner(request.user)}, 'terms': [], 'revision': 0, 'week_start': str(service.monday(service.today()))})
            return Response(dict(enabled=getattr(settings, 'SCHEDULING_ENABLED', False), user={'id': request.user.pk, 'is_superuser': is_owner(request.user)},
                business_date=str(service.today()), week_start=str(service.monday(service.today())), periods=default_periods(),
                recognition_providers=[{'id': str(p.pk), 'name': p.name, 'model_name': p.model_name} for p in AIProviderConfig.objects.filter(organization=org, enabled=True)] if is_owner(request.user) else [],
                terms=[term_json(t) for t in ScheduleTerm.objects.filter(organization=org).order_by('first_monday')], revision=service.revision(org)))
        if op == 'terms':
            return Response({'results': [term_json(t) for t in ScheduleTerm.objects.filter(organization=org).order_by('first_monday')]})
        if op == 'participants':
            self.admin()
            members = Membership.objects.filter(organization=org, active=True, user__is_active=True).select_related('user')
            participants = {p.user_id: p for p in ScheduleParticipant.objects.filter(organization=org)}
            return Response({'results': [{'user_id': m.user_id, 'name': m.display_name or m.user.get_full_name() or m.user.username,
                'active': participants[m.user_id].active if m.user_id in participants else False} for m in members]})
        if op in ('evidence', 'imports'):
            model = TimetableEvidence if op == 'evidence' else TimetableImport
            query = model.objects.filter(organization=org)
            if not is_owner(request.user) or request.query_params.get('owner'):
                query = query.filter(owner=self.owner(request.query_params.get('owner')))
            if pk:
                return Response(import_json(self.private(model, pk)))
            try:
                page = max(1, int(request.query_params.get('page', 1)))
            except ValueError:
                raise ValidationError('页码无效')
            if op == 'imports':
                query = query.select_related('term', 'evidence').prefetch_related('jobs')
            return Response({'count': query.count(), 'results': [(evidence_json(x) if op == 'evidence' else import_json(x)) for x in query.order_by('-created_at')[(page-1)*50:page*50]]})
        if op == 'content':
            e = self.private(TimetableEvidence, pk)
            root = Path(settings.SCHEDULING_PRIVATE_ROOT).resolve()
            path = (root / e.private_file).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValidationError('凭证文件不可用')
            response = FileResponse(path.open('rb'), content_type=e.content_type)
            response['Cache-Control'] = 'private, no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            response['Content-Disposition'] = 'inline'
            return response
        if op == 'jobs':
            job = get_object_or_404(TimetableRecognitionJob, organization=org, pk=pk)
            self.private(TimetableImport, job.timetable_import_id)
            return Response(job_json(job))
        if op == 'plans':
            owner = self.owner(request.query_params.get('owner'))
            query = MemberWeekPlan.objects.filter(organization=org, owner=owner)
            if request.query_params.get('week_start'):
                query = query.filter(week_start=service.parse_date(request.query_params['week_start']))
            return Response({'results': [plan_json(p) for p in query.order_by('week_start')]})
        if op == 'board':
            return Response(self.board())
        if op == 'history':
            owner = self.owner(request.query_params.get('owner'))
            overrides = ScheduleOverride.objects.filter(organization=org, owner=owner).order_by('-created_at')[:200]
            versions = MemberWeekPlanVersion.objects.filter(organization=org, plan__owner=owner).select_related('plan').order_by('-created_at')[:200]
            return Response({'adjustments': [dict(id=str(o.pk), date=str(o.date), period=o.period, authority=o.authority, status=o.status, reason=o.reason,
                show_annotation=o.show_annotation, force=o.force, revision=o.revision, revoked_at=o.revoked_at, revoke_reason=o.revoke_reason) for o in overrides],
                'versions': [dict(id=str(v.pk), week_start=str(v.plan.week_start), version=v.version, grid=v.grid, weekend_day=v.weekend_day, evidence_id=str(v.evidence_id), created_at=v.created_at) for v in versions]})
        raise ValidationError('不支持的操作')

    def board(self):
        org, request = self.organization, self.request
        start = service.parse_date(request.query_params.get('week_start', service.monday(service.today())))
        if start.weekday() != 0:
            raise ValidationError('week_start必须为周一')
        days = [start + timedelta(days=i) for i in range(7)]
        term = ScheduleTerm.objects.filter(organization=org, first_monday__lte=start).order_by('-first_monday').first()
        if term and start >= term.first_monday+timedelta(weeks=term.week_count):
            term = None
        periods = term.periods if term else default_periods()
        participants = list(ScheduleParticipant.objects.filter(organization=org).select_related('user'))
        names = {m.user_id: m.display_name for m in Membership.objects.filter(organization=org)}
        active_members = set(Membership.objects.filter(organization=org, active=True).values_list('user_id', flat=True))
        people = {p.user_id: {'user_id': p.user_id, 'name': names.get(p.user_id) or p.user.get_full_name() or p.user.username,
            'username': p.user.username} for p in participants}
        enabled = {p.user_id for p in participants if p.active and p.user.is_active and (p.user.is_superuser or p.user_id in active_members)}
        cells = {(c.owner_id, c.date, c.period): c for c in WorkScheduleCell.objects.filter(organization=org, date__range=(days[0], days[-1]))}
        overrides = {}
        for o in ScheduleOverride.objects.filter(organization=org, date__range=(days[0], days[-1]), revoked_at__isnull=True):
            key = (o.owner_id, o.date, o.period)
            if key not in overrides or o.authority == 'admin':
                overrides[key] = o
        submitted = set(MemberWeekPlan.objects.filter(organization=org, week_start=start).values_list('owner_id', flat=True))
        pending = [people[u] for u in sorted(enabled) if u not in submitted] if term else []
        output = []
        owner_filter = request.query_params.get('owner')
        for day in days:
            for p in periods:
                members = []
                for uid, person in sorted(people.items(), key=lambda item: (item[1]['name'], item[0])):
                    if owner_filter and str(uid) != owner_filter:
                        continue
                    key = (uid, day, p['number'])
                    cell = cells.get(key)
                    if not term or (uid not in enabled and (not cell or not service.started(day, cell.period_start))):
                        continue
                    override = overrides.get(key)
                    member = dict(person, status=cell.effective_status if cell else 'unknown', revision=cell.revision if cell else 0,
                        annotation=bool(override and override.show_annotation), override_id=str(override.pk) if override and (uid == request.user.pk or is_owner(request.user)) else None,
                        override_revision=override.revision if override and (uid == request.user.pk or is_owner(request.user)) else None)
                    members.append(member)
                output.append({'date': str(day), 'period': p['number'], 'members': members,
                    'counts': {s: sum(m['status'] == s for m in members) for s in ('work','leave','out','rest','class','unknown')}})
        return {'week_start': str(start), 'days': [str(d) for d in days], 'periods': periods, 'cells': output,
            'pending': pending, 'term_id': str(term.pk) if term else None, 'outside_term': term is None,
            'business_date': str(service.today()), 'revision': service.revision(org)}

    def post(self, request, pk=None):
        org, op, data = self.organization, self.operation, request.data
        if op == 'evidence':
            return self.upload()
        if op == 'terms':
            self.admin()
            return Response(self.run_mutation(lambda: self.save_term()), status=201)
        if op == 'imports':
            def create():
                evidence = self.private(TimetableEvidence, data.get('evidence_id'))
                term = get_object_or_404(ScheduleTerm, organization=org, pk=data.get('term_id'))
                imp = TimetableImport.objects.create(organization=org, owner=evidence.owner, evidence=evidence, term=term,
                    draft_grid=service.blank_grid(), selected_weeks=service.validate_weeks(data.get('week_indices', data.get('selected_weeks')), term), weekend_day=service.weekend(data.get('weekend_day', 'sat')))
                return import_json(imp)
            return Response(self.run_mutation(create), status=201)
        if op == 'recognize':
            from .timetable_recognition import enqueue_recognition
            imp = self.private(TimetableImport, pk)
            job = enqueue_recognition(imp, request.user)
            return Response(job_json(job), status=202)
        if op == 'confirm':
            return Response(self.run_mutation(lambda: service.confirm_import(self.private(TimetableImport, pk), request.user, data)))
        if op == 'archive':
            def archive():
                imp = self.private(TimetableImport, pk)
                service.assert_revision(imp.revision, data.get('revision'))
                if imp.state != 'draft':
                    raise ValidationError('仅未确认草稿可归档')
                imp.state, imp.revision = 'archived', imp.revision+1
                imp.save()
                service.audit(org, request.user, 'schedule.archive', imp)
                return import_json(imp)
            return Response(self.run_mutation(archive))
        if op == 'weekend':
            return Response(self.run_mutation(lambda: service.change_weekend(org, request.user, self.owner(data.get('target_user')), data)))
        if op == 'adjustments':
            return Response(self.run_mutation(lambda: service.adjust(org, request.user, self.owner(data.get('target_user')), data)))
        if op == 'revoke':
            return Response(self.run_mutation(lambda: service.revoke(self.private(ScheduleOverride, pk), request.user, data)))
        raise ValidationError('不支持的操作')

    def patch(self, request, pk=None):
        org, op, data = self.organization, self.operation, request.data
        if op == 'terms':
            self.admin()
            return Response(self.run_mutation(lambda: self.save_term(pk)))
        if op == 'imports':
            def update():
                imp = self.private(TimetableImport, pk)
                service.assert_revision(imp.revision, data.get('revision'))
                if imp.state != 'draft':
                    raise service.Conflict('只有草稿可以校对')
                if 'draft_grid' in data:
                    imp.draft_grid = service.validate_grid(data['draft_grid'])
                if 'selected_weeks' in data:
                    imp.selected_weeks = service.validate_weeks(data['selected_weeks'], imp.term)
                if 'weekend_day' in data:
                    imp.weekend_day = service.weekend(data['weekend_day'])
                imp.revision += 1
                imp.save()
                return import_json(imp)
            return Response(self.run_mutation(update))
        if op == 'participants':
            self.admin()
            def update_participant():
                owner = self.owner(data.get('target_user'))
                if type(data.get('active')) is not bool:
                    raise ValidationError('active必须为布尔')
                p, _ = ScheduleParticipant.objects.update_or_create(organization=org, user=owner, defaults={'active': data['active'], 'effective_from': service.today()})
                for plan in MemberWeekPlan.objects.filter(organization=org, owner=owner, week_start__gte=service.monday(service.today())).select_related('term', 'owner'):
                    v = plan.versions.get(version=plan.revision)
                    service.generate_cells(plan, v)
                service.audit(org, request.user, 'schedule.participant', p)
                return {'user_id': owner.pk, 'active': p.active}
            return Response(self.run_mutation(update_participant))
        raise ValidationError('不支持的操作')

    def save_term(self, pk=None):
        org, data = self.organization, self.request.data
        t = get_object_or_404(ScheduleTerm, organization=org, pk=pk) if pk else ScheduleTerm(organization=org)
        start = service.parse_date(data.get('first_monday', t.first_monday))
        weeks = data.get('week_count', t.week_count)
        periods = service.validate_periods(data.get('periods', t.periods))
        if start.weekday() != 0 or type(weeks) is not int or not 20 <= weeks <= 52:
            raise ValidationError('学期必须从周一开始，周数20—52')
        if t.locked_at and (start != t.first_monday or periods != t.periods or weeks != t.week_count):
            raise service.Conflict('已有确认课表，学期日期和时间模板已锁定')
        end = start+timedelta(weeks=weeks)
        for other in ScheduleTerm.objects.filter(organization=org).exclude(pk=t.pk):
            if start < other.first_monday+timedelta(weeks=other.week_count) and end > other.first_monday:
                raise ValidationError('学期日期不能重叠')
        name = str(data.get('name', t.name)).strip()
        if not name or len(name) > 120:
            raise ValidationError('请输入学期名称，最长120字')
        t.name, t.first_monday, t.week_count, t.periods = name, start, weeks, periods
        if 'recognition_provider_id' in data:
            raw = data['recognition_provider_id']
            t.recognition_provider = get_object_or_404(AIProviderConfig, organization=org, pk=raw, enabled=True) if raw else None
        t.save()
        service.audit(org, self.request.user, 'schedule.term', t)
        return term_json(t)

    def upload(self):
        owner = self.owner(self.request.data.get('owner'))
        files = self.request.FILES.getlist('files') or self.request.FILES.getlist('file')
        if not 1 <= len(files) <= 10:
            raise ValidationError('一次上传1—10张图片')
        validated = []
        for upload in files:
            if upload.size > 10*1024*1024:
                raise ValidationError('每张图片最多10MB')
            raw = upload.read(10*1024*1024+1)
            if len(raw) > 10*1024*1024:
                raise ValidationError('图片过大')
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as image:
                        fmt, width, height = image.format, image.width, image.height
                        if fmt not in ('JPEG','PNG','WEBP') or width*height > 25000000:
                            raise ValueError()
                        image.verify()
            except Exception:
                raise ValidationError('图片损坏、格式不支持或解码像素超过2500万')
            validated.append((upload, raw, fmt, width, height))
        root = Path(settings.SCHEDULING_PRIVATE_ROOT).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        if root == media or root.is_relative_to(media):
            raise ValidationError('私有凭证目录不能位于公开媒体目录')
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        paths, records = [], []
        try:
            with transaction.atomic():
                for upload, raw, fmt, width, height in validated:
                    name = f'{uuid.uuid4().hex}.bin'
                    path = root/name
                    descriptor = os.open(str(path), os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
                    with os.fdopen(descriptor, 'wb') as stream:
                        stream.write(raw)
                    paths.append(path)
                    e = TimetableEvidence.objects.create(organization=self.organization, owner=owner, uploaded_by=self.request.user,
                        private_file=name, sha256=hashlib.sha256(raw).hexdigest(), original_name=Path(upload.name).name[:250],
                        content_type={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}[fmt], size=len(raw), pixel_width=width, pixel_height=height)
                    service.audit(self.organization, self.request.user, 'schedule.upload', e)
                    records.append(evidence_json(e))
        except Exception:
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        return Response({'results': records}, status=201)

"""All schedule writes serialize on the organization and commit atomically."""
import hashlib
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from .models import Organization, OrganizationSyncState
from .scheduling_models import (ScheduleTerm, ScheduleParticipant, TimetableImport,
    MemberWeekPlan, MemberWeekPlanVersion, WorkScheduleCell, ScheduleOverride, ScheduleMutation)
from .sync import bump_sync_revision

TZ = ZoneInfo('Asia/Shanghai')

class Conflict(APIException):
    status_code = 409
    default_detail = '版本已变化，请刷新后重试'

def today():
    return timezone.now().astimezone(TZ).date()

def monday(value):
    return value - timedelta(days=value.weekday())

def parse_date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationError('日期必须为YYYY-MM-DD')

def blank_grid():
    return [[{'status': 'unknown', 'course_name': ''} for _ in range(12)] for _ in range(7)]

def validate_grid(grid, complete=False):
    if not isinstance(grid, list) or len(grid) != 7:
        raise ValidationError('课表必须有七天，每天十二节')
    result = []
    for row in grid:
        if not isinstance(row, list) or len(row) != 12:
            raise ValidationError('每天必须有十二节')
        clean = []
        for cell in row:
            if not isinstance(cell, dict) or cell.get('status') not in ('free', 'class', 'unknown'):
                raise ValidationError('课表格状态无效')
            if complete and cell['status'] == 'unknown':
                raise ValidationError('七天84格全部确认后才能生成安排')
            name = cell.get('course_name', '')
            if not isinstance(name, str) or len(name) > 200:
                raise ValidationError('课程名称过长或无效')
            clean.append({'status': cell['status'], 'course_name': name if cell['status'] == 'class' else ''})
        result.append(clean)
    return result

def validate_weeks(value, term):
    if not isinstance(value, list) or not value or any(type(i) is not int or not 1 <= i <= term.week_count for i in value):
        raise ValidationError('请选择有效周次')
    return sorted(set(value))

def weekend(value):
    if value not in ('sat', 'sun'):
        raise ValidationError('周末工作日必须为sat或sun')
    return value

def validate_periods(value):
    if not isinstance(value, list) or len(value) != 12:
        raise ValidationError('需要12个节次')
    last = time.min
    for i, p in enumerate(value):
        try:
            start, end = time.fromisoformat(p['start']), time.fromisoformat(p['end'])
            if p['number'] != i + 1 or not last <= start < end:
                raise ValueError()
            last = end
        except (KeyError, TypeError, ValueError):
            raise ValidationError('节次时间无效或重叠')
    return value

def revision(org):
    return OrganizationSyncState.objects.filter(organization=org).values_list('revision', flat=True).first() or 1

def mutate(org, actor, key, payload, action):
    if not isinstance(key, str) or not key.strip() or len(key) > 120:
        raise ValidationError('必须提供Idempotency-Key，最长120字符')
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=org.pk)
        old = ScheduleMutation.objects.filter(organization=org, actor=actor, idempotency_key=key).first()
        if old:
            if old.request_hash != digest:
                raise Conflict('同一幂等键不能用于不同请求')
            return old.response
        result = action()
        bump_sync_revision(organization_id=org.pk)
        result['schedule_revision'] = revision(org)
        ScheduleMutation.objects.create(organization=org, actor=actor, idempotency_key=key, request_hash=digest, response=result)
        return result

def assert_revision(actual, expected):
    if type(expected) is not int or actual != expected:
        raise Conflict({'detail': '版本冲突，请刷新', 'current_revision': actual})

def started(day, period_start):
    return datetime.combine(day, period_start, TZ) <= timezone.now()

def audit(org, actor, action, instance):
    # No private course text or leave reason enters the general audit log.
    from .models import AuditLog
    AuditLog.objects.create(organization=org, actor=actor, action=action,
        object_type=instance.__class__.__name__, object_id=str(instance.pk), before={}, after={})

def active_overrides(org, owner, start, end):
    rows = ScheduleOverride.objects.filter(organization=org, owner=owner, date__gte=start, date__lte=end, revoked_at__isnull=True)
    result = {}
    for row in rows:
        k = (row.date, row.period)
        if k not in result or row.authority == 'admin':
            result[k] = row
    return result

def generate_cells(plan, version, historical=False):
    overrides = active_overrides(plan.organization, plan.owner, plan.week_start, plan.week_start + timedelta(days=6))
    existing = {(c.date, c.period): c for c in WorkScheduleCell.objects.filter(organization=plan.organization, owner=plan.owner, date__gte=plan.week_start, date__lt=plan.week_start+timedelta(days=7))}
    participant = ScheduleParticipant.objects.get(organization=plan.organization, user=plan.owner)
    for d in range(7):
        day = plan.week_start + timedelta(days=d)
        for p, period in enumerate(plan.term.periods):
            begin = time.fromisoformat(period['start'])
            previous = existing.get((day, p + 1))
            if started(day, begin) and not historical:
                continue
            if not participant.active or not plan.owner.is_active:
                base = 'rest'
            elif d >= 5 and d != (5 if plan.weekend_day == 'sat' else 6):
                base = 'rest'
            else:
                base = 'class' if plan.confirmed_grid[d][p]['status'] == 'class' else 'work'
            override = overrides.get((day, p + 1))
            final = override.status if override else base
            WorkScheduleCell.objects.update_or_create(organization=plan.organization, owner=plan.owner, date=day, period=p+1,
                defaults=dict(base_status=base, effective_status=final, plan_version=version, revision=(previous.revision + 1 if previous else 1), period_start=begin, period_end=time.fromisoformat(period['end'])))

def save_version(plan, actor, historical=False):
    snapshot = MemberWeekPlanVersion.objects.create(organization=plan.organization, plan=plan, version=plan.revision,
        grid=plan.confirmed_grid, weekend_day=plan.weekend_day, evidence=plan.evidence, actor=actor)
    generate_cells(plan, snapshot, historical)

def confirm_import(imp, actor, data):
    assert_revision(imp.revision, data.get('revision'))
    if imp.state != 'draft':
        raise Conflict('只有草稿可确认；修改已确认课表请从凭证新建草稿')
    grid = validate_grid(imp.draft_grid, True)
    historical = actor.is_superuser and data.get('historical_correction') is True
    if data.get('historical_correction') and not actor.is_superuser:
        raise PermissionDenied()
    expected = data.get('expected_week_revisions', {})
    plans = []
    for index in validate_weeks(imp.selected_weeks, imp.term):
        start = imp.term.first_monday + timedelta(weeks=index-1)
        if start < monday(today()) and not historical:
            raise ValidationError('过去周次只允许管理员历史修正')
        plan = MemberWeekPlan.objects.filter(organization=imp.organization, owner=imp.owner, week_start=start).first()
        assert_revision(plan.revision if plan else 0, expected.get(start.isoformat()))
        if plan and data.get('replace_existing') is not True:
            raise Conflict('请选择明确替换已有周课表')
        plans.append((index, start, plan))
    ScheduleParticipant.objects.get_or_create(organization=imp.organization, user=imp.owner, defaults={'effective_from': today()})
    results = []
    for index, start, plan in plans:
        if plan:
            plan.revision += 1
            plan.confirmed_grid, plan.weekend_day, plan.evidence, plan.source_import = grid, imp.weekend_day, imp.evidence, imp
            plan.save()
        else:
            plan = MemberWeekPlan.objects.create(organization=imp.organization, owner=imp.owner, term=imp.term, week_index=index,
                week_start=start, confirmed_grid=grid, weekend_day=imp.weekend_day, evidence=imp.evidence, source_import=imp)
        save_version(plan, actor, historical)
        results.append({'week_start': start.isoformat(), 'revision': plan.revision})
    imp.state, imp.confirmed_at = 'confirmed', timezone.now()
    imp.revision += 1
    imp.save()
    if not imp.term.locked_at:
        imp.term.locked_at = timezone.now()
        imp.term.save(update_fields=['locked_at'])
    audit(imp.organization, actor, 'schedule.confirm', imp)
    return {'id': str(imp.pk), 'revision': imp.revision, 'plans': results}

def change_weekend(org, actor, owner, data):
    choice = weekend(data.get('weekend_day'))
    starts = sorted(set(parse_date(d) for d in data.get('week_starts', [])))
    if not starts or len(starts) > 52:
        raise ValidationError('请选择1—52个周')
    plans = list(MemberWeekPlan.objects.filter(organization=org, owner=owner, week_start__in=starts).select_related('term', 'owner'))
    if len(plans) != len(starts):
        raise ValidationError('选定周没有已确认课表')
    for plan in plans:
        if plan.week_start < monday(today()):
            raise ValidationError('过去周不可变更周末日')
        assert_revision(plan.revision, data.get('expected_revisions', {}).get(plan.week_start.isoformat()))
    for plan in plans:
        plan.weekend_day, plan.revision = choice, plan.revision + 1
        plan.save()
        save_version(plan, actor)
        audit(org, actor, 'schedule.weekend', plan)
    return {'plans': [{'week_start': p.week_start.isoformat(), 'revision': p.revision} for p in plans]}

def adjust(org, actor, owner, data):
    status = data.get('status')
    if status not in (('work', 'leave', 'out', 'rest') if actor.is_superuser else ('leave', 'out')):
        raise PermissionDenied('无权设置此状态')
    reason = str(data.get('reason', '')).strip()
    if len(reason) > 500 or (not actor.is_superuser and len(reason) < 2):
        raise ValidationError('原因/去向需2—500字')
    days = sorted(set(parse_date(v) for v in data.get('dates', [])))
    periods = data.get('periods', list(range(1, 13)))
    if not days or len(days) > 7 or not isinstance(periods, list) or not periods or any(type(p) is not int or not 1 <= p <= 12 for p in periods):
        raise ValidationError('日期/节次无效，单次最多七天')
    cells = list(WorkScheduleCell.objects.filter(organization=org, owner=owner, date__in=days, period__in=periods))
    by_key = {(c.date, c.period): c for c in cells}
    skipped, targets = [], []
    for day in days:
        for p in sorted(set(periods)):
            cell = by_key.get((day, p))
            if cell is None:
                term = next((t for t in ScheduleTerm.objects.filter(organization=org) if t.first_monday <= day < t.first_monday+timedelta(weeks=t.week_count)), None)
                if not term:
                    raise ValidationError('日期不在学期中')
                interval = term.periods[p-1]
                cell = WorkScheduleCell(organization=org, owner=owner, date=day, period=p, base_status='unknown', effective_status='unknown', period_start=time.fromisoformat(interval['start']), period_end=time.fromisoformat(interval['end']), revision=0)
            if not actor.is_superuser and started(day, cell.period_start):
                skipped.append(f'{day}:{p}')
                continue
            key = f'{day}:{p}'
            assert_revision(cell.revision, data.get('expected_revisions', {}).get(key))
            if not actor.is_superuser and ScheduleOverride.objects.filter(organization=org, owner=owner, date=day, period=p, authority='admin', revoked_at__isnull=True).exists():
                raise PermissionDenied('此时段由超级管理员调整，请联系管理员')
            if status == 'work' and cell.base_status in ('class', 'unknown') and data.get('force') is not True:
                raise Conflict('课程或未确认课表冲突，强制排班需明确force=true')
            targets.append(cell)
    if not targets:
        raise ValidationError('没有可修改的未来时段')
    result = []
    authority = 'admin' if actor.is_superuser else 'self'
    for cell in targets:
        ScheduleOverride.objects.filter(organization=org, owner=owner, date=cell.date, period=cell.period, authority=authority, revoked_at__isnull=True).update(revoked_at=timezone.now(), revoked_by=actor, revoke_reason=reason)
        row = ScheduleOverride.objects.create(organization=org, owner=owner, date=cell.date, period=cell.period, authority=authority,
            status=status, reason=reason, actor=actor, show_annotation=bool(data.get('show_annotation', True)) if actor.is_superuser else True, force=data.get('force') is True)
        cell.effective_status, cell.revision = status, cell.revision + 1
        cell.save()
        audit(org, actor, 'schedule.adjust', row)
        result.append({'id': str(row.pk), 'date': str(cell.date), 'period': cell.period, 'revision': cell.revision})
    return {'adjustments': result, 'skipped_started': skipped}

def revoke(row, actor, data):
    if not actor.is_superuser and (row.owner_id != actor.pk or row.authority != 'self'):
        raise PermissionDenied()
    assert_revision(row.revision, data.get('revision'))
    if row.revoked_at:
        raise Conflict('调整已经撤销')
    reason = str(data.get('reason', '')).strip()
    if len(reason) > 500 or (not actor.is_superuser and len(reason) < 2):
        raise ValidationError('撤销原因需2—500字')
    cell = WorkScheduleCell.objects.get(organization=row.organization, owner=row.owner, date=row.date, period=row.period)
    if not actor.is_superuser and started(cell.date, cell.period_start):
        raise PermissionDenied('已开始时段仅超级管理员可修正')
    row.revoked_at, row.revoked_by, row.revoke_reason, row.revision = timezone.now(), actor, reason, row.revision + 1
    row.save()
    others = active_overrides(row.organization, row.owner, row.date, row.date)
    remaining = others.get((row.date, row.period))
    cell.effective_status = remaining.status if remaining else cell.base_status
    cell.revision += 1
    cell.save()
    audit(row.organization, actor, 'schedule.revoke', row)
    return {'id': str(row.pk), 'revision': row.revision}

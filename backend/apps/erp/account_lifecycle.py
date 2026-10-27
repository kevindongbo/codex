"""Recoverable departure; business records and identities are never deleted."""
import hashlib
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import AccountLifecycleRequest, AccountSecurityState, Membership, Organization, PurchaseOrder, Warehouse
from .permissions import membership_permissions
from .serializers import InternalAccountSerializer
from .services import write_audit
from .sync import bump_sync_revision


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"

    def __init__(self, code, detail, **extra):
        super().__init__({"code": code, "detail": detail, **extra})


def payload(member):
    security = AccountSecurityState.objects.filter(user_id=member.user_id).first()
    return {
        "id": str(member.pk), "user_id": member.user_id, "username": member.user.username,
        "display_name": member.display_name or member.user.username, "role": member.role,
        "active": bool(member.active and member.user.is_active), "is_owner": member.user.is_superuser,
        "permissions": sorted(membership_permissions(member)),
        "warehouse_ids": [str(w.pk) for w in member.authorized_warehouses.all()],
        "warehouses": [{"id": str(w.pk), "name": w.name, "code": w.code} for w in member.authorized_warehouses.all()],
        "employment_status": member.employment_status, "revision": member.revision,
        "departed_at": member.departed_at.isoformat() if member.departed_at else None,
        "departure_date": str(member.departure_date) if member.departure_date else None,
        "needs_password_reset": bool(security and security.requires_password_reset),
        "created_at": member.created_at.isoformat(), "last_login": member.user.last_login.isoformat() if member.user.last_login else None,
    }


def owner_org(request):
    from .views import _require_owner
    return _require_owner(request)


def member_for(org, member_id, *, lock=False):
    qs = Membership.objects.select_for_update() if lock else Membership.objects.all()
    try:
        member = qs.get(pk=member_id, organization=org)
    except Membership.DoesNotExist:
        raise NotFound("子账号不存在") from None
    if member.user.is_superuser:
        raise PermissionDenied("主账号不能在此处修改")
    return member


def revision_check(member, data, required=True):
    value = data.get("revision")
    if value is None and not required:
        return
    if type(value) is not int or value < 1:
        raise ValidationError({"revision": "请携带读取到的整数版本"})
    if value != member.revision:
        raise Conflict("revision_conflict", "人员状态已变化，请刷新后重试", current_revision=member.revision)


@api_view(["GET"])
def departure_preview(request, membership_id):
    org = owner_org(request)
    member = member_for(org, membership_id)
    from .scheduling_models import WorkScheduleCell, ScheduleParticipant
    return Response({**payload(member),
                     "purchase_orders": PurchaseOrder.objects.filter(organization=org, purchaser=member.user).exclude(status__in=["received", "cancelled"]).count(),
                     "future_schedule_cells": WorkScheduleCell.objects.filter(organization=org, owner=member.user, date__gte=timezone.localdate()).count(),
                     "schedule_participating": ScheduleParticipant.objects.filter(organization=org, user=member.user, active=True).exists(),
                     "message": "立即禁止登录，隐藏日常人员及未来排班；历史及待办保留原归属，请另行交接。"})


@api_view(["POST"])
def archive(request, membership_id):
    return transition(request, membership_id, "archive")


@api_view(["POST"])
def restore(request, membership_id):
    return transition(request, membership_id, "restore")


@transaction.atomic
def transition(request, member_id, operation):
    org = owner_org(request)
    Organization.objects.select_for_update().get(pk=org.pk)
    allowed = {"revision", "reason", "departure_date"} if operation == "archive" else {"revision", "reason"}
    if set(request.data) - allowed:
        raise ValidationError("包含不支持的账号字段")
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 100:
        raise ValidationError({"Idempotency-Key": "必须提供不超过100字符的幂等键"})
    digest = hashlib.sha256(json.dumps({"id": str(member_id), **request.data}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = AccountLifecycleRequest.objects.filter(organization=org, actor=request.user, operation=operation, key=key).first()
    if previous:
        if previous.payload_hash != digest:
            raise Conflict("idempotency_conflict", "同一幂等键不能用于不同内容")
        return Response(previous.response)
    member = member_for(org, member_id, lock=True)
    user = get_user_model().objects.select_for_update().get(pk=member.user_id)
    member.user = user
    revision_check(member, request.data)
    reason = request.data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 500:
        raise ValidationError({"reason": "原因最多500字符"})
    target = "departed" if operation == "archive" else "employed"
    if member.employment_status == target:
        raise Conflict("account_state_conflict", "人员已处于此状态，请刷新")
    before = {"role": member.role, "permissions": sorted(membership_permissions(member)), "active": member.active,
              "warehouse_ids": [str(pk) for pk in member.authorized_warehouses.values_list("pk", flat=True)]}
    security, _ = AccountSecurityState.objects.select_for_update().get_or_create(user=user)
    security.auth_version += 1
    if operation == "archive":
        from rest_framework import serializers
        departure_date = serializers.DateField().run_validation(request.data.get("departure_date", str(timezone.localdate())))
        if departure_date > timezone.localdate():
            raise ValidationError({"departure_date": "离职日期不能晚于今天"})
        member.departed_at, member.departed_by = timezone.now(), request.user
        member.departure_date, member.departure_reason = departure_date, reason
    else:
        member.restored_at, member.restored_by = timezone.now(), request.user
        member.role, member.permissions = Membership.Role.VIEWER, ["view"]
        member.authorized_warehouses.clear()
        security.requires_password_reset = True
    member.employment_status, member.active = target, False
    member.revision += 1
    member.save()
    user.is_active = False
    user.save(update_fields=["is_active"])
    security.save()
    from .scheduling_models import ScheduleParticipant, TimetableRecognitionJob
    ScheduleParticipant.objects.filter(organization=org, user=user).update(active=False)
    # Failed jobs are never revived by restore. Running calls cannot be recalled,
    # but their candidates must not be applied after departure.
    TimetableRecognitionJob.objects.filter(organization=org, timetable_import__owner=user, status__in=["queued", "processing"]).update(status="failed", sanitized_error="account_departed", lease_until=None, lease_token=None)
    write_audit(organization=org, actor=request.user, action="account." + operation, instance=member,
                before=before, after={"employment_status": target, "revision": member.revision, "reason": reason, "active": False})
    bump_sync_revision(organization_id=org.pk)
    result = payload(member)
    AccountLifecycleRequest.objects.create(organization=org, actor=request.user, operation=operation, key=key, payload_hash=digest, response=result)
    return Response(result)


@api_view(["PATCH", "DELETE"])
@transaction.atomic
def detail(request, membership_id):
    org = owner_org(request)
    Organization.objects.select_for_update().get(pk=org.pk)
    member = member_for(org, membership_id, lock=True)
    user = get_user_model().objects.select_for_update().get(pk=member.user_id)
    member.user = user
    revision_check(member, request.data, required=False)
    if request.method == "DELETE":
        data = {"active": False}
    else:
        if set(request.data) - (set(InternalAccountSerializer().fields) | {"revision"}):
            raise ValidationError("包含不支持的账号字段")
        serializer = InternalAccountSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
    security, _ = AccountSecurityState.objects.select_for_update().get_or_create(user=user)
    if member.employment_status == "departed" and request.method == "DELETE":
        return Response(status=204)
    if member.employment_status == "departed":
        raise Conflict("account_departed", "请先恢复为在职，再编辑或启用")
    if "username" in data and data["username"] != user.username:
        if get_user_model().objects.exclude(pk=user.pk).filter(username=data["username"]).exists():
            raise ValidationError({"username": "该账号名已被使用"})
        user.username = data["username"]
    if "password" in data:
        try:
            validate_password(data["password"], user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc
        user.set_password(data["password"])
        security.requires_password_reset = False
        security.auth_version += 1
    if data.get("active") and security.requires_password_reset:
        raise Conflict("password_reset_required", "恢复后请先设置新密码，再审核权限并启用")
    if "active" in data:
        if member.active and not data["active"]:
            security.auth_version += 1
        member.active = user.is_active = data["active"]
    for field in ["display_name", "role", "permissions"]:
        if field in data:
            setattr(member, field, data[field])
    if "role" in data and "permissions" not in data:
        member.permissions = []
    if "warehouse_ids" in data:
        warehouses = list(Warehouse.objects.filter(organization=org, pk__in=data["warehouse_ids"]))
        if len(warehouses) != len(set(data["warehouse_ids"])):
            raise ValidationError({"warehouse_ids": "存在不属于当前组织的仓库"})
        member.authorized_warehouses.set(warehouses)
    member.revision += 1
    user.save()
    member.save()
    security.save()
    write_audit(organization=org, actor=request.user, action="account.disable" if request.method == "DELETE" else "account.update", instance=member,
                after={"username": user.username, "role": member.role, "active": member.active, "revision": member.revision})
    bump_sync_revision(organization_id=org.pk)
    return Response(status=204) if request.method == "DELETE" else Response(payload(member))

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Membership
from .single_tenant import active_internal_membership, ensure_internal_organization, internal_organization


PERMISSION_CATALOG = {
    "view": "查看系统数据",
    "catalog": "商品与竞品",
    "warehouse": "仓库与库存",
    "purchase": "采购与供应商",
    "order": "订单、发货与退货",
    "replenishment": "补货管理",
    "data": "数据导入与导出",
    "audit": "查看操作记录",
}

LEGACY_ROLE_PERMISSIONS = {
    Membership.Role.ADMIN: set(PERMISSION_CATALOG),
    Membership.Role.MANAGER: set(PERMISSION_CATALOG),
    Membership.Role.BUYER: {"catalog", "purchase", "replenishment"},
    Membership.Role.WAREHOUSE: {"warehouse", "order"},
    Membership.Role.VIEWER: {"view"},
}


def is_owner(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def membership_permissions(membership):
    configured = membership.permissions or []
    if configured:
        return set(configured)
    return LEGACY_ROLE_PERMISSIONS.get(membership.role, set())


def user_has_capability(user, membership, capability):
    return is_owner(user) or capability in membership_permissions(membership)


def allowed_warehouse_ids(user, membership, organization):
    """Return warehouses visible to a user in the single internal organization."""
    if is_owner(user) or (membership is not None and membership.role == Membership.Role.ADMIN):
        return None  # None means every warehouse in the organization.
    if membership is None:
        return set()
    return set(membership.authorized_warehouses.filter(organization=organization).values_list("pk", flat=True))


def request_organization(request, *, required=True):
    if not request.user or not request.user.is_authenticated:
        raise PermissionDenied("请先登录")
    if not request.user.is_active:
        # A previously issued JWT must stop working as soon as the owner
        # disables the internal account, rather than waiting for token expiry.
        raise PermissionDenied("该账号已被停用")
    organization = ensure_internal_organization(request.user) if is_owner(request.user) else internal_organization()
    if organization is None:
        if required:
            raise NotFound("内部组织尚未初始化，请由主账号先登录")
        return None
    if not is_owner(request.user):
        membership = active_internal_membership(request.user)
        if membership is None:
            raise PermissionDenied("账号尚未启用或未加入内部系统")
    raw = request.headers.get("X-Organization-ID") or request.query_params.get("organization")
    if raw and str(raw) != str(organization.pk):
        raise PermissionDenied("本系统仅支持一个内部组织")
    return organization


class OrganizationRolePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        organization = request_organization(request)
        view.organization = organization
        membership = active_internal_membership(request.user)
        view.membership = membership
        if getattr(view, "owner_only", False):
            return is_owner(request.user)
        if is_owner(request.user) or request.method in SAFE_METHODS:
            return True
        if membership is None:
            return False
        capability = getattr(view, "capability", None)
        if capability:
            return user_has_capability(request.user, membership, capability)
        allowed = getattr(view, "write_roles", {Membership.Role.ADMIN, Membership.Role.MANAGER})
        return membership.role in allowed

    def has_object_permission(self, request, view, obj):
        if getattr(view, "owner_only", False):
            return is_owner(request.user)
        return True

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Membership, Organization


def request_organization(request, *, required=True):
    raw = request.headers.get("X-Organization-ID") or request.query_params.get("organization")
    if not raw:
        if required:
            raise ValidationError({"organization": "请通过 X-Organization-ID 指定组织"})
        return None
    try:
        organization = Organization.objects.get(pk=raw, active=True)
    except (Organization.DoesNotExist, ValueError):
        raise NotFound("组织不存在")
    if not request.user.is_superuser and not Membership.objects.filter(
        organization=organization, user=request.user, active=True
    ).exists():
        raise PermissionDenied("无权访问该组织")
    return organization


class OrganizationRolePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(view, "organization_bootstrap", False):
            # Organization list/create cannot require an organization header yet.
            # Object writes are checked in has_object_permission below.
            return True
        organization = request_organization(request)
        view.organization = organization
        if request.user.is_superuser or request.method in SAFE_METHODS:
            return True
        role = Membership.objects.filter(
            organization=organization, user=request.user, active=True
        ).values_list("role", flat=True).first()
        allowed = getattr(view, "write_roles", {Membership.Role.ADMIN, Membership.Role.MANAGER})
        return role in allowed

    def has_object_permission(self, request, view, obj):
        if not getattr(view, "organization_bootstrap", False):
            return True
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_superuser:
            return True
        # Deleting an organization is intentionally a platform-admin operation.
        if getattr(view, "action", "") == "destroy":
            return False
        return Membership.objects.filter(
            organization=obj,
            user=request.user,
            active=True,
            role=Membership.Role.ADMIN,
        ).exists()

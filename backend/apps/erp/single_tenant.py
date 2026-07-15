"""Single-organization helpers for the internal ERP deployment."""

from django.conf import settings
from django.db import transaction

from .models import Membership, Organization, Warehouse


def internal_organization():
    """Return the one organization used by every internal account."""
    slug = settings.INTERNAL_ORGANIZATION_SLUG
    organization = Organization.objects.filter(slug=slug, active=True).first()
    if organization is not None:
        return organization
    return Organization.objects.filter(active=True).order_by("created_at", "id").first()


@transaction.atomic
def ensure_internal_organization(owner):
    """Bootstrap the one organization only for the primary account."""
    if not owner.is_superuser:
        raise PermissionError("只有主账号可以初始化内部组织")

    organization = internal_organization()
    if organization is None:
        organization = Organization.objects.create(
            name=settings.INTERNAL_ORGANIZATION_NAME,
            slug=settings.INTERNAL_ORGANIZATION_SLUG,
            active=True,
        )
        Warehouse.objects.create(
            organization=organization,
            code="DEFAULT",
            name="默认仓",
            country="CN",
        )
    membership = Membership.objects.filter(organization=organization, user=owner).first()
    if membership is None:
        Membership.objects.create(
            organization=organization,
            user=owner,
            role=Membership.Role.ADMIN,
            permissions=[],
            active=True,
        )
    elif not membership.active:
        membership.active = True
        membership.save(update_fields=["active", "updated_at"])
    return organization


def active_internal_membership(user):
    organization = internal_organization()
    if organization is None:
        return None
    return Membership.objects.filter(
        organization=organization,
        user=user,
        active=True,
    ).select_related("organization", "user").first()

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import NotFound
from .permissions import request_organization


class SchedulePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        view.organization = request_organization(request)
        if not getattr(settings, 'SCHEDULING_ENABLED', False) and getattr(view, 'operation', '') != 'context':
            raise NotFound('团队排班尚未启用')
        return True

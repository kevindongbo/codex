from django.urls import path
from .scheduling_views import ScheduleAPI

urlpatterns = []
for route, operation in [
    ('context/', 'context'), ('terms/', 'terms'), ('terms/<uuid:pk>/', 'terms'),
    ('participants/', 'participants'), ('evidence/', 'evidence'), ('evidence/<uuid:pk>/content/', 'content'),
    ('imports/', 'imports'), ('imports/<uuid:pk>/', 'imports'), ('imports/<uuid:pk>/recognize/', 'recognize'),
    ('imports/<uuid:pk>/confirm/', 'confirm'), ('imports/<uuid:pk>/archive/', 'archive'),
    ('jobs/<uuid:pk>/', 'jobs'), ('plans/', 'plans'), ('plans/weekend/', 'weekend'),
    ('board/', 'board'), ('adjustments/', 'adjustments'), ('adjustments/<uuid:pk>/revoke/', 'revoke'), ('history/', 'history')]:
    urlpatterns.append(path(route, ScheduleAPI.as_view(operation=operation)))

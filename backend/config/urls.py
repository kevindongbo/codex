from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.erp import views as erp_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", erp_views.InternalTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/owner/login/verify/", erp_views.verify_owner_login, name="owner_login_verify"),
    path("api/auth/owner/password-reset/request/", erp_views.request_owner_password_reset, name="owner_password_reset_request"),
    path("api/auth/owner/password-reset/confirm/", erp_views.confirm_owner_password_reset, name="owner_password_reset_confirm"),
    path("api/auth/owner/password/change/request/", erp_views.request_owner_password_change, name="owner_password_change_request"),
    path("api/auth/owner/password/change/confirm/", erp_views.confirm_owner_password_change, name="owner_password_change_confirm"),
    path("api/", include("apps.erp.urls")),
]

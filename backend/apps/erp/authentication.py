"""Chinese, user-facing messages for JWT authentication failures."""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from .models import AccountSecurityState, Membership, Organization


def validate_account(user, token=None):
    state = AccountSecurityState.objects.filter(user=user).first()
    version = state.auth_version if state else 0
    if (not user.is_active or (state and state.requires_password_reset)
            or Membership.objects.filter(user=user, employment_status="departed").exists()
            or (not user.is_superuser and not Membership.objects.filter(user=user, active=True, employment_status="employed", organization__active=True).exists())
            or (token is not None and token.get("auth_version", 0) != version)):
        raise AuthenticationFailed("账号已停用或登录凭证已失效，请联系主账号", code="account_revoked")
    return version


def issue_refresh(user):
    if connection.in_atomic_block:
        from .single_tenant import internal_organization
        org = internal_organization()
        if org:
            Organization.objects.select_for_update().get(pk=org.pk)
        user = get_user_model().objects.get(pk=user.pk)
    version = validate_account(user)
    token = RefreshToken.for_user(user)
    token["auth_version"] = version
    return token


class InternalTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = self.token_class(attrs["refresh"])
        try:
            user = get_user_model().objects.get(pk=token["user_id"])
        except (get_user_model().DoesNotExist, KeyError, ValueError):
            raise InvalidToken("登录凭证无效，请重新登录") from None
        validate_account(user, token)
        return super().validate(attrs)


class AccountWriteTransactionMiddleware:
    """JWT writes and departure serialize on the same organization lock.

    Authentication takes the lock before resolving the current user. A write
    waiting behind archive therefore observes revoked state, not a stale User.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            with transaction.atomic():
                response = self.get_response(request)
                if response.status_code >= 400:
                    transaction.set_rollback(True)
                return response
        return self.get_response(request)


class InternalJWTAuthentication(JWTAuthentication):
    """Keep token failures understandable in the internal Chinese-only UI."""

    def get_raw_token(self, header):
        try:
            return super().get_raw_token(header)
        except AuthenticationFailed as exc:
            raise AuthenticationFailed("登录凭证格式不正确，请重新登录", code=exc.get_codes()) from exc

    def get_validated_token(self, raw_token):
        try:
            return super().get_validated_token(raw_token)
        except InvalidToken as exc:
            raise InvalidToken("登录凭证无效或已过期，请重新登录") from exc

    def get_user(self, validated_token):
        try:
            if connection.in_atomic_block:
                from .single_tenant import internal_organization
                org = internal_organization()
                if org:
                    Organization.objects.select_for_update().get(pk=org.pk)
            user = super().get_user(validated_token)
            validate_account(user, validated_token)
            return user
        except AuthenticationFailed as exc:
            if exc.get_codes() == "user_inactive":
                detail = "该账号已被停用，请联系主账号管理员"
            elif exc.get_codes() == "password_changed":
                detail = "密码已修改，请使用新密码重新登录"
            else:
                detail = "登录凭证无效，请重新登录"
            raise AuthenticationFailed(detail, code=exc.get_codes()) from exc


from rest_framework.authentication import SessionAuthentication


class InternalSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None
        user, auth = authenticated
        if connection.in_atomic_block:
            from .single_tenant import internal_organization
            org = internal_organization()
            if org:
                Organization.objects.select_for_update().get(pk=org.pk)
        user = get_user_model().objects.get(pk=user.pk)
        validate_account(user)
        from django.contrib.auth import HASH_SESSION_KEY
        from django.utils.crypto import constant_time_compare
        if not constant_time_compare(request.session.get(HASH_SESSION_KEY, ""), user.get_session_auth_hash()):
            raise AuthenticationFailed("密码已修改，请重新登录")
        return user, auth


from rest_framework_simplejwt.views import TokenRefreshView


class InternalTokenRefreshView(TokenRefreshView):
    serializer_class = InternalTokenRefreshSerializer

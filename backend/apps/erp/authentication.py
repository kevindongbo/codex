"""Chinese, user-facing messages for JWT authentication failures."""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken


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
            return super().get_user(validated_token)
        except AuthenticationFailed as exc:
            if exc.get_codes() == "user_inactive":
                detail = "该账号已被停用，请联系主账号管理员"
            elif exc.get_codes() == "password_changed":
                detail = "密码已修改，请使用新密码重新登录"
            else:
                detail = "登录凭证无效，请重新登录"
            raise AuthenticationFailed(detail, code=exc.get_codes()) from exc

"""Email verification helpers reserved for the primary account."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import OwnerEmailChallenge


def email_verification_enabled():
    return bool(settings.OWNER_EMAIL_VERIFICATION_REQUIRED)


def create_challenge(*, user, purpose):
    if not user.is_superuser:
        raise ValidationError("只有主账号可以使用邮箱验证")
    if not user.email:
        raise ValidationError("主账号尚未设置验证邮箱")
    if not email_verification_enabled():
        raise ValidationError("邮箱验证尚未启用，请先配置邮件服务")

    OwnerEmailChallenge.objects.filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
    ).update(consumed_at=timezone.now())
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OwnerEmailChallenge.objects.create(
        user=user,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=settings.OWNER_EMAIL_CODE_TTL_SECONDS),
    )
    subject_map = {
        OwnerEmailChallenge.Purpose.LOGIN: "东铂跨境运营系统登录验证码",
        OwnerEmailChallenge.Purpose.PASSWORD_CHANGE: "东铂跨境运营系统修改密码验证码",
        OwnerEmailChallenge.Purpose.PASSWORD_RESET: "东铂跨境运营系统找回密码验证码",
    }
    try:
        send_mail(
            subject_map[purpose],
            f"你的验证码是：{code}\n有效期 {settings.OWNER_EMAIL_CODE_TTL_SECONDS // 60} 分钟。请勿向任何人透露。",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception as exc:
        challenge.delete()
        raise ValidationError("验证码邮件发送失败，请检查邮件服务配置") from exc
    return challenge


def consume_challenge(*, challenge_id, code, purpose):
    try:
        challenge = OwnerEmailChallenge.objects.select_related("user").get(
            pk=challenge_id,
            purpose=purpose,
            consumed_at__isnull=True,
        )
    except OwnerEmailChallenge.DoesNotExist as exc:
        raise ValidationError("验证码无效或已使用") from exc
    if challenge.expires_at <= timezone.now():
        raise ValidationError("验证码已过期，请重新获取")
    if not check_password(str(code or ""), challenge.code_hash):
        raise ValidationError("验证码不正确")
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at", "updated_at"])
    return challenge.user

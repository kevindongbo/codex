"""Server-side integrations for TikTok Shop and OpenAI-compatible LLM APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone as datetime_timezone
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import AIInvocationLog, AIRecommendation, TikTokShopConnection, TikTokShopOAuthState
from .secure_config import decrypt_secret, encrypt_secret


TIKTOK_TOKEN_GET_URL = "https://auth.tiktok-shops.com/api/v2/token/get"
TIKTOK_TOKEN_REFRESH_URL = "https://auth.tiktok-shops.com/api/v2/token/refresh"
TIKTOK_AUTH_URLS = {
    "US": "https://services.us.tiktokshop.com/open/authorize",
    "ROW": "https://services.tiktokshop.com/open/authorize",
}
TIKTOK_OPEN_API_BASE = "https://open-api.tiktokglobalshop.com"
TIKTOK_AUTHORIZED_SHOPS_PATH = "/authorization/202309/shops"


def _read_json(request: Request, *, timeout: int) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - configured HTTPS integration endpoint
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ValidationError(f"第三方服务返回 HTTP {exc.code}：{body}") from exc
    except URLError as exc:
        raise ValidationError(f"无法连接第三方服务：{exc.reason}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError("第三方服务返回了无法识别的 JSON") from exc


def _tiktok_settings() -> tuple[str, str, str, str]:
    app_key = os.getenv("TIKTOK_SHOP_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_SHOP_APP_SECRET", "").strip()
    service_id = os.getenv("TIKTOK_SHOP_SERVICE_ID", "").strip()
    redirect_uri = os.getenv("TIKTOK_SHOP_REDIRECT_URI", "").strip()
    if not all((app_key, app_secret, service_id, redirect_uri)):
        raise ImproperlyConfigured(
            "请配置 TIKTOK_SHOP_APP_KEY、TIKTOK_SHOP_APP_SECRET、TIKTOK_SHOP_SERVICE_ID 和 TIKTOK_SHOP_REDIRECT_URI"
        )
    return app_key, app_secret, service_id, redirect_uri


def begin_tiktok_authorization(*, organization, actor, region: str) -> str:
    _, _, service_id, redirect_uri = _tiktok_settings()
    raw_state = secrets.token_urlsafe(32)
    TikTokShopOAuthState.objects.create(
        organization=organization,
        state_hash=hashlib.sha256(raw_state.encode("utf-8")).hexdigest(),
        redirect_uri=redirect_uri,
        region=region.upper(),
        expires_at=timezone.now() + timedelta(minutes=30),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    endpoint = TIKTOK_AUTH_URLS["US" if region.upper() == "US" else "ROW"]
    return f"{endpoint}?{urlencode({'service_id': service_id, 'state': raw_state})}"


def _exchange_tiktok_token(*, auth_code: str | None = None, refresh_token: str | None = None) -> dict:
    app_key, app_secret, _, _ = _tiktok_settings()
    if bool(auth_code) == bool(refresh_token):
        raise ValidationError("必须提供授权码或刷新令牌之一")
    if auth_code:
        params = {"app_key": app_key, "app_secret": app_secret, "auth_code": auth_code, "grant_type": "authorized_code"}
        endpoint = TIKTOK_TOKEN_GET_URL
    else:
        params = {"app_key": app_key, "app_secret": app_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}
        endpoint = TIKTOK_TOKEN_REFRESH_URL
    payload = _read_json(Request(f"{endpoint}?{urlencode(params)}", method="GET"), timeout=30)
    if payload.get("code") not in (0, "0") or not isinstance(payload.get("data"), dict):
        raise ValidationError(payload.get("message") or "TikTok Shop 未返回有效授权结果")
    return payload["data"]


def _tiktok_signature(*, path: str, params: dict, app_secret: str) -> str:
    """Build the documented Open API HMAC signature without logging the secret."""
    canonical = "".join(
        f"{key}{params[key]}" for key in sorted(params)
        if key not in {"sign", "access_token"}
    )
    payload = f"{app_secret}{path}{canonical}{app_secret}".encode("utf-8")
    return hmac.new(app_secret.encode("utf-8"), payload, sha256).hexdigest()


def _get_tiktok_authorized_shops(*, access_token: str) -> list[dict]:
    """Return all shops granted by a seller-level TikTok authorization."""
    app_key, app_secret, _, _ = _tiktok_settings()
    params = {"app_key": app_key, "timestamp": str(int(time.time()))}
    params["sign"] = _tiktok_signature(
        path=TIKTOK_AUTHORIZED_SHOPS_PATH, params=params, app_secret=app_secret
    )
    request = Request(
        f"{TIKTOK_OPEN_API_BASE}{TIKTOK_AUTHORIZED_SHOPS_PATH}?{urlencode(params)}",
        headers={"Content-Type": "application/json", "x-tts-access-token": access_token},
        method="GET",
    )
    payload = _read_json(request, timeout=30)
    if payload.get("code") not in (0, "0"):
        raise ValidationError(payload.get("message") or "TikTok Shop 未返回已授权店铺")
    shops = (payload.get("data") or {}).get("shops") or []
    if not isinstance(shops, list):
        raise ValidationError("TikTok Shop 已授权店铺响应格式无效")
    return [shop for shop in shops if isinstance(shop, dict) and shop.get("id")]


def _save_tiktok_shops(*, oauth_state, token_data: dict, actor=None) -> list[TikTokShopConnection]:
    open_id = str(token_data.get("open_id") or "")
    access_token = str(token_data.get("access_token") or "")
    refresh_token = str(token_data.get("refresh_token") or "")
    if not (open_id and access_token and refresh_token):
        raise ValidationError("TikTok Shop 授权结果缺少必要令牌或授权主体")
    user_type = token_data.get("user_type")
    if user_type is not None and str(user_type) != "0":
        raise ValidationError("当前授权不是 TikTok Shop 卖家授权，请使用卖家账号重新授权")
    shops = _get_tiktok_authorized_shops(access_token=access_token)
    if not shops:
        raise ValidationError("授权成功但未读取到店铺；请确认应用已获 seller.authorization.info 权限")

    now = timezone.now()
    common = {
        "access_token_encrypted": encrypt_secret(access_token),
        "refresh_token_encrypted": encrypt_secret(refresh_token),
        "access_token_expires_at": _unix_time(token_data.get("access_token_expire_in")),
        "refresh_token_expires_at": _unix_time(token_data.get("refresh_token_expire_in")),
        "granted_scopes": token_data.get("granted_scopes") or [],
        "status": TikTokShopConnection.Status.CONNECTED,
        "last_error": "",
        "authorized_by": actor if getattr(actor, "is_authenticated", False) else oauth_state.created_by,
        "authorized_at": now,
        "disconnected_at": None,
        "seller_type": str(user_type) if user_type is not None else "seller",
    }
    # Reuse legacy one-account rows so historical sync runs remain attached.
    legacy = TikTokShopConnection.objects.filter(
        organization=oauth_state.organization, open_id=open_id, shop_id=""
    ).first()
    connections = []
    for index, shop in enumerate(shops):
        defaults = {
            **common,
            "label": str(shop.get("name") or "")[:120],
            "shop_name": str(shop.get("name") or "")[:200],
            "shop_cipher": str(shop.get("cipher") or "")[:260],
            "region": str(shop.get("region") or oauth_state.region).upper()[:8],
        }
        shop_id = str(shop["id"])
        if index == 0 and legacy is not None:
            legacy.shop_id = shop_id
            for field, value in defaults.items():
                setattr(legacy, field, value)
            legacy.save()
            connection = legacy
        else:
            connection, _ = TikTokShopConnection.objects.update_or_create(
                organization=oauth_state.organization, open_id=open_id, shop_id=shop_id,
                defaults=defaults,
            )
        connections.append(connection)
    return connections


def complete_tiktok_authorization(*, state: str, auth_code: str, actor=None) -> list[TikTokShopConnection]:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    oauth_state = TikTokShopOAuthState.objects.select_for_update().filter(state_hash=digest, used_at__isnull=True).first()
    if oauth_state is None or oauth_state.expires_at < timezone.now():
        raise ValidationError("授权状态已过期或已使用，请重新发起授权")
    data = _exchange_tiktok_token(auth_code=auth_code)
    now = timezone.now()
    connections = _save_tiktok_shops(oauth_state=oauth_state, token_data=data, actor=actor)
    oauth_state.used_at = now
    oauth_state.save(update_fields=["used_at", "updated_at"])
    return connections


def _unix_time(value):
    try:
        return datetime.fromtimestamp(int(value), tz=datetime_timezone.utc) if value else None
    except (TypeError, ValueError, OverflowError):
        return None


def refresh_tiktok_connection(connection: TikTokShopConnection) -> TikTokShopConnection:
    if connection.status == TikTokShopConnection.Status.DISCONNECTED:
        raise ValidationError("已解绑店铺不能刷新令牌，请重新授权")
    data = _exchange_tiktok_token(refresh_token=decrypt_secret(connection.refresh_token_encrypted))
    access_token = str(data.get("access_token") or "")
    refresh_token = str(data.get("refresh_token") or "")
    if not (access_token and refresh_token):
        raise ValidationError("TikTok Shop 刷新令牌结果不完整")
    # A seller token can represent multiple shops.  Propagate a token rotation
    # to every local shop row for that seller so a later sync never uses an old
    # refresh token from a sibling shop.
    updates = {
        "access_token_encrypted": encrypt_secret(access_token),
        "refresh_token_encrypted": encrypt_secret(refresh_token),
        "access_token_expires_at": _unix_time(data.get("access_token_expire_in")),
        "refresh_token_expires_at": _unix_time(data.get("refresh_token_expire_in")),
        "status": TikTokShopConnection.Status.CONNECTED,
        "last_error": "",
    }
    if data.get("granted_scopes"):
        updates["granted_scopes"] = data["granted_scopes"]
    TikTokShopConnection.objects.filter(
        organization=connection.organization, open_id=connection.open_id
    ).update(**updates)
    connection.refresh_from_db()
    return connection


def disconnect_tiktok_connection(connection: TikTokShopConnection) -> TikTokShopConnection:
    connection.status = TikTokShopConnection.Status.DISCONNECTED
    connection.access_token_encrypted = ""
    connection.refresh_token_encrypted = ""
    connection.access_token_expires_at = None
    connection.refresh_token_expires_at = None
    connection.disconnected_at = timezone.now()
    connection.save()
    return connection


def invoke_ai(*, provider, feature: str, messages: list[dict], actor=None, response_format=None) -> tuple[dict, AIInvocationLog]:
    if not provider.enabled:
        raise ValidationError("此大模型配置已停用")
    endpoint = provider.api_base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    body = {"model": provider.model_name, "messages": messages, **(provider.default_parameters or {})}
    if response_format:
        body["response_format"] = response_format
    api_key = decrypt_secret(provider.api_key_encrypted)
    started = time.monotonic()
    last_error = ""
    for attempt in range(1, provider.max_retries + 2):
        try:
            request = Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                method="POST",
            )
            result = _read_json(request, timeout=provider.timeout_seconds)
            usage = result.get("usage") or {}
            log = AIInvocationLog.objects.create(
                organization=provider.organization, provider=provider, feature=feature, model_name=provider.model_name,
                status="success", attempts=attempt, latency_ms=int((time.monotonic() - started) * 1000),
                input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"), requested_by=actor if getattr(actor, "is_authenticated", False) else None,
            )
            return result, log
        except ValidationError as exc:
            last_error = "; ".join(exc.messages)
            if attempt > provider.max_retries:
                break
            time.sleep(min(2 ** (attempt - 1), 4))
    log = AIInvocationLog.objects.create(
        organization=provider.organization, provider=provider, feature=feature, model_name=provider.model_name,
        status="failed", attempts=provider.max_retries + 1, latency_ms=int((time.monotonic() - started) * 1000),
        error_code="provider_error", error_message=last_error[:500], requested_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    raise ValidationError(f"大模型调用失败：{last_error}")


def create_ai_recommendation(*, provider, kind: str, input_data: dict, actor=None) -> AIRecommendation:
    prompt = {
        "role": "user",
        "content": "请根据输入生成可解释的 JSON 建议。不得声称已经修改库存；返回字段 summary、recommendations、assumptions、risks。\n" + json.dumps(input_data, ensure_ascii=False),
    }
    result, _ = invoke_ai(provider=provider, feature=kind, messages=[prompt], actor=actor)
    content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    try:
        proposal = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        proposal = {"summary": str(content), "recommendations": [], "assumptions": [], "risks": ["模型未返回 JSON"]}
    return AIRecommendation.objects.create(
        organization=provider.organization, provider=provider, kind=kind, input_data=input_data, proposal=proposal,
    )

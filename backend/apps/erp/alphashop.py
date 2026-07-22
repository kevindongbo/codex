"""Server-side AlphaShop selection API client.

Credentials never leave the Django process.  The browser only talks to the
authenticated ERP endpoints declared in ``views.py``.
"""

import json
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
from jwt import PyJWTError
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError as DjangoValidationError

from . import integrations
from .models import AlphaShopConfig
from .secure_config import decrypt_secret


logger = logging.getLogger(__name__)


PLATFORM_REGIONS = {
    "tiktok": ("MY", "ID", "VN", "TH", "PH", "SG", "US", "BR", "MX", "GB", "ES", "FR", "DE", "IT", "JP"),
    "amazon": ("US", "GB", "ES", "FR", "DE", "IT", "CA", "JP"),
}
LISTING_TIMES = ("90", "180")

ERROR_MESSAGES = {
    "KEYWORD_ILLEGAL": "请选择关键词查询结果中的候选词，不能直接提交任意关键词。",
    "TARGET_PLATFORM_ILLEGAL": "目标平台不受支持。",
    "TARGET_COUNTRY_ILLEGAL": "目标国家或地区不受支持。",
    "PRODUCT_LISTING_TIME_ERROR": "上架时间范围不正确。",
    "PRODUCT_FILTER_PARAMS_ERROR": "筛选条件不正确，请检查价格、销量和评分范围。",
    "PRODUCT_RECALL_EMPTY": "当前条件没有找到商品，请放宽筛选条件后重试。",
    "KEYWORD_RISK_ERROR": "该关键词存在平台风险，暂时不能生成选品报告。",
    "TIMEOUT_ERROR": "上游选品分析超时，请稍后重试。",
}


class AlphaShopError(Exception):
    def __init__(self, detail, *, code="ALPHASHOP_ERROR", status_code=502, upstream_status=None):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.status_code = status_code
        self.upstream_status = upstream_status


@dataclass(frozen=True)
class AlphaShopCredentials:
    access_key: str
    secret_key: str
    api_base_url: str
    cache_scope: str
    source: str


def _resolve_credentials(organization=None):
    """Resolve database configuration first, then retain legacy env fallback."""
    if organization is not None:
        config = AlphaShopConfig.objects.filter(organization=organization).first()
        if config is not None:
            if not config.enabled or not (config.access_key_encrypted and config.secret_key_encrypted):
                return None
            try:
                access_key = decrypt_secret(config.access_key_encrypted)
                secret_key = decrypt_secret(config.secret_key_encrypted)
            except (DjangoValidationError, ImproperlyConfigured) as exc:
                raise AlphaShopError(
                    "系统保存的选品密钥无法解密，请由主账号重新保存配置。",
                    code="ALPHASHOP_CONFIG_INVALID", status_code=422,
                ) from exc
            return AlphaShopCredentials(
                access_key=access_key,
                secret_key=secret_key,
                api_base_url=config.api_base_url.rstrip("/"),
                cache_scope=f"system:{organization.pk}:{config.updated_at.isoformat()}",
                source="system",
            )
    if settings.ALPHASHOP_ACCESS_KEY and settings.ALPHASHOP_SECRET_KEY:
        return AlphaShopCredentials(
            access_key=settings.ALPHASHOP_ACCESS_KEY,
            secret_key=settings.ALPHASHOP_SECRET_KEY,
            api_base_url=settings.ALPHASHOP_API_BASE.rstrip("/"),
            cache_scope="environment",
            source="environment",
        )
    return None


def configured(organization=None):
    return _resolve_credentials(organization) is not None


def configuration_status(organization=None):
    try:
        credentials = _resolve_credentials(organization)
    except AlphaShopError:
        return {"configured": False, "source": "system", "configuration_error": True}
    return {
        "configured": credentials is not None,
        "source": credentials.source if credentials else "none",
        "configuration_error": False,
    }


def _token(credentials):
    if credentials is None:
        raise AlphaShopError(
            "选品 API 尚未在服务器完成密钥配置，请联系主账号。",
            code="ALPHASHOP_NOT_CONFIGURED",
            status_code=503,
        )
    now = int(time.time())
    return jwt.encode(
        {"iss": credentials.access_key, "exp": now + 1800, "nbf": now - 5},
        credentials.secret_key,
        algorithm="HS256",
        headers={"alg": "HS256"},
    )


def _cache_key(endpoint, payload, cache_scope):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "alphashop:" + sha256(f"{cache_scope}:{endpoint}:{raw}".encode("utf-8")).hexdigest()


def _decode_error_body(exc):
    try:
        return json.loads(exc.read().decode("utf-8", errors="replace"))
    except (ValueError, AttributeError):
        return {}


def _upstream_message(payload):
    """Extract a safe upstream message without ever exposing credentials."""
    if not isinstance(payload, dict):
        return ""
    for key in ("msg", "message", "detail", "error"):
        value = payload.get(key)
        if isinstance(value, str):
            message = " ".join(value.split()).strip()
            if message and len(message) <= 240:
                return message
    return ""


def _http_error_detail(status_code, code=""):
    """Return a useful, credential-safe diagnosis for an upstream failure."""
    if status_code in (401, 403):
        return "选品接口鉴权失败，请核对 Access Key、Secret Key 和账号授权状态。"
    if status_code == 404:
        return "选品接口地址不存在，请核对 API 地址是否为 AlphaShop 官方基础地址。"
    if status_code == 429:
        return "选品接口调用过于频繁或额度不足，请稍后重试并检查接口套餐。"
    if 500 <= status_code <= 599:
        return "选品服务暂时异常，请稍后重试；系统没有泄露接口密钥。"
    return "选品服务拒绝了本次请求，请检查关键词、地区和接口配置。"


def _request(endpoint, payload, *, timeout, cache_seconds, organization=None):
    credentials = _resolve_credentials(organization)
    if credentials is None:
        raise AlphaShopError(
            "选品 API 尚未配置，请由主账号在“店铺与 AI 接口”中完成 AlphaShop 设置。",
            code="ALPHASHOP_NOT_CONFIGURED", status_code=503,
        )
    key = _cache_key(endpoint, payload, credentials.cache_scope)
    cached = cache.get(key)
    if cached is not None:
        return cached, True

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{credentials.api_base_url}/{endpoint}",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_token(credentials)}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "DongboERP/1.0",
        },
    )
    # AlphaShop is a synchronous AI service.  It can transiently return a
    # gateway error while the model is warming up, so retry only transport and
    # 5xx errors.  4xx responses are configuration/input errors and must be
    # returned immediately rather than spending quota on duplicate calls.
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}
    last_network_error = None
    for attempt in range(1, 3):
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            if exc.code in transient_statuses and attempt < 2:
                logger.warning(
                    "AlphaShop transient HTTP failure; retrying endpoint=%s status=%s attempt=%s",
                    endpoint, exc.code, attempt,
                )
                time.sleep(attempt)
                continue
            upstream = _decode_error_body(exc)
            code = str(upstream.get("code") or upstream.get("resultCode") or "ALPHASHOP_HTTP_ERROR")
            message = _upstream_message(upstream)
            detail = ERROR_MESSAGES.get(code) or message or _http_error_detail(exc.code, code)
            raise AlphaShopError(
                detail, code=code, status_code=502, upstream_status=exc.code,
            ) from exc
        except (URLError, socket.timeout, TimeoutError, ssl.SSLError, OSError) as exc:
            last_network_error = exc
            if attempt < 2:
                logger.warning(
                    "AlphaShop transient network failure; retrying endpoint=%s attempt=%s error=%s",
                    endpoint, attempt, exc.__class__.__name__,
                )
                time.sleep(attempt)
                continue
            raise AlphaShopError(
                "连接选品服务超时，请稍后重试。", code="ALPHASHOP_TIMEOUT", status_code=504,
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, PyJWTError) as exc:
            raise AlphaShopError("选品服务返回了无法解析的数据。", code="ALPHASHOP_BAD_RESPONSE") from exc
    else:  # Defensive guard for future retry-loop changes.
        raise AlphaShopError("连接选品服务失败，请稍后重试。", code="ALPHASHOP_NETWORK_ERROR", status_code=504) from last_network_error

    if not isinstance(result, dict):
        raise AlphaShopError("选品服务返回了异常数据。", code="ALPHASHOP_BAD_RESPONSE")
    success = result.get("success")
    result_code = str(result.get("code") or result.get("resultCode") or "")
    if success is False or (result_code and result_code != "SUCCESS"):
        detail = ERROR_MESSAGES.get(result_code) or "选品服务未能完成本次查询，请检查关键词、地区和接口授权。"
        status_code = 422 if result_code in ERROR_MESSAGES else 502
        raise AlphaShopError(detail, code=result_code or "ALPHASHOP_REJECTED", status_code=status_code)

    cache.set(key, result, cache_seconds)
    return result, False


def _payload_data(response):
    data = response.get("data")
    if isinstance(data, (dict, list)):
        return data
    result = response.get("result")
    if isinstance(result, dict):
        return result
    return response


def search_keywords(*, platform, region, keyword, listing_time=None, organization=None):
    payload = {"platform": platform, "region": region, "keyword": keyword}
    if listing_time:
        payload["listingTime"] = listing_time
    response, was_cached = _request(
        "opp.selection.keyword.search/1.0",
        payload,
        timeout=settings.ALPHASHOP_KEYWORD_TIMEOUT,
        cache_seconds=settings.ALPHASHOP_KEYWORD_CACHE_SECONDS,
        organization=organization,
    )
    data = _payload_data(response)
    if isinstance(data, list):
        keywords = data
    elif isinstance(data, dict):
        keywords = data.get("keywordList")
    else:
        keywords = None
    if not isinstance(keywords, list):
        keywords = response.get("model") if isinstance(response.get("model"), list) else []
    return {"keywords": keywords, "cached": was_cached}


def generate_report(
    *, platform, region, keyword, listing_time=None, min_price=None, max_price=None,
    min_volume=None, max_volume=None, min_rating=None, max_rating=None, organization=None,
):
    payload = {
        "productKeyword": keyword,
        "targetPlatform": platform,
        "targetCountry": region,
    }
    optional = {
        "listingTime": listing_time,
        "minPrice": min_price,
        "maxPrice": max_price,
        "minVolume": min_volume,
        "maxVolume": max_volume,
        "minRating": min_rating,
        "maxRating": max_rating,
    }
    for key, value in optional.items():
        if value is not None and value != "":
            payload[key] = float(value) if key in {"minPrice", "maxPrice", "minRating", "maxRating"} else value
    response, was_cached = _request(
        "opp.selection.newproduct.report/1.0",
        payload,
        timeout=settings.ALPHASHOP_REPORT_TIMEOUT,
        cache_seconds=settings.ALPHASHOP_REPORT_CACHE_SECONDS,
        organization=organization,
    )
    data = _payload_data(response)
    summary = data.get("keywordSummary") if isinstance(data.get("keywordSummary"), dict) else {}
    products = data.get("productList") if isinstance(data.get("productList"), list) else []
    result = {"keyword_summary": summary, "products": products, "cached": was_cached}
    config = AlphaShopConfig.objects.select_related("analysis_provider").filter(organization=organization).first() if organization else None
    provider = config.analysis_provider if config and config.analysis_enabled else None
    if provider is not None:
        result["ai_analysis"] = _analyze_report_with_ai(
            provider=provider, platform=platform, region=region, keyword=keyword,
            summary=summary, products=products,
        )
    return result


def _analyze_report_with_ai(*, provider, platform, region, keyword, summary, products):
    """Use an optional LLM only to explain AlphaShop data; it never replaces it."""
    compact_products = []
    for product in products[:20]:
        if not isinstance(product, dict):
            continue
        compact_products.append({
            key: product.get(key) for key in (
                "title", "productId", "price", "priceRange", "soldCnt30d", "rating", "reviewCnt", "listingDays"
            ) if product.get(key) is not None
        })
    prompt = {
        "platform": platform,
        "region": region,
        "keyword": keyword,
        "market_summary": summary,
        "sample_products": compact_products,
    }
    message = (
        "你是跨境电商选品分析助手。仅依据以下 AlphaShop 原始数据给出中文分析，"
        "不要编造销量或价格，不要把建议当成事实。返回 JSON 对象，字段为 summary、opportunities、risks、next_actions。\n"
        + json.dumps(prompt, ensure_ascii=False)
    )
    try:
        response, _ = integrations.invoke_ai(
            provider=provider,
            feature="product_selection_analysis",
            messages=[{"role": "user", "content": message}],
        )
        content = ((response.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        if isinstance(content, str):
            try:
                analysis = json.loads(content)
            except json.JSONDecodeError:
                analysis = {"summary": content, "opportunities": [], "risks": [], "next_actions": []}
        else:
            analysis = content
        if not isinstance(analysis, dict):
            raise ValueError("AI response is not an object")
        return {"status": "ready", "provider": provider.name, "analysis": analysis}
    except Exception:  # AI analysis must never make the already successful raw report fail.
        logger.warning("Optional product-selection AI analysis failed", exc_info=True)
        return {"status": "unavailable", "provider": provider.name, "detail": "已取得选品原始数据，但本次大模型分析未完成。"}

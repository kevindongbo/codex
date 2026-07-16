"""Server-side AlphaShop selection API client.

Credentials never leave the Django process.  The browser only talks to the
authenticated ERP endpoints declared in ``views.py``.
"""

import json
import socket
import time
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
from django.conf import settings
from django.core.cache import cache


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
    def __init__(self, detail, *, code="ALPHASHOP_ERROR", status_code=502):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.status_code = status_code


def configured():
    return bool(settings.ALPHASHOP_ACCESS_KEY and settings.ALPHASHOP_SECRET_KEY)


def _token():
    if not configured():
        raise AlphaShopError(
            "选品 API 尚未在服务器完成密钥配置，请联系主账号。",
            code="ALPHASHOP_NOT_CONFIGURED",
            status_code=503,
        )
    now = int(time.time())
    return jwt.encode(
        {"iss": settings.ALPHASHOP_ACCESS_KEY, "exp": now + 1800, "nbf": now - 5},
        settings.ALPHASHOP_SECRET_KEY,
        algorithm="HS256",
        headers={"alg": "HS256"},
    )


def _cache_key(endpoint, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "alphashop:" + sha256(f"{endpoint}:{raw}".encode("utf-8")).hexdigest()


def _decode_error_body(exc):
    try:
        return json.loads(exc.read().decode("utf-8", errors="replace"))
    except (ValueError, AttributeError):
        return {}


def _request(endpoint, payload, *, timeout, cache_seconds):
    key = _cache_key(endpoint, payload)
    cached = cache.get(key)
    if cached is not None:
        return cached, True

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{settings.ALPHASHOP_API_BASE}/{endpoint}",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "DongboERP/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        upstream = _decode_error_body(exc)
        code = str(upstream.get("code") or upstream.get("resultCode") or "ALPHASHOP_HTTP_ERROR")
        detail = ERROR_MESSAGES.get(code) or upstream.get("msg") or upstream.get("message") or "上游选品服务请求失败。"
        raise AlphaShopError(detail, code=code, status_code=502) from exc
    except (URLError, socket.timeout, TimeoutError) as exc:
        raise AlphaShopError("连接选品服务超时，请稍后重试。", code="ALPHASHOP_TIMEOUT", status_code=504) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlphaShopError("选品服务返回了无法解析的数据。", code="ALPHASHOP_BAD_RESPONSE") from exc

    if not isinstance(result, dict):
        raise AlphaShopError("选品服务返回了异常数据。", code="ALPHASHOP_BAD_RESPONSE")
    success = result.get("success")
    result_code = str(result.get("code") or result.get("resultCode") or "")
    if success is False or (result_code and result_code != "SUCCESS"):
        detail = ERROR_MESSAGES.get(result_code) or result.get("msg") or result.get("message") or "选品服务未能完成本次查询。"
        status_code = 422 if result_code in ERROR_MESSAGES else 502
        raise AlphaShopError(detail, code=result_code or "ALPHASHOP_REJECTED", status_code=status_code)

    cache.set(key, result, cache_seconds)
    return result, False


def _payload_data(response):
    data = response.get("data")
    if isinstance(data, dict):
        return data
    result = response.get("result")
    if isinstance(result, dict):
        return result
    return response


def search_keywords(*, platform, region, keyword, listing_time=None):
    payload = {"platform": platform, "region": region, "keyword": keyword}
    if listing_time:
        payload["listingTime"] = listing_time
    response, was_cached = _request(
        "opp.selection.keyword.search/1.0",
        payload,
        timeout=settings.ALPHASHOP_KEYWORD_TIMEOUT,
        cache_seconds=settings.ALPHASHOP_KEYWORD_CACHE_SECONDS,
    )
    data = _payload_data(response)
    keywords = data.get("keywordList")
    if not isinstance(keywords, list):
        keywords = response.get("model") if isinstance(response.get("model"), list) else []
    return {"keywords": keywords, "cached": was_cached}


def generate_report(
    *, platform, region, keyword, listing_time=None, min_price=None, max_price=None,
    min_volume=None, max_volume=None, min_rating=None, max_rating=None,
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
    )
    data = _payload_data(response)
    summary = data.get("keywordSummary") if isinstance(data.get("keywordSummary"), dict) else {}
    products = data.get("productList") if isinstance(data.get("productList"), list) else []
    return {"keyword_summary": summary, "products": products, "cached": was_cached}

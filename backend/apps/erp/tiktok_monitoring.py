"""Public TikTok Shop product monitoring providers.

Only buyer-visible product facts are collected.  This module intentionally does
not log in to TikTok, handle seller-backend orders, or bypass access controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
import json
import re
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone


Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], Any]


class TikTokMonitoringError(Exception):
    """Base error that is safe to return to an authenticated operator."""


class MonitoringConfigurationError(TikTokMonitoringError):
    pass


class MonitoringProviderError(TikTokMonitoringError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class MonitoringDataError(TikTokMonitoringError):
    pass


@dataclass(frozen=True)
class TikTokProductObservation:
    provider: str
    product_id: str
    market: str
    captured_at: Any
    canonical_url: str
    title: str = ""
    seller: str = ""
    currency: str = "MYR"
    price: Decimal | None = None
    sold_count: int | None = None
    rating: Decimal | None = None
    review_count: int | None = None
    availability: str = ""
    image_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    attempts: tuple[dict[str, str], ...] = ()


_PRODUCT_ID = re.compile(r"(?<!\d)(\d{12,25})(?!\d)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_COUNT = re.compile(r"(-?\d+(?:\.\d+)?)\s*([KMB])?", re.IGNORECASE)


def extract_tiktok_product_id(value: str) -> str:
    """Extract a TikTok Shop product ID from a bare ID or public product URL."""

    source = str(value or "").strip()
    if _PRODUCT_ID.fullmatch(source):
        return source
    try:
        parsed = urlsplit(source)
    except ValueError as exc:
        raise MonitoringDataError("TikTok 商品链接格式无效") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not (
        host == "tiktok.com" or host.endswith(".tiktok.com")
    ):
        raise MonitoringDataError("请填写 TikTok Shop 的公开商品链接")
    query = parse_qs(parsed.query)
    for key in ("product_id", "productId", "item_id", "itemId"):
        candidate = str((query.get(key) or [""])[0])
        if _PRODUCT_ID.fullmatch(candidate):
            return candidate
    matches = _PRODUCT_ID.findall(parsed.path)
    if matches:
        return matches[-1]
    raise MonitoringDataError("链接中没有识别到 TikTok 商品 ID；请使用完整商品链接，不要使用短链接")


def canonical_product_url(product_id: str) -> str:
    return f"https://www.tiktok.com/view/product/{product_id}"


def _default_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float):
    request = Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed provider hosts
            payload = response.read()
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # pragma: no cover - defensive for unusual HTTP handlers
            pass
        raise MonitoringProviderError(
            f"上游接口返回 HTTP {exc.code}" + (f"：{detail}" if detail else ""), status=exc.code
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise MonitoringProviderError(f"无法连接上游监控接口：{exc}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MonitoringProviderError("上游监控接口没有返回有效 JSON") from exc


def _direct(mapping: Any, *keys: str):
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _mapping(mapping: Any, *keys: str) -> Mapping[str, Any]:
    value = _direct(mapping, *keys)
    return value if isinstance(value, Mapping) else {}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Mapping):
        for key in (
            "value", "amount", "price", "price_val", "priceVal", "number",
            "sale_price", "salePrice", "current_price", "currentPrice", "min_price", "minPrice",
        ):
            parsed = _decimal(value.get(key))
            if parsed is not None:
                return parsed
        return None
    text = str(value).replace(",", "").strip()
    match = _NUMBER.search(text)
    if not match:
        return None
    try:
        parsed = Decimal(match.group(0))
    except InvalidOperation:
        return None
    return parsed if parsed >= 0 else None


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Mapping):
        for key in ("value", "count", "total", "sold_count", "soldCount"):
            parsed = _count(value.get(key))
            if parsed is not None:
                return parsed
        return None
    text = str(value).replace(",", "").strip()
    match = _COUNT.search(text)
    if not match:
        return None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
        (match.group(2) or "").upper(), 1
    )
    number = Decimal(match.group(1)) * multiplier
    return int(number) if number >= 0 else None


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    return ""


def _currency(*sources: Any, market: str) -> str:
    for source in sources:
        if isinstance(source, Mapping):
            value = _direct(source, "currency", "currency_code", "currencyCode", "currency_symbol")
            if value is None:
                nested = _mapping(source, "sale_price", "salePrice", "current_price", "currentPrice", "price")
                value = _direct(nested, "currency", "currency_code", "currencyCode", "currency_symbol")
        else:
            value = source
        normalized = _text(value).upper()
        aliases = {"RM": "MYR", "¥": "CNY", "$": "USD", "£": "GBP"}
        normalized = aliases.get(normalized, normalized)
        if re.fullmatch(r"[A-Z]{3}", normalized):
            return normalized
    return "MYR" if market == "MY" else "USD"


def _first_image(value: Any) -> str:
    if isinstance(value, str):
        return value.strip() if value.strip().startswith("https://") else ""
    if isinstance(value, Mapping):
        for key in ("url", "url_list", "urlList", "uri", "image_url", "imageUrl"):
            image = _first_image(value.get(key))
            if image:
                return image
    if isinstance(value, list):
        for item in value:
            image = _first_image(item)
            if image:
                return image
    return ""


def _availability(root: Mapping[str, Any]) -> str:
    explicit = _text(_direct(root, "availability", "availability_text", "availabilityText", "stock_status"))
    if explicit:
        return explicit[:40]
    in_stock = _direct(root, "is_in_stock", "isInStock", "in_stock", "hasStock")
    if isinstance(in_stock, bool):
        return "in_stock" if in_stock else "out_of_stock"
    stock = _count(_direct(root, "stock_count", "stockCount", "stock", "available_quantity"))
    if stock is not None:
        return "in_stock" if stock > 0 else "out_of_stock"
    return ""


def _clean_extra(root: Mapping[str, Any], price_source: Any) -> dict[str, Any]:
    original = _decimal(
        _direct(root, "original_price", "originalPrice", "list_price", "listPrice")
        or _direct(price_source, "original_price", "originalPrice", "origin_price")
    )
    discount = _decimal(_direct(root, "discount_pct", "discountPercent", "discount_percent", "discount"))
    stock = _count(_direct(root, "stock_count", "stockCount", "stock", "available_quantity"))
    distribution = _direct(root, "rating_distribution", "ratingDistribution", "review_distribution")
    variants = _direct(root, "sku_variants", "skuVariants", "variants", "skus")
    metadata: dict[str, Any] = {}
    if original is not None:
        metadata["original_price"] = str(original)
    if discount is not None:
        metadata["discount_percent"] = str(discount)
    if stock is not None:
        metadata["stock_count"] = stock
    if isinstance(distribution, (dict, list)):
        metadata["rating_distribution"] = distribution
    if isinstance(variants, list):
        metadata["sku_variants"] = variants[:50]
        metadata["sku_variant_count"] = len(variants)
    confidence = _direct(root, "parse_confidence", "parseConfidence")
    warnings = _direct(root, "warnings", "warning")
    if confidence is not None:
        metadata["parse_confidence"] = confidence
    if warnings:
        metadata["warnings"] = warnings
    return metadata


def _parse_product(root: Mapping[str, Any], *, provider: str, expected_id: str, market: str) -> TikTokProductObservation:
    nested_product = _mapping(root, "product", "product_info", "productInfo", "item")
    if nested_product:
        root = nested_product
    price_info = _mapping(root, "price_info", "priceInfo", "price", "sale_price", "salePrice")
    sale_info = _mapping(root, "sale_info", "saleInfo", "sold_info", "soldInfo", "statistics")
    review_info = _mapping(root, "review_info", "reviewInfo", "rating_info", "ratingInfo", "rating")
    shop_info = _mapping(root, "shop_info", "shopInfo", "seller", "shop")
    product_id = _text(_direct(root, "product_id", "productId", "product_id_str", "id")) or expected_id
    if product_id != expected_id:
        raise MonitoringDataError(f"{provider} 返回了不同的商品 ID，本次未写入快照")
    price = _decimal(
        _direct(root, "current_price", "currentPrice", "sale_price", "salePrice", "price_min", "priceMin", "price")
    ) or _decimal(price_info)
    sold_count = _count(
        _direct(root, "sold_count", "soldCount", "sale_count", "saleCount", "sales_count", "historical_sold")
    )
    if sold_count is None:
        sold_count = _count(_direct(sale_info, "sold_count", "soldCount", "count", "total", "value"))
    rating = _decimal(_direct(root, "rating", "rating_score", "ratingScore", "review_rating", "reviewRating"))
    if rating is None:
        rating = _decimal(_direct(review_info, "score", "rating", "average", "avg_rating"))
    review_count = _count(_direct(root, "review_count", "reviewCount", "rating_count", "ratingCount", "total_reviews"))
    if review_count is None:
        review_count = _count(_direct(review_info, "review_count", "reviewCount", "count", "total"))
    if sold_count is None:
        raise MonitoringDataError(f"{provider} 没有返回该商品的公开累计销量")
    seller = _text(_direct(root, "shop_name", "shopName", "seller_name", "sellerName")) or _text(
        _direct(shop_info, "shop_name", "shopName", "seller_name", "sellerName", "name")
    )
    images = _direct(root, "image_urls", "imageUrls", "images", "product_images", "image", "image_url", "imageUrl")
    return TikTokProductObservation(
        provider=provider,
        product_id=product_id,
        market=market,
        captured_at=timezone.now(),
        canonical_url=_text(_direct(root, "product_url", "productUrl", "canonical_url", "url"))
        or canonical_product_url(expected_id),
        title=_text(_direct(root, "title", "product_name", "productName", "name")),
        seller=seller,
        currency=_currency(root, price_info, market=market),
        price=price,
        sold_count=sold_count,
        rating=rating,
        review_count=review_count,
        availability=_availability(root),
        image_url=_first_image(images),
        metadata=_clean_extra(root, price_info),
    )


class TikHubProvider:
    name = "tikhub"

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        transport: Transport | None = None,
    ):
        self.token = (token if token is not None else settings.TIKHUB_API_TOKEN).strip()
        self.base_url = (base_url or settings.TIKHUB_BASE_URL).rstrip("/")
        self.timeout = float(timeout or settings.TIKTOK_MONITOR_TIMEOUT_SECONDS)
        self.retries = int(retries if retries is not None else settings.TIKHUB_RETRIES)
        self.transport = transport or _default_transport

    def fetch(self, *, product_id: str, market: str, product_url: str) -> TikTokProductObservation:
        if not self.token:
            raise MonitoringConfigurationError("未配置 TIKHUB_API_TOKEN")
        endpoint = self.base_url + "/api/v1/tiktok/shop/web/fetch_product_detail_v3?" + urlencode(
            {"product_id": product_id, "region": market}
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                payload = self.transport(
                    "GET", endpoint, {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}, None, self.timeout
                )
                if not isinstance(payload, Mapping):
                    raise MonitoringProviderError("TikHub 返回结构无效")
                code = payload.get("code")
                if code not in (None, 0, 200, "200"):
                    raise MonitoringProviderError(
                        "TikHub 采集失败：" + _text(payload.get("message") or payload.get("message_zh") or code),
                        status=int(code) if str(code).isdigit() else None,
                    )
                data = payload.get("data")
                if not isinstance(data, Mapping):
                    raise MonitoringDataError("TikHub 没有返回商品数据，请核对商品 ID 与 MY 市场")
                root = _mapping(data, "productInfo", "product_info", "product") or data
                return _parse_product(root, provider=self.name, expected_id=product_id, market=market)
            except MonitoringProviderError as exc:
                last_error = exc
                should_retry = exc.status == 400 or (exc.status is not None and exc.status >= 500)
                if not should_retry or attempt >= self.retries:
                    raise
                time.sleep(min(0.5 * (2**attempt), 2.0))
            except MonitoringDataError:
                raise
        raise MonitoringProviderError(f"TikHub 采集失败：{last_error}")


class ApifyProvider:
    name = "apify"

    def __init__(
        self,
        *,
        token: str | None = None,
        actor_id: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_charge_usd: Decimal | str | float | None = None,
        transport: Transport | None = None,
    ):
        self.token = (token if token is not None else settings.APIFY_API_TOKEN).strip()
        self.actor_id = (actor_id or settings.APIFY_TIKTOK_ACTOR_ID).replace("/", "~")
        self.base_url = (base_url or settings.APIFY_BASE_URL).rstrip("/")
        self.timeout = float(timeout or settings.APIFY_TIKTOK_TIMEOUT_SECONDS)
        self.max_charge_usd = str(max_charge_usd or settings.APIFY_TIKTOK_MAX_CHARGE_USD)
        self.transport = transport or _default_transport

    def fetch(self, *, product_id: str, market: str, product_url: str) -> TikTokProductObservation:
        if not self.token:
            raise MonitoringConfigurationError("未配置 APIFY_API_TOKEN")
        query = urlencode({"timeout": int(self.timeout), "maxItems": 1, "maxTotalChargeUsd": self.max_charge_usd})
        endpoint = (
            f"{self.base_url}/v2/acts/{quote(self.actor_id, safe='~')}/run-sync-get-dataset-items?{query}"
        )
        body = json.dumps(
            {
                "productIds": [product_id],
                "maxResults": 1,
                "proxyConfiguration": {
                    "useApifyProxy": True,
                    "apifyProxyGroups": ["RESIDENTIAL"],
                    "countryCode": market,
                },
            }
        ).encode("utf-8")
        payload = self.transport(
            "POST",
            endpoint,
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            body,
            self.timeout + 10,
        )
        if not isinstance(payload, list) or not payload:
            raise MonitoringDataError("Apify 没有返回商品数据")
        root = next(
            (
                item for item in payload
                if isinstance(item, Mapping)
                and _text(_direct(item, "product_id", "productId", "id")) in {"", product_id}
                and _text(item.get("record_type")).lower() != "shop"
            ),
            None,
        )
        if not isinstance(root, Mapping):
            raise MonitoringDataError("Apify 返回结果中没有目标商品")
        return _parse_product(root, provider=self.name, expected_id=product_id, market=market)


def configured_providers(provider: str = "auto", *, apify_timeout: float | None = None) -> list[Any]:
    requested = str(provider or "auto").lower()
    if requested not in {"auto", "tikhub", "apify"}:
        raise MonitoringConfigurationError("provider 只支持 auto、tikhub 或 apify")
    providers: list[Any] = []
    if requested in {"auto", "tikhub"} and settings.TIKHUB_API_TOKEN.strip():
        providers.append(TikHubProvider())
    if requested in {"auto", "apify"} and settings.APIFY_API_TOKEN.strip():
        providers.append(ApifyProvider(timeout=apify_timeout))
    if not providers:
        if requested == "tikhub":
            raise MonitoringConfigurationError("未配置 TIKHUB_API_TOKEN")
        if requested == "apify":
            raise MonitoringConfigurationError("未配置 APIFY_API_TOKEN")
        raise MonitoringConfigurationError("未配置监控接口密钥；请设置 TIKHUB_API_TOKEN，或设置 APIFY_API_TOKEN 作为备用")
    return providers


def fetch_tiktok_observation(
    product_url: str,
    *,
    market: str = "MY",
    providers: Iterable[Any] | None = None,
    provider: str = "auto",
    apify_timeout: float | None = None,
) -> TikTokProductObservation:
    market = str(market or "MY").strip().upper()
    if market != "MY":
        raise MonitoringDataError("当前自动采集只开放马来西亚 MY 市场")
    product_id = extract_tiktok_product_id(product_url)
    attempts: list[dict[str, str]] = []
    chain = list(providers) if providers is not None else configured_providers(
        provider, apify_timeout=apify_timeout
    )
    if not chain:
        raise MonitoringConfigurationError("没有可用的 TikTok 监控提供商")
    for item in chain:
        name = str(getattr(item, "name", item.__class__.__name__)).lower()
        try:
            observation = item.fetch(
                product_id=product_id,
                market=market,
                product_url=product_url,
            )
            return replace(observation, attempts=tuple(attempts))
        except TikTokMonitoringError as exc:
            attempts.append({"provider": name, "error": str(exc)[:300]})
    summary = "；".join(f"{item['provider']}：{item['error']}" for item in attempts)
    raise MonitoringProviderError("所有监控通道均失败：" + summary)

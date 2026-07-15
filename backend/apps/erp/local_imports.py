import hashlib
import json
from datetime import timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator, URLValidator
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (
    CompetitorProduct,
    CompetitorSnapshot,
    LocalImport,
    Organization,
    Product,
    ProductImage,
    PurchaseOrder,
    ReplenishmentPolicy,
    ReturnOrder,
    SalesOrder,
    SKU,
    StockLedger,
    StockTransfer,
    Supplier,
    Warehouse,
)
from .services import adjust_inventory, write_audit


HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])
HTTPS_URL_VALIDATOR = URLValidator(schemes=["https"])
MAX_LOCAL_ID_LENGTH = 200
MAX_IMPORT_COUNTS = {
    "products": 10_000,
    "snapshots": 100_000,
    "inventoryBalances": 50_000,
}
MAX_BIG_INTEGER = 9_223_372_036_854_775_807


def _items(source, key):
    value = source.get(key, []) if isinstance(source, dict) else []
    return value if isinstance(value, list) else []


def _text(value):
    return "" if value is None else str(value).strip()


def _decimal(value, default="0"):
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None else Decimal(default)


def _decimal_or_none(value):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _integer(value):
    parsed = _integer_or_none(value)
    return parsed if parsed is not None else 0


def _integer_or_none(value):
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite() or parsed != parsed.to_integral_value():
            return None
        result = int(parsed)
    except (InvalidOperation, OverflowError, TypeError, ValueError):
        return None
    return result if 0 <= result <= MAX_BIG_INTEGER else None


def _boolean(value, default=False):
    if isinstance(value, bool):
        return value
    if not isinstance(value, (int, float, str)) and value is not None:
        return default
    if value in (1, "1", "true", "True", "yes", "on"):
        return True
    if value in (0, "0", "false", "False", "no", "off", None, ""):
        return False
    return default


def _is_missing(value):
    return value is None or value == ""


def _decimal_fits(value, *, max_digits, decimal_places, minimum=Decimal("0"), maximum=None):
    parsed = _decimal_or_none(value)
    if parsed is None or parsed < minimum or (maximum is not None and parsed > maximum):
        return False
    try:
        DecimalValidator(max_digits=max_digits, decimal_places=decimal_places)(parsed)
    except ValidationError:
        return False
    return True


def _valid_http_url(value, *, https_only=False, max_length=1000):
    text = _text(value)
    if not text or len(text) > max_length:
        return False
    try:
        (HTTPS_URL_VALIDATOR if https_only else HTTP_URL_VALIDATOR)(text)
        parsed = urlsplit(text)
        hostname = parsed.hostname
    except (ValidationError, ValueError):
        return False
    schemes = {"https"} if https_only else {"http", "https"}
    return (
        parsed.scheme.lower() in schemes
        and bool(hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _source_hash(source):
    canonical = json.dumps(
        source,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _organization_has_business_data(organization):
    return any(
        queryset.filter(organization=organization).exists()
        for queryset in (
            Product.objects,
            CompetitorProduct.objects,
            PurchaseOrder.objects,
            SalesOrder.objects,
            ReturnOrder.objects,
            StockLedger.objects,
            StockTransfer.objects,
            ReplenishmentPolicy.objects,
            Supplier.objects,
            LocalImport.objects,
        )
    )


def validate_local_import(*, organization, warehouse, source):
    errors = []
    warnings = []
    if not isinstance(source, dict):
        return {
            "ready": False,
            "source_hash": "",
            "summary": {},
            "warnings": [],
            "errors": ["备份文件不是有效的 JSON 对象"],
        }

    try:
        source_hash = _source_hash(source)
    except (TypeError, ValueError):
        return {
            "ready": False,
            "source_hash": "",
            "summary": {},
            "warnings": [],
            "errors": ["备份文件包含无法规范化的 JSON 数值或对象"],
        }

    version = _integer(source.get("version"))
    if version not in {5, 6}:
        errors.append("仅支持由当前网页导出的第 5 或第 6 版完整备份")
    if warehouse.organization_id != organization.id or not warehouse.active:
        errors.append("目标仓库不属于当前组织或已停用")
    if _organization_has_business_data(organization):
        errors.append("为避免混账，当前版本只允许导入到尚无业务数据的新组织")

    for key, limit in MAX_IMPORT_COUNTS.items():
        value = source.get(key)
        if not isinstance(value, list):
            errors.append(f"{key} 必须是数组")
        elif len(value) > limit:
            errors.append(f"{key} 超过单次导入上限 {limit}")
    for key in (
        "purchaseOrders",
        "salesOrders",
        "returns",
        "inventoryMovements",
        "reservations",
    ):
        if key in source and not isinstance(source[key], list):
            errors.append(f"{key} 必须是数组")

    products = _items(source, "products")
    snapshots = _items(source, "snapshots")
    balances = _items(source, "inventoryBalances")
    own = []
    competitors = []
    products_by_local_id = {}
    seen_product_ids = set()
    seen_skus = set()
    missing_images = 0
    for index, product in enumerate(products, start=1):
        if not isinstance(product, dict):
            errors.append(f"第 {index} 个商品不是有效对象")
            continue
        local_id = _text(product.get("id"))
        if not local_id:
            errors.append(f"第 {index} 个商品缺少本机 ID")
        elif len(local_id) > MAX_LOCAL_ID_LENGTH:
            errors.append(f"第 {index} 个商品本机 ID 过长")
        elif local_id in seen_product_ids:
            errors.append(f"商品本机 ID 重复：{local_id}")
        else:
            seen_product_ids.add(local_id)
            products_by_local_id[local_id] = product

        name = _text(product.get("name"))
        if not name:
            errors.append(f"第 {index} 个商品缺少名称")
        elif len(name) > 200:
            errors.append(f"第 {index} 个商品名称超过 200 个字符")

        kind = product.get("kind")
        if kind == "own":
            own.append(product)
            sku = _text(product.get("sku")).upper()
            if not sku:
                warnings.append(f"{name or '未命名商品'} 缺少 SKU，将作为草稿导入")
            elif len(sku) > 80:
                errors.append(f"本店 SKU 超过 80 个字符：{sku[:30]}…")
            elif sku in seen_skus:
                errors.append(f"本店 SKU 重复：{sku}")
            else:
                seen_skus.add(sku)

            cost_value = product.get("standardCost", product.get("cost", 0))
            if not _decimal_fits(cost_value, max_digits=14, decimal_places=4):
                warnings.append(f"{name or local_id} 的成本无效，将以 0 导入并保持草稿")
            safety_stock = product.get("safetyStock", 0)
            if not _decimal_fits(safety_stock, max_digits=14, decimal_places=3):
                warnings.append(f"{name or local_id} 的安全库存无效，将以 0 导入")
            supplier_name = _text(
                product.get("defaultSupplier") or product.get("supplier")
            )
            if len(supplier_name) > 160:
                errors.append(f"{name or local_id} 的供应商名称超过 160 个字符")
        elif kind in {"direct", "indirect"}:
            competitors.append(product)
        else:
            errors.append(f"第 {index} 个商品类型无效：{kind!s}")

        status = _text(product.get("status", "draft"))
        if status not in {"draft", "active", "inactive"}:
            errors.append(f"{name or local_id} 的商品状态无效：{status}")
        if len(_text(product.get("seller"))) > 160:
            errors.append(f"{name or local_id} 的店铺名称超过 160 个字符")
        if len(_text(product.get("market"))) > 8:
            errors.append(f"{name or local_id} 的市场代码超过 8 个字符")

        sales_currency = _text(product.get("salesCurrency") or "CNY").upper()
        if len(sales_currency) != 3 or not sales_currency.isascii() or not sales_currency.isalpha():
            errors.append(f"{name or local_id} 的销售币种必须是 3 位字母代码")
        if kind == "own":
            cost_currency = _text(
                product.get("costCurrency") or product.get("salesCurrency") or "CNY"
            ).upper()
            if len(cost_currency) != 3 or not cost_currency.isascii() or not cost_currency.isalpha():
                errors.append(f"{name or local_id} 的成本币种必须是 3 位字母代码")

        product_url = _text(product.get("productUrl") or product.get("url"))
        url_limit = 200 if kind == "own" else 1000
        if not _valid_http_url(product_url, max_length=url_limit):
            if kind == "own":
                warnings.append(f"{name or local_id} 的商品链接无效，将清空并保持草稿")
            elif kind in {"direct", "indirect"}:
                warnings.append(f"竞品 {name or local_id} 的链接无效，将跳过")
        purchase_url = _text(product.get("purchaseUrl"))
        if purchase_url and not _valid_http_url(purchase_url, max_length=200):
            warnings.append(f"{name or local_id} 的采购链接无效，将清空")

        image = _text(product.get("image"))
        if not image or not _valid_http_url(image, https_only=True, max_length=1000):
            missing_images += 1
    if missing_images:
        warnings.append(
            f"{missing_images} 个商品缺少可共享的 HTTPS 图片，将列为待补图记录"
        )

    seen_snapshot_ids = set()
    seen_snapshot_keys = set()
    for index, snapshot in enumerate(snapshots, start=1):
        if not isinstance(snapshot, dict):
            errors.append(f"第 {index} 个快照不是有效对象")
            continue
        snapshot_id = _text(snapshot.get("id"))
        if snapshot_id:
            if len(snapshot_id) > MAX_LOCAL_ID_LENGTH:
                errors.append(f"第 {index} 个快照本机 ID 过长")
            elif snapshot_id in seen_snapshot_ids:
                errors.append(f"快照本机 ID 重复：{snapshot_id}")
            else:
                seen_snapshot_ids.add(snapshot_id)
        product_id = _text(snapshot.get("productId"))
        if product_id not in products_by_local_id:
            errors.append(f"第 {index} 个快照引用了未知商品：{product_id or '空'}")
        captured_at = _aware_datetime(snapshot.get("at"))
        if captured_at is None:
            errors.append(f"第 {index} 个快照记录时间无效")
        else:
            snapshot_key = (
                product_id,
                captured_at.astimezone(datetime_timezone.utc).isoformat(),
            )
            if snapshot_key in seen_snapshot_keys:
                errors.append(f"第 {index} 个快照与同商品同时间记录重复")
            seen_snapshot_keys.add(snapshot_key)
        if not _is_missing(snapshot.get("price")) and not _decimal_fits(
            snapshot.get("price"), max_digits=14, decimal_places=4
        ):
            errors.append(f"第 {index} 个快照价格无效")
        for field, label in (("sold", "累计销量"), ("reviews", "评价数"), ("lowReviews", "低星评价数")):
            if _integer_or_none(snapshot.get(field, 0)) is None:
                errors.append(f"第 {index} 个快照{label}无效")
        rating = snapshot.get("rating")
        if not _is_missing(rating) and not _decimal_fits(
            rating, max_digits=4, decimal_places=2, maximum=Decimal("5")
        ):
            errors.append(f"第 {index} 个快照商品评分无效")
        shop_rating = snapshot.get("shopRating")
        if not _is_missing(shop_rating) and not _decimal_fits(
            shop_rating, max_digits=4, decimal_places=2, maximum=Decimal("5")
        ):
            errors.append(f"第 {index} 个快照店铺评分无效")
        reviews = _integer_or_none(snapshot.get("reviews", 0))
        low_reviews = _integer_or_none(snapshot.get("lowReviews", 0))
        if reviews is not None and low_reviews is not None and low_reviews > reviews:
            errors.append(f"第 {index} 个快照低星评价数不能超过评价总数")

    reserved = Decimal("0")
    seen_balance_products = set()
    opening_rows = 0
    for index, balance in enumerate(balances, start=1):
        if not isinstance(balance, dict):
            errors.append(f"第 {index} 个库存余额不是有效对象")
            continue
        product_id = _text(balance.get("productId"))
        source_product = products_by_local_id.get(product_id)
        if source_product is None or source_product.get("kind") != "own":
            errors.append(f"第 {index} 个库存余额引用了未知或非本店商品：{product_id or '空'}")
        if product_id in seen_balance_products:
            errors.append(f"同一商品存在多条库存余额：{product_id}")
        seen_balance_products.add(product_id)
        on_hand = _decimal_or_none(balance.get("onHand", 0))
        reserved_value = _decimal_or_none(balance.get("reserved", 0))
        if on_hand is None or not _decimal_fits(on_hand, max_digits=14, decimal_places=3):
            errors.append(f"第 {index} 个库存余额的在库数量无效")
            continue
        if reserved_value is None or not _decimal_fits(
            reserved_value, max_digits=14, decimal_places=3
        ):
            errors.append(f"第 {index} 个库存余额的锁定数量无效")
            continue
        if reserved_value > on_hand:
            errors.append(f"第 {index} 个库存余额的锁定数量超过在库数量")
        if (
            on_hand > 0
            and source_product is not None
            and source_product.get("kind") == "own"
            and not _text(source_product.get("sku"))
        ):
            errors.append(f"第 {index} 个正库存商品缺少 SKU，无法建立期初库存")
        reserved += reserved_value
        if on_hand > 0:
            opening_rows += 1

    if reserved > 0:
        errors.append(f"本机仍有 {reserved} 件锁定库存，请先完成或取消相关订单后再迁移")
    open_purchase_count = sum(
        1
        for item in _items(source, "purchaseOrders")
        if isinstance(item, dict) and item.get("status") in {"ordered", "transit", "partial"}
    )
    open_sales_count = sum(
        1
        for item in _items(source, "salesOrders")
        if isinstance(item, dict)
        and item.get("status") in {"shortage", "picking", "review", "ready"}
    )
    open_return_count = sum(
        1
        for item in _items(source, "returns")
        if isinstance(item, dict) and item.get("status") in {"requested", "partial"}
    )
    active_reservation_count = sum(
        1
        for item in _items(source, "reservations")
        if isinstance(item, dict) and item.get("status") == "active"
    )
    if open_purchase_count:
        errors.append(f"本机仍有 {open_purchase_count} 张未完成采购单，请先完成或取消后再迁移")
    if open_sales_count or active_reservation_count:
        errors.append(
            "本机仍有未完成订单或有效锁定记录，请先出库或取消并释放库存后再迁移"
        )
    if open_return_count:
        errors.append(f"本机仍有 {open_return_count} 张未完成退货单，请处理完成后再迁移")
    document_counts = {
        "purchase_orders_archived": len(_items(source, "purchaseOrders")),
        "sales_orders_archived": len(_items(source, "salesOrders")),
        "returns_archived": len(_items(source, "returns")),
        "legacy_movements_archived": len(_items(source, "inventoryMovements")),
        "open_purchase_orders": open_purchase_count,
        "open_sales_orders": open_sales_count,
        "open_returns": open_return_count,
        "active_reservations": active_reservation_count,
    }
    if any(document_counts.values()):
        warnings.append("历史采购、订单、退货和旧流水保留在原始备份中，本次不作为可继续过账的团队单据导入")
    summary = {
        "source_version": version,
        "products": len(products),
        "own_skus": sum(1 for item in own if _text(item.get("sku"))),
        "competitors": len(competitors),
        "snapshots": len(snapshots),
        "opening_balance_rows": opening_rows,
        **document_counts,
    }
    return {
        "ready": not errors,
        "source_hash": source_hash,
        "summary": summary,
        "warnings": warnings,
        "errors": errors,
    }


def _aware_datetime(value):
    try:
        parsed = parse_datetime(str(value or ""))
    except (OverflowError, TypeError, ValueError):
        return None
    if parsed is None:
        return None
    try:
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    except (OverflowError, ValueError):
        return None


@transaction.atomic
def commit_local_import(*, organization, warehouse, source, idempotency_key, actor=None):
    idempotency_key = str(idempotency_key or "").strip()
    if not idempotency_key:
        raise ValidationError({"idempotency_key": "该字段不能为空"})
    if len(idempotency_key) > 160:
        raise ValidationError({"idempotency_key": "幂等键不能超过 160 个字符"})

    # Serialize imports for one organization. The database-level one-report
    # constraint added below is the final guard for concurrent first imports.
    try:
        organization = Organization.objects.select_for_update().get(
            pk=organization.pk,
            active=True,
        )
    except Organization.DoesNotExist as exc:
        raise ValidationError({"organization": "组织不存在或已停用"}) from exc
    try:
        warehouse = Warehouse.objects.select_for_update().get(
            pk=warehouse.pk,
            organization=organization,
            active=True,
        )
    except Warehouse.DoesNotExist as exc:
        raise ValidationError({"warehouse": "目标仓库不存在或已停用"}) from exc

    preview = validate_local_import(
        organization=organization,
        warehouse=warehouse,
        source=source,
    )
    source_hash = preview["source_hash"]
    existing_key = LocalImport.objects.filter(
        organization=organization,
        idempotency_key=idempotency_key,
    ).first()
    if existing_key:
        if existing_key.source_hash != source_hash:
            raise ValidationError("幂等键已用于另一份本机备份")
        if existing_key.warehouse_id != warehouse.pk:
            raise ValidationError("幂等键已用于另一目标仓库")
        return existing_key
    existing_hash = LocalImport.objects.filter(
        organization=organization,
        source_hash=source_hash,
    ).first()
    if existing_hash:
        if existing_hash.warehouse_id != warehouse.pk:
            raise ValidationError("同一备份已经导入到另一目标仓库")
        return existing_hash
    if not preview["ready"]:
        raise ValidationError({"source": preview["errors"]})

    mapping = {"products": {}, "competitors": {}, "snapshots": {}}
    own_by_local_id = {}
    competitor_by_local_id = {}
    supplier_by_name = {}
    warnings = list(preview["warnings"])

    for index, item in enumerate(_items(source, "products"), start=1):
        local_id = _text(item.get("id"))
        kind = item.get("kind")
        image_url = _text(item.get("image"))
        shared_image = (
            image_url
            if _valid_http_url(image_url, https_only=True, max_length=1000)
            else ""
        )
        product_url = _text(item.get("productUrl") or item.get("url"))
        if kind == "own":
            supplier = None
            supplier_name = _text(item.get("defaultSupplier") or item.get("supplier"))
            if supplier_name:
                supplier = supplier_by_name.get(supplier_name.casefold())
                if supplier is None:
                    supplier = Supplier.objects.create(
                        organization=organization,
                        code=f"MIG-{index:04d}",
                        name=supplier_name,
                    )
                    supplier_by_name[supplier_name.casefold()] = supplier
            sku_code = _text(item.get("sku")).upper()
            raw_cost = item.get("standardCost", item.get("cost", 0))
            cost = _decimal(raw_cost) if _decimal_fits(
                raw_cost, max_digits=14, decimal_places=4
            ) else Decimal("0")
            raw_safety_stock = item.get("safetyStock", 0)
            safety_stock = _decimal(raw_safety_stock) if _decimal_fits(
                raw_safety_stock, max_digits=14, decimal_places=3
            ) else Decimal("0")
            valid_product_url = _valid_http_url(product_url, max_length=200)
            purchase_url = _text(item.get("purchaseUrl"))
            valid_purchase_url = _valid_http_url(purchase_url, max_length=200)
            complete = bool(
                sku_code
                and cost > 0
                and valid_product_url
                and shared_image
            )
            desired_status = _text(item.get("status", "draft"))
            status = (
                Product.Status.ACTIVE
                if complete and desired_status == "active"
                else Product.Status.INACTIVE
                if complete and desired_status == "inactive"
                else Product.Status.DRAFT
            )
            product = Product.objects.create(
                organization=organization,
                name=_text(item.get("name")),
                seller=_text(item.get("seller")),
                market=_text(item.get("market")),
                sales_currency=_text(item.get("salesCurrency") or "CNY").upper(),
                monitoring_enabled=_boolean(item.get("monitoringEnabled")),
                source_url=product_url if valid_product_url else "",
                purchase_url=purchase_url if valid_purchase_url else "",
                default_supplier=supplier,
                status=status,
            )
            sku = None
            if sku_code:
                sku = SKU.objects.create(
                    organization=organization,
                    product=product,
                    code=sku_code,
                    cost=cost,
                    currency=_text(
                        item.get("costCurrency") or item.get("salesCurrency") or "CNY"
                    ).upper(),
                    safety_stock=safety_stock,
                    active=True,
                )
            if shared_image:
                ProductImage.objects.create(
                    product=product,
                    url=shared_image,
                    alt=product.name,
                    position=0,
                )
            own_by_local_id[local_id] = (product, sku)
            mapping["products"][local_id] = {
                "product_id": str(product.pk),
                "sku_id": str(sku.pk) if sku else None,
            }
            if _boolean(item.get("monitoringEnabled")) and valid_product_url:
                profile = CompetitorProduct.objects.create(
                    organization=organization,
                    linked_product=product,
                    name=product.name,
                    kind=CompetitorProduct.Kind.DIRECT,
                    platform="own",
                    market=product.market,
                    url=product.source_url,
                    image_url=shared_image,
                    seller=product.seller,
                    currency=product.sales_currency,
                    active=True,
                )
                competitor_by_local_id[local_id] = profile
                mapping["competitors"][local_id] = str(profile.pk)
        elif kind in {"direct", "indirect"}:
            if not _valid_http_url(product_url, max_length=1000):
                continue
            competitor = CompetitorProduct.objects.create(
                organization=organization,
                name=_text(item.get("name")),
                kind=kind,
                platform="tiktok_shop",
                market=_text(item.get("market")),
                url=product_url,
                image_url=shared_image,
                seller=_text(item.get("seller")),
                currency=_text(item.get("salesCurrency") or "CNY").upper(),
                active=item.get("status") != "inactive",
            )
            competitor_by_local_id[local_id] = competitor
            mapping["competitors"][local_id] = str(competitor.pk)

    for item in _items(source, "snapshots"):
        local_product_id = _text(item.get("productId"))
        competitor = competitor_by_local_id.get(local_product_id)
        if competitor is None:
            own_pair = own_by_local_id.get(local_product_id)
            if own_pair and _valid_http_url(own_pair[0].source_url):
                product = own_pair[0]
                competitor, _ = CompetitorProduct.objects.get_or_create(
                    organization=organization,
                    linked_product=product,
                    defaults={
                        "name": product.name,
                        "kind": CompetitorProduct.Kind.DIRECT,
                        "platform": "own",
                        "market": product.market,
                        "url": product.source_url,
                        "image_url": product.images.first().url if product.images.exists() else "",
                        "seller": product.seller,
                        "currency": product.sales_currency,
                        "active": True,
                    },
                )
                competitor_by_local_id[local_product_id] = competitor
                mapping["competitors"][local_product_id] = str(competitor.pk)
        if competitor is None:
            warnings.append(f"快照 {item.get('id') or ''} 找不到可迁移商品，已跳过")
            continue
        snapshot, _ = CompetitorSnapshot.objects.get_or_create(
            product=competitor,
            captured_at=_aware_datetime(item.get("at")),
            defaults={
                "price": _decimal(item.get("price"))
                if not _is_missing(item.get("price"))
                else None,
                "sold_count": _integer(item.get("sold")),
                "rating": _decimal(item.get("rating"))
                if not _is_missing(item.get("rating"))
                else None,
                "review_count": _integer(item.get("reviews")),
                "raw": {
                    "low_reviews": _integer(item.get("lowReviews")),
                    "shop_rating": str(_decimal(item.get("shopRating")))
                    if not _is_missing(item.get("shopRating"))
                    else None,
                },
            },
        )
        snapshot_local_id = _text(item.get("id"))
        if snapshot_local_id:
            mapping["snapshots"][snapshot_local_id] = str(snapshot.pk)

    imported_opening_rows = 0
    for item in _items(source, "inventoryBalances"):
        pair = own_by_local_id.get(_text(item.get("productId")))
        on_hand = _decimal(item.get("onHand"))
        if not pair or not pair[1] or on_hand <= 0:
            continue
        stock_key_digest = hashlib.sha256(
            f"{source_hash}:{pair[1].pk}".encode("utf-8")
        ).hexdigest()
        adjust_inventory(
            organization=organization,
            warehouse=warehouse,
            sku=pair[1],
            delta=on_hand,
            reason="本机 ERP 迁移期初库存",
            # adjust_inventory also stores this value in reference_id (max 64)
            # and prefixes it for the ledger idempotency key (max 160).
            idempotency_key=f"li:{stock_key_digest[:61]}",
            actor=actor,
        )
        imported_opening_rows += 1

    report_summary = {
        **preview["summary"],
        "imported_products": len(mapping["products"]),
        "imported_own_skus": sum(
            1 for value in mapping["products"].values() if value["sku_id"]
        ),
        "imported_monitoring_profiles": len(mapping["competitors"]),
        "imported_snapshots": len(mapping["snapshots"]),
        "imported_opening_balance_rows": imported_opening_rows,
        "draft_products": sum(
            1 for product, _sku in own_by_local_id.values()
            if product.status == Product.Status.DRAFT
        ),
    }

    report = LocalImport.objects.create(
        organization=organization,
        warehouse=warehouse,
        idempotency_key=idempotency_key,
        source_version=_integer(source.get("version")),
        source_hash=source_hash,
        summary=report_summary,
        mapping=mapping,
        warnings=warnings,
        imported_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    write_audit(
        organization=organization,
        actor=actor,
        action="local_import.complete",
        instance=report,
        after={"summary": report.summary, "source_hash": source_hash},
        request_id=idempotency_key[:80],
    )
    return report

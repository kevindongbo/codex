import hashlib
import logging
import uuid
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import (
    AIInvocationLog, AIProviderConfig, AIRecommendation, AlphaShopConfig, AuditLog, CompetitorProduct, CompetitorSnapshot, Membership, Organization, OrganizationSyncState, OwnerEmailChallenge,
    LocalImport, Product, ProductImage, PurchaseOrder, PurchaseOrderLine, PurchaseShipment, Receipt, ReceiptLine, ReplenishmentAIJob, ReplenishmentPolicy, ReplenishmentSettings,
    ReturnLine, ReturnOrder, ReturnReceipt, ReturnReceiptLine, SalesOrder, SalesOrderLine, Shipment, ShipmentLine,
    SKU, StockBalance, StockLedger, StockLedgerReversal, StockReservation, StockTransfer, StockTransferLine, Supplier, TikTokShopConnection, TikTokShopSyncRun, UploadedMediaAsset, Warehouse,
)
from .owner_security import consume_challenge, create_challenge, email_verification_enabled
from .permissions import (
    PERMISSION_CATALOG,
    OrganizationRolePermission,
    is_owner,
    allowed_warehouse_ids, LEGACY_ROLE_PERMISSIONS, membership_permissions,
    request_organization,
)
from .serializers import (
    AIInvocationLogSerializer, AIProviderConfigSerializer, AIRecommendationConfirmationSerializer, AIRecommendationInputSerializer, AIRecommendationSerializer, AlphaShopConfigSerializer,
    AdjustmentInputSerializer, AllocateInputSerializer, AuditLogSerializer,
    CompetitorProductSerializer, CompetitorSnapshotSerializer, InternalAccountSerializer, MembershipSerializer,
    ConfirmAndShipInputSerializer, LocalImportSerializer, OrganizationSerializer,
    ProductImageSerializer, ProductSerializer, QuickSalesSnapshotInputSerializer, UploadedMediaAssetSerializer,
    PurchaseOrderEditInputSerializer, PurchaseOrderSerializer, ReceiptSerializer, ReceiveInputSerializer,
    ReplenishmentPolicySerializer, ReplenishmentRecommendationQuerySerializer, ReplenishmentSettingsSerializer,
    ReturnOrderSerializer, ReturnReceiveInputSerializer, SalesOrderSerializer,
    ShipmentSerializer, ShipInputSerializer, SKUSerializer, StockBalanceSerializer,
    StockLedgerReversalInputSerializer, StockLedgerSerializer, StockTransferSerializer, SupplierSerializer,
    ManualStockMovementInputSerializer, TikTokAuthorizationStartSerializer, TikTokShopConnectionSerializer, TikTokShopSyncRunSerializer, TikTokSyncStartSerializer,
    TransferPostInputSerializer, WarehouseSerializer,
    ProductSelectionKeywordInputSerializer, ProductSelectionReportInputSerializer,
)
from . import alphashop, integrations
from .services import (
    adjust_inventory, allocate_order, cancel_order, cancel_purchase, cancel_stock_transfer,
    confirm_and_ship_order, confirm_order, create_quick_sales_snapshot,
    dispatch_stock_transfer, edit_purchase, manual_stock_movement, receive_purchase, receive_return, receive_stock_transfer, reverse_stock_ledger,
    reject_return, ship_order, start_picking, submit_purchase, verify_order, write_audit,
)
from .local_imports import commit_local_import, validate_local_import
from .replenishment import (
    ReplenishmentPolicy as ForecastPolicy,
    build_replenishment_forecast,
)
from .replenishment_automation import schedule_replenishment_ai_analysis
from .profit_calculator import (
    AFFILIATE_SOURCE,
    COMMISSION_SOURCE,
    LVG_RATE,
    LVG_TAX_SOURCE,
    PLATFORM_SUPPORT_FEE,
    RULE_EFFECTIVE_DATE,
    SHIPPING_CALCULATION_SOURCE,
    SHIPPING_SOURCE,
    SUPPORT_FEE_SOURCE,
    TRANSACTION_RATE,
    TRANSACTION_SOURCE,
    category_config,
    category_tree,
    calculate_profit,
)
from .profit_serializers import ProfitCalculationSerializer
from .single_tenant import active_internal_membership, ensure_internal_organization, internal_organization
from .sync import bump_sync_revision


logger = logging.getLogger(__name__)


ECB_DAILY_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_DAILY_RATES_CACHE_KEY = "profit-calculator:exchange-rates:ecb:daily"
ECB_LAST_GOOD_RATES_CACHE_KEY = "profit-calculator:exchange-rates:ecb:last-good"


def _parse_ecb_daily_rates(payload):
    root = ElementTree.fromstring(payload)
    dated_cube = next(
        (node for node in root.iter() if node.tag.endswith("Cube") and node.attrib.get("time")),
        None,
    )
    if dated_cube is None:
        raise ValueError("ECB response does not include a dated rate table.")
    rates = {
        node.attrib.get("currency"): Decimal(node.attrib["rate"])
        for node in dated_cube
        if node.attrib.get("currency") and node.attrib.get("rate")
    }
    missing = {"CNY", "MYR", "USD"} - set(rates)
    if missing or any(rates[currency] <= 0 for currency in ("CNY", "MYR", "USD")):
        raise ValueError("ECB response is missing a required positive exchange rate.")
    precision = Decimal("0.000001")
    return {
        "date": dated_cube.attrib["time"],
        "cny_per_myr": str((rates["CNY"] / rates["MYR"]).quantize(precision)),
        "usd_per_myr": str((rates["USD"] / rates["MYR"]).quantize(precision)),
        "source": "European Central Bank",
        "source_url": ECB_DAILY_RATES_URL,
        "stale": False,
    }


class DataConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "数据与现有记录冲突，请检查单号、SKU、条码或幂等键是否重复。"
    default_code = "data_conflict"


def _save_serializer(serializer, **kwargs):
    try:
        with transaction.atomic():
            return serializer.save(**kwargs)
    except IntegrityError as exc:
        raise DataConflict() from exc


def _service_call(function, **kwargs):
    try:
        return function(**kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    except IntegrityError as exc:
        raise DataConflict() from exc


def _require_warehouse_access(request, organization, *warehouses):
    """Reject writes outside the member's explicit warehouse authorization."""
    membership = active_internal_membership(request.user)
    allowed = allowed_warehouse_ids(request.user, membership, organization)
    if allowed is None:
        return
    for warehouse in warehouses:
        if warehouse is not None and warehouse.pk not in allowed:
            raise PermissionDenied("当前账号没有该仓库的操作权限。")


def _require_serializer_warehouse_access(request, organization, serializer):
    values = serializer.validated_data
    _require_warehouse_access(
        request,
        organization,
        values.get("warehouse"),
        values.get("source_warehouse"),
        values.get("destination_warehouse"),
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return Response({"status": "ok", "database": "ok"})


@api_view(["GET"])
def profit_calculator_config(request):
    """Expose versioned fee rules without relying on another calculator site."""
    return Response({
        "countries": [{"code": "MY", "label": "马来西亚", "currency": "MYR"}],
        "shop_identities": [
            {"code": "marketplace", "label": "Marketplace"},
            {"code": "mall", "label": "Mall"},
        ],
        "categories": category_config(),
        "category_tree": category_tree(),
        "transaction_rate": str(TRANSACTION_RATE),
        "platform_support_fee": str(PLATFORM_SUPPORT_FEE),
        "lvg_rate": str(LVG_RATE),
        "rule_effective_date": str(RULE_EFFECTIVE_DATE),
        "sources": {
            "commission": COMMISSION_SOURCE,
            "transaction": TRANSACTION_SOURCE,
            "affiliate": AFFILIATE_SOURCE,
            "platform_support": SUPPORT_FEE_SOURCE,
            "shipping": SHIPPING_SOURCE,
            "shipping_calculation": SHIPPING_CALCULATION_SOURCE,
            "lvg_tax": LVG_TAX_SOURCE,
        },
    })


@api_view(["GET"])
def profit_exchange_rates(request):
    """Return one daily MYR conversion snapshot derived from ECB reference rates."""
    force_refresh = request.query_params.get("refresh") == "1"
    if not force_refresh:
        cached = cache.get(ECB_DAILY_RATES_CACHE_KEY)
        if cached:
            return Response(cached)

    try:
        upstream_request = Request(
            ECB_DAILY_RATES_URL,
            headers={"Accept": "application/xml", "User-Agent": "DongboERP/1.0"},
        )
        with urlopen(upstream_request, timeout=6) as response:
            result = _parse_ecb_daily_rates(response.read())
        cache.set(ECB_DAILY_RATES_CACHE_KEY, result, timeout=60 * 60 * 24)
        cache.set(ECB_LAST_GOOD_RATES_CACHE_KEY, result, timeout=60 * 60 * 24 * 30)
        return Response(result)
    except Exception:
        logger.exception("Unable to refresh ECB exchange rates")
        fallback = cache.get(ECB_LAST_GOOD_RATES_CACHE_KEY)
        if fallback:
            return Response({**fallback, "stale": True})
        return Response(
            {"detail": "Daily exchange rates are temporarily unavailable; use the manual rate mode."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(["POST"])
def profit_calculator_calculate(request):
    serializer = ProfitCalculationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response(calculate_profit(serializer.validated_data))


def _selection_rate_limit(request, action, limit, seconds):
    organization = request_organization(request)
    bucket = int(timezone.now().timestamp()) // seconds
    key = f"selection-rate:{organization.pk}:{request.user.pk}:{action}:{bucket}"
    if cache.add(key, 1, timeout=seconds + 5):
        return
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds + 5)
        count = 1
    if count > limit:
        raise Throttled(wait=seconds, detail="选品查询过于频繁，请稍后再试，避免重复消耗接口额度。")


class ProductSelectionStatusView(APIView):
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def get(self, request):
        organization = request_organization(request)
        return Response({
            **alphashop.configuration_status(organization),
            "platform_regions": {key: list(value) for key, value in alphashop.PLATFORM_REGIONS.items()},
            "listing_times": list(alphashop.LISTING_TIMES),
            "defaults": {"platform": "tiktok", "region": "MY", "listing_time": "90"},
        })


class AlphaShopConfigurationView(APIView):
    """Owner-only singleton configuration for the selection service.

    The serializer exposes only boolean key-presence flags.  Raw credentials
    are accepted as write-only fields, encrypted before persistence, and never
    copied into audit records.
    """

    permission_classes = [OrganizationRolePermission]
    owner_only = True

    def get(self, request):
        organization = request_organization(request)
        config = AlphaShopConfig.objects.filter(organization=organization).first()
        if config is not None:
            data = AlphaShopConfigSerializer(config, context={"request": request}).data
            data.update(alphashop.configuration_status(organization))
            return Response(data)
        status_payload = alphashop.configuration_status(organization)
        return Response({
            "configured": status_payload["configured"],
            "source": status_payload["source"],
            "configuration_error": status_payload["configuration_error"],
            "has_access_key": False,
            "has_secret_key": False,
            "api_base_url": "https://api.alphashop.cn",
            "enabled": True,
        })

    @transaction.atomic
    def put(self, request):
        organization = request_organization(request)
        config = AlphaShopConfig.objects.filter(organization=organization).first()
        serializer = AlphaShopConfigSerializer(
            config,
            data=request.data,
            partial=config is not None,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        if config is None:
            config = serializer.save(organization=organization, configured_by=request.user, last_configured_at=now)
            action = "alphashop.config.create"
        else:
            config = serializer.save(configured_by=request.user, last_configured_at=now)
            action = "alphashop.config.update"
        write_audit(
            organization=organization,
            actor=request.user,
            action=action,
            instance=config,
            after={"enabled": config.enabled, "api_base_url": config.api_base_url, "credentials_saved": True},
        )
        bump_sync_revision(organization_id=organization.pk)
        data = AlphaShopConfigSerializer(config, context={"request": request}).data
        data.update(alphashop.configuration_status(organization))
        return Response(data)


class AlphaShopConfigurationTestView(APIView):
    """Owner-triggered connection test; saved credentials never leave the server."""

    permission_classes = [OrganizationRolePermission]
    owner_only = True

    def post(self, request):
        organization = request_organization(request)
        try:
            result = alphashop.test_connection(organization=organization)
        except alphashop.AlphaShopError as exc:
            payload = {"ok": False, "code": exc.code, "detail": exc.detail}
            if exc.upstream_status:
                payload["upstream_status"] = exc.upstream_status
            return Response(payload, status=exc.status_code)
        except Exception:
            diagnostic_id = uuid.uuid4().hex[:12]
            logger.exception("Unexpected AlphaShop connection test error diagnostic_id=%s", diagnostic_id)
            return Response({
                "ok": False,
                "code": "ALPHASHOP_UNEXPECTED_ERROR",
                "detail": "选品接口测试暂时失败，详细诊断已安全写入服务器日志。",
                "diagnostic_id": diagnostic_id,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        config = AlphaShopConfig.objects.filter(organization=organization).first()
        if config is not None:
            write_audit(
                organization=organization,
                actor=request.user,
                action="alphashop.config.test",
                instance=config,
                after={"result": "success", "keyword_count": result["keyword_count"]},
            )
        return Response(result)


class ProductSelectionKeywordView(APIView):
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def post(self, request):
        organization = request_organization(request)
        serializer = ProductSelectionKeywordInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        regions = alphashop.PLATFORM_REGIONS.get(values["platform"], ())
        if values["region"] not in regions:
            raise ValidationError({"region": "该平台暂不支持这个国家或地区。"})
        _selection_rate_limit(request, "keywords", 30, 60)
        try:
            return Response(alphashop.search_keywords(**values, organization=organization))
        except alphashop.AlphaShopError as exc:
            payload = {"code": exc.code, "detail": exc.detail}
            if exc.upstream_status:
                payload["upstream_status"] = exc.upstream_status
            return Response(payload, status=exc.status_code)
        except Exception:
            diagnostic_id = uuid.uuid4().hex[:12]
            logger.exception("Unexpected product selection keyword error diagnostic_id=%s", diagnostic_id)
            return Response({
                "code": "ALPHASHOP_UNEXPECTED_ERROR",
                "detail": "选品查询暂时失败。请检查选品接口配置后重试；详细诊断已安全写入服务器日志。",
                "diagnostic_id": diagnostic_id,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class ProductSelectionReportView(APIView):
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def post(self, request):
        organization = request_organization(request)
        serializer = ProductSelectionReportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        regions = alphashop.PLATFORM_REGIONS.get(values["platform"], ())
        if values["region"] not in regions:
            raise ValidationError({"region": "该平台暂不支持这个国家或地区。"})
        _selection_rate_limit(request, "report", 10, 3600)
        try:
            return Response(alphashop.generate_report(**values, organization=organization))
        except alphashop.AlphaShopError as exc:
            payload = {"code": exc.code, "detail": exc.detail}
            if exc.upstream_status:
                payload["upstream_status"] = exc.upstream_status
            return Response(payload, status=exc.status_code)
        except Exception:
            diagnostic_id = uuid.uuid4().hex[:12]
            logger.exception("Unexpected product selection report error diagnostic_id=%s", diagnostic_id)
            return Response({
                "code": "ALPHASHOP_UNEXPECTED_ERROR",
                "detail": "选品报告暂时失败。请检查选品接口或大模型配置后重试；详细诊断已安全写入服务器日志。",
                "diagnostic_id": diagnostic_id,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET"])
def sync_version(request):
    """Return a cheap revision token; browsers only load full state when it changes."""
    organization = request_organization(request)
    state, _ = OrganizationSyncState.objects.get_or_create(organization=organization, defaults={"revision": 1})
    return Response({"revision": state.revision, "updated_at": state.updated_at})


@api_view(["GET"])
def me(request):
    organization = ensure_internal_organization(request.user) if is_owner(request.user) else internal_organization()
    membership = active_internal_membership(request.user)
    if membership is None and is_owner(request.user):
        membership = active_internal_membership(request.user)
    memberships = [membership] i…14097 tokens truncated…_order_id):
                raise ValidationError("幂等键已被其他退货操作占用")
            try:
                incoming = sorted(
                    (
                        str(line.get("sku", "")),
                        Decimal(str(line.get("quantity_expected", "0"))),
                        str(line.get("condition", "restock")),
                    )
                    for line in request.data.get("lines", [])
                )
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValidationError("退货明细格式不正确") from exc
            recorded = sorted(
                (str(line.sku_id), line.quantity_expected, line.condition)
                for line in existing.return_order.lines.all()
            )
            if incoming != recorded:
                raise ValidationError("幂等键对应的退货明细不一致")
            return Response(self.get_serializer(existing.return_order).data)

        payload = request.data.copy()
        payload.pop("idempotency_key", None)
        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        return_order = _save_serializer(serializer, organization=organization)
        return_order = _service_call(
            receive_return,
            return_order=return_order,
            quantities=[
                {"return_line": line, "quantity": line.quantity_expected}
                for line in return_order.lines.all()
            ],
            idempotency_key=idempotency_key,
            actor=request.user,
        )
        return Response(self.get_serializer(return_order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        data = ReturnReceiveInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        return_order = _service_call(
            receive_return, return_order=self.get_object(), quantities=values["lines"],
            idempotency_key=values["idempotency_key"], actor=request.user,
        )
        return Response(self.get_serializer(return_order).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return_order = _service_call(
            reject_return, return_order=self.get_object(), actor=request.user
        )
        return Response(self.get_serializer(return_order).data)

    def perform_destroy(self, instance):
        if instance.status != ReturnOrder.Status.REQUESTED or instance.receipts.exists():
            raise ValidationError("已开始收货的退货单不可删除")
        instance.delete()


class CompetitorProductViewSet(OrganizationScopedViewSet):
    queryset = CompetitorProduct.objects.order_by("name", "id")
    serializer_class = CompetitorProductSerializer
    capability = "catalog"

    @action(detail=False, methods=["post"], url_path="add-own-products")
    @transaction.atomic
    def add_own_products(self, request):
        """Create (or reactivate) monitoring profiles for existing own products.

        The product master, its SKU records and warehouse balances are deliberately
        left untouched.  This endpoint only manages the separate monitoring profile.
        """
        raw_ids = request.data.get("product_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ValidationError({"product_ids": "请至少选择一个本店商品。"})
        product_ids = [str(item) for item in raw_ids if str(item).strip()]
        if not product_ids:
            raise ValidationError({"product_ids": "请至少选择一个本店商品。"})

        organization = self.get_organization()
        products = list(
            Product.objects.filter(organization=organization, pk__in=product_ids)
            .prefetch_related("images")
            .order_by("name", "id")
        )
        found_ids = {str(product.pk) for product in products}
        missing_ids = [product_id for product_id in product_ids if product_id not in found_ids]
        if missing_ids:
            raise ValidationError({"product_ids": "包含不存在或无权访问的本店商品。"})

        created = []
        reactivated = []
        profiles = []
        for product in products:
            image = next(iter(product.images.all()), None)
            # ProductImage can temporarily contain a browser-side data URL.  A
            # monitoring profile stores only a real URL, so never copy that
            # value into the URL field (and never make adding a product fail
            # because an old product image has not been uploaded yet).
            image_url = str(image.url or "") if image else ""
            if not image_url.startswith(("https://", "http://")):
                image_url = ""
            defaults = {
                "name": product.name,
                "kind": CompetitorProduct.Kind.DIRECT,
                "platform": "own",
                "market": product.market,
                "url": product.source_url,
                "image_url": image_url,
                "seller": product.seller,
                "currency": product.sales_currency,
                "active": True,
            }
            profile, was_created = CompetitorProduct.objects.get_or_create(
                organization=organization,
                linked_product=product,
                defaults=defaults,
            )
            changed = False
            if not profile.active:
                profile.active = True
                changed = True
            if changed:
                profile.save(update_fields=["active", "updated_at"])
                reactivated.append(str(product.pk))
            if was_created:
                created.append(str(product.pk))
            if not product.monitoring_enabled:
                product.monitoring_enabled = True
                product.save(update_fields=["monitoring_enabled", "updated_at"])
            profiles.append(profile)

        write_audit(
            organization=organization,
            actor=request.user,
            action="competitor.add_own_products",
            instance=profiles[0],
            after={"product_ids": [str(product.pk) for product in products], "created": created, "reactivated": reactivated},
        )
        bump_sync_revision(organization_id=organization.pk)
        return Response({
            "created_product_ids": created,
            "reactivated_product_ids": reactivated,
            "profiles": self.get_serializer(profiles, many=True).data,
        }, status=status.HTTP_200_OK)

    @transaction.atomic
    def perform_destroy(self, instance):
        # A monitoring profile is independent from the own-store product.  Deleting
        # it removes its snapshots but must never delete the linked Product, SKU or
        # warehouse data.
        linked_product = instance.linked_product
        snapshot_count = instance.snapshots.count()
        before = {
            "name": instance.name,
            "linked_product_id": str(linked_product.pk) if linked_product else "",
            "snapshot_count": snapshot_count,
        }
        if linked_product is not None and linked_product.monitoring_enabled:
            linked_product.monitoring_enabled = False
            linked_product.save(update_fields=["monitoring_enabled", "updated_at"])
        organization = instance.organization
        write_audit(
            organization=organization,
            actor=self.request.user,
            action="competitor.delete",
            instance=instance,
            before=before,
        )
        instance.delete()
        bump_sync_revision(organization_id=organization.pk)


class CompetitorSnapshotViewSet(viewsets.ModelViewSet):
    serializer_class = CompetitorSnapshotSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def get_queryset(self):
        return CompetitorSnapshot.objects.filter(product__organization=request_organization(self.request))

    def perform_create(self, serializer):
        organization = request_organization(self.request)
        if serializer.validated_data["product"].organization_id != organization.id:
            raise ValidationError("竞品不属于当前组织")
        _save_serializer(serializer)

    def perform_update(self, serializer):
        _save_serializer(serializer)

    @action(detail=False, methods=["post"], url_path="quick-sales")
    def quick_sales(self, request):
        data = QuickSalesSnapshotInputSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        data.is_valid(raise_exception=True)
        snapshot = _service_call(
            create_quick_sales_snapshot,
            actor=request.user,
            **data.validated_data,
        )
        return Response(self.get_serializer(snapshot).data, status=status.HTTP_201_CREATED)


class TikTokShopConnectionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = TikTokShopConnection.objects.select_related("authorized_by").order_by("-authorized_at", "id")
    serializer_class = TikTokShopConnectionSerializer
    permission_classes = [OrganizationRolePermission]
    owner_only = True
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))

    @action(detail=False, methods=["post"], url_path="authorize")
    def authorize(self, request):
        data = TikTokAuthorizationStartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        authorization_url = integrations.begin_tiktok_authorization(
            organization=request_organization(request), actor=request.user, region=data.validated_data["region"]
        )
        return Response({"authorization_url": authorization_url})

    @action(detail=True, methods=["post"], url_path="refresh")
    def refresh(self, request, pk=None):
        connection = integrations.refresh_tiktok_connection(self.get_object())
        write_audit(organization=connection.organization, actor=request.user, action="tiktok.connection.refresh", instance=connection)
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"], url_path="disconnect")
    def disconnect(self, request, pk=None):
        connection = integrations.disconnect_tiktok_connection(self.get_object())
        write_audit(organization=connection.organization, actor=request.user, action="tiktok.connection.disconnect", instance=connection)
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"], url_path="sync")
    def sync(self, request, pk=None):
        data = TikTokSyncStartSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        connection = self.get_object()
        if connection.status != TikTokShopConnection.Status.CONNECTED:
            raise ValidationError("店铺未处于已授权状态，不能发起同步")
        run = TikTokShopSyncRun.objects.create(
            organization=connection.organization, connection=connection, resource=data.validated_data["resource"],
            requested_by=request.user, summary={"note": "已预留同步任务；请接入队列 worker 后执行实际同步"},
        )
        return Response(TikTokShopSyncRunSerializer(run).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
@transaction.atomic
def tiktok_shop_oauth_callback(request):
    if request.query_params.get("error") or not request.query_params.get("code"):
        return Response({"detail": "TikTok Shop 授权未完成", "error": request.query_params.get("error", "auth_denied")}, status=status.HTTP_400_BAD_REQUEST)
    try:
        connections = integrations.complete_tiktok_authorization(
            state=str(request.query_params.get("state", "")), auth_code=str(request.query_params["code"])
        )
    except (DjangoValidationError, IntegrityError) as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else getattr(exc, "messages", [str(exc)])) from exc
    return Response({
        "detail": f"TikTok Shop 店铺授权成功，已连接 {len(connections)} 个店铺，可以关闭此页面返回 ERP",
        "connection_ids": [str(connection.pk) for connection in connections],
    })


class AIProviderConfigViewSet(OrganizationScopedViewSet):
    queryset = AIProviderConfig.objects.all().order_by("name", "id")
    serializer_class = AIProviderConfigSerializer
    owner_only = True

    @action(detail=True, methods=["post"], url_path="test")
    def test_connection(self, request, pk=None):
        provider = self.get_object()
        result, log = integrations.invoke_ai(
            provider=provider, feature="connection_test", actor=request.user,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        )
        return Response({"detail": "连接成功", "log_id": str(log.pk), "model": result.get("model", provider.model_name)})


class AIInvocationLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AIInvocationLog.objects.select_related("provider", "requested_by")
    serializer_class = AIInvocationLogSerializer
    permission_classes = [OrganizationRolePermission]
    owner_only = True
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))


class AIRecommendationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AIRecommendation.objects.select_related("provider", "confirmed_by")
    serializer_class = AIRecommendationSerializer
    permission_classes = [OrganizationRolePermission]
    owner_only = True
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))

    def create(self, request, *args, **kwargs):
        data = AIRecommendationInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        recommendation = integrations.create_ai_recommendation(
            provider=data.validated_data["provider"], kind=data.validated_data["kind"],
            input_data=data.validated_data["input_data"], actor=request.user,
        )
        return Response(self.get_serializer(recommendation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="confirm")
    @transaction.atomic
    def confirm(self, request, pk=None):
        data = AIRecommendationConfirmationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        recommendation = AIRecommendation.objects.select_for_update().get(pk=self.get_object().pk)
        if recommendation.status != AIRecommendation.Status.PROPOSED:
            raise ValidationError("该 AI 建议已处理，不能重复确认")
        # Confirmation records the user's decision only.  It intentionally does not post stock.
        recommendation.status = AIRecommendation.Status.CONFIRMED
        recommendation.confirmed_by = request.user
        recommendation.confirmed_at = timezone.now()
        recommendation.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
        write_audit(
            organization=recommendation.organization, actor=request.user, action="ai.recommendation.confirm", instance=recommendation,
            after={"kind": recommendation.kind, "reason": data.validated_data["reason"], "inventory_posted": False},
        )
        return Response(self.get_serializer(recommendation).data)

    @action(detail=True, methods=["post"], url_path="reject")
    @transaction.atomic
    def reject(self, request, pk=None):
        data = AIRecommendationConfirmationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        recommendation = AIRecommendation.objects.select_for_update().get(pk=self.get_object().pk)
        if recommendation.status != AIRecommendation.Status.PROPOSED:
            raise ValidationError("该 AI 建议已处理，不能重复拒绝")
        recommendation.status = AIRecommendation.Status.REJECTED
        recommendation.rejection_reason = data.validated_data["reason"]
        recommendation.save(update_fields=["status", "rejection_reason", "updated_at"])
        write_audit(
            organization=recommendation.organization,
            actor=request.user,
            action="ai.recommendation.reject",
            instance=recommendation,
            after={"kind": recommendation.kind, "reason": recommendation.rejection_reason, "inventory_posted": False},
        )
        return Response(self.get_serializer(recommendation).data)


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "audit"
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))


class LocalImportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = LocalImport.objects.select_related("warehouse", "imported_by")
    serializer_class = LocalImportSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "data"
    organization = None

    def get_organization(self):
        return self.organization or request_organization(self.request)

    def get_queryset(self):
        return self.queryset.filter(organization=self.get_organization())

    def _warehouse(self, request):
        warehouse_id = request.data.get("warehouse")
        try:
            return Warehouse.objects.get(
                pk=warehouse_id,
                organization=self.get_organization(),
                active=True,
            )
        except (Warehouse.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError({"warehouse": "目标仓库不存在或已停用"}) from exc

    @action(detail=False, methods=["post"])
    def validate(self, request):
        preview = validate_local_import(
            organization=self.get_organization(),
            warehouse=self._warehouse(request),
            source=request.data.get("source"),
        )
        return Response(preview)

    @action(detail=False, methods=["post"])
    def commit(self, request):
        idempotency_key = str(request.data.get("idempotency_key", "")).strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "该字段不能为空"})
        try:
            report = _service_call(
                commit_local_import,
                organization=self.get_organization(),
                warehouse=self._warehouse(request),
                source=request.data.get("source"),
                idempotency_key=idempotency_key,
                actor=request.user,
            )
        except IntegrityError as exc:
            raise DataConflict("该备份已导入或导入任务发生冲突") from exc
        return Response(self.get_serializer(report).data, status=status.HTTP_201_CREATED)

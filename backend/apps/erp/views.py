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
    AIInvocationLog, AIProviderConfig, AIRecommendation, AlphaShopConfig, AuditLog, CompetitorProduct, CompetitorSnapshot, ExchangeRateSnapshot, Membership, Organization, OrganizationSyncState, OwnerEmailChallenge, OwnStore, ProfitCalculationStrategy, ProfitCalculationWorkingConfig,
    LocalImport, Product, ProductImage, PurchaseOrder, PurchaseOrderLine, PurchaseShipment, Receipt, ReceiptLine, ReplenishmentAIJob, ReplenishmentConversionEvent, ReplenishmentPolicy, ReplenishmentSettings,
    ReturnLine, ReturnOrder, ReturnReceipt, ReturnReceiptLine, SalesOrder, SalesOrderLine, Shipment, ShipmentLine,
    SKU, StockBalance, StockLedger, StockLedgerReversal, StockReservation, StockTransfer, StockTransferLine, StockTransferPackage, ReplenishmentRecommendation, StoreProduct, Supplier, TikTokShopConnection, TikTokShopSyncRun, UploadedMediaAsset, Warehouse,
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
    CompetitorProductSerializer, CompetitorSnapshotSerializer, InternalAccountSerializer, MembershipSerializer, OwnStoreSerializer, StoreProductSerializer,
    ConfirmAndShipInputSerializer, LocalImportSerializer, OrganizationSerializer, OrderWarehouseInputSerializer,
    ProductImageSerializer, ProductSerializer, QuickSalesSnapshotInputSerializer, UploadedMediaAssetSerializer,
    PurchaseOrderEditInputSerializer, PurchaseOrderSerializer, PurchaseShipmentSerializer, PurchaseStageCloseInputSerializer, ReceiptSerializer, ReceiveInputSerializer,
    ReplenishmentPolicySerializer, ReplenishmentRecommendationQuerySerializer, ReplenishmentSettingsSerializer, ReplenishmentRecommendationSerializer,
    ReturnOrderSerializer, ReturnReceiveInputSerializer, SalesOrderSerializer,
    ShipmentSerializer, ShipInputSerializer, SKUSerializer, StockBalanceSerializer,
    StockLedgerReversalInputSerializer, StockLedgerSerializer, StockTransferSerializer, SupplierSerializer,
    ManualStockMovementInputSerializer, TikTokAuthorizationStartSerializer, TikTokShopConnectionSerializer, TikTokShopSyncRunSerializer, TikTokSyncStartSerializer,
    TransferExceptionCloseInputSerializer, TransferPostInputSerializer, TransferReceiveInputSerializer, WarehouseSerializer,
    ProductSelectionKeywordInputSerializer, ProductSelectionReportInputSerializer, ProfitCalculationStrategySerializer, ProfitCalculationWorkingConfigSerializer,
    StockTransferPackageSerializer, TransferPackagesInputSerializer,
)
from . import alphashop, integrations
from .services import (
    adjust_inventory, allocate_order, assign_order_warehouse, cancel_order, cancel_purchase, cancel_stock_transfer,
    confirm_and_ship_order, confirm_and_ship_or_shortage, confirm_order, create_quick_sales_snapshot,
    change_order_warehouse, close_purchase_transit_exception, close_purchase_unshipped, close_stock_transfer_exception, confirm_purchase_shipment, dispatch_stock_transfer, edit_purchase, manual_stock_movement, receive_purchase, receive_return, receive_stock_transfer, reverse_stock_ledger, reserve_stock_transfer_draft,
    reject_return, restore_order_fulfillment, save_stock_transfer_packages, ship_order, start_picking, submit_purchase, update_stock_transfer_package_tracking, verify_order, write_audit,
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
from .profit_shipping_rates import (
    MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE,
    MALAYSIA_CROSS_BORDER_MAX_G,
    MALAYSIA_CROSS_BORDER_RATE_VERSION,
    MALAYSIA_CROSS_BORDER_SOURCE_FILE,
    MALAYSIA_STANDARD_BUYER_SHIPPING,
    MALAYSIA_STANDARD_BUYER_SHIPPING_EFFECTIVE_DATE,
    MALAYSIA_STANDARD_BUYER_SHIPPING_RATE_VERSION,
)
from .exchange_rates import record_refresh_failure, refresh_snapshot, save_snapshot, snapshot_payload
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
        if hasattr(exc, "payload"):
            raise ValidationError(exc.payload)
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    except IntegrityError as exc:
        raise DataConflict() from exc


def _require_capability(request, capability, message="当前账号没有执行此操作的权限"):
    if is_owner(request.user):
        return
    membership = active_internal_membership(request.user)
    if membership is None or capability not in membership_permissions(membership):
        raise PermissionDenied(message)


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
    _require_capability(request, "profit_rules", "当前账号没有查看利润规则权限")
    return Response({
        "countries": [{"code": "MY", "label": "马来西亚", "currency": "MYR"}],
        "shop_identities": [
            {"code": "marketplace", "label": "Marketplace"},
            {"code": "mall", "label": "Mall"},
        ],
        "categories": category_config(),
        "category_tree": category_tree(),
        "transaction_rate": str(TRANSACTION_RATE),
        "transaction_fee_adjustment_default": "0.00",
        "buyer_shipping": {
            "rate_version": MALAYSIA_STANDARD_BUYER_SHIPPING_RATE_VERSION,
            "effective_date": MALAYSIA_STANDARD_BUYER_SHIPPING_EFFECTIVE_DATE,
            "default_region": "west_malaysia",
            "standard_rates": {key: str(value) for key, value in MALAYSIA_STANDARD_BUYER_SHIPPING.items()},
        },
        "default_commission_adjustment": "1.00",
        "platform_support_fee": str(PLATFORM_SUPPORT_FEE),
        "lvg_rate": str(LVG_RATE),
        "shipping_rate_version": MALAYSIA_CROSS_BORDER_RATE_VERSION,
        "shipping_effective_date": MALAYSIA_CROSS_BORDER_EFFECTIVE_DATE,
        "shipping_source_file": MALAYSIA_CROSS_BORDER_SOURCE_FILE,
        "shipping_max_weight_g": str(MALAYSIA_CROSS_BORDER_MAX_G),
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


@api_view(["GET", "PUT"])
def profit_calculator_working_config(request):
    """Read/write the organization shared, unnamed profit-calculation workspace."""
    _require_capability(request, "profit_rules", "当前账号没有使用利润试算配置的权限")
    organization = request_organization(request)
    record = ProfitCalculationWorkingConfig.objects.filter(organization=organization).select_related("updated_by").first()
    if request.method == "GET":
        if record is not None:
            return Response(ProfitCalculationWorkingConfigSerializer(record).data)
        fallback = ProfitCalculationStrategy.objects.filter(organization=organization, is_default=True).first()
        return Response({
            "id": None,
            "config": fallback.config if fallback else {},
            "rate_mode": "auto",
            "manual_cny_per_myr": None,
            "manual_usd_per_myr": None,
            "updated_by_name": None,
            "updated_at": None,
        })
    _require_capability(request, "profit_rules", "当前账号没有修改利润试算配置的权限")
    with transaction.atomic():
        record, _ = ProfitCalculationWorkingConfig.objects.select_for_update().get_or_create(
            organization=organization
        )
        serializer = ProfitCalculationWorkingConfigSerializer(record, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        saved = serializer.save(
            updated_by=request.user,
            config=_profit_strategy_config(serializer.validated_data.get("config", record.config)),
        )
        write_audit(
            organization=organization, actor=request.user, action="profit_calculator.working_config.save",
            instance=saved, after={"rate_mode": saved.rate_mode},
        )
        bump_sync_revision(organization_id=organization.pk)
    return Response(ProfitCalculationWorkingConfigSerializer(saved).data)


@api_view(["GET", "POST"])
def profit_exchange_rates(request):
    """Return or refresh one durable, atomic MYR/CNY+MYR/USD snapshot."""
    organization = request_organization(request)
    if request.method == "POST":
        _require_capability(request, "exchange_manual", "当前账号没有修改手动汇率权限")
        try:
            snapshot = save_snapshot(
                organization=organization, effective_date=timezone.localdate(),
                cny=Decimal(str(request.data["cny_per_myr"])), usd=Decimal(str(request.data["usd_per_myr"])),
                source="Manual", source_url="", summary="owner supplied rates", manual=True,
            )
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise ValidationError("请填写有效的 MYR/CNY 与 MYR/USD 汇率") from exc
        write_audit(organization=organization, actor=request.user, action="exchange_rate.manual", instance=snapshot, after={"snapshot_id": str(snapshot.pk)})
        return Response(snapshot_payload(snapshot))
    force_refresh = request.query_params.get("refresh") == "1"
    if force_refresh:
        _require_capability(request, "exchange", "当前账号没有刷新汇率权限")
    current = ExchangeRateSnapshot.objects.filter(organization=organization, is_current=True).first()
    if current and not force_refresh:
        return Response(snapshot_payload(current))
    snapshot, failures = refresh_snapshot(organization)
    if snapshot:
        source_changed = current is not None and current.source != snapshot.source
        write_audit(
            organization=organization, actor=request.user,
            action="exchange_rate.source_switch" if source_changed else "exchange_rate.refresh",
            instance=snapshot,
            before={"source": current.source, "snapshot_id": str(current.pk)} if current else {},
            after={"source": snapshot.source, "snapshot_id": str(snapshot.pk), "failures": failures},
        )
        return Response(snapshot_payload(snapshot, failures=failures))
    fallback = ExchangeRateSnapshot.objects.filter(organization=organization, validation_status__in=("valid", "manual")).first()
    if fallback:
        record_refresh_failure(fallback, failures)
        write_audit(organization=organization, actor=request.user, action="exchange_rate.history_fallback", instance=fallback, after={"failures": failures})
        return Response(snapshot_payload(fallback, fallback=True, failures=failures))
    return Response({"detail": "汇率来源暂时不可用，数据库中也没有历史有效快照", "failures": failures}, status=503)


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
    memberships = [membership] if membership is not None and organization is not None else []
    permissions = sorted(PERMISSION_CATALOG) if is_owner(request.user) else sorted(
        membership_permissions(membership) if membership is not None else []
    )
    return Response({
        "user": {
            "id": request.user.pk,
            "username": request.user.get_username(),
            "display_name": ((membership.display_name if membership else "") or request.user.get_username()),
            "email": request.user.email,
            "is_owner": is_owner(request.user),
        },
        "permissions": permissions,
        "email_verification_enabled": email_verification_enabled() if is_owner(request.user) else False,
        "memberships": [
            {
                "id": str(membership.pk),
                "organization": {
                    "id": str(membership.organization_id),
                    "name": membership.organization.name,
                    "slug": membership.organization.slug,
                },
                "role": membership.role,
            }
            for membership in memberships
        ],
    })


def _require_owner(request):
    if not is_owner(request.user):
        raise PermissionDenied("只有主账号可以管理内部账号")
    return ensure_internal_organization(request.user)


def _account_payload(membership):
    user = membership.user
    return {
        "id": str(membership.pk),
        "user_id": user.pk,
        "username": user.get_username(),
        "display_name": membership.display_name or user.get_username(),
        "role": membership.role,
        "active": bool(membership.active and user.is_active),
        "permissions": sorted(membership_permissions(membership)),
        "warehouse_ids": [str(pk) for pk in membership.authorized_warehouses.values_list("pk", flat=True)],
        "warehouses": [
            {"id": str(warehouse.pk), "name": warehouse.name, "code": warehouse.code}
            for warehouse in membership.authorized_warehouses.order_by("code", "id")
        ],
        "is_owner": bool(user.is_superuser),
        "last_login": user.last_login,
        "created_at": membership.created_at,
    }


@api_view(["GET", "POST"])
def internal_accounts(request):
    organization = _require_owner(request)
    if request.method == "GET":
        memberships = Membership.objects.filter(organization=organization).select_related("user").order_by(
            "user__is_superuser", "user__username", "id"
        )
        return Response({
            "permission_catalog": PERMISSION_CATALOG,
            "roles": {key: value for key, value in Membership.Role.choices},
            "warehouses": [
                {"id": str(warehouse.pk), "name": warehouse.name, "code": warehouse.code, "active": warehouse.active}
                for warehouse in Warehouse.objects.filter(organization=organization).order_by("code", "id")
            ],
            "accounts": [_account_payload(membership) for membership in memberships],
        })

    serializer = InternalAccountSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if not data.get("password"):
        raise ValidationError({"password": "请设置子账号的初始密码"})
    user_model = get_user_model()
    if user_model.objects.filter(username=data["username"]).exists():
        raise ValidationError({"username": "该账号名已被使用"})
    try:
        validate_password(data["password"])
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from exc
    with transaction.atomic():
        warehouse_ids = data.get("warehouse_ids", [])
        warehouses = list(Warehouse.objects.filter(organization=organization, pk__in=warehouse_ids))
        if len(warehouses) != len(set(warehouse_ids)):
            raise ValidationError({"warehouse_ids": "存在不属于当前组织的仓库。"})
        user = user_model.objects.create_user(
            username=data["username"],
            password=data["password"],
            is_active=data.get("active", True),
        )
        role = data.get("role", Membership.Role.VIEWER)
        permissions = data.get("permissions", [])
        membership = Membership.objects.create(
            organization=organization,
            user=user,
            role=role,
            display_name=data.get("display_name", "").strip(),
            permissions=permissions,
            active=data.get("active", True),
        )
        membership.authorized_warehouses.set(warehouses)
        write_audit(
            organization=organization,
            actor=request.user,
            action="account.create",
            instance=membership,
            after={"username": user.username, "display_name": membership.display_name, "role": membership.role, "permissions": sorted(membership_permissions(membership)), "warehouse_ids": [str(item.pk) for item in warehouses], "active": membership.active},
        )
    bump_sync_revision(organization_id=organization.pk)
    return Response(_account_payload(membership), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
def internal_account_detail(request, membership_id):
    organization = _require_owner(request)
    try:
        membership = Membership.objects.select_related("user").get(pk=membership_id, organization=organization)
    except (Membership.DoesNotExist, ValueError) as exc:
        raise NotFound("子账号不存在") from exc
    if membership.user.is_superuser:
        raise PermissionDenied("主账号不能在此处修改，请使用主账号安全设置")
    if request.method == "DELETE":
        membership.active = False
        membership.user.is_active = False
        membership.active = False
        membership.save(update_fields=["active", "updated_at"])
        membership.user.save(update_fields=["is_active"])
        write_audit(
            organization=organization,
            actor=request.user,
            action="account.disable",
            instance=membership,
            after={"username": membership.user.username, "active": False},
        )
        bump_sync_revision(organization_id=organization.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = InternalAccountSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if "username" in data and data["username"] != membership.user.username:
        if get_user_model().objects.exclude(pk=membership.user_id).filter(username=data["username"]).exists():
            raise ValidationError({"username": "该账号名已被使用"})
        membership.user.username = data["username"]
    if "password" in data:
        try:
            validate_password(data["password"], membership.user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc
        membership.user.set_password(data["password"])
    if "active" in data:
        membership.active = data["active"]
        membership.user.is_active = data["active"]
    if "permissions" in data:
        membership.permissions = data["permissions"]
    if "display_name" in data:
        membership.display_name = data["display_name"].strip()
    if "role" in data:
        membership.role = data["role"]
        if "permissions" not in data:
            membership.permissions = []
    with transaction.atomic():
        if "warehouse_ids" in data:
            warehouses = list(Warehouse.objects.filter(organization=organization, pk__in=data["warehouse_ids"]))
            if len(warehouses) != len(set(data["warehouse_ids"])):
                raise ValidationError({"warehouse_ids": "存在不属于当前组织的仓库。"})
            membership.authorized_warehouses.set(warehouses)
        membership.user.save()
        membership.save()
        write_audit(
            organization=organization,
            actor=request.user,
            action="account.update",
            instance=membership,
            after={"username": membership.user.username, "display_name": membership.display_name, "role": membership.role, "permissions": sorted(membership_permissions(membership)), "warehouse_ids": [str(item.pk) for item in membership.authorized_warehouses.all()], "active": membership.active},
        )
        bump_sync_revision(organization_id=organization.pk)
    return Response(_account_payload(membership))


@api_view(["GET"])
@permission_classes([OrganizationRolePermission])
def purchase_members(request):
    """Active organization members available as a purchaser on a PO."""
    organization = request_organization(request)
    memberships = Membership.objects.filter(
        organization=organization,
        active=True,
        user__is_active=True,
    ).select_related("user").order_by("display_name", "user__username", "id")
    return Response([
        {
            "user_id": item.user_id,
            "display_name": item.display_name or item.user.get_username(),
            "username": item.user.get_username(),
            "role": item.role,
        }
        for item in memberships
    ])


class InternalTokenObtainPairSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        "no_active_account": "账号名或密码错误，或账号已被停用",
    }

    def validate(self, attrs):
        data = super().validate(attrs)
        if is_owner(self.user) and email_verification_enabled():
            challenge = create_challenge(user=self.user, purpose=OwnerEmailChallenge.Purpose.LOGIN)
            return {
                "email_verification_required": True,
                "challenge_id": str(challenge.pk),
                "username": self.user.get_username(),
            }
        return data


class InternalTokenObtainPairView(TokenObtainPairView):
    serializer_class = InternalTokenObtainPairSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_owner_login(request):
    user = consume_challenge(
        challenge_id=request.data.get("challenge_id"),
        code=request.data.get("code"),
        purpose=OwnerEmailChallenge.Purpose.LOGIN,
    )
    refresh = RefreshToken.for_user(user)
    return Response({"refresh": str(refresh), "access": str(refresh.access_token)})


@api_view(["POST"])
@permission_classes([AllowAny])
def request_owner_password_reset(request):
    identifier = str(request.data.get("identifier", "")).strip()
    user_model = get_user_model()
    owner = user_model.objects.filter(is_superuser=True, is_active=True).filter(
        username=identifier
    ).first() or user_model.objects.filter(is_superuser=True, is_active=True, email__iexact=identifier).first()
    if owner is not None:
        create_challenge(user=owner, purpose=OwnerEmailChallenge.Purpose.PASSWORD_RESET)
    return Response({"detail": "如账号存在，验证码已发送至主账号邮箱"})


@api_view(["POST"])
@permission_classes([AllowAny])
def confirm_owner_password_reset(request):
    user = consume_challenge(
        challenge_id=request.data.get("challenge_id"),
        code=request.data.get("code"),
        purpose=OwnerEmailChallenge.Purpose.PASSWORD_RESET,
    )
    password = str(request.data.get("password", ""))
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from exc
    user.set_password(password)
    user.save(update_fields=["password"])
    return Response({"detail": "主账号密码已更新"})


@api_view(["POST"])
def request_owner_password_change(request):
    _require_owner(request)
    challenge = create_challenge(user=request.user, purpose=OwnerEmailChallenge.Purpose.PASSWORD_CHANGE)
    return Response({"challenge_id": str(challenge.pk), "detail": "验证码已发送至主账号邮箱"})


@api_view(["POST"])
def confirm_owner_password_change(request):
    _require_owner(request)
    user = consume_challenge(
        challenge_id=request.data.get("challenge_id"),
        code=request.data.get("code"),
        purpose=OwnerEmailChallenge.Purpose.PASSWORD_CHANGE,
    )
    if user.pk != request.user.pk:
        raise PermissionDenied("验证码不属于当前主账号")
    password = str(request.data.get("password", ""))
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from exc
    user.set_password(password)
    user.save(update_fields=["password"])
    return Response({"detail": "主账号密码已更新"})


@api_view(["GET"])
def replenishment_recommendations(request):
    organization = request_organization(request)
    query = ReplenishmentRecommendationQuerySerializer(
        data=request.query_params, context={"request": request}
    )
    query.is_valid(raise_exception=True)
    warehouse = query.validated_data["warehouse"]
    policies = {
        policy.sku_id: policy
        for policy in ReplenishmentPolicy.objects.filter(
            organization=organization, warehouse=warehouse
        )
    }
    settings, _ = ReplenishmentSettings.objects.get_or_create(organization=organization)
    default_policy = ForecastPolicy(
        safety_days=settings.safety_days,
        review_cycle_days=Decimal(settings.review_cycle_days),
        target_days=Decimal(settings.target_days),
        manual_lead_days=Decimal(warehouse.default_lead_time_days or 0),
        coverage_days=Decimal(warehouse.default_coverage_days) if warehouse.default_coverage_days is not None else None,
        service_level_factor=settings.service_level_factor,
        safety_margin_ratio=settings.safety_margin_ratio,
        initial_reference_shipment_count=settings.initial_reference_shipment_count,
    )
    weights = (settings.velocity_weight_3, settings.velocity_weight_7, settings.velocity_weight_15, settings.velocity_weight_30)
    recommendations = []
    skus = SKU.objects.filter(
        organization=organization,
        active=True,
        product__status=Product.Status.ACTIVE,
    ).select_related("product", "product__default_supplier").order_by("code", "id")
    for sku in skus:
        stored_policy = policies.get(sku.pk)
        if stored_policy is not None and not stored_policy.replenishment_enabled:
            continue
        lead_value = stored_policy.lead_time_override if stored_policy and stored_policy.lead_time_override is not None else warehouse.default_lead_time_days
        coverage_value = stored_policy.coverage_days if stored_policy and stored_policy.coverage_days is not None else warehouse.default_coverage_days
        if lead_value is None or coverage_value is None:
            recommendations.append({"warehouse": str(warehouse.pk), "sku": str(sku.pk), "sku_code": sku.code, "status": "missing_parameters", "reason": "缺少补货参数，请先配置仓库默认值或 SKU 单独参数"})
            continue
        forecast_policy = default_policy
        if stored_policy is not None:
            forecast_policy = ForecastPolicy(
                safety_days=default_policy.safety_days,
                review_cycle_days=Decimal(stored_policy.review_cycle_days),
                target_days=Decimal(stored_policy.target_days),
                coverage_days=Decimal(coverage_value),
                moq=stored_policy.min_order_qty,
                pack_size=stored_policy.pack_size,
                manual_lead_days=(
                    Decimal(lead_value)
                ),
                safety_stock_units=stored_policy.safety_stock_override,
                service_level_factor=settings.service_level_factor,
                safety_margin_ratio=default_policy.safety_margin_ratio,
                initial_reference_shipment_count=settings.initial_reference_shipment_count,
            )
        forecast = build_replenishment_forecast(
            organization=organization,
            sku=sku,
            warehouse=warehouse,
            supplier=sku.product.default_supplier,
            policy=forecast_policy,
            weights=weights,
        )
        recommendations.append({
            "warehouse": str(warehouse.pk),
            "sku": str(sku.pk),
            "sku_code": sku.code,
            "product": str(sku.product_id),
            "product_name": sku.product.name,
            "policy": str(stored_policy.pk) if stored_policy is not None else None,
            **asdict(forecast),
        })
    return Response(recommendations)


def _require_replenishment_write(request):
    organization = request_organization(request)
    membership = active_internal_membership(request.user)
    if not is_owner(request.user) and (membership is None or "replenishment" not in membership_permissions(membership)):
        raise PermissionDenied("当前账号没有补货管理权限")
    return organization


@api_view(["POST"])
def replenishment_batch_policy(request):
    """Apply only explicitly supplied fields to selected SKUs in the selected warehouse."""
    organization = _require_replenishment_write(request)
    payload = request.data if isinstance(request.data, dict) else {}
    warehouse_id = payload.get("warehouse")
    sku_ids = list(dict.fromkeys(str(value) for value in (payload.get("sku_ids") or []) if value))
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    allowed = {"lead_time_override", "coverage_days", "replenishment_enabled", "review_cycle_days", "target_days", "min_order_qty", "pack_size", "safety_stock_override"}
    fields = {key: value for key, value in fields.items() if key in allowed}
    if not warehouse_id or not sku_ids or not fields:
        raise ValidationError("请选择仓库、至少一个 SKU 和至少一个需要修改的参数")
    warehouse = Warehouse.objects.filter(pk=warehouse_id, organization=organization, active=True).first()
    if warehouse is None:
        raise ValidationError({"warehouse": "仓库不存在或已停用"})
    skus = list(SKU.objects.filter(pk__in=sku_ids, organization=organization, active=True, product__status=Product.Status.ACTIVE))
    if len(skus) != len(sku_ids):
        raise ValidationError({"sku_ids": "包含无效或不属于当前组织的 SKU"})
    integer_fields = {"lead_time_override", "coverage_days", "review_cycle_days", "target_days"}
    decimal_fields = {"min_order_qty", "pack_size", "safety_stock_override"}
    cleaned = {}
    for key, value in fields.items():
        if value in (None, "") and key in {"lead_time_override", "safety_stock_override"}:
            cleaned[key] = None
            continue
        try:
            cleaned[key] = int(value) if key in integer_fields else Decimal(str(value))
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ValidationError({key: "请输入有效数值"}) from exc
        if cleaned[key] < 0 or (key not in {"safety_stock_override"} and cleaned[key] <= 0):
            raise ValidationError({key: "该参数必须为正数（安全库存可为 0）"})
    settings, _ = ReplenishmentSettings.objects.get_or_create(organization=organization)
    saved = []
    with transaction.atomic():
        for sku in skus:
            policy, _ = ReplenishmentPolicy.objects.get_or_create(
                organization=organization, warehouse=warehouse, sku=sku,
                defaults={
                    "review_cycle_days": settings.review_cycle_days, "target_days": settings.target_days,
                    "min_order_qty": Decimal("1"), "pack_size": Decimal("1"),
                },
            )
            for key, value in cleaned.items():
                setattr(policy, key, value)
            policy.full_clean()
            policy.save()
            saved.append(str(policy.pk))
            schedule_replenishment_ai_analysis(organization=organization, warehouse=warehouse, sku_id=sku.pk, reason="policy_changed")
    return Response({"updated": len(saved), "policy_ids": saved})


@api_view(["POST"])
def replenishment_recompute(request):
    organization = _require_replenishment_write(request)
    payload = request.data if isinstance(request.data, dict) else {}
    warehouse = Warehouse.objects.filter(pk=payload.get("warehouse"), organization=organization, active=True).first()
    if warehouse is None:
        raise ValidationError({"warehouse": "仓库不存在或已停用"})
    sku_ids = [str(value) for value in (payload.get("sku_ids") or []) if value]
    skus = SKU.objects.filter(organization=organization, active=True, product__status=Product.Status.ACTIVE)
    if sku_ids:
        skus = skus.filter(pk__in=sku_ids)
    count = 0
    for sku_id in skus.values_list("pk", flat=True):
        schedule_replenishment_ai_analysis(organization=organization, warehouse=warehouse, sku_id=sku_id, reason="manual_recompute")
        count += 1
    job = ReplenishmentAIJob.objects.filter(organization=organization, warehouse=warehouse).values("status", "due_at", "last_error").first()
    return Response({"queued_skus": count, "ai_job": job})


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [OrganizationRolePermission]
    owner_only = True
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        organization = ensure_internal_organization(self.request.user)
        return Organization.objects.filter(pk=organization.pk)


class OrganizationScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [OrganizationRolePermission]
    organization = None

    def get_organization(self):
        return self.organization or request_organization(self.request)

    def get_queryset(self):
        queryset = self.queryset.filter(organization=self.get_organization())
        allowed = allowed_warehouse_ids(self.request.user, getattr(self, "membership", None), self.get_organization())
        if allowed is None:
            return queryset
        if queryset.model is Warehouse:
            return queryset.filter(pk__in=allowed)
        fields = {field.name for field in queryset.model._meta.get_fields()}
        if "warehouse" in fields:
            return queryset.filter(warehouse_id__in=allowed)
        if {"source_warehouse", "destination_warehouse"}.issubset(fields):
            return queryset.filter(Q(source_warehouse_id__in=allowed) | Q(destination_warehouse_id__in=allowed))
        return queryset

    def perform_create(self, serializer):
        organization = self.get_organization()
        _require_serializer_warehouse_access(self.request, organization, serializer)
        _save_serializer(serializer, organization=organization)

    def perform_update(self, serializer):
        _require_serializer_warehouse_access(self.request, self.get_organization(), serializer)
        _save_serializer(serializer)


def _profit_strategy_config(values):
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in values.items()}


class ProfitCalculationStrategyViewSet(OrganizationScopedViewSet):
    queryset = ProfitCalculationStrategy.objects.select_related("created_by", "updated_by").order_by("-is_default", "name", "id")
    serializer_class = ProfitCalculationStrategySerializer
    capability = "profit_rules"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_capability(request, "profit_rules", "当前账号没有维护利润策略权限")

    def _lock_organization(self, organization):
        # Locking the parent row also serializes an empty strategy list, which a
        # filtered strategy-row lock alone cannot protect from concurrent creates.
        return Organization.objects.select_for_update().get(pk=organization.pk)

    def _make_default(self, organization, instance):
        ProfitCalculationStrategy.objects.filter(organization=organization, is_default=True).exclude(pk=instance.pk).update(is_default=False)
        if not instance.is_default:
            instance.is_default = True
            instance.save(update_fields=["is_default", "updated_at"])

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = self._lock_organization(self.get_organization())
        name = serializer.validated_data["name"]
        config = _profit_strategy_config(serializer.validated_data["config"])
        instance = ProfitCalculationStrategy.objects.select_for_update().filter(
            organization=organization, name=name,
        ).first()
        created = instance is None
        if created:
            ProfitCalculationStrategy.objects.filter(organization=organization, is_default=True).update(is_default=False)
            instance = ProfitCalculationStrategy.objects.create(
                organization=organization, name=name, config=config, is_default=True,
                created_by=request.user, updated_by=request.user,
            )
            action = "profit_strategy.create"
            before = None
        else:
            before = {"name": instance.name, "config": instance.config, "is_default": instance.is_default}
            instance.config = config
            instance.updated_by = request.user
            self._make_default(organization, instance)
            instance.save(update_fields=["config", "updated_by", "updated_at"])
            action = "profit_strategy.overwrite"
        write_audit(
            organization=organization, actor=request.user, action=action, instance=instance,
            before=before, after={"name": instance.name, "config": instance.config, "is_default": True},
        )
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(self.get_serializer(instance).data, status=response_status)

    @transaction.atomic
    def perform_update(self, serializer):
        organization = self._lock_organization(self.get_organization())
        instance = ProfitCalculationStrategy.objects.select_for_update().get(pk=serializer.instance.pk, organization=organization)
        before = {"name": instance.name, "config": instance.config, "is_default": instance.is_default}
        self._make_default(organization, instance)
        instance = serializer.save(
            is_default=True, updated_by=self.request.user,
            config=_profit_strategy_config(serializer.validated_data.get("config", instance.config)),
        )
        write_audit(organization=organization, actor=self.request.user, action="profit_strategy.update", instance=instance, before=before, after={"name": instance.name, "config": instance.config, "is_default": True})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def activate(self, request, pk=None):
        organization = self._lock_organization(self.get_organization())
        instance = ProfitCalculationStrategy.objects.select_for_update().get(pk=pk, organization=organization)
        before = {"is_default": instance.is_default}
        self._make_default(organization, instance)
        instance.updated_by = request.user
        instance.save(update_fields=["updated_by", "updated_at"])
        write_audit(
            organization=organization, actor=request.user, action="profit_strategy.activate", instance=instance,
            before=before, after={"is_default": True},
        )
        return Response(self.get_serializer(instance).data)

    @transaction.atomic
    def perform_destroy(self, instance):
        organization = self._lock_organization(self.get_organization())
        instance = ProfitCalculationStrategy.objects.select_for_update().get(pk=instance.pk, organization=organization)
        was_default = instance.is_default
        before = {"name": instance.name, "config": instance.config, "is_default": was_default}
        write_audit(
            organization=organization, actor=self.request.user, action="profit_strategy.delete", instance=instance,
            before=before, after={"deleted": True},
        )
        instance.delete()
        if was_default:
            replacement = ProfitCalculationStrategy.objects.select_for_update().filter(
                organization=organization,
            ).order_by("name", "id").first()
            if replacement is not None:
                self._make_default(organization, replacement)


class MembershipViewSet(OrganizationScopedViewSet):
    queryset = Membership.objects.select_related("user", "organization").order_by("user__username", "id")
    serializer_class = MembershipSerializer
    owner_only = True
    http_method_names = ["get", "head", "options"]

    @transaction.atomic
    def perform_create(self, serializer):
        membership = _save_serializer(serializer, organization=self.get_organization())
        write_audit(
            organization=membership.organization, actor=self.request.user,
            action="membership.create", instance=membership,
            after={"user_id": membership.user_id, "role": membership.role, "active": membership.active},
        )

    def _protect_last_admin(self, membership, *, next_role=None, next_active=None):
        role = membership.role if next_role is None else next_role
        active = membership.active if next_active is None else next_active
        if membership.role == Membership.Role.ADMIN and membership.active and (
            role != Membership.Role.ADMIN or not active
        ):
            others = Membership.objects.filter(
                organization=membership.organization,
                role=Membership.Role.ADMIN,
                active=True,
            ).exclude(pk=membership.pk)
            if not others.exists():
                raise ValidationError("组织必须至少保留一名有效管理员")

    @transaction.atomic
    def perform_update(self, serializer):
        membership = serializer.instance
        self._protect_last_admin(
            membership,
            next_role=serializer.validated_data.get("role"),
            next_active=serializer.validated_data.get("active"),
        )
        before = {"role": membership.role, "active": membership.active}
        membership = _save_serializer(serializer)
        write_audit(
            organization=membership.organization, actor=self.request.user,
            action="membership.update", instance=membership,
            before=before, after={"role": membership.role, "active": membership.active},
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        self._protect_last_admin(
            instance,
            next_role=Membership.Role.VIEWER,
            next_active=False,
        )
        write_audit(
            organization=instance.organization, actor=self.request.user,
            action="membership.delete", instance=instance,
            before={"user_id": instance.user_id, "role": instance.role, "active": instance.active},
        )
        instance.delete()


class WarehouseViewSet(OrganizationScopedViewSet):
    queryset = Warehouse.objects.order_by("code", "id")
    serializer_class = WarehouseSerializer
    capability = "warehouse"


class OwnStoreViewSet(OrganizationScopedViewSet):
    queryset = OwnStore.objects.order_by("name", "id")
    serializer_class = OwnStoreSerializer
    capability = "store"

    @transaction.atomic
    def perform_create(self, serializer):
        store = _save_serializer(serializer, organization=self.get_organization())
        write_audit(organization=store.organization, actor=self.request.user, action="store.create", instance=store, after={"name": store.name, "is_active": store.is_active})

    @transaction.atomic
    def perform_update(self, serializer):
        before = {"name": serializer.instance.name, "is_active": serializer.instance.is_active}
        store = _save_serializer(serializer)
        write_audit(organization=store.organization, actor=self.request.user, action="store.update", instance=store, before=before, after={"name": store.name, "is_active": store.is_active})

    @transaction.atomic
    def perform_destroy(self, instance):
        if instance.store_products.exists():
            raise ValidationError("店铺已关联 SKU，只能停用，不能删除")
        write_audit(organization=instance.organization, actor=self.request.user, action="store.delete", instance=instance, before={"name": instance.name})
        instance.delete()


class StoreProductViewSet(OrganizationScopedViewSet):
    queryset = StoreProduct.objects.select_related("store", "sku", "sku__product").order_by("store__name", "id")
    serializer_class = StoreProductSerializer
    capability = "store"

    def perform_create(self, serializer):
        item = _save_serializer(serializer, organization=self.get_organization())
        write_audit(organization=item.organization, actor=self.request.user, action="store_product.create", instance=item, after={"store": str(item.store_id), "sku": str(item.sku_id)})

    def perform_update(self, serializer):
        before = {"store": str(serializer.instance.store_id), "sku": str(serializer.instance.sku_id), "include": serializer.instance.include_in_list_calculation}
        item = _save_serializer(serializer)
        write_audit(organization=item.organization, actor=self.request.user, action="store_product.update", instance=item, before=before, after={"store": str(item.store_id), "sku": str(item.sku_id), "include": item.include_in_list_calculation})

    def perform_destroy(self, instance):
        write_audit(organization=instance.organization, actor=self.request.user, action="store_product.delete", instance=instance, before={"store": str(instance.store_id), "sku": str(instance.sku_id)})
        instance.delete()


class ProductViewSet(OrganizationScopedViewSet):
    queryset = Product.objects.select_related("default_supplier").prefetch_related("images", "skus__store_products__store").order_by("name", "id")
    serializer_class = ProductSerializer
    capability = "catalog"

    def perform_create(self, serializer):
        _require_capability(self.request, "product_edit", "当前账号没有新增商品权限")
        return super().perform_create(serializer)

    def perform_update(self, serializer):
        _require_capability(self.request, "product_edit", "当前账号没有编辑商品权限")
        return super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        _require_capability(self.request, "product_delete", "当前账号没有删除商品权限")
        skus = list(instance.skus.select_for_update())
        sku_ids = [sku.pk for sku in skus]
        if sku_ids:
            balances = StockBalance.objects.select_for_update().filter(sku_id__in=sku_ids)
            if balances.exclude(on_hand=0, reserved=0).exists():
                raise ValidationError(
                    "商品仍有在库或锁定库存，不能删除。请先处理库存；需要保留历史时请使用停用。"
                )

            # Zero balances and replenishment rules are derived/configuration data.
            # Remove them before deleting otherwise-unreferenced SKU masters.
            ReplenishmentPolicy.objects.filter(sku_id__in=sku_ids).delete()
            balances.delete()
            try:
                SKU.objects.filter(pk__in=sku_ids).delete()
            except ProtectedError as exc:
                raise ValidationError(
                    "商品已有采购、库存流水、调拨、销售或退货记录，不能彻底删除；请改为停用，或先删除关联草稿单。"
                ) from exc

        write_audit(
            organization=instance.organization,
            actor=self.request.user,
            action="product.delete",
            instance=instance,
            before={
                "name": instance.name,
                "status": instance.status,
                "sku_codes": [sku.code for sku in skus],
            },
        )
        try:
            instance.delete()
        except ProtectedError as exc:
            raise ValidationError(
                "商品仍被其他业务数据引用，不能彻底删除；请改为停用。"
            ) from exc

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def activate(self, request, pk=None):
        _require_capability(request, "product_status", "当前账号没有启用或停用商品权限")
        product = self.get_object()
        missing = []
        if not product.source_url:
            missing.append("商品链接")
        if not product.images.exists():
            missing.append("商品图片")
        valid_sku = product.skus.filter(
            organization=product.organization, active=True, cost__gt=0
        ).exists()
        if not valid_sku:
            missing.append("有效 SKU 和商品成本")
        if missing:
            raise ValidationError({"missing": missing, "detail": "商品资料未完善，不能启用"})
        if product.status != Product.Status.ACTIVE:
            before = product.status
            product.status = Product.Status.ACTIVE
            product.save(update_fields=["status", "updated_at"])
            write_audit(
                organization=product.organization, actor=request.user,
                action="product.activate", instance=product,
                before={"status": before}, after={"status": product.status},
            )
        return Response(self.get_serializer(product).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def deactivate(self, request, pk=None):
        _require_capability(request, "product_status", "当前账号没有启用或停用商品权限")
        product = self.get_object()
        if product.status == Product.Status.DRAFT:
            raise ValidationError("草稿商品无需停用")
        if product.status != Product.Status.INACTIVE:
            before = product.status
            product.status = Product.Status.INACTIVE
            product.save(update_fields=["status", "updated_at"])
            write_audit(
                organization=product.organization, actor=request.user,
                action="product.deactivate", instance=product,
                before={"status": before}, after={"status": product.status},
            )
        return Response(self.get_serializer(product).data)


    @staticmethod
    def _raw_delete(queryset):
        """Explicit owner purge path: bypass append-only guards after confirmation."""
        if queryset.exists():
            queryset._raw_delete(queryset.db)

    @transaction.atomic
    def _purge_inactive_product(self, instance):
        """Permanently erase an inactive SKU master and every SKU-level record."""
        skus = list(instance.skus.select_for_update())
        sku_ids = [sku.pk for sku in skus]
        if sku_ids:
            purchase_line_ids = list(PurchaseOrderLine.objects.filter(sku_id__in=sku_ids).values_list("pk", flat=True))
            sales_line_ids = list(SalesOrderLine.objects.filter(sku_id__in=sku_ids).values_list("pk", flat=True))
            return_line_ids = list(ReturnLine.objects.filter(sku_id__in=sku_ids).values_list("pk", flat=True))
            ledger_ids = list(StockLedger.objects.filter(sku_id__in=sku_ids).values_list("pk", flat=True))

            # This endpoint is intentionally available only for an inactive product.
            self._raw_delete(ReturnReceiptLine.objects.filter(Q(sku_id__in=sku_ids) | Q(return_line_id__in=return_line_ids)))
            self._raw_delete(ReturnLine.objects.filter(pk__in=return_line_ids))
            self._raw_delete(ShipmentLine.objects.filter(Q(sku_id__in=sku_ids) | Q(order_line_id__in=sales_line_ids)))
            self._raw_delete(StockReservation.objects.filter(Q(sku_id__in=sku_ids) | Q(order_line_id__in=sales_line_ids)))
            self._raw_delete(SalesOrderLine.objects.filter(pk__in=sales_line_ids))
            self._raw_delete(ReceiptLine.objects.filter(Q(sku_id__in=sku_ids) | Q(purchase_line_id__in=purchase_line_ids)))
            self._raw_delete(PurchaseOrderLine.objects.filter(pk__in=purchase_line_ids))
            self._raw_delete(StockTransferLine.objects.filter(sku_id__in=sku_ids))
            self._raw_delete(StockLedgerReversal.objects.filter(Q(original_ledger_id__in=ledger_ids) | Q(reversal_ledger_id__in=ledger_ids)))
            self._raw_delete(StockLedger.objects.filter(pk__in=ledger_ids))
            self._raw_delete(ReplenishmentPolicy.objects.filter(sku_id__in=sku_ids))
            self._raw_delete(StockBalance.objects.filter(sku_id__in=sku_ids))
            SKU.objects.filter(pk__in=sku_ids).delete()

        write_audit(
            organization=instance.organization,
            actor=self.request.user,
            action="product.force_delete",
            instance=instance,
            before={"name": instance.name, "status": instance.status, "sku_codes": [sku.code for sku in skus]},
        )
        instance.delete()

    @action(detail=True, methods=["delete"], url_path="force-delete")
    def force_delete(self, request, pk=None):
        _require_capability(request, "product_delete", "当前账号没有删除商品权限")
        instance = self.get_object()
        if instance.status != Product.Status.INACTIVE:
            raise ValidationError("Only an inactive product can be force deleted.")
        self._purge_inactive_product(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SKUViewSet(OrganizationScopedViewSet):
    queryset = SKU.objects.select_related("product").prefetch_related("store_products__store").order_by("code", "id")
    serializer_class = SKUSerializer
    capability = "catalog"

    @transaction.atomic
    def perform_create(self, serializer):
        _require_capability(self.request, "product_edit", "当前账号没有新增 SKU 权限")
        sku = _save_serializer(serializer, organization=self.get_organization())
        write_audit(
            organization=sku.organization, actor=self.request.user,
            action="sku.create", instance=sku,
            after={"code": sku.code, "cost": str(sku.cost), "currency": sku.currency},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        requested_active = serializer.validated_data.get("active", serializer.instance.active)
        capability = "product_status" if requested_active != serializer.instance.active else "product_edit"
        _require_capability(self.request, capability, "当前账号没有修改该 SKU 的权限")
        before = {"cost": str(serializer.instance.cost), "active": serializer.instance.active, "code": serializer.instance.code}
        sku = _save_serializer(serializer)
        if before["cost"] != str(sku.cost):
            write_audit(
                organization=sku.organization, actor=self.request.user,
                action="sku.cost.update", instance=sku,
                before={"cost": before["cost"]}, after={"cost": str(sku.cost)},
            )
        if before["active"] != sku.active:
            write_audit(
                organization=sku.organization, actor=self.request.user,
                action="sku.activate" if sku.active else "sku.deactivate", instance=sku,
                before={"active": before["active"]}, after={"active": sku.active},
            )

    @transaction.atomic
    def perform_destroy(self, instance):
        _require_capability(self.request, "product_delete", "当前账号没有删除 SKU 权限")
        if instance.store_products.exists():
            raise ValidationError("SKU 已关联店铺商品，只能停用，不能删除")
        write_audit(
            organization=instance.organization, actor=self.request.user, action="sku.delete", instance=instance,
            before={"code": instance.code, "active": instance.active},
        )
        try:
            instance.delete()
        except ProtectedError as exc:
            raise ValidationError("SKU 已有库存、出入库或业务记录，只能停用，不能删除") from exc

    @action(detail=True, methods=["put"], url_path="store-products")
    @transaction.atomic
    def replace_store_products(self, request, pk=None):
        _require_capability(request, "product_edit", "当前账号没有编辑 SKU 店铺资料权限")
        sku = SKU.objects.select_for_update().get(pk=self.get_object().pk)
        rows = request.data.get("items") if isinstance(request.data, dict) else None
        if not isinstance(rows, list):
            raise ValidationError({"items": "请提交店铺商品列表"})
        seen = set()
        saved = []
        for row in rows:
            data = dict(row)
            data["sku"] = str(sku.pk)
            store_id = str(data.get("store", ""))
            if not store_id or store_id in seen:
                raise ValidationError({"items": "同一店铺只能配置一次"})
            seen.add(store_id)
            existing = sku.store_products.filter(store_id=store_id).first()
            serializer = StoreProductSerializer(
                existing, data=data, context={"request": request}, partial=existing is not None
            )
            serializer.is_valid(raise_exception=True)
            item = _save_serializer(serializer, organization=sku.organization) if existing is None else _save_serializer(serializer)
            saved.append(item)
        removed = list(sku.store_products.exclude(store_id__in=seen))
        for item in removed:
            write_audit(organization=item.organization, actor=request.user, action="store_product.delete", instance=item, before={"store": str(item.store_id), "sku": str(item.sku_id)})
            item.delete()
        write_audit(
            organization=sku.organization, actor=request.user, action="sku.store_products.replace", instance=sku,
            after={"store_ids": sorted(seen), "count": len(saved)},
        )
        return Response(StoreProductSerializer(saved, many=True, context={"request": request}).data)

    def _profit_detail(self, sku, item, snapshot):
        commission = item.commission_override_percent
        if commission is None:
            commission = sku.default_creator_commission_percent
        cost = sku.purchase_cost_cny
        if cost is None and sku.currency == "CNY" and sku.cost > 0:
            cost = sku.cost
        required = {
            "类目": sku.category_code,
            "包装重量": sku.packed_weight_g,
            "采购成本": cost,
            "达人佣金": commission,
            "商品售价": item.sale_price_myr,
            "汇率": snapshot,
        }
        missing = [label for label, value in required.items() if value is None or value == ""]
        if missing:
            return {"store": str(item.store_id), "store_name": item.store.name, "missing": missing, "calculable": False}
        payload = {
            "country": "MY", "seller_type": "cross_border", "shop_identity": "marketplace", "bxp": False,
            "delivered": True, "commission_adjustment": Decimal("1.00"), "cny_per_myr": snapshot.myr_cny,
            "usd_per_myr": snapshot.myr_usd,
            "items": [{"sku_name": sku.code, "category_code": sku.category_code, "weight_g": sku.packed_weight_g,
                       "item_price": item.sale_price_myr, "product_cost_cny": cost, "affiliate_rate": commission}],
        }
        try:
            result = calculate_profit(payload)
        except (KeyError, ValueError):
            return {"store": str(item.store_id), "store_name": item.store.name, "missing": ["有效类目规则"], "calculable": False}
        return {
            "store": str(item.store_id), "store_name": item.store.name, "sale_price": str(item.sale_price_myr),
            "commission_percent": str(commission), "gross_profit": result["gross_profit"],
            "gross_margin": result["gross_margin"], "break_even_roi": result["break_even_roi"],
            "missing": [], "calculable": True, "breakdown": result["breakdown"], "rule_version": result["rule_version"],
        }

    @action(detail=False, methods=["get"], url_path="profit-summary")
    def profit_summary(self, request):
        organization = self.get_organization()
        snapshot = ExchangeRateSnapshot.objects.filter(organization=organization, is_current=True).first()
        response = []
        for sku in self.get_queryset():
            items = [item for item in sku.store_products.all() if item.store.is_active and item.include_in_list_calculation]
            details = [self._profit_detail(sku, item, snapshot) for item in items]
            calculated = [item for item in details if item["calculable"]]
            def bounds(field):
                values = [Decimal(item[field]) for item in calculated if item[field] is not None]
                return {"min": str(min(values)), "max": str(max(values))} if values else None
            response.append({"sku": str(sku.pk), "code": sku.code, "stores": details, "calculable_store_count": len(calculated),
                             "incomplete_store_count": len(details) - len(calculated), "sale_price": bounds("sale_price"),
                             "gross_profit": bounds("gross_profit"), "gross_margin": bounds("gross_margin"),
                             "break_even_roi": bounds("break_even_roi"), "exchange_snapshot": str(snapshot.pk) if snapshot else None,
                             "rule_version": calculated[0]["rule_version"] if calculated else None,
                             "missing_fields": sorted({field for item in details for field in item.get("missing", [])})})
        return Response(response)

    @action(detail=True, methods=["get"], url_path="profit-comparison")
    def profit_comparison(self, request, pk=None):
        sku = self.get_object()
        snapshot = ExchangeRateSnapshot.objects.filter(organization=sku.organization, is_current=True).first()
        items = sku.store_products.select_related("store").filter(store__is_active=True, include_in_list_calculation=True)
        stores = [self._profit_detail(sku, item, snapshot) for item in items]
        return Response({"sku": str(sku.pk), "exchange_snapshot": str(snapshot.pk) if snapshot else None,
                         "rule_version": next((item["rule_version"] for item in stores if item["calculable"]), None), "stores": stores})


class ProductImageViewSet(viewsets.ModelViewSet):
    serializer_class = ProductImageSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def get_queryset(self):
        organization = request_organization(self.request)
        return ProductImage.objects.filter(product__organization=organization)

    def perform_create(self, serializer):
        organization = request_organization(self.request)
        product = serializer.validated_data["product"]
        if product.organization_id != organization.id:
            raise ValidationError("商品不属于当前组织")
        _save_serializer(serializer)

    def perform_update(self, serializer):
        _save_serializer(serializer)


class UploadedMediaAssetViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = UploadedMediaAssetSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"
    MAX_IMAGE_SIZE = 5 * 1024 * 1024
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}

    def get_queryset(self):
        return UploadedMediaAsset.objects.filter(organization=request_organization(self.request)).order_by("-created_at")

    def perform_create(self, serializer):
        uploaded = serializer.validated_data["file"]
        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type not in self.ALLOWED_TYPES:
            raise ValidationError({"file": "仅支持 JPG、PNG、WebP 图片。"})
        if uploaded.size > self.MAX_IMAGE_SIZE:
            raise ValidationError({"file": "图片不能超过 5 MB。"})
        digest = hashlib.sha256()
        for chunk in uploaded.chunks():
            digest.update(chunk)
        uploaded.seek(0)
        asset = _save_serializer(
            serializer,
            organization=request_organization(self.request),
            original_name=(getattr(uploaded, "name", "") or "")[:255],
            content_type=content_type,
            size=uploaded.size,
            sha256=digest.hexdigest(),
        )
        write_audit(
            organization=asset.organization, actor=self.request.user,
            action="media_asset.upload", instance=asset,
            after={"content_type": asset.content_type, "size": asset.size, "sha256": asset.sha256},
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def media_asset_content(request, pk):
    try:
        asset = UploadedMediaAsset.objects.get(pk=pk)
    except UploadedMediaAsset.DoesNotExist as exc:
        raise Http404 from exc
    if not asset.file:
        raise Http404
    response = FileResponse(asset.file.open("rb"), content_type=asset.content_type or "application/octet-stream")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


class SupplierViewSet(OrganizationScopedViewSet):
    queryset = Supplier.objects.order_by("code", "id")
    serializer_class = SupplierSerializer
    capability = "purchase"


class PurchaseOrderViewSet(OrganizationScopedViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier", "warehouse", "purchaser").prefetch_related(
        "lines__sku", "shipments__lines__purchase_line__sku", "shipments__receipts__lines"
    ).order_by("-created_at", "id")
    serializer_class = PurchaseOrderSerializer
    capability = "purchase"

    @transaction.atomic
    def perform_create(self, serializer):
        organization = self.get_organization()
        _require_serializer_warehouse_access(self.request, organization, serializer)
        purchaser = serializer.validated_data.get("purchaser") or self.request.user
        purchase_order = _save_serializer(
            serializer,
            organization=organization,
            purchaser=purchaser,
        )
        write_audit(
            organization=purchase_order.organization,
            actor=self.request.user,
            action="purchase.create",
            instance=purchase_order,
            after={"number": purchase_order.number, "purchaser_id": str(purchase_order.purchaser_id)},
        )

    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        try:
            input_serializer = PurchaseOrderEditInputSerializer(
                data=request.data,
                context=self.get_serializer_context(),
            )
            input_serializer.is_valid(raise_exception=True)
            _require_warehouse_access(
                request,
                self.get_organization(),
                input_serializer.validated_data.get("warehouse") or self.get_object().warehouse,
            )
            purchase_order = _service_call(
                edit_purchase,
                purchase_order=self.get_object(),
                data=input_serializer.validated_data,
                actor=request.user,
            )
            return Response(self.get_serializer(purchase_order).data)
        except APIException:
            raise
        except Exception:
            # Keep the API response safe, but retain the actionable traceback in
            # the service log when an old purchase record exposes an unexpected
            # data shape during its second edit.
            logger.exception("Purchase order edit failed", extra={"purchase_order_id": str(pk), "actor_id": request.user.pk})
            raise

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        purchase_order = _service_call(
            submit_purchase, purchase_order=self.get_object(), actor=request.user
        )
        return Response(self.get_serializer(purchase_order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        purchase_order = _service_call(
            cancel_purchase, purchase_order=self.get_object(), actor=request.user
        )
        return Response(self.get_serializer(purchase_order).data)

    @action(detail=True, methods=["post"], url_path="confirm-shipment")
    def confirm_shipment(self, request, pk=None):
        shipment_id = request.data.get("shipment")
        shipment = PurchaseShipment.objects.filter(
            pk=shipment_id, purchase_order=self.get_object()
        ).first()
        if shipment is None:
            raise ValidationError({"shipment": "请选择属于当前采购单的发货批次"})
        shipment = _service_call(confirm_purchase_shipment, purchase_shipment=shipment, actor=request.user)
        return Response(PurchaseShipmentSerializer(shipment, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="close-unshipped")
    def close_unshipped(self, request, pk=None):
        data = PurchaseStageCloseInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        order = _service_call(close_purchase_unshipped, purchase_order=self.get_object(), quantities=data.validated_data["lines"], reason=data.validated_data["reason"], actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="close-transit-exception")
    def close_transit_exception(self, request, pk=None):
        data = PurchaseStageCloseInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        shipment = PurchaseShipment.objects.filter(pk=request.data.get("shipment"), purchase_order=self.get_object()).first()
        if shipment is None:
            raise ValidationError({"shipment": "请选择属于当前采购单的发货批次"})
        shipment = _service_call(close_purchase_transit_exception, purchase_shipment=shipment, quantities=data.validated_data["lines"], reason=data.validated_data["reason"], actor=request.user)
        return Response(PurchaseShipmentSerializer(shipment, context=self.get_serializer_context()).data)

    @transaction.atomic
    def perform_destroy(self, instance):
        if instance.status != PurchaseOrder.Status.DRAFT:
            raise ValidationError("只有草稿采购单可以删除；其他状态请使用取消动作")
        write_audit(
            organization=instance.organization,
            actor=self.request.user,
            action="purchase_order.delete",
            instance=instance,
            before={
                "number": instance.number,
                "status": instance.status,
                "line_count": instance.lines.count(),
            },
        )
        instance.delete()


class ReceiptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Receipt.objects.select_related("purchase_order", "warehouse").prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = ReceiptSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "warehouse"
    organization = None

    def get_organization(self):
        return self.organization or request_organization(self.request)

    def get_queryset(self):
        queryset = self.queryset.filter(organization=self.get_organization())
        allowed = allowed_warehouse_ids(self.request.user, getattr(self, "membership", None), self.get_organization())
        return queryset if allowed is None else queryset.filter(warehouse_id__in=allowed)

    def create(self, request, *args, **kwargs):
        data = ReceiveInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        if values["purchase_order"].organization_id != self.get_organization().id:
            raise ValidationError("采购单不属于当前组织")
        _require_warehouse_access(request, self.get_organization(), values["purchase_order"].warehouse)
        receipt = _service_call(
            receive_purchase,
            organization=self.get_organization(), actor=request.user, **values,
        )
        return Response(self.get_serializer(receipt).data, status=status.HTTP_201_CREATED)


class StockBalanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = StockBalance.objects.select_related("warehouse", "sku").order_by("warehouse_id", "sku_id")
    serializer_class = StockBalanceSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "warehouse"
    organization = None

    def get_organization(self):
        return self.organization or request_organization(self.request)

    def get_queryset(self):
        queryset = self.queryset.filter(organization=self.get_organization())
        allowed = allowed_warehouse_ids(self.request.user, getattr(self, "membership", None), self.get_organization())
        if allowed is None:
            return queryset
        fields = {field.name for field in queryset.model._meta.get_fields()}
        if queryset.model is Warehouse:
            return queryset.filter(pk__in=allowed)
        if "warehouse" in fields:
            return queryset.filter(warehouse_id__in=allowed)
        if {"source_warehouse", "destination_warehouse"}.issubset(fields):
            return queryset.filter(Q(source_warehouse_id__in=allowed) | Q(destination_warehouse_id__in=allowed))
        return queryset

    @transaction.atomic
    def perform_destroy(self, instance):
        balance = StockBalance.objects.select_for_update().get(pk=instance.pk)
        if balance.on_hand != 0 or balance.reserved != 0:
            raise ValidationError("只有在库、锁定和可用库存都为 0 的库存记录才能删除；请先清空库存并释放占用")
        pending_outbound = SalesOrder.objects.filter(
            organization=balance.organization,
            warehouse=balance.warehouse,
            status__in=[
                SalesOrder.Status.READY,
                SalesOrder.Status.ALLOCATED,
                SalesOrder.Status.PICKING,
                SalesOrder.Status.VERIFIED,
            ],
            lines__sku=balance.sku,
        ).exists()
        if pending_outbound:
            raise ValidationError("该 SKU 仍有关联的待出库订单，不能删除零库存记录；请先取消订单或完成出库")
        write_audit(
            organization=balance.organization, actor=self.request.user, action="inventory.balance.delete", instance=balance,
            before={"warehouse": str(balance.warehouse_id), "sku": str(balance.sku_id), "on_hand": str(balance.on_hand), "reserved": str(balance.reserved)},
        )
        balance.delete()

    @action(detail=False, methods=["post"])
    def adjust(self, request):
        data = AdjustmentInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        organization = self.get_organization()
        if values["warehouse"].organization_id != organization.id or values["sku"].organization_id != organization.id:
            raise ValidationError("仓库或 SKU 不属于当前组织")
        _require_warehouse_access(request, organization, values["warehouse"])
        ledger = _service_call(adjust_inventory, organization=organization, actor=request.user, **values)
        return Response(StockLedgerSerializer(ledger).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path="force-delete")
    @transaction.atomic
    def force_delete(self, request, pk=None):
        """Irreversibly delete the balance and its stock ledger for this warehouse/SKU."""
        balance = StockBalance.objects.select_for_update().get(pk=self.get_object().pk)
        ledgers = StockLedger.objects.filter(
            organization=balance.organization, warehouse=balance.warehouse, sku=balance.sku
        )
        ledger_ids = list(ledgers.values_list("pk", flat=True))
        if ledger_ids:
            StockLedgerReversal.objects.filter(
                Q(original_ledger_id__in=ledger_ids) | Q(reversal_ledger_id__in=ledger_ids)
            ).delete()
            ledgers._raw_delete(ledgers.db)
        ReplenishmentPolicy.objects.filter(
            organization=balance.organization, warehouse=balance.warehouse, sku=balance.sku
        ).delete()
        write_audit(
            organization=balance.organization,
            actor=request.user,
            action="inventory.balance.force_delete",
            instance=balance,
            before={"warehouse": str(balance.warehouse_id), "sku": str(balance.sku_id), "on_hand": str(balance.on_hand), "reserved": str(balance.reserved)},
        )
        balance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _manual_move(self, request, direction):
        data = ManualStockMovementInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        organization = self.get_organization()
        if values["warehouse"].organization_id != organization.id or values["sku"].organization_id != organization.id:
            raise ValidationError("仓库或 SKU 不属于当前组织")
        _require_warehouse_access(request, organization, values["warehouse"])
        ledger = _service_call(
            manual_stock_movement, organization=organization, actor=request.user, direction=direction, **values
        )
        return Response(StockLedgerSerializer(ledger).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="manual-inbound")
    def manual_inbound(self, request):
        return self._manual_move(request, "inbound")

    @action(detail=False, methods=["post"], url_path="manual-outbound")
    def manual_outbound(self, request):
        return self._manual_move(request, "outbound")


class StockLedgerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = StockLedger.objects.select_related("warehouse", "sku", "actor").select_related("reversal__reversal_ledger", "reversal__reversed_by")
    serializer_class = StockLedgerSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "warehouse"
    organization = None

    def get_queryset(self):
        organization = self.organization or request_organization(self.request)
        queryset = self.queryset.filter(organization=organization)
        allowed = allowed_warehouse_ids(self.request.user, getattr(self, "membership", None), organization)
        return queryset if allowed is None else queryset.filter(warehouse_id__in=allowed)

    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke(self, request, pk=None):
        data = StockLedgerReversalInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        reversal = _service_call(
            reverse_stock_ledger,
            organization=request_organization(request), ledger=self.get_object(), actor=request.user, **data.validated_data,
        )
        return Response({"reversal": str(reversal.pk), "reversal_ledger": StockLedgerSerializer(reversal.reversal_ledger).data})


class ReplenishmentPolicyViewSet(OrganizationScopedViewSet):
    queryset = ReplenishmentPolicy.objects.select_related("warehouse", "sku").order_by(
        "warehouse__code", "sku__code", "id"
    )
    serializer_class = ReplenishmentPolicySerializer
    capability = "replenishment"


class ReplenishmentSettingsViewSet(OrganizationScopedViewSet):
    queryset = ReplenishmentSettings.objects.all()
    serializer_class = ReplenishmentSettingsSerializer
    capability = "replenishment"

    def create(self, request, *args, **kwargs):
        organization = self.get_organization()
        existing = ReplenishmentSettings.objects.filter(organization=organization).first()
        if existing is not None:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)
        return super().create(request, *args, **kwargs)


class ReplenishmentRecommendationViewSet(OrganizationScopedViewSet):
    queryset = ReplenishmentRecommendation.objects.select_related("warehouse", "sku").order_by("-calculated_at", "id")
    serializer_class = ReplenishmentRecommendationSerializer
    capability = "replenishment"

    @action(detail=True, methods=["post"], url_path="confirm")
    @transaction.atomic
    def confirm(self, request, pk=None):
        item = self.get_queryset().select_for_update().get(pk=pk)
        quantity = request.data.get("quantity", item.user_confirmed_quantity or item.system_suggested_quantity)
        try:
            quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({"quantity": "请输入有效数量"}) from exc
        if quantity < 0:
            raise ValidationError({"quantity": "数量不能为负数"})
        before = {"status": item.status, "user_confirmed_quantity": str(item.user_confirmed_quantity or "")}
        item.user_confirmed_quantity = quantity
        item.adjusted_by = request.user
        item.adjusted_at = timezone.now()
        item.status = ReplenishmentRecommendation.Status.CONFIRMED
        item.save(update_fields=["user_confirmed_quantity", "adjusted_by", "adjusted_at", "status", "updated_at"])
        write_audit(organization=item.organization, actor=request.user, action="replenishment.recommendation.adjust", instance=item, before=before, after={"quantity": str(quantity)})
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=["post"], url_path="convert")
    @transaction.atomic
    def convert(self, request, pk=None):
        item = self.get_queryset().select_for_update().get(pk=pk)
        idem = str(request.data.get("idempotency_key", "")).strip()
        if not idem:
            raise ValidationError({"idempotency_key": "不能为空"})
        existing = ReplenishmentConversionEvent.objects.filter(
            organization=item.organization, idempotency_key=idem
        ).first()
        if existing:
            if existing.recommendation_id != item.pk:
                raise ValidationError("幂等键已被其它补货建议占用")
            return Response(self.get_serializer(item).data)
        supplier = Supplier.objects.filter(
            organization=item.organization, pk=request.data.get("supplier"), active=True
        ).first()
        if supplier is None:
            raise ValidationError({"supplier": "转采购前必须人工选择启用的供应商"})
        quantity = item.user_confirmed_quantity if item.user_confirmed_quantity is not None else item.system_suggested_quantity
        remaining = quantity - item.converted_purchase_quantity
        requested = Decimal(str(request.data.get("quantity", remaining)))
        if requested <= 0 or requested > remaining:
            raise ValidationError({"quantity": "转采购数量超过剩余可转数量"})
        purchase_order = PurchaseOrder.objects.filter(
            organization=item.organization, supplier=supplier, warehouse=item.warehouse,
            status=PurchaseOrder.Status.DRAFT, number__startswith="RPL-",
        ).order_by("created_at").first()
        if purchase_order is None:
            purchase_order = PurchaseOrder.objects.create(
                organization=item.organization, supplier=supplier, warehouse=item.warehouse,
                number=f"RPL-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}", purchaser=request.user,
                notes="由补货建议转换创建；草稿不会进入待发货库存。",
            )
        purchase_line, created = PurchaseOrderLine.objects.select_for_update().get_or_create(
            purchase_order=purchase_order, sku=item.sku,
            defaults={"quantity_ordered": requested, "unit_cost": item.sku.cost},
        )
        if not created:
            purchase_line.quantity_ordered += requested
            purchase_line.save(update_fields=["quantity_ordered", "updated_at"])
        ReplenishmentConversionEvent.objects.create(
            organization=item.organization, recommendation=item, purchase_order=purchase_order,
            quantity=requested, idempotency_key=idem,
        )
        item.converted_purchase_quantity += requested
        item.status = ReplenishmentRecommendation.Status.CONVERTED if item.converted_purchase_quantity >= quantity else ReplenishmentRecommendation.Status.PARTIALLY_CONVERTED
        item.save(update_fields=["converted_purchase_quantity", "status", "updated_at"])
        write_audit(organization=item.organization, actor=request.user, action="replenishment.recommendation.convert", instance=item, after={"quantity": str(requested), "remaining": str(quantity - item.converted_purchase_quantity), "purchase_order": str(purchase_order.pk)})
        return Response(self.get_serializer(item).data)


class StockTransferViewSet(OrganizationScopedViewSet):
    queryset = StockTransfer.objects.select_related(
        "source_warehouse", "destination_warehouse", "dispatched_by", "received_by"
    ).prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = StockTransferSerializer
    capability = "warehouse"

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)
        reserve_stock_transfer_draft(transfer=serializer.instance, actor=self.request.user)

    @action(detail=True, methods=["get", "put"], url_path="packages")
    def packages(self, request, pk=None):
        transfer = self.get_object()
        if request.method == "GET":
            packages = StockTransferPackage.objects.filter(transfer=transfer).prefetch_related("lines").order_by("created_at", "id")
            return Response(StockTransferPackageSerializer(packages, many=True).data)
        data = TransferPackagesInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        if transfer.status == StockTransfer.Status.DRAFT:
            saved = _service_call(
                save_stock_transfer_packages, transfer=transfer,
                packages=data.validated_data["packages"], actor=request.user,
            )
        else:
            saved = _service_call(
                update_stock_transfer_package_tracking, transfer=transfer,
                packages=data.validated_data["packages"], actor=request.user,
            )
        packages = StockTransferPackage.objects.filter(transfer=saved).prefetch_related("lines").order_by("created_at", "id")
        return Response(StockTransferPackageSerializer(packages, many=True).data)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_transfer(self, request, pk=None):
        data = TransferPostInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        transfer = _service_call(
            dispatch_stock_transfer,
            transfer=self.get_object(),
            actor=request.user,
            **data.validated_data,
        )
        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=["post"], url_path="close-transit-exception")
    def close_transit_exception(self, request, pk=None):
        data = TransferExceptionCloseInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        transfer = _service_call(
            close_stock_transfer_exception, transfer=self.get_object(), actor=request.user,
            quantities=data.validated_data.get("quantities") or {}, reason=data.validated_data["reason"],
        )
        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        data = TransferReceiveInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        transfer = _service_call(
            receive_stock_transfer,
            transfer=self.get_object(),
            actor=request.user,
            **data.validated_data,
        )
        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        transfer = _service_call(
            cancel_stock_transfer, transfer=self.get_object(), actor=request.user
        )
        return Response(self.get_serializer(transfer).data)

    def perform_destroy(self, instance):
        if instance.status != StockTransfer.Status.DRAFT:
            raise ValidationError("只有草稿调拨单可以删除")
        instance.delete()


class SalesOrderViewSet(OrganizationScopedViewSet):
    queryset = SalesOrder.objects.select_related("warehouse").prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = SalesOrderSerializer
    capability = "order"

    @action(detail=False, methods=["post"], url_path="create-and-ship")
    @transaction.atomic
    def create_and_ship(self, request):
        payload = request.data.copy()
        idempotency_key = str(payload.pop("idempotency_key", "") or "").strip()
        shipment_number = str(payload.pop("shipment_number", "") or "").strip()
        tracking_number = str(payload.pop("tracking_number", "") or "").strip()
        if not idempotency_key or len(idempotency_key) > 120:
            raise ValidationError({"idempotency_key": "幂等键不能为空且不能超过 120 个字符"})
        if len(shipment_number) > 60 or len(tracking_number) > 100:
            raise ValidationError("出库单号或物流单号过长")

        organization = Organization.objects.select_for_update().get(pk=self.get_organization().pk)
        external_ref = "erp-create:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        order = SalesOrder.objects.filter(organization=organization, external_ref=external_ref).first()
        if order is None:
            payload["external_ref"] = external_ref
            serializer = self.get_serializer(data=payload)
            serializer.is_valid(raise_exception=True)
            _require_serializer_warehouse_access(request, organization, serializer)
            order = _save_serializer(serializer, organization=organization)
            order, shipment, shortages = _service_call(
                confirm_and_ship_or_shortage,
                order=order,
                idempotency_key=idempotency_key,
                number=shipment_number,
                tracking_number=tracking_number,
                actor=request.user,
            )
        else:
            shipment = Shipment.objects.filter(
                organization=organization, order=order, idempotency_key=idempotency_key
            ).first()
            shortages = []
        outcome = "shipped" if shipment is not None else "shortage"
        return Response(
            {
                "outcome": outcome,
                "order": self.get_serializer(order).data,
                "shipment": ShipmentSerializer(shipment).data if shipment is not None else None,
                "shortages": shortages,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = _service_call(confirm_order, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = _service_call(cancel_order, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="restore-fulfillment")
    def restore_fulfillment(self, request, pk=None):
        order = _service_call(restore_order_fulfillment, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["get"], url_path="warehouse-options")
    def warehouse_options(self, request, pk=None):
        """A side-effect free preview used by the warehouse choice modal."""
        order = self.get_object()
        lines = list(order.lines.select_related("sku__product").order_by("sku__code", "external_sku_code", "id"))
        membership = active_internal_membership(request.user)
        allowed = allowed_warehouse_ids(request.user, membership, order.organization)
        warehouses = Warehouse.objects.filter(organization=order.organization, active=True, can_ship=True).order_by("code", "name")
        if allowed is not None:
            warehouses = warehouses.filter(pk__in=allowed)
        unmapped = [line for line in lines if line.sku_id is None]
        options = []
        for warehouse in warehouses:
            preview_lines, total_shortage = [], Decimal("0")
            for line in lines:
                if line.sku_id is None:
                    preview_lines.append({
                        "line_id": str(line.pk), "sku": None, "sku_code": line.external_sku_code,
                        "required": str(line.quantity), "available": "0", "shortage": str(line.quantity),
                        "unmapped": True,
                    })
                    total_shortage += Decimal(line.quantity)
                    continue
                balance = StockBalance.objects.filter(
                    organization=order.organization, warehouse=warehouse, sku=line.sku
                ).first()
                required = Decimal(line.quantity) - Decimal(line.quantity_shipped) - Decimal(line.quantity_reserved)
                available = (Decimal(balance.on_hand) - Decimal(balance.reserved)) if balance else Decimal("0")
                shortage = max(Decimal("0"), required - available)
                total_shortage += shortage
                preview_lines.append({
                    "line_id": str(line.pk), "sku": str(line.sku_id), "sku_code": line.sku.code,
                    "required": str(required), "available": str(available), "shortage": str(shortage), "unmapped": False,
                })
            options.append({
                "warehouse": {"id": str(warehouse.pk), "code": warehouse.code, "name": warehouse.name},
                "lines": preview_lines, "shortage": str(total_shortage),
                "selectable": not unmapped and total_shortage == 0,
            })
        return Response({"order": str(order.pk), "order_number": order.number, "unmapped": bool(unmapped), "options": options})

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        data = AllocateInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        order = _service_call(allocate_order, order=self.get_object(), actor=request.user, **data.validated_data)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="assign-warehouse")
    def assign_warehouse(self, request, pk=None):
        data = OrderWarehouseInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        _require_warehouse_access(request, self.get_organization(), data.validated_data["warehouse"])
        order = _service_call(assign_order_warehouse, order=self.get_object(), actor=request.user, **data.validated_data)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="change-warehouse")
    def change_warehouse(self, request, pk=None):
        data = OrderWarehouseInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        _require_warehouse_access(request, self.get_organization(), data.validated_data["warehouse"])
        order = _service_call(change_order_warehouse, order=self.get_object(), actor=request.user, **data.validated_data)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"], url_path="start-picking")
    def start_picking(self, request, pk=None):
        order = _service_call(start_picking, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        order = _service_call(verify_order, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def ship(self, request, pk=None):
        data = ShipInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        shipment = _service_call(ship_order, order=self.get_object(), actor=request.user, **data.validated_data)
        return Response(ShipmentSerializer(shipment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="confirm-and-ship")
    def confirm_and_ship(self, request, pk=None):
        data = ConfirmAndShipInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        shipment = _service_call(
            confirm_and_ship_order,
            order=self.get_object(),
            actor=request.user,
            **data.validated_data,
        )
        return Response(
            ShipmentSerializer(shipment, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_destroy(self, instance):
        if instance.status != SalesOrder.Status.DRAFT:
            raise ValidationError("只有草稿订单可以删除；其他状态请使用取消动作")
        instance.delete()


class ShipmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Shipment.objects.select_related("order", "warehouse").prefetch_related("lines").order_by("-shipped_at", "id")
    serializer_class = ShipmentSerializer
    permission_classes = [OrganizationRolePermission]
    capability = "order"
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))


class ReturnOrderViewSet(OrganizationScopedViewSet):
    queryset = ReturnOrder.objects.prefetch_related("lines", "receipts__lines").order_by("-created_at", "id")
    serializer_class = ReturnOrderSerializer
    capability = "order"

    @action(detail=False, methods=["post"], url_path="receive-from-order")
    @transaction.atomic
    def receive_from_order(self, request):
        organization = self.get_organization()
        idempotency_key = str(request.data.get("idempotency_key", "")).strip()
        if not idempotency_key:
            raise ValidationError({"idempotency_key": "该字段不能为空"})

        existing = ReturnReceipt.objects.select_related(
            "return_order__original_order"
        ).prefetch_related("return_order__lines").filter(
            organization=organization,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            requested_order = str(request.data.get("original_order", ""))
            if requested_order != str(existing.return_order.original_order_id):
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
    capability = "competitor"

    @transaction.atomic
    def perform_create(self, serializer):
        item = _save_serializer(serializer, organization=self.get_organization())
        write_audit(organization=item.organization, actor=self.request.user, action="competitor.create", instance=item, after={"url": item.url, "kind": item.kind, "seller_group": str(item.seller_group_id or "")})

    @transaction.atomic
    def perform_update(self, serializer):
        previous_group = serializer.instance.seller_group
        before = {
            "seller": serializer.instance.seller,
            "seller_group": str(serializer.instance.seller_group_id or ""),
            "shipping_type": serializer.instance.shipping_type,
            "seller_rating": str(previous_group.rating) if previous_group and previous_group.rating is not None else None,
            "seller_is_star": previous_group.is_star if previous_group else None,
            "seller_type": previous_group.seller_type if previous_group else None,
        }
        item = _save_serializer(serializer)
        current_group = item.seller_group
        after = {
            "seller": item.seller,
            "seller_group": str(item.seller_group_id or ""),
            "shipping_type": item.shipping_type,
            "seller_rating": str(current_group.rating) if current_group and current_group.rating is not None else None,
            "seller_is_star": current_group.is_star if current_group else None,
            "seller_type": current_group.seller_type if current_group else None,
        }
        if before != after:
            write_audit(organization=item.organization, actor=self.request.user, action="competitor.seller_or_shipping.update", instance=item, before=before, after=after)

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
    capability = "competitor"

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

    @action(detail=True, methods=["post"], url_path="bind-store")
    @transaction.atomic
    def bind_store(self, request, pk=None):
        connection = self.get_object()
        store = OwnStore.objects.select_for_update().filter(
            pk=request.data.get("store"), organization=connection.organization
        ).first()
        if store is None:
            raise ValidationError({"store": "店铺不存在或不属于当前组织"})
        if store.market and connection.region and store.market.upper() != connection.region.upper():
            raise ValidationError({"store": "店铺市场与 TikTok 授权市场不一致"})
        existing = TikTokShopConnection.objects.select_for_update().filter(
            organization=connection.organization, store=store,
            status=TikTokShopConnection.Status.CONNECTED,
        ).exclude(pk=connection.pk).first()
        if existing:
            raise ValidationError({"store": "该 ERP 店铺已有有效授权"})
        remote = TikTokShopConnection.objects.filter(
            organization=connection.organization, shop_id=connection.shop_id,
            status=TikTokShopConnection.Status.CONNECTED,
        ).exclude(pk=connection.pk).first()
        if remote:
            raise ValidationError({"shop_id": "该远端店铺已绑定其它 ERP 店铺"})
        connection.store = store
        if not store.market and connection.region:
            store.market = connection.region
            store.save(update_fields=["market", "updated_at"])
        connection.save(update_fields=["store", "updated_at"])
        write_audit(organization=connection.organization, actor=request.user, action="tiktok.connection.bind_store", instance=connection, after={"store_id": str(store.pk), "shop_id": connection.shop_id})
        return Response(self.get_serializer(connection).data)

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

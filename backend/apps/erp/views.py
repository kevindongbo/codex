import hashlib
from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404
from django.db import IntegrityError, connection, transaction
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
    AIInvocationLog, AIProviderConfig, AIRecommendation, AuditLog, CompetitorProduct, CompetitorSnapshot, Membership, Organization, OrganizationSyncState, OwnerEmailChallenge,
    LocalImport, Product, ProductImage, PurchaseOrder, Receipt, ReplenishmentPolicy, ReplenishmentSettings,
    ReturnOrder, ReturnReceipt, SalesOrder, Shipment,
    SKU, StockBalance, StockLedger, StockLedgerReversal, StockTransfer, Supplier, TikTokShopConnection, TikTokShopSyncRun, UploadedMediaAsset, Warehouse,
)
from .owner_security import consume_challenge, create_challenge, email_verification_enabled
from .permissions import (
    PERMISSION_CATALOG,
    OrganizationRolePermission,
    is_owner,
    membership_permissions,
    request_organization,
)
from .serializers import (
    AIInvocationLogSerializer, AIProviderConfigSerializer, AIRecommendationConfirmationSerializer, AIRecommendationInputSerializer, AIRecommendationSerializer,
    AdjustmentInputSerializer, AllocateInputSerializer, AuditLogSerializer,
    CompetitorProductSerializer, CompetitorSnapshotSerializer, InternalAccountSerializer, MembershipSerializer,
    ConfirmAndShipInputSerializer, LocalImportSerializer, OrganizationSerializer,
    ProductImageSerializer, ProductSerializer, QuickSalesSnapshotInputSerializer, UploadedMediaAssetSerializer,
    PurchaseOrderSerializer, ReceiptSerializer, ReceiveInputSerializer,
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
    dispatch_stock_transfer, manual_stock_movement, receive_purchase, receive_return, receive_stock_transfer, reverse_stock_ledger,
    reject_return, ship_order, start_picking, submit_purchase, verify_order, write_audit,
)
from .local_imports import commit_local_import, validate_local_import
from .replenishment import (
    ReplenishmentPolicy as ForecastPolicy,
    build_replenishment_forecast,
)
from .single_tenant import active_internal_membership, ensure_internal_organization, internal_organization
from .sync import bump_sync_revision


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


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return Response({"status": "ok", "database": "ok"})


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
        request_organization(request)
        return Response({
            "configured": alphashop.configured(),
            "platform_regions": {key: list(value) for key, value in alphashop.PLATFORM_REGIONS.items()},
            "listing_times": list(alphashop.LISTING_TIMES),
            "defaults": {"platform": "tiktok", "region": "MY", "listing_time": "90"},
        })


class ProductSelectionKeywordView(APIView):
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def post(self, request):
        request_organization(request)
        serializer = ProductSelectionKeywordInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        regions = alphashop.PLATFORM_REGIONS.get(values["platform"], ())
        if values["region"] not in regions:
            raise ValidationError({"region": "该平台暂不支持这个国家或地区。"})
        _selection_rate_limit(request, "keywords", 30, 60)
        try:
            return Response(alphashop.search_keywords(**values))
        except alphashop.AlphaShopError as exc:
            return Response({"code": exc.code, "detail": exc.detail}, status=exc.status_code)


class ProductSelectionReportView(APIView):
    permission_classes = [OrganizationRolePermission]
    capability = "catalog"

    def post(self, request):
        request_organization(request)
        serializer = ProductSelectionReportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        regions = alphashop.PLATFORM_REGIONS.get(values["platform"], ())
        if values["region"] not in regions:
            raise ValidationError({"region": "该平台暂不支持这个国家或地区。"})
        _selection_rate_limit(request, "report", 10, 3600)
        try:
            return Response(alphashop.generate_report(**values))
        except alphashop.AlphaShopError as exc:
            return Response({"code": exc.code, "detail": exc.detail}, status=exc.status_code)


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
        "active": bool(membership.active and user.is_active),
        "permissions": sorted(membership_permissions(membership)),
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
        user = user_model.objects.create_user(
            username=data["username"],
            password=data["password"],
            is_active=data.get("active", True),
        )
        permissions = data.get("permissions", ["view"])
        membership = Membership.objects.create(
            organization=organization,
            user=user,
            role=Membership.Role.VIEWER,
            permissions=permissions or ["view"],
            active=data.get("active", True),
        )
        write_audit(
            organization=organization,
            actor=request.user,
            action="account.create",
            instance=membership,
            after={"username": user.username, "permissions": membership.permissions, "active": membership.active},
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
        membership.permissions = data["permissions"] or ["view"]
    with transaction.atomic():
        membership.user.save()
        membership.save()
        write_audit(
            organization=organization,
            actor=request.user,
            action="account.update",
            instance=membership,
            after={"username": membership.user.username, "permissions": membership.permissions, "active": membership.active},
        )
        bump_sync_revision(organization_id=organization.pk)
    return Response(_account_payload(membership))


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
        manual_lead_days=Decimal(settings.default_lead_time_days),
        service_level_factor=settings.service_level_factor,
        initial_reference_shipment_count=settings.initial_reference_shipment_count,
    )
    weights = (settings.velocity_weight_7, settings.velocity_weight_14, settings.velocity_weight_30)
    recommendations = []
    skus = SKU.objects.filter(
        organization=organization,
        active=True,
        product__status=Product.Status.ACTIVE,
    ).select_related("product", "product__default_supplier").order_by("code", "id")
    for sku in skus:
        stored_policy = policies.get(sku.pk)
        forecast_policy = default_policy
        if stored_policy is not None:
            forecast_policy = ForecastPolicy(
                safety_days=default_policy.safety_days,
                review_cycle_days=Decimal(stored_policy.review_cycle_days),
                target_days=Decimal(stored_policy.target_days),
                moq=stored_policy.min_order_qty,
                pack_size=stored_policy.pack_size,
                manual_lead_days=(
                    Decimal(stored_policy.lead_time_override)
                    if stored_policy.lead_time_override is not None
                    else default_policy.manual_lead_days
                ),
                safety_stock_units=stored_policy.safety_stock_override,
                service_level_factor=settings.service_level_factor,
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
        return self.queryset.filter(organization=self.get_organization())

    def perform_create(self, serializer):
        _save_serializer(serializer, organization=self.get_organization())

    def perform_update(self, serializer):
        _save_serializer(serializer)


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


class ProductViewSet(OrganizationScopedViewSet):
    queryset = Product.objects.select_related("default_supplier").prefetch_related("images", "skus").order_by("name", "id")
    serializer_class = ProductSerializer
    capability = "catalog"

    @transaction.atomic
    def perform_destroy(self, instance):
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


class SKUViewSet(OrganizationScopedViewSet):
    queryset = SKU.objects.select_related("product").order_by("code", "id")
    serializer_class = SKUSerializer
    capability = "catalog"

    @transaction.atomic
    def perform_create(self, serializer):
        sku = _save_serializer(serializer, organization=self.get_organization())
        write_audit(
            organization=sku.organization, actor=self.request.user,
            action="sku.create", instance=sku,
            after={"code": sku.code, "cost": str(sku.cost), "currency": sku.currency},
        )

    @transaction.atomic
    def perform_update(self, serializer):
        before_cost = str(serializer.instance.cost)
        sku = _save_serializer(serializer)
        if before_cost != str(sku.cost):
            write_audit(
                organization=sku.organization, actor=self.request.user,
                action="sku.cost.update", instance=sku,
                before={"cost": before_cost}, after={"cost": str(sku.cost)},
            )


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
    queryset = PurchaseOrder.objects.select_related("supplier", "warehouse").prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = PurchaseOrderSerializer
    capability = "purchase"

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
        return self.queryset.filter(organization=self.get_organization())

    def create(self, request, *args, **kwargs):
        data = ReceiveInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        if values["purchase_order"].organization_id != self.get_organization().id:
            raise ValidationError("采购单不属于当前组织")
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
        return self.queryset.filter(organization=self.get_organization())

    @transaction.atomic
    def perform_destroy(self, instance):
        balance = StockBalance.objects.select_for_update().get(pk=instance.pk)
        if balance.on_hand != 0 or balance.reserved != 0:
            raise ValidationError("只有在库和锁定数量都为 0 的库存记录才能删除")
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
        ledger = _service_call(adjust_inventory, organization=organization, actor=request.user, **values)
        return Response(StockLedgerSerializer(ledger).data, status=status.HTTP_201_CREATED)

    def _manual_move(self, request, direction):
        data = ManualStockMovementInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        organization = self.get_organization()
        if values["warehouse"].organization_id != organization.id or values["sku"].organization_id != organization.id:
            raise ValidationError("仓库或 SKU 不属于当前组织")
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
        return self.queryset.filter(organization=self.organization or request_organization(self.request))

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


class StockTransferViewSet(OrganizationScopedViewSet):
    queryset = StockTransfer.objects.select_related(
        "source_warehouse", "destination_warehouse", "dispatched_by", "received_by"
    ).prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = StockTransferSerializer
    capability = "warehouse"

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

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        data = TransferPostInputSerializer(data=request.data)
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

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = _service_call(confirm_order, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = _service_call(cancel_order, order=self.get_object(), actor=request.user)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        data = AllocateInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        order = _service_call(allocate_order, order=self.get_object(), actor=request.user, **data.validated_data)
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
    capability = "catalog"


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
        connection = integrations.complete_tiktok_authorization(
            state=str(request.query_params.get("state", "")), auth_code=str(request.query_params["code"])
        )
    except (DjangoValidationError, IntegrityError) as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else getattr(exc, "messages", [str(exc)])) from exc
    return Response({"detail": "TikTok Shop 店铺授权成功，可以关闭此页面返回 ERP", "connection_id": str(connection.pk)})


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

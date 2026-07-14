from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, connection, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import APIException, ValidationError

from .models import (
    AuditLog, CompetitorProduct, CompetitorSnapshot, Membership, Organization,
    Product, ProductImage, PurchaseOrder, Receipt, ReturnOrder, SalesOrder, Shipment,
    SKU, StockBalance, StockLedger, Supplier, Warehouse,
)
from .permissions import OrganizationRolePermission, request_organization
from .serializers import (
    AdjustmentInputSerializer, AllocateInputSerializer, AuditLogSerializer,
    CompetitorProductSerializer, CompetitorSnapshotSerializer, MembershipSerializer,
    OrganizationSerializer, ProductImageSerializer, ProductSerializer,
    PurchaseOrderSerializer, ReceiptSerializer, ReceiveInputSerializer,
    ReturnOrderSerializer, ReturnReceiveInputSerializer, SalesOrderSerializer,
    ShipmentSerializer, ShipInputSerializer, SKUSerializer, StockBalanceSerializer,
    StockLedgerSerializer, SupplierSerializer, WarehouseSerializer,
)
from .services import (
    adjust_inventory, allocate_order, cancel_order, cancel_purchase, confirm_order,
    receive_purchase, receive_return, reject_return, ship_order, start_picking, submit_purchase,
    verify_order, write_audit,
)


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


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return Response({"status": "ok", "database": "ok"})


@api_view(["GET"])
def me(request):
    memberships = Membership.objects.filter(
        user=request.user, active=True, organization__active=True
    ).select_related("organization")
    return Response({
        "user": {
            "id": request.user.pk,
            "username": request.user.get_username(),
            "email": request.user.email,
        },
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


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [OrganizationRolePermission]
    organization_bootstrap = True

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Organization.objects.order_by("name", "id")
        return Organization.objects.filter(
            memberships__user=self.request.user, memberships__active=True
        ).distinct().order_by("name", "id")

    @transaction.atomic
    def perform_create(self, serializer):
        organization = _save_serializer(serializer)
        Membership.objects.create(
            organization=organization, user=self.request.user, role=Membership.Role.ADMIN
        )


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
    write_roles = {Membership.Role.ADMIN}

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


class ProductViewSet(OrganizationScopedViewSet):
    queryset = Product.objects.select_related("default_supplier").prefetch_related("images", "skus").order_by("name", "id")
    serializer_class = ProductSerializer

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


class SupplierViewSet(OrganizationScopedViewSet):
    queryset = Supplier.objects.order_by("code", "id")
    serializer_class = SupplierSerializer
    write_roles = {Membership.Role.ADMIN, Membership.Role.MANAGER, Membership.Role.BUYER}


class PurchaseOrderViewSet(OrganizationScopedViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier", "warehouse").prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = PurchaseOrderSerializer
    write_roles = {Membership.Role.ADMIN, Membership.Role.MANAGER, Membership.Role.BUYER}

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

    def perform_destroy(self, instance):
        if instance.status != PurchaseOrder.Status.DRAFT:
            raise ValidationError("只有草稿采购单可以删除；其他状态请使用取消动作")
        instance.delete()


class ReceiptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = Receipt.objects.select_related("purchase_order", "warehouse").prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = ReceiptSerializer
    permission_classes = [OrganizationRolePermission]
    write_roles = {Membership.Role.ADMIN, Membership.Role.MANAGER, Membership.Role.BUYER, Membership.Role.WAREHOUSE}
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


class StockBalanceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = StockBalance.objects.select_related("warehouse", "sku").order_by("warehouse_id", "sku_id")
    serializer_class = StockBalanceSerializer
    permission_classes = [OrganizationRolePermission]
    write_roles = {Membership.Role.ADMIN, Membership.Role.MANAGER, Membership.Role.WAREHOUSE}
    organization = None

    def get_organization(self):
        return self.organization or request_organization(self.request)

    def get_queryset(self):
        return self.queryset.filter(organization=self.get_organization())

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


class StockLedgerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = StockLedger.objects.select_related("warehouse", "sku", "actor")
    serializer_class = StockLedgerSerializer
    permission_classes = [OrganizationRolePermission]
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))


class SalesOrderViewSet(OrganizationScopedViewSet):
    queryset = SalesOrder.objects.select_related("warehouse").prefetch_related("lines").order_by("-created_at", "id")
    serializer_class = SalesOrderSerializer
    write_roles = {Membership.Role.ADMIN, Membership.Role.MANAGER, Membership.Role.WAREHOUSE}

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

    def perform_destroy(self, instance):
        if instance.status != SalesOrder.Status.DRAFT:
            raise ValidationError("只有草稿订单可以删除；其他状态请使用取消动作")
        instance.delete()


class ShipmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Shipment.objects.select_related("order", "warehouse").prefetch_related("lines").order_by("-shipped_at", "id")
    serializer_class = ShipmentSerializer
    permission_classes = [OrganizationRolePermission]
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))


class ReturnOrderViewSet(OrganizationScopedViewSet):
    queryset = ReturnOrder.objects.prefetch_related("lines", "receipts__lines").order_by("-created_at", "id")
    serializer_class = ReturnOrderSerializer
    write_roles = {Membership.Role.ADMIN, Membership.Role.MANAGER, Membership.Role.WAREHOUSE}

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


class CompetitorSnapshotViewSet(viewsets.ModelViewSet):
    serializer_class = CompetitorSnapshotSerializer
    permission_classes = [OrganizationRolePermission]

    def get_queryset(self):
        return CompetitorSnapshot.objects.filter(product__organization=request_organization(self.request))

    def perform_create(self, serializer):
        organization = request_organization(self.request)
        if serializer.validated_data["product"].organization_id != organization.id:
            raise ValidationError("竞品不属于当前组织")
        _save_serializer(serializer)

    def perform_update(self, serializer):
        _save_serializer(serializer)


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    permission_classes = [OrganizationRolePermission]
    organization = None

    def get_queryset(self):
        return self.queryset.filter(organization=self.organization or request_organization(self.request))

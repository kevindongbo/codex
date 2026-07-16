import re
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import (
    AuditLog, CompetitorProduct, CompetitorSnapshot, LocalImport, Membership, Organization,
    Product, ProductImage, PurchaseOrder, PurchaseOrderLine, Receipt, ReceiptLine,
    ReplenishmentPolicy,
    ReturnLine, ReturnOrder, ReturnReceipt, ReturnReceiptLine, SalesOrder, SalesOrderLine, Shipment, ShipmentLine,
    SKU, StockBalance, StockLedger, StockTransfer, StockTransferLine, Supplier, Warehouse,
)
from .permissions import PERMISSION_CATALOG, request_organization


def _context_organization(serializer):
    view = serializer.context.get("view")
    organization = getattr(view, "organization", None)
    if organization is not None:
        return organization
    request = serializer.context.get("request")
    return request_organization(request) if request is not None else None


def _draft_warehouse(organization):
    """Return a usable warehouse for an incomplete order without colliding on DEFAULT."""
    warehouse = Warehouse.objects.filter(organization=organization, active=True).order_by("created_at", "id").first()
    if warehouse is not None:
        return warehouse

    warehouse = Warehouse.objects.filter(organization=organization, code="DEFAULT").first()
    if warehouse is not None:
        if not warehouse.active:
            warehouse.active = True
            warehouse.save(update_fields=["active", "updated_at"])
        return warehouse

    return Warehouse.objects.create(
        organization=organization,
        code="DEFAULT",
        name="默认仓",
    )


class OrganizationValidationMixin:
    """Scope writable relations and provide a single tenant assertion helper."""

    def get_organization(self):
        return _context_organization(self)

    def scope_relation(self, field_name, model, *, lookup="organization"):
        organization = self.get_organization()
        field = self.fields.get(field_name)
        if organization is not None and field is not None and hasattr(field, "queryset"):
            field.queryset = model.objects.filter(**{lookup: organization})

    def require_same_organization(self, value, label):
        organization = self.get_organization()
        if value is not None and organization is not None and value.organization_id != organization.id:
            raise serializers.ValidationError({label: "不属于当前组织"})


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class MembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(source="user", queryset=get_user_model().objects.all(), write_only=True)

    class Meta:
        model = Membership
        fields = ["id", "organization", "user_id", "username", "role", "active", "created_at", "updated_at"]
        read_only_fields = ["id", "organization", "created_at", "updated_at"]


class InternalAccountSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=tuple(PERMISSION_CATALOG)),
        required=False,
        allow_empty=True,
    )
    active = serializers.BooleanField(required=False)

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("账号名不能为空")
        return value

    def validate_permissions(self, value):
        return sorted(set(value))


class ScopedSerializer(serializers.ModelSerializer):
    class Meta:
        read_only_fields = ["id", "organization", "created_at", "updated_at"]


class WarehouseSerializer(ScopedSerializer):
    def validate(self, attrs):
        if self.instance is None:
            if not str(attrs.get("code", "")).strip():
                attrs["code"] = f"WH-{uuid.uuid4().hex[:8].upper()}"
            if not str(attrs.get("name", "")).strip():
                attrs["name"] = "待完善仓库"
        return attrs

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise serializers.ValidationError("请输入有效的 IANA 时区，例如 Asia/Kuala_Lumpur") from exc
        return value

    def validate_country(self, value):
        return value.upper()

    def validate_address(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("地址必须是键值对象")
        return value

    def validate_contact(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("联系人必须是键值对象")
        return value

    class Meta(ScopedSerializer.Meta):
        model = Warehouse
        fields = "__all__"
        extra_kwargs = {
            "code": {"required": False, "allow_blank": True},
            "name": {"required": False, "allow_blank": True},
        }


class ProductImageSerializer(OrganizationValidationMixin, serializers.ModelSerializer):
    url = serializers.CharField(max_length=560000)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("product", Product)

    def validate(self, attrs):
        self.require_same_organization(attrs.get("product", getattr(self.instance, "product", None)), "product")
        url = attrs.get("url", getattr(self.instance, "url", ""))
        is_https_url = isinstance(url, str) and url.lower().startswith("https://")
        is_uploaded_image = isinstance(url, str) and re.match(
            r"^data:image/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=\s]+$", url, re.IGNORECASE
        )
        if not (is_https_url or is_uploaded_image):
            raise serializers.ValidationError({"url": "商品图片必须使用 HTTPS 地址或本地上传的 JPG、PNG、WebP 图片"})
        return attrs

    class Meta:
        model = ProductImage
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class SKUSerializer(OrganizationValidationMixin, ScopedSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("product", Product)

    def validate(self, attrs):
        self.require_same_organization(attrs.get("product", getattr(self.instance, "product", None)), "product")
        if self.instance is None and not str(attrs.get("code", "")).strip():
            attrs["code"] = f"SKU-{uuid.uuid4().hex[:8].upper()}"
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = SKU
        fields = "__all__"
        extra_kwargs = {
            "barcode": {"required": False, "allow_blank": True},
            "code": {"required": False, "allow_blank": True},
        }


class ProductSerializer(OrganizationValidationMixin, ScopedSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    skus = SKUSerializer(many=True, read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("default_supplier", Supplier)

    def validate(self, attrs):
        if "status" in getattr(self, "initial_data", {}):
            raise serializers.ValidationError({"status": "请使用启用或停用动作修改商品状态"})
        self.require_same_organization(
            attrs.get("default_supplier", getattr(self.instance, "default_supplier", None)),
            "default_supplier",
        )
        if self.instance is None and not str(attrs.get("name", "")).strip():
            attrs["name"] = "待完善商品"
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = Product
        fields = "__all__"
        read_only_fields = ScopedSerializer.Meta.read_only_fields + ["status"]
        extra_kwargs = {"name": {"required": False, "allow_blank": True}}


class SupplierSerializer(ScopedSerializer):
    def validate(self, attrs):
        if self.instance is None:
            if not str(attrs.get("code", "")).strip():
                attrs["code"] = f"SUP-{uuid.uuid4().hex[:8].upper()}"
            if not str(attrs.get("name", "")).strip():
                attrs["name"] = "待完善供应商"
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = Supplier
        fields = "__all__"
        extra_kwargs = {
            "code": {"required": False, "allow_blank": True},
            "name": {"required": False, "allow_blank": True},
        }


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    quantity_in_transit = serializers.SerializerMethodField()

    def get_quantity_in_transit(self, line):
        if line.purchase_order.status not in {PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIAL}:
            return "0.000"
        return str(max(line.quantity_ordered - line.quantity_received, 0))

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id", "sku", "quantity_ordered", "quantity_received", "quantity_in_transit",
            "unit_cost", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "quantity_received", "quantity_in_transit", "created_at", "updated_at"]


class PurchaseOrderSerializer(OrganizationValidationMixin, ScopedSerializer):
    lines = PurchaseOrderLineSerializer(many=True, required=False)
    in_transit_quantity = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            self.fields["supplier"].queryset = Supplier.objects.filter(
                organization=organization, active=True
            )
            self.fields["warehouse"].queryset = Warehouse.objects.filter(
                organization=organization, active=True
            )
            self.fields["lines"].child.fields["sku"].queryset = SKU.objects.filter(
                organization=organization, active=True, product__status=Product.Status.ACTIVE
            )

    def get_in_transit_quantity(self, order):
        if order.status not in {PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIAL}:
            return "0.000"
        return str(sum((line.quantity_ordered - line.quantity_received for line in order.lines.all()), 0))

    def validate(self, attrs):
        if "status" in getattr(self, "initial_data", {}):
            raise serializers.ValidationError({"status": "请使用提交或取消动作修改采购单状态"})
        self.require_same_organization(attrs.get("supplier", getattr(self.instance, "supplier", None)), "supplier")
        self.require_same_organization(attrs.get("warehouse", getattr(self.instance, "warehouse", None)), "warehouse")
        lines = attrs.get("lines")
        if self.instance is not None and lines is not None:
            raise serializers.ValidationError({"lines": "单据明细创建后不可直接覆盖，请使用专用业务动作"})
        if self.instance is not None and self.instance.status != PurchaseOrder.Status.DRAFT:
            frozen = {"supplier", "warehouse", "currency", "number"}.intersection(attrs)
            if frozen:
                raise serializers.ValidationError("采购单提交后，供应商、仓库、币种和单号不可修改")
        seen = set()
        for line in lines or []:
            self.require_same_organization(line["sku"], "lines")
            if not line["sku"].active or line["sku"].product.status != Product.Status.ACTIVE:
                raise serializers.ValidationError({"lines": "采购单只能选择已启用商品的有效 SKU"})
            if line["sku"].pk in seen:
                raise serializers.ValidationError({"lines": "同一 SKU 只能出现一次"})
            seen.add(line["sku"].pk)
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ScopedSerializer.Meta.read_only_fields + ["status"]
        extra_kwargs = {
            "number": {"required": False, "allow_blank": True},
            "supplier": {"required": False, "allow_null": True},
            "warehouse": {"required": False, "allow_null": True},
        }

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        organization = validated_data["organization"]
        if not validated_data.get("supplier"):
            validated_data["supplier"] = Supplier.objects.create(
                organization=organization,
                code=f"SUP-{uuid.uuid4().hex[:8].upper()}",
                name="待完善供应商",
            )
        if not validated_data.get("warehouse"):
            validated_data["warehouse"] = _draft_warehouse(organization)
        if not str(validated_data.get("number", "")).strip():
            validated_data["number"] = f"PO-DRAFT-{uuid.uuid4().hex[:10].upper()}"
        purchase_order = PurchaseOrder.objects.create(**validated_data)
        for line in lines:
            PurchaseOrderLine.objects.create(purchase_order=purchase_order, **line)
        return purchase_order


class ReceiptLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReceiptLine
        fields = "__all__"
        read_only_fields = ["id", "receipt", "created_at", "updated_at"]


class ReceiptSerializer(ScopedSerializer):
    lines = ReceiptLineSerializer(many=True, read_only=True)

    class Meta(ScopedSerializer.Meta):
        model = Receipt
        fields = "__all__"


class ReceiveLineInputSerializer(serializers.Serializer):
    purchase_line = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrderLine.objects.all())
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=4, required=False)


class ReceiveInputSerializer(OrganizationValidationMixin, serializers.Serializer):
    purchase_order = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrder.objects.all())
    number = serializers.CharField(max_length=60)
    idempotency_key = serializers.CharField(max_length=120)
    lines = ReceiveLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            self.fields["purchase_order"].queryset = PurchaseOrder.objects.filter(organization=organization)
            self.fields["lines"].child.fields["purchase_line"].queryset = PurchaseOrderLine.objects.filter(
                purchase_order__organization=organization
            )

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("至少需要一条收货明细")
        if any(line["quantity"] <= 0 for line in lines):
            raise serializers.ValidationError("收货数量必须大于 0")
        return lines


class StockBalanceSerializer(ScopedSerializer):
    available = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    in_transit = serializers.SerializerMethodField()

    def get_in_transit(self, balance):
        lines = PurchaseOrderLine.objects.filter(
            sku=balance.sku,
            purchase_order__organization=balance.organization,
            purchase_order__warehouse=balance.warehouse,
            purchase_order__status__in=[
                PurchaseOrder.Status.SUBMITTED,
                PurchaseOrder.Status.PARTIAL,
            ],
        )
        purchase_in_transit = sum(
            (line.quantity_ordered - line.quantity_received for line in lines),
            Decimal("0"),
        )
        transfer_in_transit = sum(
            StockTransferLine.objects.filter(
                sku=balance.sku,
                transfer__organization=balance.organization,
                transfer__destination_warehouse=balance.warehouse,
                transfer__status=StockTransfer.Status.IN_TRANSIT,
            ).values_list("quantity", flat=True),
            Decimal("0"),
        )
        return purchase_in_transit + transfer_in_transit

    class Meta(ScopedSerializer.Meta):
        model = StockBalance
        fields = "__all__"
        read_only_fields = ScopedSerializer.Meta.read_only_fields + ["on_hand", "reserved"]


class StockLedgerSerializer(ScopedSerializer):
    class Meta(ScopedSerializer.Meta):
        model = StockLedger
        fields = "__all__"


class ReplenishmentPolicySerializer(OrganizationValidationMixin, ScopedSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("warehouse", Warehouse)
        self.scope_relation("sku", SKU)

    def validate(self, attrs):
        self.require_same_organization(
            attrs.get("warehouse", getattr(self.instance, "warehouse", None)),
            "warehouse",
        )
        self.require_same_organization(
            attrs.get("sku", getattr(self.instance, "sku", None)), "sku"
        )
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = ReplenishmentPolicy
        fields = "__all__"


class ReplenishmentRecommendationQuerySerializer(
    OrganizationValidationMixin, serializers.Serializer
):
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("warehouse", Warehouse)

    def validate_warehouse(self, value):
        if not value.active:
            raise serializers.ValidationError("仓库已停用")
        return value


class StockTransferLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransferLine
        fields = ["id", "sku", "quantity", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StockTransferSerializer(OrganizationValidationMixin, ScopedSerializer):
    lines = StockTransferLineSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            warehouse_queryset = Warehouse.objects.filter(organization=organization)
            self.fields["source_warehouse"].queryset = warehouse_queryset
            self.fields["destination_warehouse"].queryset = warehouse_queryset
            self.fields["lines"].child.fields["sku"].queryset = SKU.objects.filter(
                organization=organization, active=True
            )

    def validate(self, attrs):
        if "status" in getattr(self, "initial_data", {}):
            raise serializers.ValidationError({"status": "请使用发出、收货或取消动作修改状态"})
        source = attrs.get("source_warehouse", getattr(self.instance, "source_warehouse", None))
        destination = attrs.get(
            "destination_warehouse", getattr(self.instance, "destination_warehouse", None)
        )
        self.require_same_organization(source, "source_warehouse")
        self.require_same_organization(destination, "destination_warehouse")
        if source is not None and destination is not None and source.pk == destination.pk:
            raise serializers.ValidationError("来源仓和目标仓不能相同")
        lines = attrs.get("lines")
        if self.instance is None and not lines:
            raise serializers.ValidationError({"lines": "调拨单至少需要一条明细"})
        if self.instance is not None:
            if self.instance.status != StockTransfer.Status.DRAFT:
                raise serializers.ValidationError("已发出或已取消的调拨单不可编辑")
            if lines is not None:
                raise serializers.ValidationError({"lines": "调拨明细创建后不可直接覆盖"})
        seen = set()
        for line in lines or []:
            self.require_same_organization(line["sku"], "lines")
            if line["sku"].pk in seen:
                raise serializers.ValidationError({"lines": "同一 SKU 只能出现一次"})
            seen.add(line["sku"].pk)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        transfer = StockTransfer.objects.create(**validated_data)
        for line in lines:
            StockTransferLine.objects.create(transfer=transfer, **line)
        return transfer

    class Meta(ScopedSerializer.Meta):
        model = StockTransfer
        fields = "__all__"
        read_only_fields = ScopedSerializer.Meta.read_only_fields + [
            "status", "dispatch_idempotency_key", "receive_idempotency_key",
            "dispatched_at", "dispatched_by", "received_at", "received_by",
        ]


class TransferPostInputSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=120)


class AdjustmentInputSerializer(OrganizationValidationMixin, serializers.Serializer):
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    sku = serializers.PrimaryKeyRelatedField(queryset=SKU.objects.all())
    delta = serializers.DecimalField(max_digits=14, decimal_places=3)
    reason = serializers.CharField(max_length=240)
    idempotency_key = serializers.CharField(max_length=120)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            self.fields["warehouse"].queryset = Warehouse.objects.filter(organization=organization)
            self.fields["sku"].queryset = SKU.objects.filter(organization=organization)

    def validate_delta(self, value):
        if value == 0:
            raise serializers.ValidationError("调整数量不能为 0")
        return value


class SalesOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrderLine
        fields = ["id", "sku", "quantity", "quantity_reserved", "quantity_shipped", "unit_price", "created_at", "updated_at"]
        read_only_fields = ["id", "quantity_reserved", "quantity_shipped", "created_at", "updated_at"]


class SalesOrderSerializer(OrganizationValidationMixin, ScopedSerializer):
    lines = SalesOrderLineSerializer(many=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            self.fields["warehouse"].queryset = Warehouse.objects.filter(
                organization=organization, active=True
            )
            self.fields["lines"].child.fields["sku"].queryset = SKU.objects.filter(
                organization=organization, active=True, product__status=Product.Status.ACTIVE
            )

    def validate(self, attrs):
        if "status" in getattr(self, "initial_data", {}):
            raise serializers.ValidationError({"status": "请使用确认、锁库、拣货、复核、出库或取消动作修改订单状态"})
        self.require_same_organization(attrs.get("warehouse", getattr(self.instance, "warehouse", None)), "warehouse")
        lines = attrs.get("lines")
        if self.instance is not None and lines is not None:
            raise serializers.ValidationError({"lines": "订单明细创建后不可直接覆盖，请使用专用业务动作"})
        if self.instance is not None and self.instance.status != SalesOrder.Status.DRAFT:
            frozen = {"warehouse", "number", "external_ref"}.intersection(attrs)
            if frozen:
                raise serializers.ValidationError("订单确认后，仓库、单号和外部单号不可修改")
        seen = set()
        for line in lines or []:
            self.require_same_organization(line["sku"], "lines")
            if not line["sku"].active or line["sku"].product.status != Product.Status.ACTIVE:
                raise serializers.ValidationError({"lines": "订单只能选择已启用商品的有效 SKU"})
            if line["sku"].pk in seen:
                raise serializers.ValidationError({"lines": "同一 SKU 只能出现一次"})
            seen.add(line["sku"].pk)
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = SalesOrder
        fields = "__all__"
        read_only_fields = ScopedSerializer.Meta.read_only_fields + ["status"]
        extra_kwargs = {
            "number": {"required": False, "allow_blank": True},
            "warehouse": {"required": False, "allow_null": True},
            "external_ref": {"required": False, "allow_blank": True},
            "customer": {"required": False},
            "notes": {"required": False, "allow_blank": True},
        }

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        organization = validated_data["organization"]
        if not validated_data.get("warehouse"):
            validated_data["warehouse"] = _draft_warehouse(organization)
        if not str(validated_data.get("number", "")).strip():
            validated_data["number"] = f"SO-DRAFT-{uuid.uuid4().hex[:10].upper()}"
        order = SalesOrder.objects.create(**validated_data)
        for line in lines:
            SalesOrderLine.objects.create(order=order, **line)
        return order


class AllocateInputSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=120)


class ConfirmAndShipInputSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=120)
    number = serializers.CharField(max_length=60, required=False, allow_blank=True)
    tracking_number = serializers.CharField(max_length=100, required=False, allow_blank=True)


class ShipInputSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=60)
    tracking_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=120)


class ShipmentLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentLine
        fields = "__all__"


class ShipmentSerializer(ScopedSerializer):
    lines = ShipmentLineSerializer(many=True, read_only=True)

    class Meta(ScopedSerializer.Meta):
        model = Shipment
        fields = "__all__"


class ReturnLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnLine
        fields = "__all__"
        read_only_fields = ["id", "return_order", "quantity_received", "created_at", "updated_at"]


class ReturnReceiptLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnReceiptLine
        fields = "__all__"
        read_only_fields = [field.name for field in ReturnReceiptLine._meta.fields]


class ReturnReceiptSerializer(serializers.ModelSerializer):
    lines = ReturnReceiptLineSerializer(many=True, read_only=True)

    class Meta:
        model = ReturnReceipt
        fields = "__all__"
        read_only_fields = [field.name for field in ReturnReceipt._meta.fields]


class ReturnOrderSerializer(OrganizationValidationMixin, ScopedSerializer):
    lines = ReturnLineSerializer(many=True)
    receipts = ReturnReceiptSerializer(many=True, read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("original_order", SalesOrder)
        self.scope_relation("warehouse", Warehouse)
        organization = self.get_organization()
        if organization is not None:
            self.fields["lines"].child.fields["sku"].queryset = SKU.objects.filter(organization=organization)

    def validate(self, attrs):
        if "status" in getattr(self, "initial_data", {}):
            raise serializers.ValidationError({"status": "退货状态只能由收货动作推进"})
        original_order = attrs.get("original_order", getattr(self.instance, "original_order", None))
        warehouse = attrs.get("warehouse", getattr(self.instance, "warehouse", None))
        self.require_same_organization(original_order, "original_order")
        self.require_same_organization(warehouse, "warehouse")
        lines = attrs.get("lines")
        if self.instance is not None and lines is not None:
            raise serializers.ValidationError({"lines": "退货明细创建后不可直接覆盖"})
        if self.instance is not None and {"original_order", "warehouse", "number"}.intersection(attrs):
            raise serializers.ValidationError("退货单创建后，原订单、仓库和单号不可修改")
        if self.instance is None:
            if original_order is None:
                raise serializers.ValidationError({"original_order": "当前版本只允许按已出库订单创建退货"})
            if original_order.status != SalesOrder.Status.SHIPPED:
                raise serializers.ValidationError({"original_order": "只有已出库订单可以退货"})
            if warehouse is None or warehouse.pk != original_order.warehouse_id:
                raise serializers.ValidationError({"warehouse": "退货仓库必须与原订单出库仓一致"})
            if not lines:
                raise serializers.ValidationError({"lines": "退货单至少需要一条明细"})

            proposed = {}
            for line in lines:
                sku = line["sku"]
                self.require_same_organization(sku, "lines")
                if line["quantity_expected"] <= 0:
                    raise serializers.ValidationError({"lines": "预计退货数量必须大于 0"})
                proposed[sku.pk] = proposed.get(sku.pk, 0) + line["quantity_expected"]

            for sku_id, quantity in proposed.items():
                shipped = sum(
                    (line.quantity_shipped for line in original_order.lines.filter(sku_id=sku_id)),
                    0,
                )
                already_requested = sum(
                    (
                        line.quantity_expected
                        for line in ReturnLine.objects.filter(
                            return_order__original_order=original_order,
                            sku_id=sku_id,
                        ).exclude(return_order__status=ReturnOrder.Status.REJECTED)
                    ),
                    0,
                )
                if already_requested + quantity > shipped:
                    raise serializers.ValidationError({"lines": "累计退货数量不能超过原订单已出库数量"})
        return attrs

    class Meta(ScopedSerializer.Meta):
        model = ReturnOrder
        fields = "__all__"
        read_only_fields = ScopedSerializer.Meta.read_only_fields + ["status", "received_at"]

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        return_order = ReturnOrder.objects.create(**validated_data)
        for line in lines:
            ReturnLine.objects.create(return_order=return_order, **line)
        return return_order


class ReturnReceiveLineInputSerializer(serializers.Serializer):
    return_line = serializers.PrimaryKeyRelatedField(queryset=ReturnLine.objects.all())
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class ReturnReceiveInputSerializer(OrganizationValidationMixin, serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=120)
    lines = ReturnReceiveLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            self.fields["lines"].child.fields["return_line"].queryset = ReturnLine.objects.filter(
                return_order__organization=organization
            )

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("至少需要一条退货收货明细")
        if any(line["quantity"] <= 0 for line in lines):
            raise serializers.ValidationError("退货收货数量必须大于 0")
        return lines


class CompetitorProductSerializer(OrganizationValidationMixin, ScopedSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("linked_product", Product)

    def validate(self, attrs):
        self.require_same_organization(
            attrs.get("linked_product", getattr(self.instance, "linked_product", None)),
            "linked_product",
        )
        if self.instance is None and not str(attrs.get("name", "")).strip():
            attrs["name"] = "待完善竞品"
        return attrs

    def validate_image_url(self, value):
        if value and not value.lower().startswith("https://"):
            raise serializers.ValidationError("竞品图片必须使用 HTTPS 地址")
        return value

    class Meta(ScopedSerializer.Meta):
        model = CompetitorProduct
        fields = "__all__"
        extra_kwargs = {
            "name": {"required": False, "allow_blank": True},
            "url": {"required": False, "allow_blank": True},
        }


class CompetitorSnapshotSerializer(OrganizationValidationMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_relation("product", CompetitorProduct)

    def validate(self, attrs):
        self.require_same_organization(attrs.get("product", getattr(self.instance, "product", None)), "product")
        return attrs

    class Meta:
        model = CompetitorSnapshot
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class QuickSalesSnapshotInputSerializer(OrganizationValidationMixin, serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=CompetitorProduct.objects.all())
    sold_count = serializers.IntegerField(min_value=0)
    captured_at = serializers.DateTimeField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.get_organization()
        if organization is not None:
            self.fields["product"].queryset = CompetitorProduct.objects.filter(
                organization=organization
            )

    def validate(self, attrs):
        self.require_same_organization(attrs.get("product"), "product")
        return attrs


class AuditLogSerializer(ScopedSerializer):
    class Meta(ScopedSerializer.Meta):
        model = AuditLog
        fields = "__all__"


class LocalImportSerializer(ScopedSerializer):
    class Meta(ScopedSerializer.Meta):
        model = LocalImport
        fields = "__all__"
        read_only_fields = [field.name for field in LocalImport._meta.fields]

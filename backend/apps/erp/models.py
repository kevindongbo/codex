import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class TimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("追加记录不可批量修改")

    def delete(self):
        raise ValidationError("追加记录不可批量删除")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("追加记录不可批量修改")


AppendOnlyManager = models.Manager.from_queryset(AppendOnlyQuerySet)


class Organization(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Membership(TimeStampedModel):
    class Role(models.TextChoices):
        ADMIN = "admin", "管理员"
        MANAGER = "manager", "经理"
        BUYER = "buyer", "采购"
        WAREHOUSE = "warehouse", "仓库"
        VIEWER = "viewer", "只读"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="erp_memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="uniq_org_user")]


class OrganizationScopedModel(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class Warehouse(OrganizationScopedModel):
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    country = models.CharField(max_length=2, default="CN")
    address = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_warehouse_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Product(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    source_url = models.URLField(blank=True)
    purchase_url = models.URLField(blank=True)
    default_supplier = models.ForeignKey(
        "Supplier", null=True, blank=True, on_delete=models.SET_NULL, related_name="default_products"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    def __str__(self):
        return self.name


class SKU(OrganizationScopedModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="skus")
    code = models.CharField(max_length=80)
    barcode = models.CharField(max_length=80, blank=True)
    cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    currency = models.CharField(max_length=3, default="CNY")
    safety_stock = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    attributes = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_sku_code"),
            models.UniqueConstraint(fields=["organization", "barcode"], condition=~Q(barcode=""), name="uniq_org_sku_barcode"),
            models.CheckConstraint(condition=Q(cost__gte=0), name="sku_cost_nonnegative"),
            models.CheckConstraint(condition=Q(safety_stock__gte=0), name="sku_safety_nonnegative"),
        ]

    def __str__(self):
        return self.code


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    url = models.URLField(max_length=1000)
    alt = models.CharField(max_length=200, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [models.UniqueConstraint(fields=["product", "position"], name="uniq_product_image_position")]


class Supplier(OrganizationScopedModel):
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=160)
    contact = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_supplier_code")]


class PurchaseOrder(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        SUBMITTED = "submitted", "已下单"
        PARTIAL = "partial", "部分收货"
        RECEIVED = "received", "已收货"
        CANCELLED = "cancelled", "已取消"

    number = models.CharField(max_length=60)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    currency = models.CharField(max_length=3, default="CNY")
    ordered_at = models.DateTimeField(null=True, blank=True)
    expected_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="uniq_org_po_number")]


class PurchaseOrderLine(TimeStampedModel):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="purchase_lines")
    quantity_ordered = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_received = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["purchase_order", "sku"], name="uniq_po_sku"),
            models.CheckConstraint(condition=Q(quantity_ordered__gt=0), name="po_line_qty_positive"),
            models.CheckConstraint(condition=Q(quantity_received__gte=0), name="po_received_nonnegative"),
            models.CheckConstraint(
                condition=Q(quantity_received__lte=F("quantity_ordered")),
                name="po_received_lte_ordered",
            ),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="po_cost_nonnegative"),
        ]


class Receipt(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "待收货"
        COMPLETED = "completed", "已收货"

    number = models.CharField(max_length=60)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="receipts")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    idempotency_key = models.CharField(max_length=120)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="uniq_org_receipt_number"),
            models.UniqueConstraint(fields=["organization", "idempotency_key"], name="uniq_org_receipt_idem"),
        ]


class ReceiptLine(TimeStampedModel):
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, related_name="lines")
    purchase_line = models.ForeignKey(PurchaseOrderLine, null=True, blank=True, on_delete=models.PROTECT)
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="receipt_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="receipt_qty_positive"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="receipt_cost_nonnegative"),
        ]


class StockBalance(OrganizationScopedModel):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_balances")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="stock_balances")
    on_hand = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    reserved = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "warehouse", "sku"], name="uniq_stock_balance"),
            models.CheckConstraint(condition=Q(on_hand__gte=0), name="stock_on_hand_nonnegative"),
            models.CheckConstraint(condition=Q(reserved__gte=0), name="stock_reserved_nonnegative"),
            models.CheckConstraint(condition=Q(reserved__lte=F("on_hand")), name="stock_reserved_lte_on_hand"),
        ]

    @property
    def available(self):
        return self.on_hand - self.reserved


class StockLedger(OrganizationScopedModel):
    class Type(models.TextChoices):
        RECEIPT = "receipt", "采购收货"
        ADJUSTMENT = "adjustment", "库存调整"
        RESERVE = "reserve", "锁定"
        RELEASE = "release", "释放"
        SHIPMENT = "shipment", "出库"
        RETURN = "return", "退货入库"

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_ledger")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="stock_ledger")
    event_type = models.CharField(max_length=20, choices=Type.choices)
    on_hand_delta = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    reserved_delta = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    on_hand_after = models.DecimalField(max_digits=14, decimal_places=3)
    reserved_after = models.DecimalField(max_digits=14, decimal_places=3)
    reference_type = models.CharField(max_length=40)
    reference_id = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=160)
    reason = models.CharField(max_length=240, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    occurred_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyManager()

    class Meta:
        ordering = ["-occurred_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "idempotency_key"], name="uniq_org_ledger_idem"),
            models.CheckConstraint(condition=Q(on_hand_after__gte=0), name="ledger_on_hand_after_nonnegative"),
            models.CheckConstraint(condition=Q(reserved_after__gte=0), name="ledger_reserved_after_nonnegative"),
            models.CheckConstraint(
                condition=Q(reserved_after__lte=F("on_hand_after")),
                name="ledger_reserved_after_lte_on_hand",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("库存流水不可修改")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("库存流水不可删除")


class SalesOrder(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        READY = "ready", "待锁库"
        ALLOCATED = "allocated", "已锁库"
        PICKING = "picking", "拣货中"
        VERIFIED = "verified", "已复核"
        SHIPPED = "shipped", "已出库"
        CANCELLED = "cancelled", "已取消"

    number = models.CharField(max_length=60)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="sales_orders")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    external_ref = models.CharField(max_length=100, blank=True)
    customer = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="uniq_org_order_number"),
            models.UniqueConstraint(fields=["organization", "external_ref"], condition=~Q(external_ref=""), name="uniq_org_order_ext"),
        ]


class SalesOrderLine(TimeStampedModel):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="order_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_reserved = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    quantity_shipped = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "sku"], name="uniq_order_sku"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="order_qty_positive"),
            models.CheckConstraint(condition=Q(quantity_reserved__gte=0), name="order_reserved_nonnegative"),
            models.CheckConstraint(condition=Q(quantity_shipped__gte=0), name="order_shipped_nonnegative"),
            models.CheckConstraint(
                condition=Q(quantity_reserved__lte=F("quantity") - F("quantity_shipped")),
                name="order_reserved_plus_shipped_lte_qty",
            ),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="order_price_nonnegative"),
        ]


class StockReservation(OrganizationScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        RELEASED = "released", "已释放"
        CONSUMED = "consumed", "已出库"

    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT, related_name="reservations")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    idempotency_key = models.CharField(max_length=160)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "idempotency_key"], name="uniq_org_reservation_idem"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="reservation_qty_positive"),
        ]


class Shipment(OrganizationScopedModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "已出库"

    number = models.CharField(max_length=60)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="shipments")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    idempotency_key = models.CharField(max_length=160)
    tracking_number = models.CharField(max_length=100, blank=True)
    shipped_at = models.DateTimeField()
    shipped_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="uniq_org_shipment_number"),
            models.UniqueConstraint(fields=["organization", "idempotency_key"], name="uniq_org_shipment_idem"),
        ]


class ShipmentLine(TimeStampedModel):
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="lines")
    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.PROTECT)
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="shipment_qty_positive")]


class ReturnOrder(OrganizationScopedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "待收货"
        PARTIAL = "partial", "部分收货"
        RECEIVED = "received", "已收货"
        REJECTED = "rejected", "已拒绝"

    number = models.CharField(max_length=60)
    original_order = models.ForeignKey(SalesOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="returns")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    reason = models.CharField(max_length=240, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="uniq_org_return_number")]


class ReturnLine(TimeStampedModel):
    class Condition(models.TextChoices):
        RESTOCK = "restock", "可重新入库"
        DAMAGED = "damaged", "残损"

    return_order = models.ForeignKey(ReturnOrder, on_delete=models.PROTECT, related_name="lines")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT)
    quantity_expected = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_received = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.RESTOCK)
    unit_refund = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity_expected__gt=0), name="return_expected_positive"),
            models.CheckConstraint(condition=Q(quantity_received__gte=0), name="return_received_nonnegative"),
            models.CheckConstraint(condition=Q(quantity_received__lte=F("quantity_expected")), name="return_received_lte_expected"),
            models.CheckConstraint(condition=Q(unit_refund__gte=0), name="return_refund_nonnegative"),
        ]


class ReturnReceipt(OrganizationScopedModel):
    return_order = models.ForeignKey(ReturnOrder, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="return_receipts")
    idempotency_key = models.CharField(max_length=160)
    received_at = models.DateTimeField()
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"], name="uniq_org_return_receipt_idem"
            )
        ]


class ReturnReceiptLine(TimeStampedModel):
    receipt = models.ForeignKey(ReturnReceipt, on_delete=models.PROTECT, related_name="lines")
    return_line = models.ForeignKey(ReturnLine, on_delete=models.PROTECT, related_name="receipt_lines")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    condition = models.CharField(max_length=16, choices=ReturnLine.Condition.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["receipt", "return_line"], name="uniq_return_receipt_line"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="return_receipt_qty_positive"),
        ]


class CompetitorProduct(OrganizationScopedModel):
    name = models.CharField(max_length=200)
    platform = models.CharField(max_length=40, default="other")
    url = models.URLField(max_length=1000)
    image_url = models.URLField(max_length=1000, blank=True)
    seller = models.CharField(max_length=160, blank=True)
    currency = models.CharField(max_length=3, default="CNY")
    active = models.BooleanField(default=True)


class CompetitorSnapshot(TimeStampedModel):
    product = models.ForeignKey(CompetitorProduct, on_delete=models.CASCADE, related_name="snapshots")
    captured_at = models.DateTimeField()
    price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    sold_count = models.BigIntegerField(null=True, blank=True)
    rating = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    review_count = models.BigIntegerField(null=True, blank=True)
    availability = models.CharField(max_length=40, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-captured_at"]
        constraints = [
            models.UniqueConstraint(fields=["product", "captured_at"], name="uniq_competitor_capture"),
            models.CheckConstraint(
                condition=Q(price__isnull=True) | Q(price__gte=0), name="competitor_price_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(sold_count__isnull=True) | Q(sold_count__gte=0), name="competitor_sold_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | (Q(rating__gte=0) & Q(rating__lte=5)),
                name="competitor_rating_range",
            ),
            models.CheckConstraint(
                condition=Q(review_count__isnull=True) | Q(review_count__gte=0),
                name="competitor_reviews_nonnegative",
            ),
        ]


class AuditLog(OrganizationScopedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=80, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyManager()

    class Meta:
        ordering = ["-occurred_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("审计日志不可修改")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("审计日志不可删除")

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
    name = models.CharField("组织名称", max_length=120)
    slug = models.SlugField("组织标识", max_length=80, unique=True)
    active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "组织"
        verbose_name_plural = "组织"

    def __str__(self):
        return self.name


class Membership(TimeStampedModel):
    class Role(models.TextChoices):
        ADMIN = "admin", "管理员"
        MANAGER = "manager", "经理"
        BUYER = "buyer", "采购"
        WAREHOUSE = "warehouse", "仓库"
        VIEWER = "viewer", "只读"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships", verbose_name="所属组织")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="erp_memberships", verbose_name="用户")
    role = models.CharField("角色", max_length=20, choices=Role.choices, default=Role.VIEWER)
    permissions = models.JSONField("权限清单", default=list, blank=True)
    active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "成员关系"
        verbose_name_plural = "成员关系"
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="uniq_org_user")]


class OwnerEmailChallenge(TimeStampedModel):
    class Purpose(models.TextChoices):
        LOGIN = "login", "登录验证"
        PASSWORD_CHANGE = "password_change", "修改密码"
        PASSWORD_RESET = "password_reset", "找回密码"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owner_email_challenges")
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "主账号邮箱验证码"
        verbose_name_plural = "主账号邮箱验证码"


class OrganizationSyncState(models.Model):
    """A lightweight revision counter used by browser clients for near-real-time refresh."""

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="sync_state",
        verbose_name="所属组织",
    )
    revision = models.PositiveBigIntegerField("数据版本", default=1)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "数据同步状态"
        verbose_name_plural = "数据同步状态"


class OrganizationScopedModel(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)

    class Meta:
        abstract = True


class Warehouse(OrganizationScopedModel):
    class Type(models.TextChoices):
        OVERSEAS = "overseas", "海外仓"
        FORWARDER = "forwarder", "货代仓"
        SCHOOL = "school", "学校仓"
        DOMESTIC = "domestic", "国内仓"
        OTHER = "other", "其他"

    code = models.CharField("仓库编码", max_length=40)
    name = models.CharField("仓库名称", max_length=120)
    warehouse_type = models.CharField("仓库类型", max_length=20, choices=Type.choices, default=Type.OTHER)
    country = models.CharField("国家/地区代码", max_length=2, default="CN")
    address = models.JSONField("地址", default=dict, blank=True)
    timezone = models.CharField("时区", max_length=64, default="Asia/Shanghai")
    contact = models.JSONField("联系方式", default=dict, blank=True)
    can_receive = models.BooleanField("允许收货", default=True)
    can_ship = models.BooleanField("允许发货", default=True)
    active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "仓库"
        verbose_name_plural = "仓库"
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_warehouse_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"


class Product(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    name = models.CharField("商品名称", max_length=200)
    description = models.TextField("商品描述", blank=True)
    seller = models.CharField("店铺/卖家", max_length=160, blank=True)
    market = models.CharField("销售市场", max_length=8, blank=True)
    sales_currency = models.CharField("销售币种", max_length=3, default="CNY")
    monitoring_enabled = models.BooleanField("启用监控", default=False)
    source_url = models.URLField("来源链接", blank=True)
    purchase_url = models.URLField("采购链接", blank=True)
    default_supplier = models.ForeignKey(
        "Supplier", null=True, blank=True, on_delete=models.SET_NULL, related_name="default_products", verbose_name="默认供应商"
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        verbose_name = "商品"
        verbose_name_plural = "商品"

    def __str__(self):
        return self.name


class SKU(OrganizationScopedModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="skus", verbose_name="商品")
    code = models.CharField("库存单位编码（SKU）", max_length=80)
    barcode = models.CharField("条形码", max_length=80, blank=True)
    cost = models.DecimalField("成本", max_digits=14, decimal_places=4, default=Decimal("0"))
    currency = models.CharField("成本币种", max_length=3, default="CNY")
    safety_stock = models.DecimalField("安全库存", max_digits=14, decimal_places=3, default=Decimal("0"))
    attributes = models.JSONField("规格属性", default=dict, blank=True)
    active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "库存单位（SKU）"
        verbose_name_plural = "库存单位（SKU）"
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
    code = models.CharField("供应商编码", max_length=40)
    name = models.CharField("供应商名称", max_length=160)
    contact = models.JSONField("联系方式", default=dict, blank=True)
    active = models.BooleanField("启用", default=True)

    class Meta:
        verbose_name = "供应商"
        verbose_name_plural = "供应商"
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
    extra_cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    ordered_at = models.DateTimeField(null=True, blank=True)
    expected_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="uniq_org_po_number"),
            models.CheckConstraint(condition=Q(extra_cost__gte=0), name="po_extra_cost_nonnegative"),
        ]


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


class ReplenishmentPolicy(OrganizationScopedModel):
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="replenishment_policies", verbose_name="仓库"
    )
    sku = models.ForeignKey(
        SKU, on_delete=models.PROTECT, related_name="replenishment_policies", verbose_name="库存单位（SKU）"
    )
    lead_time_override = models.PositiveIntegerField("补货提前期（天）", null=True, blank=True)
    review_cycle_days = models.PositiveIntegerField("复核周期（天）", default=7)
    target_days = models.PositiveIntegerField("目标覆盖天数", default=30)
    min_order_qty = models.DecimalField(
        "最小订购量", max_digits=14, decimal_places=3, default=Decimal("1")
    )
    pack_size = models.DecimalField("整箱数量", max_digits=14, decimal_places=3, default=Decimal("1"))
    safety_stock_override = models.DecimalField(
        "安全库存覆盖值", max_digits=14, decimal_places=3, null=True, blank=True
    )

    class Meta:
        verbose_name = "补货策略"
        verbose_name_plural = "补货策略"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "warehouse", "sku"],
                name="uniq_replenishment_policy",
            ),
            models.CheckConstraint(
                condition=Q(review_cycle_days__gt=0), name="replenishment_review_positive"
            ),
            models.CheckConstraint(
                condition=Q(target_days__gt=0), name="replenishment_target_positive"
            ),
            models.CheckConstraint(
                condition=Q(min_order_qty__gt=0), name="replenishment_moq_positive"
            ),
            models.CheckConstraint(
                condition=Q(pack_size__gt=0), name="replenishment_pack_positive"
            ),
            models.CheckConstraint(
                condition=Q(safety_stock_override__isnull=True)
                | Q(safety_stock_override__gte=0),
                name="replenishment_safety_nonnegative",
            ),
        ]


class StockLedger(OrganizationScopedModel):
    class Type(models.TextChoices):
        RECEIPT = "receipt", "采购收货"
        ADJUSTMENT = "adjustment", "库存调整"
        RESERVE = "reserve", "锁定"
        RELEASE = "release", "释放"
        SHIPMENT = "shipment", "出库"
        RETURN = "return", "退货入库"
        TRANSFER_OUT = "transfer_out", "调拨发出"
        TRANSFER_IN = "transfer_in", "调拨收货"
        TRANSFER_CANCEL = "transfer_cancel", "调拨撤回"

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


class StockTransferQuerySet(models.QuerySet):
    def delete(self):
        if self.exclude(status="draft").exists():
            raise ValidationError("已过账的调拨单不可删除")
        return super().delete()


class StockTransfer(OrganizationScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        IN_TRANSIT = "in_transit", "调拨在途"
        RECEIVED = "received", "已收货"
        CANCELLED = "cancelled", "已取消"

    number = models.CharField("调拨单号", max_length=60)
    source_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="outbound_transfers", verbose_name="调出仓库"
    )
    destination_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="inbound_transfers", verbose_name="调入仓库"
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField("备注", blank=True)
    dispatch_idempotency_key = models.CharField("发出幂等键", max_length=120, blank=True)
    receive_idempotency_key = models.CharField("收货幂等键", max_length=120, blank=True)
    dispatched_at = models.DateTimeField("发出时间", null=True, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispatched_stock_transfers",
        verbose_name="发出人",
    )
    received_at = models.DateTimeField("收货时间", null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="received_stock_transfers", verbose_name="收货人")

    objects = StockTransferQuerySet.as_manager()

    class Meta:
        verbose_name = "库存调拨单"
        verbose_name_plural = "库存调拨"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "number"], name="uniq_org_transfer_number"
            ),
            models.UniqueConstraint(
                fields=["organization", "dispatch_idempotency_key"],
                condition=~Q(dispatch_idempotency_key=""),
                name="uniq_org_transfer_dispatch_idem",
            ),
            models.UniqueConstraint(
                fields=["organization", "receive_idempotency_key"],
                condition=~Q(receive_idempotency_key=""),
                name="uniq_org_transfer_receive_idem",
            ),
            models.CheckConstraint(
                condition=~Q(source_warehouse=F("destination_warehouse")),
                name="transfer_warehouses_differ",
            ),
        ]

    def delete(self, *args, **kwargs):
        persisted_status = (
            type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
        )
        if persisted_status != self.Status.DRAFT:
            raise ValidationError("已过账的调拨单不可删除")
        return super().delete(*args, **kwargs)


class StockTransferLineQuerySet(models.QuerySet):
    def _assert_draft(self):
        if self.exclude(transfer__status=StockTransfer.Status.DRAFT).exists():
            raise ValidationError("已过账调拨单的明细不可修改或删除")

    def update(self, **kwargs):
        self._assert_draft()
        return super().update(**kwargs)

    def delete(self):
        self._assert_draft()
        return super().delete()


class StockTransferLine(TimeStampedModel):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines", verbose_name="调拨单")
    sku = models.ForeignKey(SKU, on_delete=models.PROTECT, related_name="transfer_lines", verbose_name="库存单位（SKU）")
    quantity = models.DecimalField("数量", max_digits=14, decimal_places=3)

    objects = StockTransferLineQuerySet.as_manager()

    class Meta:
        verbose_name = "调拨明细"
        verbose_name_plural = "调拨明细"
        constraints = [
            models.UniqueConstraint(fields=["transfer", "sku"], name="uniq_transfer_sku"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="transfer_qty_positive"),
        ]

    def delete(self, *args, **kwargs):
        persisted_status = StockTransfer.objects.filter(pk=self.transfer_id).values_list(
            "status", flat=True
        ).first()
        if persisted_status != StockTransfer.Status.DRAFT:
            raise ValidationError("已过账调拨单的明细不可删除")
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            persisted_status = StockTransfer.objects.filter(pk=self.transfer_id).values_list(
                "status", flat=True
            ).first()
            if persisted_status != StockTransfer.Status.DRAFT:
                raise ValidationError("已过账调拨单的明细不可修改")
        return super().save(*args, **kwargs)


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
    platform = models.CharField(max_length=40, blank=True)
    store = models.CharField(max_length=120, blank=True)
    ordered_at = models.DateTimeField(null=True, blank=True)
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
    class Kind(models.TextChoices):
        DIRECT = "direct", "直接竞品"
        INDIRECT = "indirect", "间接竞品"

    name = models.CharField(max_length=200, blank=True)
    linked_product = models.OneToOneField(
        Product,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="monitoring_profile",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.DIRECT)
    platform = models.CharField(max_length=40, default="other")
    market = models.CharField(max_length=8, blank=True)
    url = models.URLField(max_length=1000, blank=True)
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


class LocalImport(OrganizationScopedModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", "已完成"

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="local_imports", verbose_name="仓库")
    idempotency_key = models.CharField("幂等键", max_length=160)
    source_version = models.PositiveIntegerField("来源版本", default=0)
    source_hash = models.CharField("来源校验值", max_length=64)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.COMPLETED)
    summary = models.JSONField("导入摘要", default=dict)
    mapping = models.JSONField("字段映射", default=dict)
    warnings = models.JSONField("警告信息", default=list)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="erp_local_imports",
        verbose_name="导入人",
    )
    imported_at = models.DateTimeField("导入时间", auto_now_add=True)

    objects = AppendOnlyManager()

    class Meta:
        verbose_name = "本地导入记录"
        verbose_name_plural = "本地导入记录"
        ordering = ["-imported_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                name="uniq_org_local_import",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="uniq_org_local_import_idem",
            ),
            models.UniqueConstraint(
                fields=["organization", "source_hash"],
                name="uniq_org_local_import_hash",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("本机迁移报告不可修改")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("本机迁移报告不可删除")

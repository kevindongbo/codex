from django.contrib import admin

from .models import (
    LocalImport,
    Membership,
    Organization,
    Product,
    ReplenishmentPolicy,
    SKU,
    StockTransfer,
    StockTransferLine,
    Supplier,
    Warehouse,
)

admin.site.register([
    Organization,
    Membership,
    Warehouse,
    Product,
    SKU,
    Supplier,
    ReplenishmentPolicy,
])


class StockTransferLineInline(admin.TabularInline):
    model = StockTransferLine
    extra = 0

    def has_add_permission(self, request, obj):
        return obj is None or obj.status == StockTransfer.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.Status.DRAFT


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "number", "organization", "source_warehouse", "destination_warehouse", "status",
        "dispatched_at", "received_at",
    )
    list_filter = ("status", "organization")
    inlines = [StockTransferLineInline]

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.Status.DRAFT


@admin.register(LocalImport)
class LocalImportAdmin(admin.ModelAdmin):
    list_display = ("organization", "warehouse", "status", "imported_at", "imported_by")
    readonly_fields = tuple(field.name for field in LocalImport._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

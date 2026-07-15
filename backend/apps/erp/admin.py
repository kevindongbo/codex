from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.admin.sites import NotRegistered

from .models import (
    LocalImport,
    Product,
    ReplenishmentPolicy,
    SKU,
    StockTransfer,
    StockTransferLine,
    Supplier,
    Warehouse,
)

admin.site.site_header = "东铂跨境运营管理后台"
admin.site.site_title = "东铂跨境运营管理系统"
admin.site.index_title = "系统管理"

# Internal accounts and permissions are managed through the application’s
# dedicated “账号与权限” screen.  The stock Django user/group screens would
# create a second, confusing management path for this single-organization app.
for auth_model in (get_user_model(), Group):
    try:
        admin.site.unregister(auth_model)
    except NotRegistered:
        pass


class ChineseLabelsAdmin(admin.ModelAdmin):
    """Translate inherited field labels without changing database columns."""

    inherited_field_labels = {"organization": "所属组织"}

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if formfield and db_field.name in self.inherited_field_labels:
            formfield.label = self.inherited_field_labels[db_field.name]
        return formfield


admin.site.register([
    Warehouse,
    Product,
    SKU,
    Supplier,
    ReplenishmentPolicy,
], ChineseLabelsAdmin)


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
class StockTransferAdmin(ChineseLabelsAdmin):
    list_display = (
        "number", "organization_name", "source_warehouse", "destination_warehouse", "status",
        "dispatched_at", "received_at",
    )
    list_filter = ("status", "organization")
    inlines = [StockTransferLineInline]

    @admin.display(description="所属组织", ordering="organization")
    def organization_name(self, obj):
        return obj.organization

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status == StockTransfer.Status.DRAFT


@admin.register(LocalImport)
class LocalImportAdmin(ChineseLabelsAdmin):
    list_display = ("organization_name", "warehouse", "status", "imported_at", "imported_by")
    readonly_fields = tuple(field.name for field in LocalImport._meta.fields)

    @admin.display(description="所属组织", ordering="organization")
    def organization_name(self, obj):
        return obj.organization

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

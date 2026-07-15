"""Revision based synchronization for the one internal organization."""

from django.db import transaction
from django.db.models import F
from django.db.models.signals import post_delete, post_save

from .models import (
    AuditLog, CompetitorProduct, CompetitorSnapshot, LocalImport, Membership,
    Organization, OrganizationSyncState, Product, ProductImage, PurchaseOrder,
    PurchaseOrderLine, Receipt, ReceiptLine, ReplenishmentPolicy, ReturnLine,
    ReturnOrder, ReturnReceipt, ReturnReceiptLine, SalesOrder, SalesOrderLine,
    Shipment, ShipmentLine, SKU, StockBalance, StockLedger, StockReservation, StockTransfer,
    StockTransferLine, Supplier, Warehouse,
)


def _organization_id(instance):
    direct = getattr(instance, "organization_id", None)
    if direct:
        return direct
    for relation in ("product", "purchase_order", "receipt", "transfer", "order", "shipment", "return_order", "order_line"):
        # On cascaded deletes a parent relationship can already be gone.  A
        # failed relationship lookup must not make the original delete fail.
        try:
            related = getattr(instance, relation, None)
        except Exception:  # Django raises the related model's DoesNotExist.
            continue
        if related is not None and getattr(related, "organization_id", None):
            return related.organization_id
        if related is not None:
            try:
                parent = getattr(related, "order", None)
            except Exception:
                parent = None
            if parent is not None and getattr(parent, "organization_id", None):
                return parent.organization_id
    return None


def bump_sync_revision(*, organization_id):
    if not organization_id:
        return
    state, created = OrganizationSyncState.objects.get_or_create(
        organization_id=organization_id,
        defaults={"revision": 1},
    )
    if not created:
        OrganizationSyncState.objects.filter(pk=state.pk).update(revision=F("revision") + 1)


def _sync_after_write(sender, instance, raw=False, **kwargs):
    if raw or sender in {Organization, OrganizationSyncState}:
        return
    organization_id = _organization_id(instance)
    if organization_id:
        transaction.on_commit(lambda: bump_sync_revision(organization_id=organization_id))


SYNC_MODELS = (
    Membership, Warehouse, Product, ProductImage, SKU, Supplier,
    PurchaseOrder, PurchaseOrderLine, Receipt, ReceiptLine, StockReservation, StockBalance,
    StockLedger, StockTransfer, StockTransferLine, ReplenishmentPolicy,
    SalesOrder, SalesOrderLine, Shipment, ShipmentLine, ReturnOrder, ReturnLine,
    ReturnReceipt, ReturnReceiptLine, CompetitorProduct, CompetitorSnapshot,
    AuditLog, LocalImport,
)


def register_sync_signals():
    for model in SYNC_MODELS:
        post_save.connect(_sync_after_write, sender=model, dispatch_uid=f"erp-sync-save-{model.__name__}")
        post_delete.connect(_sync_after_write, sender=model, dispatch_uid=f"erp-sync-delete-{model.__name__}")

from decimal import Decimal
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.erp.inbound import calculate_inbound_snapshot
from apps.erp.models import AuditLog, Organization, StockBalance


class Command(BaseCommand):
    help = "Dry-run or reconcile cached purchase/transfer inbound stage balances."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="Organization UUID or slug")
        parser.add_argument("--warehouse", help="Optional warehouse UUID or code")
        parser.add_argument("--sku", help="Optional SKU UUID or code")
        parser.add_argument("--apply", action="store_true", help="Persist exact calculated stage balances")

    def handle(self, *args, **options):
        organization_value = options["organization"]
        try:
            organization_id = uuid.UUID(organization_value)
        except (ValueError, TypeError, AttributeError):
            organization_id = None
        organization = Organization.objects.filter(pk=organization_id).first() if organization_id else None
        if organization is None:
            organization = Organization.objects.filter(slug=organization_value).first()
        if organization is None:
            raise CommandError("Organization not found")

        balances = StockBalance.objects.filter(organization=organization).select_related("warehouse", "sku")
        if options.get("warehouse"):
            value = options["warehouse"]
            try:
                object_id = uuid.UUID(value)
            except (ValueError, TypeError, AttributeError):
                object_id = None
            selector = Q(warehouse__code=value)
            if object_id:
                selector |= Q(warehouse_id=object_id)
            balances = balances.filter(selector)
        if options.get("sku"):
            value = options["sku"]
            try:
                object_id = uuid.UUID(value)
            except (ValueError, TypeError, AttributeError):
                object_id = None
            selector = Q(sku__code=value)
            if object_id:
                selector |= Q(sku_id=object_id)
            balances = balances.filter(selector)

        differences = []
        for balance in balances.order_by("warehouse__code", "sku__code"):
            snapshot = calculate_inbound_snapshot(
                organization=organization,
                warehouse=balance.warehouse,
                sku=balance.sku,
                balance=balance,
            )
            if not snapshot.has_balance_difference:
                continue
            row = {
                "balance": balance,
                "stored_pending": snapshot.stored_pending_shipment,
                "stored_transit": snapshot.stored_in_transit,
                "calculated_pending": snapshot.purchased_pending_shipment,
                "calculated_transit": snapshot.in_transit,
                "sources": [item["source_number"] for item in snapshot.pending_sources + snapshot.transit_sources],
            }
            differences.append(row)
            self.stdout.write(
                "DIFF warehouse={warehouse} sku={sku} stored_pending={stored_pending} "
                "calculated_pending={calculated_pending} stored_transit={stored_transit} "
                "calculated_transit={calculated_transit} sources={sources}".format(
                    warehouse=balance.warehouse.code,
                    sku=balance.sku.code,
                    **{key: row[key] for key in row if key != "balance"},
                )
            )

        if options["apply"] and differences:
            applied = 0
            with transaction.atomic():
                for row in differences:
                    balance = StockBalance.objects.select_for_update().get(pk=row["balance"].pk)
                    snapshot = calculate_inbound_snapshot(
                        organization=organization,
                        warehouse=balance.warehouse,
                        sku=balance.sku,
                        balance=balance,
                    )
                    if not snapshot.has_balance_difference:
                        continue
                    before = {
                        "purchased_pending_shipment": str(balance.purchased_pending_shipment),
                        "in_transit": str(balance.in_transit),
                    }
                    balance.purchased_pending_shipment = Decimal(snapshot.purchased_pending_shipment)
                    balance.in_transit = Decimal(snapshot.in_transit)
                    balance.save(update_fields=["purchased_pending_shipment", "in_transit", "updated_at"])
                    AuditLog.objects.create(
                        organization=organization,
                        action="inventory.inbound_balance_reconcile",
                        object_type="StockBalance",
                        object_id=str(balance.pk),
                        before=before,
                        after={
                            "purchased_pending_shipment": str(balance.purchased_pending_shipment),
                            "in_transit": str(balance.in_transit),
                            "sources": [
                                item["source_number"]
                                for item in snapshot.pending_sources + snapshot.transit_sources
                            ],
                        },
                    )
                    applied += 1
            self.stdout.write(self.style.SUCCESS(f"APPLIED differences={applied}"))
        else:
            self.stdout.write(f"DRY-RUN differences={len(differences)}")

"""Durable scheduling for optional, explainable replenishment AI analysis.

Rule forecasts are calculated synchronously from warehouse ledgers.  This module
only queues the slower model review and never posts inventory or a purchase order.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import integrations
from .models import (
    ReplenishmentAIJob,
    ReplenishmentPolicy,
    ReplenishmentSettings,
    SKU,
)
from .replenishment import ReplenishmentPolicy as ForecastPolicy, build_replenishment_forecast


def schedule_replenishment_ai_analysis(*, organization, warehouse, sku_id, reason: str) -> None:
    """Debounce stock events into one pending job for each warehouse."""
    settings, _ = ReplenishmentSettings.objects.get_or_create(organization=organization)
    if not (settings.ai_enabled and settings.ai_provider_id):
        return
    due_at = timezone.now() + timedelta(minutes=settings.ai_debounce_minutes)
    with transaction.atomic():
        job, _ = ReplenishmentAIJob.objects.select_for_update().get_or_create(
            organization=organization,
            warehouse=warehouse,
            defaults={"due_at": due_at, "sku_ids": [], "reasons": [], "status": ReplenishmentAIJob.Status.QUEUED},
        )
        sku_ids = {str(value) for value in (job.sku_ids or [])}
        sku_ids.add(str(sku_id))
        reasons = list(job.reasons or [])
        if reason and reason not in reasons:
            reasons.append(reason)
        job.sku_ids = sorted(sku_ids)
        job.reasons = reasons[-10:]
        job.due_at = due_at
        job.status = ReplenishmentAIJob.Status.QUEUED
        job.last_error = ""
        job.save(update_fields=["sku_ids", "reasons", "due_at", "status", "last_error", "updated_at"])


def _forecast_policy(*, settings, stored_policy, sku):
    return ForecastPolicy(
        safety_days=settings.safety_days,
        review_cycle_days=Decimal(stored_policy.review_cycle_days if stored_policy else settings.review_cycle_days),
        target_days=Decimal(stored_policy.target_days if stored_policy else settings.target_days),
        moq=stored_policy.min_order_qty if stored_policy else Decimal("0"),
        pack_size=stored_policy.pack_size if stored_policy else Decimal("1"),
        manual_lead_days=Decimal(stored_policy.lead_time_override) if stored_policy and stored_policy.lead_time_override is not None else Decimal(settings.default_lead_time_days),
        safety_stock_units=stored_policy.safety_stock_override if stored_policy else None,
        service_level_factor=settings.service_level_factor,
        safety_margin_ratio=settings.safety_margin_ratio,
        initial_reference_shipment_count=settings.initial_reference_shipment_count,
        initial_safety_reference=getattr(sku, "safety_stock", Decimal("0")),
    )


def _is_complex(forecast) -> bool:
    demand = forecast.demand
    return (
        forecast.confidence == "low"
        or forecast.needs_reorder
        or (demand.daily_velocity > 0 and demand.daily_stddev >= demand.daily_velocity * Decimal("0.50"))
    )


def process_due_replenishment_ai_jobs(*, limit: int = 20) -> int:
    """Run due jobs. Safe for cron/systemd; failures remain visible in the job."""
    now = timezone.now()
    job_ids = list(
        ReplenishmentAIJob.objects.filter(status=ReplenishmentAIJob.Status.QUEUED, due_at__lte=now)
        .order_by("due_at").values_list("pk", flat=True)[:limit]
    )
    processed = 0
    for job_id in job_ids:
        with transaction.atomic():
            job = ReplenishmentAIJob.objects.select_for_update().select_related("warehouse", "organization").get(pk=job_id)
            if job.status != ReplenishmentAIJob.Status.QUEUED or job.due_at > timezone.now():
                continue
            job.status = ReplenishmentAIJob.Status.RUNNING
            job.save(update_fields=["status", "updated_at"])
        settings = ReplenishmentSettings.objects.filter(organization=job.organization).select_related("ai_provider").first()
        provider = settings.ai_provider if settings and settings.ai_enabled else None
        if provider is None or not provider.enabled or not provider.api_key_encrypted:
            job.status = ReplenishmentAIJob.Status.COMPLETED
            job.last_run_at = timezone.now()
            job.last_error = "AI 未启用或配置不可用；已保留规则计算结果。"
            job.save(update_fields=["status", "last_run_at", "last_error", "updated_at"])
            processed += 1
            continue
        try:
            policies = {policy.sku_id: policy for policy in ReplenishmentPolicy.objects.filter(organization=job.organization, warehouse=job.warehouse)}
            skus = SKU.objects.filter(organization=job.organization, pk__in=job.sku_ids, active=True, product__status="active").select_related("product", "product__default_supplier")
            rows = []
            weights = (settings.velocity_weight_3, settings.velocity_weight_7, settings.velocity_weight_15, settings.velocity_weight_30)
            for sku in skus:
                forecast = build_replenishment_forecast(
                    organization=job.organization, sku=sku, warehouse=job.warehouse,
                    supplier=sku.product.default_supplier, policy=_forecast_policy(settings=settings, stored_policy=policies.get(sku.pk), sku=sku), weights=weights,
                )
                if not _is_complex(forecast):
                    continue
                rows.append({
                    "sku": sku.code, "product": sku.product.name, "available": str(forecast.inventory.available),
                    "in_transit": str(forecast.inventory.in_transit), "daily_demand": str(forecast.demand.daily_velocity),
                    "demand_stddev": str(forecast.demand.daily_stddev), "lead_days": forecast.lead_time.selected_days,
                    "suggested_quantity": str(forecast.suggested_order_quantity), "confidence": forecast.confidence,
                    "rule_reasons": list(forecast.reasons),
                })
            if rows:
                integrations.create_ai_recommendation(
                    provider=provider, kind="replenishment",
                    input_data={
                        "scope": "warehouse", "warehouse": job.warehouse.code, "event_reasons": job.reasons,
                        "rules_already_calculated": True, "must_not_modify_inventory": True,
                        "must_not_confirm_purchase_order": True, "items": rows,
                    },
                )
            job.status = ReplenishmentAIJob.Status.COMPLETED
            job.last_error = "" if rows else "规则结果稳定，未达到 AI 分析阈值。"
        except Exception as exc:  # provider details are already redacted by integrations
            job.status = ReplenishmentAIJob.Status.FAILED
            job.last_error = str(exc)[:500]
        job.last_run_at = timezone.now()
        job.save(update_fields=["status", "last_run_at", "last_error", "updated_at"])
        processed += 1
    return processed

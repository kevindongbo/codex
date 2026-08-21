"""Transactional persistence for server-authoritative profit calculations."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.core.exceptions import ValidationError

from .models import (
    ExchangeRateSnapshot,
    ProfitCalculationBatch,
    ProfitCalculationWorkingConfig,
    ProfitPlan,
    ProfitPlanVersion,
)
from .profit_calculator import calculate_profit
from .services import WorkflowConflictError, write_audit


METADATA_KEYS = {
    "sku", "sku_code", "image_url", "store", "plan_name", "action", "target_plan",
}


def jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        return str(value.pk)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _canonical_hash(payload):
    return sha256(
        json.dumps(jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _calculation_payload(validated_data):
    return {
        key: value
        for key, value in validated_data.items()
        if key not in {"idempotency_key", "items"}
    } | {
        "items": [
            {key: value for key, value in item.items() if key not in METADATA_KEYS}
            for item in validated_data["items"]
        ]
    }


def _plan_snapshot(item):
    sku = item.get("sku")
    if sku is not None:
        image_url = sku.image_url or ""
        if not image_url:
            image = sku.product.images.order_by("position", "created_at").first()
            image_url = image.url if image is not None else ""
        return sku.code, sku.product.name, image_url
    return (
        str(item.get("sku_code") or item.get("sku_name") or "未命名 SKU").strip(),
        str(item.get("sku_name") or "").strip(),
        str(item.get("image_url") or "").strip(),
    )


def _batch_response(batch, plans_and_versions):
    return {
        "batch_id": str(batch.pk),
        "plans": [
            {
                "plan_id": str(plan.pk),
                "version_id": str(version.pk),
                "version_number": version.version_number,
                "sku_code": plan.sku_code_snapshot,
                "plan_name": plan.name,
            }
            for plan, version in plans_and_versions
        ],
    }


@transaction.atomic
def save_profit_batch(*, organization, validated_data, actor, can_edit_all=False):
    """Recalculate original inputs and save all SKU versions in one transaction."""

    idempotency_key = str(validated_data["idempotency_key"]).strip()
    content = {key: value for key, value in validated_data.items() if key != "idempotency_key"}
    # Browser-supplied exchange values are deliberately excluded: persistence
    # always resolves them from the shared manual config or current rate record.
    hash_content = {key: value for key, value in content.items() if key not in {"cny_per_myr", "usd_per_myr"}}
    request_hash = _canonical_hash(hash_content)

    # The organization lock serializes both the empty first-write case and plan
    # version number allocation without relying on a racy unique-error retry.
    organization.__class__.objects.select_for_update().get(pk=organization.pk)
    existing = ProfitCalculationBatch.objects.filter(
        organization=organization, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise WorkflowConflictError("幂等键已用于不同的利润保存请求", code="idempotency_conflict")
        return existing.result, existing

    calculation_input = _calculation_payload(validated_data)
    working = ProfitCalculationWorkingConfig.objects.select_for_update().filter(
        organization=organization
    ).first()
    current_rate = ExchangeRateSnapshot.objects.filter(
        organization=organization, is_current=True
    ).first()
    if working is not None and working.rate_mode == "manual":
        if working.manual_cny_per_myr is None or working.manual_usd_per_myr is None:
            raise ValidationError("手工汇率配置不完整，不能保存利润方案")
        calculation_input["cny_per_myr"] = working.manual_cny_per_myr
        calculation_input["usd_per_myr"] = working.manual_usd_per_myr
        rate_source = "working_config_manual"
    elif current_rate is not None:
        calculation_input["cny_per_myr"] = current_rate.myr_cny
        calculation_input["usd_per_myr"] = current_rate.myr_usd
        rate_source = current_rate.source
    else:
        raise ValidationError("当前组织没有可用的权威汇率，不能保存利润方案")
    calculation_result = calculate_profit(calculation_input)
    if len(calculation_result.get("items", [])) != len(validated_data["items"]):
        raise ValueError("利润计算结果与输入 SKU 数量不一致")

    batch = ProfitCalculationBatch.objects.create(
        organization=organization,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        request_snapshot=jsonable({**content, "cny_per_myr": calculation_input["cny_per_myr"], "usd_per_myr": calculation_input["usd_per_myr"]}),
        created_by=actor,
    )
    exchange_snapshot = {
        "snapshot_id": str(current_rate.pk) if current_rate else None,
        "effective_date": current_rate.effective_date.isoformat() if current_rate else None,
        "source": rate_source,
        "cny_per_myr": str(calculation_input["cny_per_myr"]),
        "usd_per_myr": str(calculation_input.get("usd_per_myr")),
    }

    saved = []
    full_input_snapshot = jsonable(calculation_input)
    for index, item in enumerate(validated_data["items"]):
        sku_code, sku_name, image_url = _plan_snapshot(item)
        if item.get("action") == "new_version":
            plan = ProfitPlan.objects.select_for_update().get(
                pk=item["target_plan"].pk, organization=organization
            )
            if plan.status == ProfitPlan.Status.ARCHIVED:
                raise WorkflowConflictError("已归档方案请先恢复后再新增版本", code="profit_plan_archived")
            if not can_edit_all and plan.created_by_id != getattr(actor, "pk", None):
                raise WorkflowConflictError("只能为自己创建的利润方案新增版本", code="profit_plan_forbidden")
            if item.get("sku") is not None and plan.sku_id and plan.sku_id != item["sku"].pk:
                raise WorkflowConflictError("目标方案与本次 SKU 不一致", code="profit_plan_sku_mismatch")
            version_number = (
                plan.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0
            ) + 1
            plan.updated_by = actor
            plan.save(update_fields=["updated_by", "updated_at"])
        else:
            plan = ProfitPlan.objects.create(
                organization=organization,
                source_batch=batch,
                sku=item.get("sku"),
                store=item.get("store"),
                name=str(item.get("plan_name") or f"{sku_code} · 默认方案").strip(),
                sku_code_snapshot=sku_code,
                sku_name_snapshot=sku_name,
                image_url_snapshot=image_url,
                created_by=actor,
                updated_by=actor,
            )
            version_number = 1

        version = ProfitPlanVersion.objects.create(
            organization=organization,
            plan=plan,
            batch=batch,
            version_number=version_number,
            input_snapshot={
                "calculation": full_input_snapshot,
                "item_index": index,
                "metadata": jsonable({key: value for key, value in item.items() if key in METADATA_KEYS}),
            },
            result_snapshot={
                "calculation": calculation_result,
                "item_index": index,
                "item": calculation_result["items"][index],
            },
            exchange_rate_snapshot=exchange_snapshot,
            rule_version=str(calculation_result.get("rule_version") or "unknown"),
            created_by=actor,
        )
        saved.append((plan, version))

    response = _batch_response(batch, saved)
    batch.result = response
    batch.save(update_fields=["result", "updated_at"])
    write_audit(
        organization=organization,
        actor=actor,
        action="profit_record.batch.save",
        instance=batch,
        after={
            "plan_ids": [str(plan.pk) for plan, _version in saved],
            "version_ids": [str(version.pk) for _plan, version in saved],
            "sku_count": len(saved),
        },
        request_id=idempotency_key,
    )
    return response, batch

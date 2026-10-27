"""Additive v2 storage. MY v1 tables and immutable historical data stay intact."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from .models import OrganizationScopedModel, AppendOnlyManager


class MarketWorkspace(OrganizationScopedModel):
    country = models.CharField(max_length=2)
    config = models.JSONField(default=dict)
    revision = models.PositiveBigIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "country"], name="market_workspace_country")]


class MarketStrategy(OrganizationScopedModel):
    country = models.CharField(max_length=2)
    name = models.CharField(max_length=120)
    config = models.JSONField(default=dict)
    revision = models.PositiveBigIntegerField(default=1)
    is_default = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "country", "name"], name="market_strategy_name"),
                       models.UniqueConstraint(fields=["organization", "country"], condition=Q(is_default=True), name="market_strategy_default")]


class MarketSnapshot(OrganizationScopedModel):
    """Append-only rate, quote and plan evidence, scoped by organization/country."""
    country = models.CharField(max_length=2)
    currency = models.CharField(max_length=3)
    kind = models.CharField(max_length=12, choices=[("rates", "汇率"), ("quote", "报价"), ("plan", "方案")])
    name = models.CharField(max_length=120, blank=True)
    plan_key = models.UUIDField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()
    content_hash = models.CharField(max_length=64)
    valid_until = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    idempotency_key = models.CharField(max_length=100, blank=True)
    objects = AppendOnlyManager()
    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "created_by", "idempotency_key"], condition=~Q(idempotency_key=""), name="market_snapshot_request"),
                       models.UniqueConstraint(fields=["organization", "plan_key", "version"], condition=Q(kind="plan"), name="market_plan_version")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("市场快照不可修改")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("市场快照不可删除")


class SKUMarketProfile(OrganizationScopedModel):
    sku = models.ForeignKey("erp.SKU", on_delete=models.PROTECT, related_name="market_profiles")
    country = models.CharField(max_length=2)
    profile = models.JSONField(default=dict)
    revision = models.PositiveBigIntegerField(default=1)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["sku", "country"], name="sku_market_profile")]

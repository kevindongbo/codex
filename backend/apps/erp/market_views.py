"""Country-scoped v2 APIs. Manual scenarios are labeled, never official quotes."""
from datetime import timedelta
from decimal import Decimal
import uuid

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from .account_lifecycle import Conflict
from .market_calculator import (CATEGORIES, CURRENCIES, RULE_VERSION, SOURCES, CalculationInput,
    PackageInput, Weight, Dimensions, StrictSerializer, amount, calculate, digest, package_metrics, quote_binding)
from .models import MarketSnapshot, MarketWorkspace, MarketStrategy, Organization, OwnStore, SKU, SKUMarketProfile
from .permissions import request_organization, is_owner
from .profit_records import jsonable
from .services import write_audit
from .sync import bump_sync_revision


def require(request, capability="profit_rules"):
    from .views import _require_capability
    _require_capability(request, capability, "当前账号没有操作此功能的权限")
    return request_organization(request)


def country_of(raw):
    if raw not in ("US", "MX"):
        raise ValidationError({"country": "v2新市场接口请明确选择US或MX；MY继续使用兼容接口"})
    return raw


def enabled():
    if not settings.MARKET_V2_ENABLED:
        raise NotFound("美国试算暂未启用")


def country(request):
    enabled()
    query = request.query_params.get("country")
    body = request.data.get("country") if isinstance(request.data, dict) else None
    if query and body and query != body:
        raise ValidationError({"country": "查询参数与请求内容国家不一致"})
    c = country_of(query or body)
    if c == "MX" and not settings.MARKET_MX_ENABLED and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise ValidationError({"country": "墨西哥试算已暂停，历史记录保留只读"})
    return c


def check_store(org, data):
    if data.get("store_id"):
        store = get_object_or_404(OwnStore, pk=data["store_id"], organization=org, is_active=True)
        if store.country_code != data["country"] or store.currency != data["currency"]:
            raise ValidationError({"store_id": "店铺国家／币种与试算不一致，请先完善店铺市场"})
        if store.seller_program != data["seller_program"]:
            raise ValidationError({"seller_program": "卖家项目与店铺档案不一致"})
        if data["fulfillment_service"] not in store.fulfillment_capabilities:
            raise ValidationError({"fulfillment_service": "店铺档案尚未确认此履约能力；可使用未关联店铺的人工情景"})


@api_view(["GET"])
def markets(request):
    require(request)
    return Response({"markets": [
        {"code": "MY", "label": "马来西亚", "currency": "MYR", "mode": "legacy"},
        *[{"code": c, "label": n, "currency": CURRENCIES[c], "enabled": settings.MARKET_V2_ENABLED,
           "mode": "merchant_scenario", "official_status": "blocked", "reason": "官方末级类目、店铺税务资格及完整物流价表待核验；可填写有依据的人工情景"}
          for c, n in ([("US", "美国"), ("MX", "墨西哥")] if settings.MARKET_MX_ENABLED else [("US", "美国")])]]})


@api_view(["GET"])
def config(request):
    org = require(request)
    c = country(request)
    if c == "MX" and not settings.MARKET_MX_ENABLED:
        raise NotFound("墨西哥试算已暂停，历史记录保留只读")
    return Response({"schema_version": 2, "country": c, "currency": CURRENCIES[c], "rule_version": RULE_VERSION,
        "mode": "merchant_scenario", "sources": {k: v for k, v in SOURCES.items() if k.startswith(c)},
        "official_status": "blocked", "categories": [{"id": c + ":" + key, "label": "3C／数码 · " + label,
            "official_leaf_id": None, "mapping_status": "pending", "commission_hint": "6%仅供参考；请确认实际收费组及人工佣金"} for key, label in CATEGORIES],
        "fulfillment_services": [{"code": code, "label": label, "enabled": c == "US" or code != "platform_warehouse",
            "status": "manual_quote_required" if c == "US" or code != "platform_warehouse" else "not_verified"}
            for code, label in [("seller_shipping", "当地仓自发货"), ("platform_label_standard", "平台Standard面单"),
                                ("platform_collection", "平台揽收（需资格）"), ("platform_warehouse", "平台仓／FBT（需资格）")]],
        "stores": [{"id": str(s.pk), "name": s.name, "seller_program": s.seller_program, "capabilities": s.fulfillment_capabilities}
                   for s in OwnStore.objects.filter(organization=org, country_code=c, is_active=True)],
        "skus": [{"id": str(s.pk), "name": s.code + " · " + s.product.name,
                  "cost_cny": str(s.purchase_cost_cny) if s.purchase_cost_cny is not None else (str(s.cost) if s.currency == "CNY" else None),
                  "profile": next((p.profile for p in s.market_profiles.all() if p.country == c), {}),
                  "listings": [{"store": str(l.store_id), "price": str(l.price_amount),
                                "affiliate_rate": str(l.commission_override_percent) if l.commission_override_percent is not None else None}
                               for l in s.store_products.all() if l.country == c]}
                 for s in SKU.objects.filter(organization=org, active=True).select_related("product").prefetch_related("market_profiles", "store_products")[:1000]],
        "notes": ["尾程不默认免费；头程独立填写，已包含成本的项目明确填0并说明。",
                  "完整官方价卡尚未准入：包裹重量尺寸用于绑定人工报价，不自动猜测区域、体积重或旺季费用。"]})


class SKUProfileInput(StrictSerializer):
    revision = serializers.IntegerField(min_value=0)
    category_mapping_id = serializers.CharField(max_length=80)
    weight = Weight()
    dimensions = Dimensions()
    battery_profile = PackageInput().fields["battery_profile"]
    affiliate_rate = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal(0), max_value=Decimal(100), required=False, allow_null=True)


@api_view(["GET", "PUT"])
@transaction.atomic
def sku_profile(request, sku_id):
    org = require(request, "product_edit")
    c = country(request)
    Organization.objects.select_for_update().get(pk=org.pk)
    sku = get_object_or_404(SKU, pk=sku_id, organization=org)
    profile = SKUMarketProfile.objects.filter(organization=org, sku=sku, country=c).first()
    if request.method == "PUT":
        serializer = SKUProfileInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        revision(profile, data.pop("revision"))
        if data["category_mapping_id"] not in [c + ":" + key for key, _ in CATEGORIES]:
            raise ValidationError("SKU类目不属于当前国家")
        data = jsonable(data)
        if profile:
            profile.profile, profile.revision = data, profile.revision + 1
            profile.save()
        else:
            profile = SKUMarketProfile.objects.create(organization=org, sku=sku, country=c, profile=data)
        write_audit(organization=org, actor=request.user, action="sku.market_profile.update", instance=profile,
                    after={"country": c, "revision": profile.revision})
    return Response({"country": c, "sku_id": str(sku.pk), "profile": profile.profile if profile else {}, "revision": profile.revision if profile else 0})


def valid_config(c, value):
    if not isinstance(value, dict) or len(str(value)) > 150000:
        raise ValidationError({"config": "配置必须为不超过150KB的对象"})
    if value.get("country", c) != c or value.get("currency", CURRENCIES[c]) != CURRENCIES[c]:
        raise ValidationError({"config": "配置国家／币种不一致"})
    return value


def revision(record, value):
    current = record.revision if record else 0
    if type(value) is not int or value != current:
        raise Conflict("revision_conflict", "配置已被其他成员修改，请重新加载", current_revision=current)


@api_view(["GET", "PUT"])
@transaction.atomic
def working(request):
    org = require(request)
    c = country(request)
    Organization.objects.select_for_update().get(pk=org.pk)
    record = MarketWorkspace.objects.filter(organization=org, country=c).first()
    if request.method == "PUT":
        revision(record, request.data.get("revision"))
        value = valid_config(c, request.data.get("config"))
        if record:
            record.config, record.revision = value, record.revision + 1
            record.save()
        else:
            record = MarketWorkspace.objects.create(organization=org, country=c, config=value)
        bump_sync_revision(organization_id=org.pk)
    return Response({"country": c, "config": record.config if record else {}, "revision": record.revision if record else 0})


def strategy_payload(s):
    return {"id": str(s.pk), "country": s.country, "name": s.name, "config": s.config, "revision": s.revision, "is_default": s.is_default}


@api_view(["GET", "POST", "PATCH", "DELETE"])
@transaction.atomic
def strategies(request, strategy_id=None):
    org = require(request)
    c = country(request)
    Organization.objects.select_for_update().get(pk=org.pk)
    qs = MarketStrategy.objects.filter(organization=org, country=c)
    if request.method == "GET":
        return Response([strategy_payload(s) for s in qs.order_by("-is_default", "name", "id")])
    record = get_object_or_404(qs, pk=strategy_id) if strategy_id else None
    if request.method != "POST" and record is None:
        raise NotFound("策略不存在")
    if record:
        revision(record, request.data.get("revision"))
    if request.method == "DELETE":
        record.delete()
        return Response(status=204)
    name = request.data.get("name", record.name if record else "")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValidationError({"name": "策略名称须为1至120字符"})
    if qs.filter(name=name.strip()).exclude(pk=record.pk if record else None).exists():
        raise Conflict("strategy_name_conflict", "当前国家已有同名策略")
    value = valid_config(c, request.data.get("config", record.config if record else {}))
    is_default = request.data.get("is_default", record.is_default if record else False)
    if type(is_default) is not bool:
        raise ValidationError({"is_default": "须为布尔值"})
    if is_default:
        for old in qs.filter(is_default=True).exclude(pk=record.pk if record else None):
            old.is_default, old.revision = False, old.revision + 1
            old.save()
    if record:
        record.name, record.config, record.is_default, record.revision = name.strip(), value, is_default, record.revision + 1
        record.save()
    else:
        record = MarketStrategy.objects.create(organization=org, country=c, name=name.strip(), config=value, is_default=is_default)
    return Response(strategy_payload(record))


@api_view(["POST"])
@transaction.atomic
def activate(request, strategy_id):
    org = require(request)
    c = country(request)
    Organization.objects.select_for_update().get(pk=org.pk)
    s = get_object_or_404(MarketStrategy, pk=strategy_id, organization=org, country=c)
    revision(s, request.data.get("revision"))
    w = MarketWorkspace.objects.filter(organization=org, country=c).first()
    revision(w, request.data.get("working_revision"))
    if not w:
        w = MarketWorkspace(organization=org, country=c, config=s.config)
    else:
        w.config, w.revision = s.config, w.revision + 1
    w.save()
    return Response({"country": c, "config": w.config, "revision": w.revision})


class RateInput(StrictSerializer):
    country = serializers.ChoiceField(choices=["US", "MX"])
    cny_per_base = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"))
    usd_per_base = serializers.DecimalField(max_digits=14, decimal_places=6, min_value=Decimal("0.000001"))
    source = serializers.CharField(max_length=200)

    def validate(self, data):
        if data["cny_per_base"] <= 0 or data["usd_per_base"] <= 0:
            raise ValidationError("汇率必须大于0")
        if data["country"] == "US" and data["usd_per_base"] != 1:
            raise ValidationError("USD/USD必须为1")
        return data


def snapshot(s):
    return {"id": str(s.pk), "country": s.country, "currency": s.currency, "payload": s.payload,
            "content_hash": s.content_hash, "valid_until": s.valid_until, "created_at": s.created_at,
            "plan_key": str(s.plan_key) if s.plan_key else None, "version": s.version, "name": s.name}


@api_view(["GET", "POST"])
def exchange(request):
    org = require(request)
    c = country(request)
    if request.method == "GET":
        s = MarketSnapshot.objects.filter(organization=org, country=c, kind="rates").order_by("-created_at", "-id").first()
        return Response(snapshot(s) if s else {"id": None, "country": c, "missing": True})
    require(request, "exchange_manual")
    serializer = RateInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = jsonable(serializer.validated_data)
    data["source_type"] = "merchant_manual"
    s = MarketSnapshot.objects.create(organization=org, country=c, currency=CURRENCIES[c], kind="rates", payload=data,
                                     content_hash=digest(data), valid_until=timezone.now() + timedelta(hours=24), created_by=request.user)
    return Response(snapshot(s), status=201)


class QuoteLine(StrictSerializer):
    package_id = serializers.CharField(max_length=80)
    amount = amount()


class QuoteInput(StrictSerializer):
    country = serializers.ChoiceField(choices=["US", "MX"])
    currency = serializers.ChoiceField(choices=["USD", "MXN"])
    store_id = serializers.UUIDField(required=False, allow_null=True)
    seller_program = serializers.CharField(max_length=40)
    fulfillment_service = CalculationInput().fields["fulfillment_service"]
    packages = PackageInput(many=True, allow_empty=False)
    lines = QuoteLine(many=True, allow_empty=False)
    source = serializers.CharField(max_length=200)
    origin = serializers.CharField(max_length=120)
    destination = serializers.CharField(max_length=120)
    payment_channel = serializers.ChoiceField(choices=["platform", "offline"])
    includes = serializers.ListField(child=serializers.ChoiceField(choices=["pick_pack", "materials", "last_mile", "storage", "surcharges"]), allow_empty=False)
    eligibility_confirmed = serializers.BooleanField()
    battery_accepted = serializers.BooleanField()
    surcharges_confirmed = serializers.BooleanField()
    valid_for_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=60)

    def validate(self, data):
        if data["currency"] != CURRENCIES[data["country"]]:
            raise ValidationError("报价国家／币种不一致")
        if len(data["packages"]) > 100:
            raise ValidationError("包裹数量超限")
        ids = [p["client_package_id"] for p in data["packages"]]
        if len(set(ids)) != len(ids) or [l["package_id"] for l in data["lines"]] != ids:
            raise ValidationError("报价行必须按包裹顺序一一匹配")
        if not all(data[k] for k in ("eligibility_confirmed", "battery_accepted", "surcharges_confirmed")):
            raise ValidationError("请确认服务资格、电池承运及全部附加费")
        if any(p["battery_profile"] == "unknown" for p in data["packages"]):
            raise ValidationError("电池属性未知，不能确认有效报价")
        if data["country"] == "MX" and data["fulfillment_service"] == "platform_warehouse":
            raise ValidationError("墨西哥平台仓未核验，不可报价")
        if "last_mile" not in data["includes"]:
            raise ValidationError("请提交含当地尾程的完整履约报价")
        if data["fulfillment_service"] == "platform_warehouse" and not {"pick_pack", "materials", "last_mile"}.issubset(data["includes"]):
            raise ValidationError("平台仓报价须明确包含拣包、耗材、尾程；其他成本栏勿重复计入")
        if data["country"] == "MX" and data["fulfillment_service"] == "platform_label_standard":
            if any(Decimal(package_metrics(p)["actual_weight_g"]) > 30000 for p in data["packages"]):
                raise ValidationError("墨西哥Standard包裹超过30kg，不可外推报价")
        return data


@api_view(["POST"])
def shipping_quote(request):
    org = require(request)
    c = country(request)
    serializer = QuoteInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["country"] == "MX" and not settings.MARKET_MX_ENABLED:
        raise ValidationError({"country": "墨西哥试算已暂停，历史记录保留只读"})
    check_store(org, data)
    value = jsonable(data)
    value.update(binding_hash=quote_binding(data), source_type="merchant_manual", rule_version=RULE_VERSION)
    s = MarketSnapshot.objects.create(organization=org, country=c, currency=CURRENCIES[c], kind="quote", payload=value,
                                     content_hash=digest(value), valid_until=timezone.now() + timedelta(minutes=data["valid_for_minutes"]), created_by=request.user)
    return Response(snapshot(s), status=201)


def resolve_snapshot(org, c, key, kind):
    if not key:
        return None
    s = get_object_or_404(MarketSnapshot, pk=key, organization=org, country=c, kind=kind)
    if s.valid_until and s.valid_until <= timezone.now():
        raise Conflict("context_changed", "汇率或报价已过期，请重新确认")
    if kind == "rates":
        latest = MarketSnapshot.objects.filter(organization=org, country=c, kind=kind).order_by("-created_at", "-id").first()
        if latest.pk != s.pk:
            raise Conflict("context_changed", "共享汇率已更新，请重新计算")
    return s


def perform_calculation(org, raw):
    serializer = CalculationInput(data=raw)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["country"] == "MX" and not settings.MARKET_MX_ENABLED:
        raise ValidationError({"country": "墨西哥试算已暂停，历史记录保留只读"})
    check_store(org, data)
    for item in data["items"]:
        if item.get("sku_id") and not SKU.objects.filter(pk=item["sku_id"], organization=org).exists():
            raise NotFound("SKU不存在")
    rates = resolve_snapshot(org, data["country"], data.get("exchange_rate_set_id"), "rates")
    quote = resolve_snapshot(org, data["country"], data.get("shipping_quote_id"), "quote")
    if quote and quote.payload["binding_hash"] != quote_binding(data):
        raise Conflict("shipping_quote_mismatch", "包裹、店铺或履约方式已改变，请重新报价")
    return calculate(data, rates, quote)


@api_view(["POST"])
@transaction.atomic
def calculation(request):
    org = require(request)
    enabled()
    Organization.objects.select_for_update().get(pk=org.pk)
    return Response(perform_calculation(org, request.data))


@api_view(["GET"])
def plans(request, snapshot_id=None):
    org = require(request, "profit_record_view")
    c = country(request)
    qs = MarketSnapshot.objects.filter(organization=org, country=c, kind="plan")
    if not is_owner(request.user):
        qs = qs.filter(created_by=request.user)
    if snapshot_id:
        return Response(snapshot(get_object_or_404(qs, pk=snapshot_id)))
    return Response([{"id": str(s.pk), "name": s.name, "country": c, "currency": s.currency,
                      "plan_key": str(s.plan_key), "version": s.version, "created_at": s.created_at,
                      "gross_profit": s.payload["result"]["gross_profit"]} for s in qs.order_by("-created_at")[:100]])


@api_view(["POST"])
@transaction.atomic
def save_plan(request):
    org = require(request, "profit_record_edit")
    require(request)
    enabled()
    Organization.objects.select_for_update().get(pk=org.pk)
    raw = request.data.get("input")
    if not isinstance(raw, dict):
        raise ValidationError("需要原始试算输入")
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 100:
        raise ValidationError("必须提供不超过100字符的Idempotency-Key")
    request_hash = digest(request.data)
    previous = MarketSnapshot.objects.filter(organization=org, created_by=request.user, idempotency_key=key).first()
    if previous:
        if previous.payload.get("request_hash") != request_hash:
            raise Conflict("idempotency_conflict", "幂等键内容冲突")
        return Response(snapshot(previous))
    result = perform_calculation(org, raw)
    if result["calculation_status"] != "complete":
        raise ValidationError({"missing_inputs": result["missing_inputs"]})
    if request.data.get("expected_context_hash") != result["context_hash"]:
        raise Conflict("context_changed", "输入或规则上下文已改变，请重算后保存")
    plan_key = request.data.get("plan_key")
    version = 1
    if plan_key:
        try:
            plan_key = uuid.UUID(str(plan_key))
        except ValueError:
            raise ValidationError("方案标识无效") from None
        previous = MarketSnapshot.objects.filter(organization=org, plan_key=plan_key, kind="plan").order_by("-version").first()
        if not previous:
            raise NotFound("方案不存在")
        if previous.country != result["country"]:
            raise ValidationError("不能给已有方案换国，请另存新方案")
        if not is_owner(request.user) and previous.created_by_id != request.user.pk:
            raise PermissionDenied("只能修改本人创建的方案")
        if request.data.get("expected_version") != previous.version:
            raise Conflict("revision_conflict", "方案已有新版本，请重新加载")
        version = previous.version + 1
    name = request.data.get("name", "摄像头试算")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValidationError("方案名称须为1至120字符")
    s = MarketSnapshot.objects.create(organization=org, country=result["country"], currency=result["currency"], kind="plan",
        name=name.strip(), plan_key=plan_key or uuid.uuid4(), version=version,
        payload={"input": raw, "result": result, "request_hash": request_hash, "ui_draft": valid_config(result["country"], request.data.get("ui_draft", {}))}, content_hash=digest(result),
        created_by=request.user, idempotency_key=key)
    write_audit(organization=org, actor=request.user, action="profit.market.save", instance=s,
                after={"country": s.country, "currency": s.currency, "version": s.version, "context_hash": result["context_hash"]})
    bump_sync_revision(organization_id=org.pk)
    return Response(snapshot(s), status=201)

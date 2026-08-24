# 当前代码审计：V4 开工基线

审计时间：**2026-08-24 21:43 +08:00**

## 1. 基线

- 仓库：`kevindongbo/codex`
- 上一实现分支：`codex/erp-replenishment-v3-implementation-20260823`
- 上一实现 HEAD：`26083e6146ea2717d376065857045089d8b4e6aa`
- 新 V4 实现分支：`codex/erp-transfer-replenishment-v4-implementation-20260824`
- 新 V4 分支创建时与上一实现 HEAD 完全一致。
- 上一实现相对 `codex/erp-analytics-profit-creator-workflow-20260820`（`8c76fd377bcba18a7d853ebad75a942ab5607d3f`）ahead 2 commits。

上一 V3 实现已经改动：

- `app.js`
- `team.js`
- `index.html`
- `backend/apps/erp/models.py`
- `backend/apps/erp/replenishment.py`
- `backend/apps/erp/serializers.py`
- `backend/apps/erp/views.py`
- `backend/apps/erp/tests/test_replenishment.py`
- `tests/domain.test.mjs`
- `tests/site.test.mjs`
- `tests/team.test.mjs`
- 新 migration `0035_sku_replenishment_profile_v3.py`
- 每日检查 management command / systemd timer 文件

因此 V4 **不能从旧 PR #16 基线重新做一遍**，必须从新的 V4 实现分支继续，保留已经完成的 V3 改造。

---

# 2. 已经完成/基本完成的 V3 代码，不要回滚

## 2.1 调拨异常关闭幂等键前端已经补上

当前 `team.js` 的 `closeTransferException()` 已经：

- 标准化 `transfer_line + quantity`；
- 生成 `idempotencyKey('transfer-close-transit-exception', ...)`；
- 请求 `/stock-transfers/{id}/close-transit-exception/`；
- body 已包含 `idempotency_key`、`quantities`、`reason`；
- 成功后 `completeIdempotency(key)`。

因此 V4 **不要删除或重写掉这段幂等逻辑**。

用户截图里出现过 `idempotency_key: 该字段是必填项`，说明生产/截图版本可能不是当前 V3 实现分支，或者仍有旧静态资源/部署版本。V4 的任务是：保留当前正确实现并补回归测试，确保最终部署版本真实生效。

## 2.2 V3 补货核心销量公式已进入后端

当前 `backend/apps/erp/replenishment.py` 的 `estimate_demand_velocity()` 已明确：

- 只统计 `StockLedger.Type.SHIPMENT` 和 `MANUAL_OUTBOUND`；
- 排除 reversal；
- 退货/入库/调整不代表销量；
- Q3/Q7/Q15/Q30 使用总量；
- 加权 numerator = `quantity × weight`；
- denominator = `days × weight`；
- 不再使用错误的“各周期日均先乘权重”算法。

这是 V3 的关键业务真值，V4 只能修 UI/接口展示和未完成部分，不能改回旧算法。

## 2.3 SKU 级补货 Profile 已建立

migration `0035_sku_replenishment_profile_v3.py` 已新增 `SKUReplenishmentProfile`，包含：

- primary_warehouse；
- 3/7/15/30 SKU override 权重；
- target_coverage_days；
- manual_lead_time_days；
- min_order_qty nullable；
- pack_size nullable；
- SKU OneToOne。

迁移还把旧 `min_order_qty=1`、`pack_size=1` 默认值优先迁移成 null，符合 V3 语义。

本轮不要再新建第二套同语义模型。

---

# 3. 当前仍未完成：异常关闭原因可选

## 3.1 后端仍强制 reason

当前：

```python
class TransferExceptionCloseInputSerializer(TransferReceiveInputSerializer):
    reason = serializers.CharField(max_length=240)
```

仍然 required。

需要改为可空，并检查 view/service 不能直接使用 `validated_data['reason']` 假设必然存在。

## 3.2 前端仍 required

当前 `openTransferWorkflow(..., 'exception')` 仍生成：

```html
<input id="transferExceptionReason" maxlength="240" required />
```

必须去掉 `required`。

当前提交仍直接：

```js
$('#transferExceptionReason').value
```

需要 null guard。

## 3.3 “结束调拨”仍强制 reason

当前 `confirmTransferCompletion()` / `handleTransferCompleteSubmit()` 仍会：

```js
if (!reason) return showToast('请填写结束调拨的异常原因。');
```

`TransferCompleteWithExceptionInputSerializer` 也仍 required。

V4 要统一为可选，但保留二次确认和幂等。

---

# 4. 当前仍未完成：调拨商品明细展开

当前 `renderTransfers()`：

```js
const lineText = lines.slice(0, 2).map(...).join('<br>')
  + (lines.length > 2 ? '<br>等 ' + lines.length + ' 项' : '');
```

问题：

- 只渲染前两条；
- “等 N 项”是文本；
- 没有 `<details>`；
- 没有 toggle button；
- 没有完整列表 DOM；
- 没有图片 + 数量的统一视觉。

因此用户“点不开”是代码层面真实缺失，不是单纯 CSS 问题。

---

# 5. 当前仍未完成：全业务商品数量组件

现有 `productMedia(product)` 已经正确封装：

- 安全图片 URL；
- img；
- 无图占位；
- 商品名；
- SKU/辅助信息。

但采购、调拨、收货、异常关闭、订单等大量“商品 + 数量”场景仍自己拼字符串。

V4 应在现有函数上封装 `productQuantityMedia()` 或等价组件，避免每个页面重复实现和视觉不一致。

---

# 6. 当前仍未完成：智能补货主表字段

当前 `renderReplenishment()` 仍按：

```text
选择 | 商品 | 日均/velocity + 查看周期明细 | 预测到货周期 | 可用/在途 | 可售天数 | 最迟下单 | 建议量 | 紧急度 | 操作
```

缺少独立：

```text
近30天出库来源
```

而且“查看周期明细”仍然写在 velocity 的 `<td>` 内。

V4 必须按最终顺序重排。

---

# 7. 当前仍未完成：前端仍存在旧退货净销量文案/算法 fallback

虽然 V3 后端 forecast 已经不扣退货，但当前 `app.js` 仍有旧代码：

```js
const returns = ...
const net = ... ? ... : orderOutbound + manualOutbound - returns;
```

以及周期文字：

```text
订单 + 手动 - 退货 = 净销量
```

和：

```text
近 30 天没有订单出库或手动销售出库，或已被原销售日退货完全冲减
```

这些全部与 V3 最新业务规则冲突。

V4 要删除前端旧“退货冲减需求”口径，保证显示与后端一致：

```text
真实需求 = SHIPMENT + MANUAL_OUTBOUND
```

退货不扣历史需求。

---

# 8. 当前仍未完成：周期明细仍固定 7 天

当前：

- `getReplenishmentDemandDetail(product, 7)`；
- modal 标题“近 7 天”；
- fallback 平均值 `net / 7`。

V4 要改成 30 天来源，并把 3/7/15/30 周期信息和 30 天仓库来源统一放到“近30天出库来源”的详情交互中。

---

# 9. 当前仍未完成：智能补货按钮真实运行时验收

用户真实页面已经出现：

```text
Cannot set properties of null (setting 'value')
```

当前源码虽然存在大量事件绑定，但不能据此判定“按钮已完成”。

必须用浏览器逐个点击：

- 全局补货参数；
- 重新计算；
- 批量调整参数；
- 重新计算所选；
- 生成采购草稿；
- 创建采购；
- 调整参数；
- 恢复默认；
- 查看周期明细。

同时检查异步 `openPurchaseEditor()` 等路径，避免 modal 尚未初始化就写 `.value`。

---

# 10. 当前代码审计结论

V3 已经完成了后端核心补货公式、SKU Profile、部分 API/调度和异常关闭幂等前端；V4 不应重写这些部分。

V4 的真实重点是：

1. 原因可选的前后端契约；
2. 调拨明细真实展开；
3. 商品 + 数量视觉组件统一；
4. 智能补货字段位置和 30 天来源；
5. 清理旧退货冲减显示；
6. 7 天详情改 30 天；
7. 修复所有补货按钮运行时错误；
8. 完整回归 V3 核心公式和 migration。

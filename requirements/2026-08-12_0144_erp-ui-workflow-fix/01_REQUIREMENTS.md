# ERP 工作流修复需求说明

需求编号：`ERP-UI-WORKFLOW-FIX-20260812-0144`

上传时间：`2026-08-12 01:44 UTC+8`

实施分支：`codex/erp-ui-workflow-fix-20260812-0144`

基线：`codex/implement-erp-replenishment-intransit-store-20260811 @ 5b86a1192a2cabbfa564de9e842aa39d93bd87fa`

---

# 1. 本轮目标

本轮只修以下五类真实业务问题：

1. 利润试算“当前配置”刷新后丢失。
2. 订单“选择仓库/更换仓库”要求业务人员输入 UUID，必须改成正常可操作 UI。
3. 订单“取消”已有代码但实际点击不可用，需要定位真实故障并补回归测试。
4. 库存列表缺少“在途库存”；仓间调拨已有部分模型但物流包、发货、部分收货、异常关闭没有完整接通。
5. 店铺新增提示成功，但刷新/同步后店铺列表继续为空。

不要把本轮扩大成 ERP 全面重构。

---

# 2. 开工前检查

Codex 必须先执行：

```bash
git status --short
git branch -vv
git log --oneline --decorate -20
git reflog -20
```

如果发现本机存在未提交或未 push 的修改：

- 不允许覆盖；
- 先识别这些修改与本需求是否重叠；
- 能复用则复用；
- 不能确定时在最终报告中明确说明。

然后切换到：

```bash
git checkout codex/erp-ui-workflow-fix-20260812-0144
```

所有修改、migration、测试代码都提交到此分支，最终 push 到 GitHub。

不要自动 merge main，不要自动部署生产。

---

# 3. 需求一：利润试算当前配置自动保存

## 3.1 业务规则

采用“组织共享当前工作配置”。

用户修改利润试算中的配置项后自动保存，不需要点击“保存当前策略”。同一组织其他成员刷新后看到同一份最新配置。

正式命名策略继续独立存在，自动保存当前配置不能静默覆盖某个命名策略。

用户点击某个命名策略时：

1. 将命名策略内容加载到当前页面；
2. 同时把它作为组织当前工作配置保存；
3. 后续修改只修改当前工作配置，除非用户显式执行“覆盖命名策略”。

自动保存采用 debounce，建议 500–800ms。

UI 至少显示：

- `保存中…`
- `已保存`
- `保存失败，点击重试`
- 最后修改人
- 最后修改时间

## 3.2 自动保存范围

只保存团队共享配置项，至少包括现有 `strategyConfig()` 的：

```text
country
seller_type
shop_identity
bxp
commission_adjustment
buyer_pays_shipping
buyer_shipping_region
transaction_fee_adjustment
display_currency
```

以及汇率配置：

```text
rate_mode = auto / manual
manual_cny_per_myr
manual_usd_per_myr
```

当 `rate_mode=auto` 时，只保存 auto 模式，不把自动汇率快照误写成手工汇率。

## 3.3 明确不自动保存

以下内容仍然只属于当前页面会话，不自动同步为团队共享草稿：

```text
临时 SKU 行
SKU 名称
商品售价
商品成本
包装重量
单行达人佣金
单行广告数据
ROI / CPA
临时计算结果
```

## 3.4 当前代码审计结论

当前已有 `ProfitCalculationStrategy` 和命名策略 CRUD，但没有组织级 current working config。

因此需求一当前为：`未完成`。

## 3.5 推荐实现

新增一个组织唯一的 working config 模型，名称按项目风格决定，例如：

```python
class ProfitCalculationWorkingConfig(OrganizationScopedModel):
    config = models.JSONField(default=dict)
    rate_mode = models.CharField(...)
    manual_cny_per_myr = models.DecimalField(..., null=True, blank=True)
    manual_usd_per_myr = models.DecimalField(..., null=True, blank=True)
    updated_by = models.ForeignKey(..., null=True, blank=True)
```

约束：一个 organization 只有一条。

API 建议：

```text
GET /api/profit-calculator/working-config/
PUT /api/profit-calculator/working-config/
```

加载优先级：

```text
组织 working config
→ 没有则组织默认命名策略
→ 没有则系统默认配置
```

所有写入写 AuditLog，并触发组织 sync revision。

不要复用 `ProfitCalculationStrategy.is_default` 伪装工作草稿。

---

# 4. 需求二：订单选择仓库改为正常 ERP 弹窗

## 4.1 当前后端已经存在

当前代码已有：

```text
assign_order_warehouse()
change_order_warehouse()
POST /orders/{id}/assign-warehouse/
POST /orders/{id}/change-warehouse/
```

并且已具备：

- 整单 SKU 库存校验；
- 全部充足后才锁库；
- 目标仓不足则整单拒绝；
- 换仓前先校验新仓；
- 新仓不足不破坏旧仓 reservation；
- transaction；
- idempotency；
- AuditLog。

这些逻辑优先复用，不允许重新写第二套。

## 4.2 当前真正的问题

前端仍使用类似：

```javascript
window.prompt('输入仓库编号...')
```

并将数据库 UUID 暴露给业务人员人工输入。

需求二当前为：`后端基本完成，前端未完成`。

## 4.3 新 UI

点击：

```text
选择仓库
```

或：

```text
更换仓库
```

打开正式弹窗。

每个仓库至少显示：

```text
仓库名称
仓库编码

SKU-A
需要：11
可用：216
缺口：0

SKU-B
需要：5
可用：2
缺口：3
```

仓库状态：

```text
✓ 库存充足，可选择
✕ 库存不足，缺 N 件
```

不足仓允许查看，但选择按钮禁用。

未映射 ERP SKU 的订单行必须明确显示，并使所有仓库不可选择。

## 4.4 推荐预检 API

新增只读接口，例如：

```text
GET /api/orders/{id}/warehouse-options/
```

返回当前用户有权限且可出库的仓库及每个 SKU 的：

```text
required
available
shortage
selectable
```

此接口只能读取，不得产生 reservation。

用户点击“选择此仓库”后再调用现有 assign/change API。

选择成功即完成整单 reservation，不再让用户多点一个“锁库”。

---

# 5. 需求三：ERP 订单取消必须真实可用

## 5.1 当前代码审计

前端和后端已经存在 cancel 调用链，后端 `cancel_order()` 也包含释放 reservation 的逻辑。

因此不能把它标记为“完全没做”。

但用户实际系统中点击取消仍不可用，所以当前状态为：`已有代码，但存在真实回归 Bug`。

Codex 不允许只看到函数存在就宣布完成。

## 5.2 最终业务含义

“取消”仅代表：

```text
停止 ERP 内部履约
```

不代表：

```text
调用 TikTok API 取消买家平台订单
```

不要给 TikTok/Shopee/Ozon 等平台发送远端取消请求。

## 5.3 点击取消后的行为

1. 前端显示二次确认；
2. 确认后只发一次 cancel 请求；
3. 未锁库订单直接变 ERP CANCELLED；
4. 已锁库订单原子释放 reservation；
5. 已出库订单必须返回可理解的 4xx 业务错误；
6. 成功后立即刷新列表；
7. 不能点击没反应；
8. 不能重复请求造成重复释放；
9. 失败不能被吞掉或只显示笼统 HTTP 500。

## 5.4 平台后续同步规则

ERP 人工取消后，即使后续平台同步仍显示订单有效：

- ERP 不自动恢复履约；
- 只更新平台侧状态/快照；
- 页面应能表达类似：

```text
平台：仍有效
ERP：已停止履约
```

必须人工执行：

```text
恢复履约
```

恢复后：

```text
warehouse 清空
旧 reservation 必须不存在
订单回待处理
重新选择仓库
重新校验库存
重新锁库
```

可用字段名按项目风格设计，例如：

```text
erp_cancelled_at
erp_cancelled_by
platform_status
fulfillment_override
```

关键是领域语义要存在，不能让未来平台同步覆盖 ERP 人工停止履约。

## 5.5 必须定位真实故障

必须覆盖：

```text
DRAFT cancel
READY cancel
ALLOCATED cancel + release reservation
PICKING cancel（按现有业务允许范围）
VERIFIED cancel（按现有业务允许范围）
SHIPPED reject
double click / replay
```

并做真实前端链路测试：

```text
点击取消
→ 确认弹层
→ POST 一次
→ 成功
→ UI 更新
```

如果历史数据出现：

```text
order.quantity_reserved > 0
但 StockReservation 缺失
```

不能静默失败。应提供可诊断错误，并视实际数据情况提供 repair migration/management command。

---

# 6. 需求四 A：库存列表增加在途库存

## 6.1 当前已有

后端已存在：

```text
StockBalance.in_transit
StockBalance.purchased_pending_shipment
```

前端 TeamGateway 也已经读取服务器 `in_transit`。

但当前库存表未展示。

因此当前状态：`后端已有，前端未完成`。

## 6.2 库存列表

至少展示：

```text
仓库商品
SKU
已在库
锁定
可用
在途库存
安全库存
库存金额
状态
操作
```

`在途库存` 使用服务器真实 `StockBalance.in_transit`。

定义：

```text
在途库存 =
已确认发货、尚未收货/异常关闭的采购在途
+
已确认发出的调拨入库在途
```

在途只属于目的仓。

以下不算在途：

```text
采购草稿
已提交但尚未确认发货的采购数量
```

已有“已采购待发货”继续保持独立，不与 in_transit 合并。

## 6.3 在途详情

在途数量应支持查看来源明细，至少包含：

```text
来源类型：采购 / 仓间调拨
来源单号
物流单号（如有）
剩余在途数量
发货时间
```

总明细必须与 `StockBalance.in_transit` 对得上。

不要从 `StockLedger.on_hand_delta` 猜在途数量。

优先根据真实业务单据计算：

```text
PurchaseShipment / PurchaseShipmentLine / package
StockTransfer / StockTransferPackage / StockTransferLine
```

---

# 7. 需求四 B：仓间调拨物流完整接通

## 7.1 已有模型必须复用

当前已经存在：

```text
StockTransfer
StockTransferLine
StockTransferPackage
StockTransferPackageLine
StockTransferReceipt
```

不要再创建第二套 transfer/package 模型。

## 7.2 调拨物流 UI

一个调拨单允许多个物流包，例如：

```text
TR-001

包裹 1
物流单号 JT123
SKU-A × 60
SKU-B × 10

包裹 2
物流单号 JT456
SKU-A × 40
SKU-B × 20
```

物流单号允许为空，后续补录。

即使没有 tracking number，也必须先有 package 承载 SKU 数量。

## 7.3 调拨生命周期

保持：

```text
创建草稿
→ 来源仓预占
→ 配置 package
→ 确认发货
→ 来源仓实际扣库 + 释放调拨 reservation
→ 目标仓增加 in_transit
→ 部分/全部收货
→ 目标仓 in_transit 减少 + on_hand 增加
```

发货后不能直接 cancel/delete。

异常丢失：

```text
关闭在途异常
→ 目标仓 in_transit 减少
→ 不增加目标仓 on_hand
→ 不恢复来源仓库存
→ 保存原因和 AuditLog
```

## 7.4 package API

提供 package 查询和编辑能力，具体路径可按现有 DRF 风格，例如：

```text
GET /stock-transfers/{id}/packages/
PUT /stock-transfers/{id}/packages/
```

只有 DRAFT 可改 package SKU 数量。

确认发货前，对每个 SKU 强校验：

```text
sum(package_line.quantity) == StockTransferLine.quantity
```

少一件、多一件都不能发货。

发货后：

- package SKU 数量锁定；
- tracking number 允许后补；
- tracking 修改写 AuditLog。

## 7.5 真正的部分收货

当前接口存在“传 quantities 后要求包含全部 SKU”的行为，需要修改。

新规则：

- 本次可以只提交真正收到的 SKU；
- 未提交的 SKU 保持原状；
- 每条数量 > 0；
- 不超过该 SKU 当前剩余在途。

例如：

```json
{
  "idempotency_key": "...",
  "quantities": {
    "line-A": "50"
  }
}
```

只收 A 50 件，B 不动。

## 7.6 异常关闭数量不能伪装成已收货

不要为了把单据结清而把“丢失 2 件”加进 `received_quantity`。

正确数据语义应为：

```text
计划 100
实际收到 98
异常关闭 2
剩余在途 0
```

推荐新增：

```text
exception_closed_quantity
```

或独立不可变 exception event。

公式：

```text
remaining_transit
= quantity
- received_quantity
- exception_closed_quantity
```

最终状态：

```text
COMPLETED_WITH_EXCEPTION
```

---

# 8. 需求五：店铺保存成功但列表为空

## 8.1 当前后端已有

已经存在：

```text
OwnStore
OwnStoreSerializer
OwnStoreViewSet
/stores/
/store-products/
```

组织内店铺名称有唯一约束。

手工创建店铺不依赖 TikTok OAuth，这一点保持不变。

## 8.2 已定位的明确根因

TeamGateway 已经从服务器加载：

```text
/stores/
/store-products/
```

`adaptState()` 也返回：

```javascript
stores: raw.stores || []
storeProducts: raw.storeProducts || []
```

但 `app.js` 的 `normalizeV5(saved)` 重新从 `emptyState()` 构造状态时，没有把这些字段复制回来。

因此实际链路变成：

```text
POST /stores/ 成功
→ toast 显示店铺已创建
→ loadState() 从服务器读到店铺
→ adaptState() 带回 stores
→ normalizeV5() 丢掉 stores/storeProducts
→ renderStores() 读到空数组
→ 页面仍显示尚未创建店铺
```

这是明确前端状态归一化 Bug。

## 8.3 必须修复

`emptyState()` 至少初始化：

```javascript
stores: [],
storeProducts: [],
profitCategories: []
```

`normalizeV5(saved)` 至少保留：

```javascript
base.stores = Array.isArray(saved.stores) ? saved.stores : [];
base.storeProducts = Array.isArray(saved.storeProducts) ? saved.storeProducts : [];
base.profitCategories = Array.isArray(saved.profitCategories) ? saved.profitCategories : [];
```

同时检查本次新增的 server state 字段，防止 normalize 再次静默丢字段。

## 8.4 保存成功的验收定义

必须满足：

```text
POST 成功
→ UI 立即出现新店铺
→ F5
→ GET /stores/ 仍返回新店铺
→ normalize 后仍存在
→ renderStores 仍显示
```

不允许只弹 toast 就算完成。

## 8.5 店铺平台字段收口

当前 OwnStore 同时存在：

```text
platform_code
custom_platform_name
platform
```

前端不能永远只传旧 `platform`，否则 Shopee/Ozon/Other 也可能仍落成默认 TikTok code。

建议：

- `platform_code` 为机器字段；
- common platform 使用预设；
- `other` 要求 `custom_platform_name`；
- `platform` 可保留为兼容展示字段或后端派生；
- 不创建第二套 Store 模型。

---

# 9. 必须新增的自动测试

## 9.1 Working config

- 修改配置触发 debounce PUT。
- debounce 多次修改只保存最后一次。
- F5 后配置不丢。
- 成员 A 修改，成员 B 刷新看到新配置。
- 临时 SKU/售价/成本/广告输入不进入 working config。
- 命名策略仍独立存在。
- 点击命名策略后 working config 同步更新。
- 保存失败有可见状态和重试。

## 9.2 Warehouse modal

- 页面不再使用 `window.prompt` 输入仓库 UUID。
- 显示 warehouse code/name。
- 显示每 SKU required/available/shortage。
- 缺货仓不能选择。
- 充足仓选择后整单 reservation 成功。
- 换仓新仓不足时旧 reservation 不受影响。
- 未映射 SKU 时所有仓库禁用。

## 9.3 Cancel

- DRAFT cancel。
- READY cancel。
- ALLOCATED cancel 并 release。
- SHIPPED 返回业务错误。
- duplicate request 不重复释放。
- 前端 click → confirm → POST 一次 → UI 更新。
- ERP 人工取消后平台状态变化不能自动恢复履约。
- restore fulfillment 后必须重新选仓和重新锁库。

## 9.4 Inventory transit

- purchase transit + transfer transit 汇总正确。
- 未确认发货采购不计 in_transit。
- 调拨只在目的仓体现 in_transit。
- 收货后 in_transit 下降。
- 异常关闭后 in_transit 下降。
- F5 后值不丢。

## 9.5 Transfer logistics

- 一个 transfer 多 package。
- 一个 package 多 SKU。
- tracking 可空。
- 发货前 package SKU 合计必须完全等于 transfer plan。
- 发货后 package quantity 不可修改。
- tracking 可后补。
- 部分收货可以只提交一个 SKU。
- 异常关闭不增加 received_quantity。
- 发货后 cancel 被拒绝。

## 9.6 Store

- POST store 成功。
- GET stores 返回新店。
- adaptState 后存在。
- normalizeV5 后仍存在。
- renderStores 显示。
- F5 后仍显示。
- create/update/delete/toggle 均不因 normalize 丢状态。
- 非 TikTok 平台 platform_code 正确。

---

# 10. 建议实施顺序

1. 先修 `normalizeV5()` 丢 stores/storeProducts/profitCategories。
2. 给店铺保存与刷新加自动测试。
3. 新增 Profit Working Config 模型/API/migration。
4. 接利润配置 debounce autosave。
5. 新增 order warehouse options/preflight API。
6. 正式仓库选择弹窗替代 UUID prompt。
7. 真实复现并修订单取消。
8. 增加 ERP manual-cancel override / restore fulfillment。
9. inventory table 显示 inTransit。
10. 接通 transfer package API/UI。
11. 修真正的 transfer partial receive。
12. 分离 transfer received 与 exception closed。
13. 跑完整测试。
14. commit 并 push 本需求分支。

---

# 11. 不允许的实现方式

- 不创建第二套 Store。
- 不创建第二套 StockTransfer/Package。
- 不重写已经可复用的 assign/change warehouse 后端。
- 不继续使用 UUID prompt。
- 不把 localStorage 当组织共享业务配置数据库。
- 不把异常丢失数量伪装为实际收货。
- 不用 toast 代替真实状态持久化验证。
- 不静默吞 API 错误。
- 不自动 merge main。
- 不自动部署生产。

---

# 12. 最低测试命令

根据当前项目至少运行：

```bash
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py test apps.erp.tests --noinput

node --check app.js
node --check team.js
node --check profit-calculator.js

node --test tests/site.test.mjs
node --test tests/domain.test.mjs
node --test tests/team.test.mjs

node scripts/build-site.mjs
```

如果仓库实际测试命令已变化，以当前 package/project 配置为准，但不能少跑现有后端和前端测试。

---

# 13. Codex 最终交付格式

Codex 完成后必须输出：

```text
Implementation branch:
Final HEAD SHA:
PR:
Migrations:
Modified files:
Tests run:
Tests passed/failed:
New regression tests:
Known remaining issues:
Deployment impact:
Rollback impact:
```

并逐项：

```text
1 利润当前配置自动保存：PASS / FAIL
2 仓库选择弹窗：PASS / FAIL
3 ERP 取消订单：PASS / FAIL
4 库存在途 + 调拨物流：PASS / FAIL
5 店铺保存并显示：PASS / FAIL
```

只要仍存在以下任意情况，就不能写“全部完成”：

```text
仍要求业务人员输入 UUID
刷新后丢配置或店铺
取消按钮点击无有效结果
后端有字段但前端不可见
调拨 package 模型存在但业务 UI 无法操作
测试未覆盖真实前端链路
```

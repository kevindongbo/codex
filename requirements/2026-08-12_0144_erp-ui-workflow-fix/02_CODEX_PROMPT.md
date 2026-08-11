# Codex 执行提示词

请在 GitHub 仓库 `kevindongbo/codex` 中完成本次 ERP 修复。

## 1. 指定分支

必须使用：

```text
codex/erp-ui-workflow-fix-20260812-0144
```

该分支已经从：

```text
codex/implement-erp-replenishment-intransit-store-20260811
```

创建，需求上传时间为：

```text
2026-08-12 01:44 UTC+8
```

不要直接修改 main，不要自动 merge，不要部署生产。

## 2. 先阅读需求

首先完整阅读：

```text
requirements/2026-08-12_0144_erp-ui-workflow-fix/00_README.md
requirements/2026-08-12_0144_erp-ui-workflow-fix/01_REQUIREMENTS.md
```

以 `01_REQUIREMENTS.md` 为本轮业务验收标准。

## 3. 开工前先保护已有工作

先执行：

```bash
git status --short
git branch -vv
git log --oneline --decorate -20
git reflog -20
```

如果发现尚未提交或尚未 push 的本地修改，不要覆盖。先识别这些修改和本需求是否重复，能复用则复用，并在最终报告说明。

然后确认当前工作分支：

```bash
git checkout codex/erp-ui-workflow-fix-20260812-0144
git pull --ff-only origin codex/erp-ui-workflow-fix-20260812-0144
```

## 4. 本轮只处理五项

1. 利润试算当前配置刷新后丢失：实现组织共享 working config + debounce 自动保存；临时 SKU/售价/成本/广告试算内容不要自动共享保存。
2. 订单选择/更换仓库：保留已有后端 assign/change 逻辑，删除 UUID `window.prompt`，做正式仓库选择弹窗和库存预检。
3. ERP 取消订单：当前代码已有但实际有回归故障，必须真实复现、定位、修复并增加前后端回归测试；ERP 取消只停止内部履约，不调用平台 API 取消买家订单。
4. 库存在途 + 仓间调拨物流：库存列表展示已有 `in_transit`；复用现有 StockTransferPackage/Line 接通物流包 API/UI、发货校验、真正的部分收货、异常关闭；异常关闭数量不能伪装为 received quantity。
5. 店铺新增后列表为空：优先修明确的前端状态归一化 Bug，确保 `stores/storeProducts/profitCategories` 不再被 `normalizeV5()` 丢失；创建后立即显示且 F5 后仍显示。

不要把本轮扩大成 ERP 全面重构。

## 5. 优先复用现有实现

重点检查并复用：

```text
ProfitCalculationStrategy
assign_order_warehouse
change_order_warehouse
cancel_order
StockBalance.in_transit
StockBalance.purchased_pending_shipment
StockTransfer
StockTransferPackage
StockTransferPackageLine
StockTransferReceipt
OwnStore
OwnStoreSerializer
OwnStoreViewSet
TeamGateway.loadState/adaptState
app.js normalizeV5
```

禁止为同一业务再创建第二套 Store、Transfer、Package 或订单选仓领域模型。

## 6. 店铺 Bug 已知根因，先验证再修

当前已知链路：

```text
/stores/ 返回成功
TeamGateway.adaptState() 已返回 stores/storeProducts
app.js normalizeV5() 从 emptyState() 重建后没有保留这些字段
renderStores() 因此重新看到空列表
```

先用测试复现，再修复。不要重新实现 Store 后端 CRUD 来绕过问题。

## 7. 订单仓库选择

不得再使用：

```javascript
window.prompt(...UUID...)
```

建议增加只读 `warehouse-options`/preflight API，返回每个可操作仓库每个 SKU 的：

```text
required
available
shortage
selectable
```

前端以仓库卡片/表格展示；库存不足仓不可选择。真正点击“选择此仓库”后再调用现有 assign/change API，并一次完成整单 reservation。

## 8. 订单取消

必须测试真实 UI 链路：

```text
点击取消
→ 二次确认
→ cancel API 调用一次
→ reservation 正确释放
→ 订单变 ERP CANCELLED
→ UI 立即更新
```

需要覆盖 DRAFT、READY、ALLOCATED、PICKING、VERIFIED、SHIPPED、重复请求。

平台后续同步不能自动覆盖 ERP 人工停止履约。实现人工“恢复履约”时必须清除旧锁库、清空 warehouse 并重新选仓。

## 9. 调拨

发货前必须确保每个 SKU：

```text
sum(package sku quantity) == transfer planned quantity
```

tracking number 允许为空并后补。

部分收货允许本次只提交实际收到的 SKU，不要求请求包含所有 SKU。

异常关闭必须保持：

```text
received_quantity = 实际收到
exception_closed_quantity = 丢失/异常关闭
remaining = planned - received - exception
```

不要把 exception 数量加到 received_quantity。

## 10. 测试

至少运行：

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

如果仓库测试入口有变化，以当前工程配置为准，但必须运行完整现有后端和前端测试，并新增本需求回归测试。

## 11. 提交与 push

完成后：

```bash
git status
git diff --stat
git add -A
git commit -m "fix(erp): complete workflow persistence warehouse transit and store fixes"
git push origin codex/erp-ui-workflow-fix-20260812-0144
```

如需要多个逻辑清晰的 commit，可以拆分，但全部必须 push 到同一需求分支。

不要 merge main。

## 12. 最终回复格式

完成后请完整回复：

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

如果任何一项仍存在“UUID 人工输入、刷新丢数据、点击无反应、后端有模型但 UI 不能操作、测试未覆盖真实链路”，不得标记全部完成。
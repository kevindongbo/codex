# PR #12 第二轮严格修复需求

需求编号：`ERP-REPLENISHMENT-INTRANSIT-STORE-20260811-FIX-01`

基线：`codex/implement-erp-replenishment-intransit-store-20260811` @ `d47fed21f2f45d747f87d6c4efc45b3e93020aa3`

PR #12 目前只能视为“部分实现”。以下项目全部完成并测试通过前，不得声称原需求已完成。

## P0-1 订单 HTTP 500 与人工选仓

1. `SalesOrderLine.sku` 已允许为空，但 `confirm_order/allocate_order/confirm-and-ship` 等路径仍直接访问 `line.sku.product/active/code`。未映射 SKU 必须返回 4xx 业务错误，响应至少包含订单号、`external_sku_code` 和“SKU 未映射，不能锁库/出库”，绝不能 500。
2. 新增人工选仓 API（等价 `POST /orders/{id}/assign-warehouse/`）：在一个事务里锁订单/订单行/库存，整单检查目标仓 available；任一 SKU 不足整单失败并返回 required/available/shortage；全部足够才设置 warehouse 并立即创建 StockReservation、增加 reserved。
3. 新增出库前换仓 API（等价 `change-warehouse`）：先校验新仓，失败时旧仓预占保持；成功后原子释放旧仓并在新仓完整预占；已有 Shipment 后禁止换仓。
4. 前端：无仓订单显示“选择仓库”；已选仓未出库显示“更换仓库”；库存不足显示 SKU 级缺口；锁库成功前不允许直接“确认并出库”。删除 `(order.warehouseId || DEFAULT_WAREHOUSE_ID)` 这类把无仓订单伪装成默认仓的逻辑。
5. 新增回归测试：`sku=None + external_sku_code=AI-BAG-JALUR-08` 调 confirm/allocate/confirm-and-ship 返回业务错误而非 HTTP 500。

## P0-2 修复库存阶段公式

6. `已采购待发货` 正确公式：`ordered - confirmed_shipped - unshipped_closed`。不能再减 received，因为 received 已包含在 confirmed_shipped 的后续阶段。验收：ordered=100、shipped=40、received=30 => pending=60。
7. 采购在途：`confirmed_shipped - received - transit_exception_closed`。上例 in_transit=10。
8. 同 SKU 同仓若采购在途=10、调拨在途=5，总 in_transit 必须=15。当前 `purchase_in_transit if purchase_in_transit else transfer_in_transit` 会吞掉一种来源，必须修正。若持久化 `StockBalance.in_transit` 作为唯一事实，则所有动作统一维护它，查询不得重复派生相加。
9. 采购提交/确认发货/收货/异常关闭/未发货关闭，以及调拨发货/收货/异常关闭，都走统一事务化库存领域服务，不要散落直接 `balance.in_transit +=`。

## P0-3 修复 migration

10. 原需求是旧 `review_cycle_days` 初始化新 `coverage_days`。当前 0028 对 warehouse default 使用 `target_days`，需要新的 forward repair migration；如果 0028 已执行，不得改历史 migration 假装没发生。只能安全修正可识别的旧初始化值，不能覆盖上线后人工改过的 coverage。
11. 真实调拨状态是小写 `in_transit/partially_received`，0028 却用大写值查询。新增幂等 repair migration：补建遗漏的历史迁移 package 和剩余在途，不重复扣来源库存、不重复加目标在途，并写 migration test。

## P0-4 采购发货批次必须真正可用

12. 采用 `PurchaseShipment(批次) -> PurchaseShipmentPackage -> PackageLine` 两层结构即可，但必须有完整 API/UI。
13. 草稿批次支持新增/删除 package、tracking 可空、配置每包 SKU 数量；草稿编辑不改变 pending/in_transit。
14. 增加“确认本批发货”：汇总包内 SKU 数量，不能超过剩余未发货；批次只能确认一次；`pending -= qty`、`in_transit += qty`；写 confirmed_at/by 和 AuditLog；tracking 为空可确认，后补 tracking 不得重复增加在途。
15. 采购收货必须选择具体批次，支持同批次多次部分收货；本次实收不能超过该批次 SKU 剩余在途；收货 `in_transit -= qty`、`on_hand += qty`。
16. 增加采购在途异常关闭：具体批次+SKU，必填原因；`in_transit -= exception_qty`，on_hand 不增加，历史 confirmed/received 不改。
17. 增加关闭未发货数量：针对当前 pending，原 quantity_ordered 不改，必填原因，pending 减少。
18. 全部订购数量被 received / transit exception / unshipped close 核销后允许结束；存在异常则状态 `COMPLETED_WITH_EXCEPTION` 或等价业务字段。

## P0-5 调拨物流与异常必须真正落地

19. 草稿创建预占已有基础，但编辑必须增量调整预占：增加数量加 reserved、减少/删行释放 reserved；任一 SKU 不足整单失败并回滚。
20. 调拨多 package API/UI：tracking 可空，每包 SKU 数量可配置。
21. dispatch 前每 SKU 强校验 `sum(package sku qty) == transfer planned qty`。确认发货时来源 `on_hand -= qty`、`reserved -= qty`，目的 `in_transit += qty`，整单一次确认且幂等。
22. 当前前端仍“确认全部到达”，必须改为部分收货弹窗：显示 planned / cumulative received / remaining，每 SKU 输入本次实收，可多次提交，未完成状态 `partially_received`。
23. 增加调拨在途异常关闭：目的 in_transit 减少、目的 on_hand 不增加、来源不恢复、必填原因；全部核销且有异常 => `completed_with_exception`。
24. 已发出禁止 cancel 这一条方向正确，保留并补 API/UI 测试。

## P1-1 统一净销量补齐

25. 保留已完成的跨仓统一 `SHIPMENT` 销量、排除 `MANUAL_OUTBOUND`。同时修正 reasons 文案，不能再写“包含手动出库”。
26. 实现退货回溯原销售日：真实退货/退款都冲减原销售日净销量；RESTOCK 和 DAMAGED 都冲销量，只有 RESTOCK 增库存；未关联原订单的退货暂不冲销量并标记未关联。
27. 外部 SKU 映射完成后，回填“同店铺 + 同 external_sku_code”最近 30 天未映射订单行到 internal SKU，保留 external 字段并写 AuditLog；不得误回填其它店铺同名外部 SKU。

## P1-2 补货建议转采购重做

28. 预测结果需要真正生成/持久化 ReplenishmentRecommendation snapshot，而不是只有模型。
29. 人工修改保留 system_suggested 和 user_confirmed，这部分可复用。
30. 一条 recommendation 要支持多次转换。当前单一 `conversion_idempotency_key` 会阻止第二次转换。应建立独立 conversion event（含 recommendation、quantity、idempotency_key、purchase_order/line、actor/time）。
31. convert 必须创建真实 `PurchaseOrder(status=DRAFT)` 和 `PurchaseOrderLine`，而不是只把 converted 数字加大。按 `warehouse + supplier` 自动分组；无默认 supplier 时前端先要求选择；草稿本身不计入 pending，submit 后才进入 pending。
32. 前端支持多选建议批量转采购，展示 system / confirmed / converted / remaining。验收：系统500→人工350→转200→再转150；两次都成功并生成真实草稿，remaining=0；再转1失败。

## P1-3 店铺与 TikTok OAuth 真正分离

33. OwnStore 手动 CRUD：TikTok/Shopee/Ozon/Other，Other 必填 custom platform，market 可空，同组织 name 唯一，无 OAuth 也能保存。
34. OAuth 从已有 ERP Store 发起并携带 target store context；callback 返回多个 remote shop 时只给候选，不自动创建 OwnStore；用户选一个绑定当前 store；其它 remote shops 不自动建店；market 空可自动补 region，冲突则阻止绑定。
35. 检查旧 TikTokConnection 是否真正迁移绑定 OwnStore；若 0028 未完成，需要 forward data migration/管理命令并输出冲突报告。

## P1-4 库存列表与前端核对

36. SKU×仓库库存表实际展示 `on_hand / reserved / available / purchased_pending_shipment / in_transit`。
37. pending 点击查看 PO/supplier/qty；in_transit 点击查看 source type、单号、采购批次/调拨、package/tracking、remaining qty。
38. TEAM_MODE 与本地模式不能保留不同核心业务捷径；补货转采购、调拨部分收货、订单选仓都必须走真实后端业务链。

## 必测场景

1. 未映射 SKU 出库是 4xx，不是500。
2. 无仓订单选仓成功整单预占；任一 SKU 不足整单回滚并返回 shortage。
3. 换仓失败保留旧预占；成功原子迁移。
4. ordered100/shipped40/received30 => pending60/in_transit10。
5. 采购在途10+调拨在途5 => 总在途15。
6. tracking 空可发货，后补 tracking 不重复入途。
7. 采购部分收货+异常关闭+关闭未发货 => completed_with_exception。
8. 调拨草稿编辑正确增减 reserved。
9. 调拨包分配不等计划量禁止 dispatch。
10. 调拨100→收60→收38→异常2 => completed_with_exception；来源不恢复2。
11. 历史小写 in_transit/partially_received migration repair。
12. 销售10后退2 => 原销售日净销量8；手动/调拨出库不计销量。
13. 外部 SKU 映射只回填同店近30天。
14. 推荐500→确认350→转200→转150，真实采购草稿产生且剩余0。
15. OAuth 返回3店只绑定用户选中的1店。
16. 前端测试覆盖选择仓库、SKU未映射、部分收货、pending/in-transit 列。

## 完成定义

只有以下全部满足才可回复“已完成”：

- P0/P1 全部落地；
- `python manage.py check` 通过；
- `makemigrations --check --dry-run` 无待生成迁移；
- 完整 `apps.erp.tests` 通过；
- Node 语法检查、site/domain/team tests、build 全通过；
- 上述关键业务场景有自动化回归测试；
- 实施分支 push 到 GitHub；
- PR #12 更新到新的最终 40 位 HEAD SHA，并更新 migrations、测试结果、风险；
- 不自动 merge；
- 不部署生产。

# Codex 实施需求：统一销量智能补货、在途库存/调拨物流、店铺资料与授权分离

- 需求编号：`ERP-REPLENISHMENT-INTRANSIT-STORE-20260811-01`
- 需求上传时间：**2026-08-11 01:57（UTC+8）**
- 仓库：`kevindongbo/codex`
- 需求分支：`docs/erp-replenishment-intransit-store-20260811-0157`
- 需求目录：`requirements/2026-08-11_0157_UTC+8/`
- 代码审计证据基线：`main` @ `3353edaaa4dce8ca44e8da729f22e3800aafa570`
- 实际实施继承基线：`codex/implement-profit-strategy-ui-fixes-20260805` @ `63cad114ef9567ad40a1c9001b81261fedf830cc`（Draft PR #10 HEAD）

> 注意：本文“当前代码审计”主要以 main 为证据基线；实际编码必须继承 PR #10 HEAD，避免丢失尚未合并到 main 的现有功能。PR #10 链路中若已经存在 `OwnStore`、`StoreProduct`、利润策略等结构，应优先演进复用，禁止平行再建第二套模型。

---

# 一、最终目标

本次只围绕三个核心目标实施：

1. **同一 ERP 内部 SKU 的真实销量跨仓库、跨平台、跨店铺统一统计。**统一后的完整销量速度，分别用于每一个启用智能补货的仓库；每个仓库再使用自身 SKU×仓库的总备货时效、覆盖天数、库存位置、安全库存、MOQ、整箱数等计算补货。
2. **库存严格区分现货、锁定、可用、已采购待发货、在途库存。**采购和调拨只有“确认实际发货”后才进入在途；调拨需要物流包、预占、部分收货、异常关闭。
3. **ERP 店铺资料与平台授权彻底分离。**所有平台都允许手工创建店铺，TikTok OAuth 只是后续绑定方式之一，绝不能成为创建店铺的前置条件。

---

# 二、当前代码审计结论

## 2.1 智能补货：部分完成，核心销量范围和周期口径需修改

现有基础可复用：

- `StockBalance` 已有 `on_hand / reserved / available`。
- `ReplenishmentPolicy` 已按 `organization + warehouse + sku` 唯一。
- `ReplenishmentSettings` 已有安全库存、服务系数、安全余量、MOQ/pack 相关默认以及 3/7/15/30 日销量权重。
- `replenishment.py` 已实现 3/7/15/30 加权、波动、安全库存、历史采购周期、MOQ、pack 向上取整、解释 reasons。

当前不符合：

1. `estimate_demand_velocity()` 目前按 `warehouse` 过滤，是单仓销量。
2. 当前把 `MANUAL_OUTBOUND` 算作需求销量；新规则只允许真实销售订单实际出库。
3. 当前退货不会回溯冲减原销售日。
4. 当前历史采购 P80 可能成为实际 lead time；新规则要求人工总备货时效是最终计算值，历史值只作参考。
5. 当前 `review_cycle_days` 和 `target_days` 同时参与需求周期；新规则只允许“总备货时效 + 覆盖天数”作为需求周期。
6. 当前默认补货参数是组织级，不是仓库级。
7. 当前没有 SKU×仓库“启用智能补货”开关。
8. 当前采购未收数量直接进入在途，未区分是否真实发货。
9. 当前没有独立“已采购待发货”。
10. 当前补货建议没有系统建议/人工确认/已转采购/剩余可转采购的持久化业务状态。
11. 当前前端本地模式仍存在与后端不同的一套 7/15/30 权重计算，必须收敛为同一业务口径。

## 2.2 采购与调拨：已有基础，但状态机需重构

可复用：

- 已有 `PurchaseShipment / PurchaseShipmentLine`，可以记录多个物流号及 SKU 数量。
- 采购 Receipt 可关联 PurchaseShipment。
- 已有 `StockTransfer / StockTransferLine`、发出/收货、库存流水、幂等。

当前不符合：

1. 采购在途当前基本等于 `ordered - received`，不是真实发货在途。
2. 没有采购“发货批次 → 多物流包”的两层结构。
3. 没有独立“确认本批发货”。
4. 没有采购“已采购待发货”、未发货关闭、在途异常关闭、已完成（有异常）。
5. 调拨创建时没有预占来源仓，dispatch 才直接扣现货。
6. 调拨没有物流包和每包 SKU 数量。
7. main 调拨收货仍偏整单；新规则要求按 SKU 多次部分收货。
8. 当前在途调拨可取消并恢复来源仓库存；新规则确认发货后禁止直接取消。
9. 没有调拨在途异常关闭和已完成（有异常）。
10. 库存列表缺少“已采购待发货”独立列和在途来源明细。

## 2.3 店铺：main 未完成；PR #10 链路已有基础结构但仍需演进

main 中 `TikTokShopConnection` 同时保存 shop_id、shop_name、region、open_id、token、授权状态，等于把店铺资料和授权混在一起。OAuth 成功后还会读取全部授权店铺并创建/更新多个连接。

PR #10 继承链中已经出现 `OwnStore / StoreProduct` 基础结构，应复用演进，但仍需补：

- Store 与 TikTokConnection 正式绑定；
- market 允许为空；
- 常用平台 + Other 自定义平台；
- 同组织店铺名唯一；
- OAuth 从已有 ERP 店铺发起；
- OAuth 返回多个远端店铺时人工只选一个绑定；
- 旧 TikTokConnection → ERP Store 的迁移。

---

# 三、硬性不允许修改的补货算法部分

后端现有 3/7/15/30 默认权重保持：

- 3 日：0.40
- 7 日：0.30
- 15 日：0.20
- 30 日：0.10

**不得私自修改窗口、权重、波动算法。**

继续保留：

- 日销量波动；
- service level factor；
- safety stock；
- 初始安全库存参考；
- safety margin ratio；
- MOQ；
- pack size 向上取整；
- 解释 reasons；
- 事务、幂等、不可负库存等基础安全机制。

本次只改变：

- 销量事实来源；
- 销量统计范围；
- 退货净销量；
- 补货参数层级；
- 需求周期；
- 有效库存位置。

---

# 四、统一销量与净销量

## 4.1 内部 SKU 是唯一补货身份

平台外部 SKU 不同没关系，只要映射到同一个 ERP `SKU.id`，全部合并。

## 4.2 跨仓库、跨平台、跨店铺统一

计算 3/7/15/30 日销量时只按：

`organization + internal_sku`

不得按 warehouse/store/platform 过滤。

平台/店铺/仓库维度只用于统计展示，不得影响补货需求速度。

## 4.3 每个仓库使用完整统一销量，不分摊

例如 SKU-A 全系统日销量 100：

- 马来仓使用 100/天；
- 新加坡仓也使用 100/天；
- 其它启用补货的仓库同样使用 100/天。

禁止按仓库历史销量占比进行分配。

## 4.4 只统计真实销售订单实际出库

推荐以 `Shipment / ShipmentLine` 为销售事实。

不计入销量：

- manual outbound；
- transfer out；
- adjustment；
- write-off / shrinkage；
- reserve/release；
- inventory reversal；
- purchase/manual inbound。

## 4.5 退货冲减原销售日期

8 月 1 日卖 10，8 月 10 日退 2，则 8 月 1 日净销量为 8。

- RESTOCK：冲减原销售 + 增加库存；
- DAMAGED：冲减原销售 + 不增加库存。

两种都必须冲减销量。

若退货找不到原订单：

- 标记“未关联原订单”；
- 暂不进入净销量冲减；
- 后续关联后再回溯原销售日期；
- 禁止直接在退货当天做负销量。

---

# 五、外部 SKU 映射

平台订单即使外部 SKU 未映射，也必须同步进入 ERP。

订单行至少保留：

- external SKU code；
- external product/listing id（有则保留）；
- 商品快照/名称；
- 数量；
- 店铺；
- 平台订单标识；
- `internal_sku` 可为空。

未映射期间：不进入智能补货销量。

完成映射后：回填最近 **30 天**真实销售到该内部 SKU，并触发/允许重新计算补货。

---

# 六、补货参数层级

新增仓库级默认值，至少：

- `default_lead_time_days`
- `default_coverage_days`

优先级：

`SKU×仓库覆盖值 > 仓库默认值`

每个 SKU×仓库新增：

- `replenishment_enabled`
- `lead_time_override`
- `coverage_days`（或同义字段）
- 现有 MOQ、pack、safety override 等继续保留。

如果 SKU 没有 override、仓库也没有默认 lead/coverage：

- 不生成建议；
- 返回明确原因：`缺少补货参数，请先配置仓库默认值或 SKU 单独参数`；
- 禁止系统自行猜默认天数。

补货参数必须同时可从：

1. 智能补货/策略页；
2. 库存列表 SKU×仓库快捷编辑；

读写同一后端数据模型。

---

# 七、总备货时效与覆盖天数

## 7.1 总备货时效

用户只填写一个总天数，不拆采购、运输、清关、入仓。

SKU×仓库人工值优先；无 override 则仓库默认。

历史采购 P80 可以继续统计并展示“历史参考时效”，但**不能覆盖人工值**。

## 7.2 覆盖天数

唯一需求周期：

`horizon = lead_time_days + coverage_days`

例如日销量 10、lead 15、coverage 30：基础需求周期 45 天，基础需求 450。

旧 `review_cycle_days`：迁移到新的 `coverage_days` 初始值。

旧 `target_days`：不得再构成第二个需求周期；可为兼容保留数据，但不再参与新目标需求公式。

UI 不再让用户同时维护两个含义重叠的周期字段。

---

# 八、库存定义与补货库存位置

## 8.1 现货

`on_hand`

## 8.2 锁定

至少包含：

- 销售订单锁定；
- 调拨草稿锁定。

可共用 `StockBalance.reserved`，但必须能通过领域记录追踪来源。

## 8.3 可用

`available = on_hand - reserved`

## 8.4 已采购待发货

正式 Submit/已下单，但尚未确认实际发货，且未被“关闭未发货”的数量。

**不是在途库存。**

采购草稿不算。

## 8.5 在途库存

只包含：

- 采购已确认发货 - 已收货 - 在途异常关闭；
- 调拨已确认发出 - 已收货 - 在途异常关闭。

在途只属于目的仓，来源仓不显示调出在途。

## 8.6 补货有效库存位置

`effective_inventory_position = available + purchased_pending_shipment + in_transit`

同一件货在任意阶段只能计一次。

---

# 九、库存列表

每个 SKU×仓库至少显示：

- 现货；
- 锁定；
- 可用；
- 已采购待发货；
- 在途库存；
- 智能补货开关；
- 总备货时效；
- 覆盖天数。

“已采购待发货”可点击查看：采购单号、供应商、SKU、待发数量、下单时间。

“在途库存”可点击查看：

- 来源类型（采购/调拨）；
- 来源单号；
- 采购发货批次；
- 物流包/物流单号（有则显示）；
- SKU 当前剩余在途；
- 确认发货时间。

---

# 十、采购物流：发货批次 → 多物流包

建议数据结构按项目风格实现，但业务必须有两层：

`Purchase Shipment Batch -> Packages -> Package SKU Lines`

一个发货批次可有多个物流包；每个物流包可有多个 SKU 数量。

物流单号允许为空，后续补录。

## 10.1 编辑批次/物流包

只编辑资料，不改变现货、不进入在途、不减少已采购待发货。

## 10.2 确认本批发货

必须有独立动作。

确认后：

- 本批数量从“已采购待发货”转入“采购在途”；
- 不增加现货；
- 写 confirmed_at/confirmed_by；
- 批次不能重复确认；
- 必须事务 + 幂等。

采购允许部分发货，所以本批无需覆盖整张采购单，但本批累计数量不能超过 SKU 当前剩余可发数量。

## 10.3 采购收货

收货必须选择具体发货批次。

按 SKU 填“本次实收”，支持同批次多次部分收货。

`本次实收 <= 该批次该 SKU 当前剩余在途`

收货：

- 采购在途减少；
- 目的仓现货增加；
- 保留 Receipt/ReceiptLine；
- 不要求选择具体 tracking package。

## 10.4 在途异常关闭

只允许处理“已确认发货但尚未收货”的数量。

例如发 100、收 97、丢 3：异常关闭 3 后：

- in_transit -3；
- on_hand 不增加；
- 原发货/收货记录不改；
- 必填原因、操作者、时间；
- 仅作用于具体发货批次。

## 10.5 关闭未发货数量

例如订 100、已发 80、供应商确认 20 不再发：

- purchased_pending -20；
- in_transit 不增加；
- on_hand 不增加；
- 原订购数量仍保留 100；
- 单独记录未发货关闭 20 + 原因。

不得直接把采购数量从 100 改成 80 来抹掉历史。

## 10.6 采购最终状态

所有订购量被“收货 / 已发货异常关闭 / 未发货关闭”完全核销后可结束。

有任意异常或关闭：`COMPLETED_WITH_EXCEPTION / 已完成（有异常）`。

无异常：正常已收货完成。

---

# 十一、历史采购物流迁移

旧 `PurchaseShipment + PurchaseShipmentLine`：

- 已有物流单和 SKU 发货数量的历史记录，迁移后默认视为**已确认发货**；
- 防止升级后旧在途突然归零。

建议每个旧采购单创建“历史迁移发货批次”，把原 PurchaseShipment 作为其 Package；tracking、SKU 数量、Receipt 关联全部保留。

迁移必须避免：

- 重复计算在途；
- 丢 Receipt 历史；
- 重复增加库存。

---

# 十二、调拨

状态至少：

- DRAFT
- IN_TRANSIT
- RECEIVED / COMPLETED
- COMPLETED_WITH_EXCEPTION
- CANCELLED（只允许未确认发货草稿）

## 12.1 创建调拨立即预占来源仓

例如 on_hand=100/reserved=0，创建调拨 30：

- on_hand=100；
- reserved=30；
- available=70。

创建/编辑必须整单校验库存并事务化。

草稿：

- 增量 → 增加预占；
- 减量 → 释放预占；
- 删除行 → 释放对应预占；
- 取消草稿 → 全量释放。

## 12.2 调拨物流包

一个调拨可有多个物流包；每个包 tracking 可为空；包内记录多个 SKU 数量。

确认发货前，对每个 SKU 必须满足：

`所有包分配数量之和 == 调拨计划数量`

不能少、不能多。

没有物流单号时也必须先建一个 tracking 为空的“待补单号包”承载数量。

## 12.3 整单确认发货

调拨只有一个整单确认发货动作，不按包分别确认。

确认后：

- source on_hand -= quantity；
- source reserved -= quantity；
- destination 形成调拨在途；
- status → IN_TRANSIT；
- 写发货时间、人、幂等键；
- 不能重复确认。

## 12.4 部分收货

按 SKU 填“本次实收”，不要求选择 tracking package。

允许多次收货。

`本次收货 <= 当前剩余在途`

收货：目的仓 on_hand 增加，在途减少，保留不可变收货事件。

## 12.5 确认发货后禁止直接取消

IN_TRANSIT 后：

- 禁止 cancel；
- 禁止 delete；
- 禁止把来源仓库存简单恢复。

纠错只能通过可追溯业务动作：正常收货、在途异常关闭、未来独立退回流程。

当前 main 中“在途调拨 cancel 并恢复来源库存”的行为必须移除/限制。

## 12.6 调拨在途异常关闭

调出 100、实收 98、丢 2：

- destination in_transit -2；
- destination on_hand 不增加；
- source 不恢复；
- 记录原因、人、时间。

剩余全部处理后，有异常则状态为“已完成（有异常）”。

## 12.7 历史调拨迁移

旧 IN_TRANSIT 调拨：自动生成“历史迁移发货包”，包内 SKU 数量继承已发数量，tracking 可空，视为已确认发货。

不得重复扣来源仓；迁移前后目标仓在途总量必须一致。

---

# 十三、销售订单与仓库

## 13.1 一张订单只能一个仓库

订单级 warehouse，所有 SKU 同仓出库，不拆仓、不自动按就近/库存选择。

## 13.2 订单允许先无仓库

平台同步/人工创建订单时 warehouse 允许 null。

当前自动塞入 DEFAULT 仓库的行为需要取消。

## 13.3 人工选仓立即整单锁库

用户选仓后：

- 一次性校验整单所有 SKU；
- 任一 SKU 不足则整次失败并返回每 SKU shortage；
- 不允许部分锁定；
- 不允许系统自动换仓；
- 成功后立即增加 reservation，on_hand 不变，available 下降。

## 13.4 出库前可换仓

必须一个事务完成：

1. 锁订单/库存；
2. 校验新仓整单库存；
3. 若不足则不释放旧仓预占；
4. 若足够则释放旧仓预占；
5. 新仓建立完整预占；
6. 更新 warehouse；
7. 写 AuditLog。

真实 Shipment 完成后仓库锁死。

---

# 十四、ERP 店铺主数据

使用/演进独立 `OwnStore`（名称可按项目现有结构），至少：

- organization
- name
- platform_code
- custom_platform_name（Other 时）
- market（nullable/blank）
- is_active/status
- timestamps

同一组织内店铺名唯一：

`UniqueConstraint(organization, name)`

不要使用跨所有组织的 `unique=True`。

平台预置：

- TikTok Shop
- Shopee
- Ozon
- Other

Other 允许自定义平台名称。

市场允许为空。

没有任何平台 Token 也必须可以创建店铺。

---

# 十五、TikTok 授权与店铺分离

关系：

`ERP Store <- TikTokShopConnection`

要求：

- ERP Store 可以无授权；
- connection 绑定一个 ERP Store；
- 同一 ERP Store 同一时间只能一个有效平台授权连接；
- 历史失效/解绑连接可留审计；
- 同一远端 shop_id 不得同时绑定多个 ERP Store；
- OAuth 绝不能自动制造重复 ERP 店铺。

## 15.1 从已有 ERP 店铺发起 OAuth

店铺列表/详情提供“绑定 TikTok / 重新授权”。OAuth state 记录 target store。

## 15.2 OAuth 返回多个远端店铺

若授权返回 A/B/C：

- 不自动创建 3 个 ERP 店；
- 返回候选列表；
- 用户只选择 1 个绑定当前 ERP Store；
- 其它店以后先手工建 ERP Store，再绑定。

## 15.3 市场处理

Store.market 为空：绑定成功后用远端真实 region 自动补全。

Store.market 已填写且与远端冲突：阻止绑定并提示，不静默覆盖。

## 15.4 旧 TikTok 授权迁移

对已有 TikTokShopConnection：

1. 为每个现有 remote shop 创建/匹配 ERP Store；
2. 名称优先 shop_name，其次 label；
3. platform=TikTok；
4. market=region；
5. 原 connection 绑定 store；
6. token、shop_id、open_id、授权状态、过期时间、历史 sync run 全保留；
7. 店铺名唯一冲突必须明确报迁移冲突，禁止静默覆盖或偷偷加随机后缀。

---

# 十六、StoreProduct / 外部 SKU

StoreProduct 至少支持：

- store
- internal SKU
- external SKU code
- external listing/product id（可空）
- 商品链接（可空）
- 已有利润相关字段可继续保留

同一店铺同一 external SKU 只能映射一个 internal SKU。

映射成功后允许最近 30 天历史销售回填。

---

# 十七、补货建议持久化与人工采购

需要持久化业务建议（模型名可按项目风格），至少保存：

- organization
- warehouse
- sku
- calculated_at
- calculation snapshot/version
- system_suggested_quantity
- user_confirmed_quantity
- adjusted_by / adjusted_at
- converted_purchase_quantity
- status
- reasons/snapshot JSON

## 17.1 人工修改建议数量

系统建议 500，允许用户改 350。

同时保留：

- system=500；
- confirmed=350；
- 谁改；
- 何时改。

人工修改只影响本次执行，不反向改算法参数。

## 17.2 生成采购单草稿

用户主动勾选后生成，禁止自动采购/自动提交。

按：

`目的仓库 + 供应商`

自动分组拆成采购草稿。

无默认供应商的 SKU 先要求人工选择。

## 17.3 支持分次转采购

最终确认 500，可先转 300，再转 200。

必须显示：

- 最终确认量；
- 已转采购；
- 剩余可转。

累计不能超过最终确认量。

采购草稿不参与库存位置；采购单 Submit 后才进入“已采购待发货”。

---

# 十八、最终补货计算口径

对每个 `replenishment_enabled=true` 的 SKU×Warehouse：

1. 取同组织同内部 SKU 的统一净销量；
2. 按现有 3/7/15/30 权重计算 daily velocity；
3. lead：SKU override，否则 warehouse default；
4. coverage：SKU override，否则 warehouse default；
5. 缺参数则不生成建议；
6. `horizon = lead + coverage`；
7. `base_target_demand = daily_velocity × horizon`；
8. 保留现有波动、安全库存、service factor、safety margin、MOQ、pack；
9. `inventory_position = available + purchased_pending_shipment + in_transit`；
10. 建议量根据目标库存位置减 inventory_position，再按 MOQ/pack 向上取整。

不得：

- 按仓库销量比例分摊；
- 把 manual outbound 算销量；
- 把未发货采购算 in_transit；
- 把采购草稿算库存位置；
- 再叠加旧 review/target 第二套需求周期。

---

# 十九、数据迁移

必须生成正式 Django migration，不能只改 models.py。

## 19.1 补货

- 新建/增加 warehouse defaults；
- 现有仓库可从组织级 `default_lead_time_days` 初始化 lead default；
- 现有组织级 `review_cycle_days` 初始化 warehouse coverage default；
- 现有 ReplenishmentPolicy 的旧 review cycle 迁移为 coverage；
- 现有 policy 默认 `replenishment_enabled=True`，避免升级后突然失效；
- target_days 不再参与新公式。

## 19.2 采购

- 老 PurchaseShipment 迁入 batch/package；
- 已有物流 SKU 数量默认已确认发货；
- Receipt 关系保留；
- 不重复计算在途。

## 19.3 调拨

- 老 IN_TRANSIT 调拨生成历史迁移包；
- 保留原发货时间/人/库存流水；
- 不重复扣来源库存；
- 迁移前后调拨在途一致。

## 19.4 店铺

- 如果实施基线已有 OwnStore，则演进它；
- 名称唯一必须组织级；
- market 改为 nullable/blank；
- TikTokConnection 迁移绑定 Store；
- token/sync history 不丢。

---

# 二十、事务、并发、幂等、审计

以下动作都必须 `transaction.atomic` + 必要 `select_for_update`：

- 订单选仓/换仓；
- 调拨创建/编辑预占；
- 调拨草稿取消；
- 调拨确认发货；
- 调拨部分收货；
- 调拨异常关闭；
- 采购批次确认发货；
- 采购批次收货；
- 采购在途异常关闭；
- 采购未发货关闭；
- 补货建议转采购草稿。

必须保证并发下：

- 不超卖；
- 不重复发货；
- 不重复收货；
- 不重复异常关闭；
- 不重复/超量转采购。

必须写 AuditLog：

- 补货参数修改；
- 建议人工调整；
- 建议转采购；
- 店铺 CRUD/停用；
- 平台授权绑定/解绑/重新授权；
- SKU 映射和历史回填；
- 订单选仓/换仓；
- 调拨预占/释放/发货/收货/异常；
- 采购发货/收货/异常/未发货关闭；
- 物流单号后补/修改。

---

# 二十一、前端/API 最低要求

API URL 可按现有 DRF 风格命名，但必须提供等价能力。

## Store

- store CRUD；
- 从 store 发起 TikTok authorization；
- OAuth 候选 remote shops；
- 选择一个 remote shop 绑定；
- disconnect/re-authorize；
- SKU mapping。

## Inventory

Stock balance list 返回：

- on_hand
- reserved
- available
- purchased_pending_shipment
- in_transit

并提供 pending/in-transit 明细。

## Purchase

- shipment batch CRUD；
- draft package/line 编辑；
- confirm batch shipment；
- receive against batch；
- close in-transit exception；
- close unshipped quantity。

## Transfer

- draft create/edit with reservation；
- packages；
- dispatch；
- partial receive by SKU；
- close exception；
- cancel draft only。

## Replenishment

- warehouse defaults；
- SKU×warehouse policy；
- recommendations；
- suggestion confirm/adjust；
- suggestions → purchase drafts。

## Orders

- create/sync warehouse null；
- assign warehouse；
- change warehouse before ship；
- shortage response；
- ship/cancel 继续幂等。

前端对应展示和操作必须完成，且本地模式不得保留与后端冲突的另一套补货计算公式。

---

# 二十二、明确非目标

本轮不做：

- 自动仓库选择；
- 订单拆仓；
- 外部物流 API 自动查轨迹；
- 自动采购执行；
- 自动提交采购单；
- 按仓库销量占比分配需求；
- 修改 3/7/15/30 权重；
- 重写既有安全库存/波动/MOQ/pack 算法（本文明确的输入和周期除外）；
- OAuth 自动批量创建 ERP 店铺；
- 根据店铺名称自动猜测合并授权。

物流 API 只需要在模型上预留未来扩展空间，本期不接。

---

# 二十三、关键验收测试

Codex 必须为以下场景补自动化测试或等价覆盖证据。

## A. 统一销量

同 SKU：MY 仓真实销售 30、SG 仓真实销售 60、手动出库 100、调拨出库 50。

统一销量只统计 90；MY 和 SG 的补货都使用同一套统一速度。

## B. 退货回溯

8/1 出库 10、8/10 退 2，则 8/1 净销量=8。RESTOCK/DAMAGED 都减销量，仅 RESTOCK 增库存。

## C. 采购阶段

订 100 Submit：pending=100、in_transit=0。

确认第一批发 40：pending=60、in_transit=40。

收 30：pending=60、in_transit=10、on_hand+30。

异常关闭 10：in_transit=0。

关闭未发 60：pending=0，采购完成（有异常）。

## D. 同批多物流包

同批包 A=70、包 B=30，一次确认批次后 in_transit+100；重复确认必须拒绝。

## E. tracking 后补

采购和调拨都允许 tracking 为空的包先确认发货，后补 tracking 不得再次增加在途。

## F. 调拨预占

来源 on_hand=100/reserved=0，建调拨 30 → on_hand=100/reserved=30/available=70；确认发货后 on_hand=70/reserved=0，目标 in_transit=30。

## G. 调拨部分收货+丢件

调出 100，收 60，再收 38，异常关闭 2 → in_transit=0，状态已完成（有异常），来源不得恢复 2。

## H. 发出后禁止取消

IN_TRANSIT 调拨调用 cancel 必须失败，不恢复来源库存。

## I. 订单人工选仓/换仓

订单可无 warehouse 创建。选仓 A 全量锁库。换仓 B 若任一 SKU 不足，则换仓整体失败且 A 原预占不变；若足够则事务化释放 A、锁 B、更新订单。

## J. 补货参数优先级

SKU override 缺失时用 warehouse default；两层都缺则不生成建议；replenishment_enabled=false 不生成建议。

## K. 人工 lead 优先

历史 P80=12、人工 SKU×仓 lead=20，补货必须用 20；12 只作参考。

## L. 周期

daily=10、lead=15、coverage=30，基础 horizon 必须 45 天；不得叠加旧 review/target。

## M. 店铺手工创建

无 token 情况下 TikTok/Shopee/Ozon 都能创建；market 空也能创建；同组织同名重复失败；Other 自定义平台成功。

## N. TikTok 绑定

Store market 空 + OAuth MY → 绑定后自动补 MY；Store=SG + remote=MY → 阻止绑定；OAuth 返回 3 店时只选择 1 店绑定，其余不自动创建 ERP Store。

## O. 补货建议转采购

系统建议 500，人工改 350；先转 200，再转 150，剩余 0；再转 1 必须拒绝。

---

# 二十四、Codex 工作纪律与交付

Codex 不得：

- 直接部署生产；
- 自动 merge；
- 省略 migration；
- 静默改历史数量；
- 静默删除库存流水；
- 静默修复店铺名迁移冲突；
- 为了通过测试写死数字。

完成后必须：

1. 推送实施分支到 GitHub；
2. 创建 Draft PR；
3. 报告最终精确 HEAD SHA；
4. 报告 migrations；
5. 报告测试命令和结果；
6. 报告部署影响、回滚风险；
7. 更新 `docs/deployment/aliyun/ERP-REPLENISHMENT-INTRANSIT-STORE-20260811.md`，只记录真实部署事实，不连接/执行生产；
8. 明确写：`代码已推送 GitHub；未自动合并；未部署生产。`

---

# 二十五、最终业务口径摘要

**销量：** 同一 ERP SKU 的所有平台/店铺/仓库真实订单出库合并，退货回溯原销售日得到净销量。

**补货：** 统一销量完整应用到每个启用仓库；每仓按 `总备货时效 + 覆盖天数`、有效库存位置、安全参数、MOQ/pack 算建议。

**有效库存位置：** `现货 - 销售锁定 - 调拨锁定 + 已采购待发货 + 已确认在途`。

**采购：** 下单未发不等于在途；确认发货批次才进入在途；一批可多物流包；支持部分收货、在途异常、未发货关闭。

**调拨：** 创建即预占；整单确认发货；目的仓形成在途；支持部分收货和异常关闭；发货后禁止直接取消。

**店铺：** 先有独立 ERP 店铺，再绑定平台授权；所有平台都允许手工建店；TikTok OAuth 只负责授权绑定，不负责制造 ERP 店铺。
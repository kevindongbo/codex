# Codex 第二轮修复提示词

请处理 GitHub 仓库 `kevindongbo/codex` 的 PR #12 验收失败补漏。

## 固定基线

- 实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 当前待修 HEAD：`d47fed21f2f45d747f87d6c4efc45b3e93020aa3`
- 不要从旧 main 重做。
- 不要创建另一套平行实现。

## 先读取

完整读取：

1. `requirements/2026-08-11_1135_UTC+8/README.md`
2. `requirements/2026-08-11_1135_UTC+8/ERP_PR12_REMEDIATION_REQUIREMENTS.md`
3. 原需求：`requirements/2026-08-11_0157_UTC+8/ERP_REPLENISHMENT_INTRANSIT_STORE_REQUIREMENTS.md`

第二轮修复文档是对原需求的验收补充，不替代原需求；冲突时以第二轮“明确指出的缺陷修正”为准。

## 第一优先级

先修生产可见问题：订单 `SKU 未映射/库存不足 -> 确认并出库 -> HTTP 500`。

必须做到：

- 未映射 SKU 永远返回明确 4xx 业务错误，不得 500；
- 完整实现人工选择仓库 / 更换仓库 / 整单库存校验 / 原子锁库；
- 前端无仓订单先选仓，锁库成功前不能直接出库；
- 库存不足返回每个 SKU 的 shortage 明细；
- 为该故障增加自动回归测试。

## 关键逻辑必须修正

- pending 公式：`ordered - confirmed_shipped - unshipped_closed`；received 不得二次扣 pending。
- purchase in-transit：`confirmed_shipped - received - transit_exception_closed`。
- 采购在途 + 调拨在途必须正确合计，不能 if/else 吞掉来源。
- 修复 0028 中 coverage 初始化口径及历史调拨状态大小写遗漏，使用新的 forward repair migration，不要篡改已经可能执行过的 migration 历史。
- 把“只有模型”的采购批次/package、调拨 package 真正接入 service/API/UI。
- 采购/调拨必须有确认发货、部分收货、异常关闭；采购还要有关闭未发货。
- 调拨草稿编辑必须正确调整 reserved。
- 退货必须回溯原销售日形成统一净销量。
- external SKU 映射后回填同店最近30天订单。
- ReplenishmentRecommendation 必须支持多次 conversion event，并真正创建 PurchaseOrder Draft；不能只增加 converted 数字。
- TikTok OAuth 必须从已有 ERP Store 发起，多店只选择一个绑定，不自动批量创建 ERP 店铺。
- 前端库存表必须显示 pending/in-transit 并可查看来源明细。

## 不允许改动

- 不改变现有后端 3/7/15/30 加权窗口及权重；
- 不改变安全库存、波动、service factor、MOQ、pack rounding 核心算法，除非为修正原需求明确指出的数据源/周期错误；
- 不自动选择订单仓库；
- 不拆单跨仓；
- 不自动提交采购单；
- 不接外部物流 API；
- 不自动 merge；
- 不部署生产。

## 实施要求

1. 直接在 `codex/implement-erp-replenishment-intransit-store-20260811` 继续提交修复。
2. 对现有已可能执行的 migrations 只新增 forward repair migration；不要修改历史 migration 来掩盖问题。
3. 所有库存阶段变更使用 `transaction.atomic`、必要的 `select_for_update`、幂等键和 AuditLog。
4. 对订单选仓/换仓、采购确认发货、采购收货、采购异常关闭、采购未发货关闭、调拨预占/编辑/发货/收货/异常关闭、建议转采购全部做并发安全。
5. 前后端必须完整串通，不接受“模型已建但页面/API没有入口”。
6. TEAM_MODE 与本地/前端逻辑不得保留互相矛盾的核心业务规则。

## 测试门槛

至少执行并真实通过：

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.erp.tests --noinput
node --check app.js
node --check team.js
node --check profit-calculator.js
node --test tests/site.test.mjs
node --test tests/domain.test.mjs
node --test tests/team.test.mjs
node scripts/build-site.mjs
```

并确保 `ERP_PR12_REMEDIATION_REQUIREMENTS.md` 中列出的关键场景都有自动化覆盖。

## GitHub 交付

修复完成后：

- push 到原实施分支：`codex/implement-erp-replenishment-intransit-store-20260811`
- 更新 PR #12，不要另开一个业务实施 PR；
- PR #12 body 重新写清：修复项、新增 migration、测试数量、数据迁移风险、最终 SHA；
- 不要自动 merge；
- 不要部署生产。

最终回复必须给：

- Implementation branch
- PR #12 URL
- New final HEAD SHA（40位）
- 新增/修改 migration 列表
- 修复文件清单
- 自动化测试命令与最终结果
- P0/P1 每一项完成状态
- 数据迁移风险
- 部署影响
- 回滚影响
- Remaining risks

最后一句必须明确：

`代码已推送 GitHub；PR #12 未自动合并；未部署生产。`

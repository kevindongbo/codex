# Codex Implementation Prompt — ERP Transfer + Replenishment V4

把下面整段原样交给 Codex。

---

你现在要继续实现 `kevindongbo/codex` 的 ERP 仓间调拨 + 智能补货 V4。

## 绝对分支规则

1. **禁止修改 `main`。**
2. **禁止在需求分支写实现代码。**
3. 所有代码、测试、migration 只能提交并 push 到：

```text
codex/erp-transfer-replenishment-v4-implementation-20260824
```

4. 需求只从以下需求分支读取：

```text
requirements/erp-transfer-replenishment-v4-20260824-2143
```

5. 不要 merge，不要 squash 到 main，不要部署生产。

## 第一步：同步并确认分支

先执行并把结果记录下来：

```bash
git status
git remote -v
git fetch origin --prune
git branch -vv
git log --oneline --decorate -10
```

确认实现分支存在后：

```bash
git checkout codex/erp-transfer-replenishment-v4-implementation-20260824
git pull --ff-only origin codex/erp-transfer-replenishment-v4-implementation-20260824
```

开工基线应源自上一 V3 实现 HEAD：

```text
26083e6146ea2717d376065857045089d8b4e6aa
```

如果实际 HEAD 已经比这个更新，不要 reset 或覆盖别人提交；先审计新增提交，再继续。

## 第二步：从 GitHub 读取完整需求

不要只看这段提示词。

必须从 `origin/requirements/erp-transfer-replenishment-v4-20260824-2143` 读取目录：

```text
requirements/2026-08-24_2143_erp-transfer-replenishment-v4/
```

阅读顺序：

```text
README.md
00_UPLOAD_METADATA.md
01_INHERITED_V3_FULL_REQUIREMENTS.md
02_V4_CURRENT_REQUIREMENTS_AND_OVERRIDES.md
03_CURRENT_CODE_AUDIT_2026-08-24.md
04_INHERITED_V3_ACCEPTANCE_TESTS.md
05_V4_ACCEPTANCE_AND_REGRESSION_TESTS.md
06_CODEX_IMPLEMENTATION_PROMPT.md
07_HANDOFF_CHECKLIST.md
08_REQUIREMENT_TRACEABILITY.md
```

可以使用：

```bash
git show origin/requirements/erp-transfer-replenishment-v4-20260824-2143:requirements/2026-08-24_2143_erp-transfer-replenishment-v4/01_INHERITED_V3_FULL_REQUIREMENTS.md
```

逐个读取。

**不要只读摘要。`01_INHERITED_V3_FULL_REQUIREMENTS.md` 是完整 V3 业务规则，不能因为篇幅长而跳过。**

优先级：

```text
V4 明确覆盖条款 > V3 完整需求 > 当前代码行为
```

当前代码不是业务真值。

## 第三步：先做需求追踪，不要立刻乱改

在动代码前，建立你自己的追踪表：

```text
需求编号 / 需求说明 / 当前代码位置 / 当前状态 / 修改方案 / 测试
```

至少覆盖：

- 调拨异常关闭 reason 可空；
- 结束调拨 reason 可空；
- 幂等键继续保留；
- 调拨商品明细真实展开；
- 商品图片 + 名称 + SKU + 数量统一组件；
- 智能补货表头顺序；
- 近30天出库来源；
- 查看周期明细归属近30天来源；
- 30天接口；
- 不扣退货；
- V3 全仓加权公式；
- 主力仓规则；
- 两种补货目标模式；
- nullable 起订量/整箱数；
- lead P80 优先；
- 所有智能补货按钮；
- sticky header；
- migration / AuditLog / 幂等 / 并发；
- 自动化测试和真实浏览器测试。

## 第四步：必须复用当前 V3 实现，不要回滚

当前实现分支已经包含部分正确 V3 工作。

特别注意：

### 已有正确实现 1：异常关闭幂等键

`team.js` 的 `closeTransferException()` 已经发送 `idempotency_key`。

**不要为了让 reason 可空而删除幂等。**

### 已有正确实现 2：后端全仓加权公式

`backend/apps/erp/replenishment.py` 已经按：

```text
Σ(Qn×Wn) / Σ(n×Wn)
```

计算，并只使用 `SHIPMENT + MANUAL_OUTBOUND`。

不要改回旧算法，不要让退货重新冲减需求。

### 已有正确实现 3：SKUReplenishmentProfile

migration `0035_sku_replenishment_profile_v3.py` 已存在。

不要再创建第二套重复 Profile。

## 第五步：本轮必须修的代码

### A. 调拨异常关闭 reason 可空

前后端一起改。

后端 serializer：

- required=False
- allow_blank=True
- trim_whitespace=True

view/service 用 `.get('reason', '')`。

前端：

- 删除 required；
- 文案标“可选”；
- null guard；
- 保留 `idempotency_key`。

“结束调拨”剩余异常结案 reason 同样可空，但保留二次确认和幂等。

### B. 调拨商品明细

当前 `lines.slice(0, 2) + 等 N 项` 必须替换为真正可展开组件。

1 SKU 直显；多 SKU 可展开/收起；展开显示全部。

### C. 商品数量统一组件

基于 `productMedia(product)` 复用图片逻辑，新增 `productQuantityMedia()` 或等价 helper。

采购、调拨、收货、异常关闭、订单、退货、补货采购草稿等业务“商品 + 数量”场景统一使用。

不要重写图片安全逻辑。

### D. 智能补货表格

严格顺序：

```text
选择 | 商品 | 全仓加权日均出库 | 近30天出库来源 | 预测到货周期 | 可用 / 在途 | 可售天数 | 最迟下单 | 建议补货量 | 紧急度 | 操作
```

商品为第一业务列。

“查看周期明细”从 velocity 列移动到“近30天出库来源”。

### E. 近30天来源业务口径

```text
SHIPMENT + MANUAL_OUTBOUND
```

按真实 warehouse 汇总，**不扣退货**。

删除前端旧：

```text
订单 + 手动 - 退货 = 净销量
```

等与 V3 冲突的文案/fallback。

### F. 周期明细

接口不要再固定 7 天。

使用 30 天来源详情，同时展示 Q3/Q7/Q15/Q30、权重、加权结果、30 天各仓来源。

禁止 `net / 7` 硬编码。

### G. 智能补货按钮

逐个修复并实际点击：

- 全局补货参数
- 重新计算
- 批量调整参数
- 重新计算所选
- 生成采购草稿
- 创建采购
- 调整参数
- 恢复默认
- 查看周期明细

重点定位并消除：

```text
Cannot set properties of null (setting 'value')
```

检查模板 ID 与 JS 版本一致，所有异步 modal 初始化在写值前完成。

`openPurchaseEditor()` 等 async 函数必须在调用路径中正确 `await`。

### H. Sticky Header

新增字段后重新校验 1440×900、1920×1080。

商品列不能错位到中间。

## 第六步：不得破坏 V3 业务规则

完整规则必须以需求文件为准，尤其：

- 全仓销量；
- 主力仓库存；
- 无主力仓不给正式决策；
- 可售天数不含在途；
- 补货库存位含已确认在途；
- coverage / fixed safety stock 两模式互斥；
- 未触发 suggested=0；
- 起订量/整箱数 nullable；
- 先起订量再整箱；
- lead P80 优先；
- 用户可编辑 review cycle 取消，每日后台检查；
- 后端唯一计算真值。

## 第七步：测试

必须补测试，不允许只手工改页面。

至少执行：

```bash
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py test apps.erp.tests --noinput
node --check app.js
node --check team.js
node --test tests/site.test.mjs tests/domain.test.mjs tests/team.test.mjs
node scripts/build-site.mjs
git diff --check
```

另外必须运行真实浏览器 E2E / Playwright（按仓库现有方式）：

- 调拨展开；
- 空 reason 异常关闭；
- 结束调拨空 reason；
- 智能补货全部按钮；
- 30 天详情；
- 生成采购草稿；
- sticky header 1440×900 和 1920×1080。

要求：

```text
pageerror = 0
console.error = 0
Cannot set properties of null = 0
```

如果环境不允许真实浏览器测试，不能写“通过”，必须写“未验证：原因……”。

## 第八步：migration

先检查当前 migration 状态。

已有：

```text
0035_sku_replenishment_profile_v3.py
```

只有确实需要数据库结构变化时才新增 migration。

如果只把 DRF serializer 的 reason 改为 optional 且模型字段本身允许空，不要为了形式制造无意义 migration。

如需要 migration：

- 正常生成；
- 测试升级路径；
- 不静默丢数据；
- 报告迁移和回滚方式。

## 第九步：commit + push

确认：

```bash
git status
git diff --check
```

只在：

```text
codex/erp-transfer-replenishment-v4-implementation-20260824
```

commit，例如：

```bash
git add <实际修改文件>
git commit -m "fix(erp): complete transfer and replenishment v4 workflows"
git push origin codex/erp-transfer-replenishment-v4-implementation-20260824
```

禁止 push 到 main。

## 第十步：最终必须返回完整报告

按 `07_HANDOFF_CHECKLIST.md` 返回：

- 仓库；
- 实现分支；
- 起始 HEAD；
- 最终 HEAD SHA；
- commit；
- 修改文件；
- migration；
- 每项需求完成状态；
- 测试命令和实际结果；
- Playwright 实测结果；
- 未验证项；
- 已知风险；
- 部署是否需要 migrate/build/collectstatic/定时任务；
- 回滚方式。

不要 merge，不要生产部署。完成后只 push 实现分支并把报告交回用户。

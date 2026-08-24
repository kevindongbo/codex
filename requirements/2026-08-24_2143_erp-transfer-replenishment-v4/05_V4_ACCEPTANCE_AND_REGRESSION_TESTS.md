# V4 新增验收与回归测试

时间：2026-08-24 21:43 +08:00

> 本文件是在 `04_INHERITED_V3_ACCEPTANCE_TESTS.md` 基础上追加。V3 测试不能删除或弱化。

---

# 1. 调拨异常关闭：API / 幂等 / 原因可空

## 1.1 前端 TeamGateway

`tests/team.test.mjs` 至少新增：

- `closeTransferException()` body 包含 `idempotency_key`；
- `reason=''` 可以发送；
- 不传/传空 reason 不会在前端直接抛错；
- 相同 transfer + 相同 quantities 的重试使用稳定的业务签名；
- 成功调用 `completeIdempotency(key)`；
- 失败正确完成/释放 pending key，且不会让下一次合法重试永久卡死。

## 1.2 Django serializer/API

至少覆盖：

- `reason` 完全省略：成功；
- `reason: ''`：成功；
- `reason: '运输丢失'`：成功；
- 缺少 `idempotency_key`：仍失败；
- 同一个 `idempotency_key` 重试：库存事实只执行一次；
- 不同幂等键重复关闭同一已关闭数量：业务层仍拒绝或不重复扣减。

## 1.3 库存语义

场景：

```text
来源仓发出 100
目的仓收货 80
异常关闭 20
```

必须：

- 来源仓累计发出仍 100；
- 目的仓在库只增加 80；
- 调拨剩余在途 0；
- exception_closed 20；
- 不产生 +20 来源仓恢复；
- 不产生 +20 目的仓收货；
- AuditLog 可追溯。

## 1.4 结束调拨

剩余全部异常结案时：

- reason 空：允许；
- 二次确认仍存在；
- 幂等仍存在；
- 全部 remaining 原子关闭；
- 不重复扣库存。

---

# 2. 调拨商品明细真实展开

`tests/site.test.mjs` + 浏览器测试：

- 1 SKU：不折叠，直接显示商品图片/占位、名称、SKU、×数量；
- 2 SKU：存在可展开交互；
- 7 SKU：默认摘要不会把 7 行全部撑开；
- 点击后 7 个 SKU 全部存在于可见区域；
- 再点击可收起；
- 不再只出现“等 7 项”却无详情；
- 展开区域中的数量与调拨计划一致；
- 已收货/异常关闭数量如有单独展示，必须使用后端事实。

---

# 3. 商品 + 数量统一组件

结构测试至少抽查：

- 采购列表；
- 采购已选明细；
- 调拨列表；
- 调拨收货；
- 调拨异常关闭；
- 订单明细；
- 退货明细；
- 补货生成采购草稿。

每个业务商品数量条目至少能找到：

- 图片或无图占位；
- 商品名称；
- SKU；
- 数量。

无图片时不得出现浏览器破图图标。

---

# 4. 智能补货主表结构

`tests/site.test.mjs` 必须断言表头顺序：

```text
选择
商品
全仓加权日均出库
近30天出库来源
预测到货周期
可用 / 在途
可售天数
最迟下单
建议补货量
紧急度
操作
```

并断言：

- “商品”是 checkbox 后第一列；
- “查看周期明细”出现在近30天出库来源列；
- velocity 列不再包含这个按钮；
- 不存在旧表头“日均出库”。

---

# 5. 近30天出库来源业务口径

后端测试：

同一 SKU：

- 学校仓订单出库 100；
- 广州仓订单出库 200；
- 马来仓手动销售出库 50；
- 客户退货 30；
- 报损 40；
- 调拨出库 60。

近30天真实出库来源必须：

```text
100 + 200 + 50 = 350
```

不能是：

- 320（扣退货）；
- 390（加报损）；
- 410（加调拨）；
- 其他口径。

明细按仓必须能还原到 350。

---

# 6. 周期明细

点击“查看周期明细”后：

必须能看到：

- Q3；
- Q7；
- Q15；
- Q30；
- W3/W7/W15/W30；
- weight source；
- weighted denominator；
- weighted daily outbound；
- 30 天每仓订单出库；
- 30 天每仓手动销售出库；
- 每仓合计；
- 全仓总计。

禁止显示“退货冲减后净销量”作为补货需求口径。

接口请求窗口必须是 30，不得固定 7。

---

# 7. V3 核心补货公式回归

保留并再次运行 V3 Case A-K。

尤其必须防止前端修复时回归：

```text
weighted_daily = Σ(Qn×Wn) / Σ(n×Wn)
```

以及：

- 退货不扣需求；
- 报损不计需求；
- 主力仓库存隔离；
- 可售天数不含在途；
- 补货库存位包含已确认在途；
- coverage 模式与 safety-stock 模式互斥；
- 未触发时 suggested=0；
- nullable 起订量 / 整箱数；
- lead P80 优先级。

---

# 8. 智能补货按钮真实浏览器回归

必须用真实浏览器逐一点击，不能只做 DOM/单测。

顺序：

1. 进入智能补货；
2. 点击“全局补货参数”；
3. 修改一个允许修改的字段并保存；
4. 点击“重新计算”；
5. 勾选 2 个 SKU；
6. 点击“批量调整参数”；
7. 仅启用 1 个批量字段保存，确认未选字段保持原值；
8. 点击“重新计算所选”；
9. 点击“生成采购草稿”；
10. 确认采购草稿 modal 已完全打开且商品/数量正确；
11. 回到补货页面，点击单 SKU“调整参数”；
12. 点击“恢复默认”；
13. 点击“查看周期明细”；
14. 对建议量 >0 的 SKU 点击“创建采购”。

全过程要求：

```text
pageerror = 0
console.error = 0
Cannot set properties of null = 0
UnhandledPromiseRejection = 0
```

---

# 9. Sticky Header / 几何测试

至少：

- 1440×900；
- 1920×1080。

断言 header 与 tbody 对应列的 x/width 误差在合理像素范围内，不发生列错位。

特别检查新增“近30天出库来源”后：

- 商品仍为第一业务列；
- 商品图片没有被 sticky clone 遮挡；
- 表头不重叠；
- 横向滚动正常。

---

# 10. 静态与后端测试最低命令

Codex 应根据项目实际环境执行等价命令，至少包括：

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

如果仓库测试命令发生变化，以仓库当前配置为准，但不得少跑 ERP 后端、前端 domain/team/site 和真实浏览器回归。

---

# 11. 完成门槛

Codex 只有在以下全部满足时才能写“完成”：

- 自动化测试通过；
- migration 状态明确；
- 真实浏览器点击全部通过；
- 页面无裸 JS 错误；
- V3 公式未回归；
- 用户截图对应问题全部消失；
- commit 已 push 到指定实现分支；
- 没有修改 `main`；
- 没有自动 merge；
- 没有直接生产部署。

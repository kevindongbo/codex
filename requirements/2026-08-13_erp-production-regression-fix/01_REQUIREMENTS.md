# ERP 生产回归修复需求：在途库存与订单取消

需求日期：2026-08-13（Asia/Shanghai）

GitHub 仓库：`kevindongbo/codex`

生产当前分支：`codex/erp-inventory-order-workflow-corrections-20260813`

生产当前提交：`caa688a58bb2bbd0f29da890c8e89e022a025aca`

关联 Draft PR：<https://github.com/kevindongbo/codex/pull/14>

状态：已实施，待代码审查与生产数据验证

本文件是本次修复的最终业务验收标准。若旧需求、旧测试或旧实现与本文件冲突，以本文件和生产真实数据为准。

---

## 1. 已确认的生产问题

### 1.1 在途库存口径仍不一致

生产页面中，SKU `AI-BAG-BROWN-05`（豹纹托特-棕色）出现：

- 库存列表“在途库存”：`95`
- 在途来源弹窗：采购单 `PO-20260805-2715` 剩余 `150`
- 在途来源弹窗：仓间调拨 `TR-20260729-1510` 剩余 `95`
- 来源剩余合计：`245`

因此列表显示 `95` 是错误结果，正确结果应为：

```text
150 + 95 = 245
```

代码审计确认，来源弹窗按采购/调拨业务单据实时汇总；库存列表仍通过 `StockBalance.purchased_pending_shipment + StockBalance.in_transit` 读取历史余额。老采购单未正确回填余额时，两个位置就会不一致。

### 1.2 ERP 订单取消仍返回 HTTP 500

生产页面点击“取消”后仍失败：

```text
服务器处理失败，请提供诊断编号给技术人员排查。
诊断编号：31612395edf2
```

前端点击、确认和请求已经发生，但后端未完成取消。当前不能把 ERP 取消订单判定为完成。

---

## 2. 实施前强制检查

1. 完整阅读项目记忆、根目录和适用子目录的 `AGENTS.md`、相关 `agent-memory`、旧需求以及本文件。
2. 检查当前分支、HEAD、工作区、远端分支和 PR #14，不覆盖已有修改。
3. 从已部署提交 `caa688a58bb2bbd0f29da890c8e89e022a025aca` 创建新的 `codex/` 修复分支；不得直接修改或合并 `main`。
4. 先读取生产日志和数据库只读诊断结果，再修改取消逻辑；不得仅凭代码猜测 HTTP 500 根因。
5. 不创建第二套采购、调拨、库存余额、订单或 reservation 模型。
6. 涉及历史库存数据修复前必须创建数据库备份，并先提供 dry-run 结果。
7. 不读取、输出、提交或覆盖生产 `.env`，不得泄露密码、Token、AccessKey 或私钥。

开始前至少执行：

```bash
git status --short
git branch -vv
git log --oneline --decorate -20
git reflog -20
git remote -v
```

---

## 3. 需求一：在途数量采用统一权威计算

### 3.1 统一公式

每个组织、仓库、SKU 的在途库存必须为：

```text
采购待发货剩余
+ 采购已发货在途剩余
+ 调入本仓的调拨在途剩余
```

各来源剩余量：

```text
采购待发货剩余
= 采购计划数量
- 已确认发货数量
- 未发货异常关闭数量
- 未绑定已确认发货批次的完成收货数量

采购已发货在途剩余
= 已确认发货数量
- 对应完成收货数量
- 已发货异常关闭数量

调拨在途剩余
= 调拨计划数量
- 已收货数量
- 异常关闭数量
```

所有结果最小为 `0`。采购草稿、已取消来源、已完成且无剩余来源不得计入。

### 3.2 单一权威来源

- 抽取一个后端领域级汇总函数/服务，同时返回 `total` 和 `sources`。
- 库存列表、顶部在途总数、智能补货、`inventory_position`、来源弹窗必须调用同一计算规则。
- API 返回的 `inbound_total` 必须严格等于其来源数组中所有 `remaining_quantity` 的总和。
- 不允许列表继续读取一个数、弹窗再用另一套查询计算另一个数。
- `StockBalance.purchased_pending_shipment` 和 `StockBalance.in_transit` 如继续保留，应视为业务动作维护的缓存/余额，并必须能与权威来源核对；不能在页面上压过权威汇总结果。
- 不得把同一采购数量同时从余额字段和业务单据重复相加。

### 3.3 历史数据核对与修复

必须提供只读诊断和可审查的修复方式：

1. 按组织、仓库、SKU 输出：余额字段、来源计算值、差异和涉及单号。
2. 默认 dry-run，不修改任何数据。
3. 对确认需要修复的历史余额，提供带明确组织/仓库/SKU 范围的 management command 或 data migration。
4. 正式修复必须事务化、幂等，并记录修复前后值；不得修改 `on_hand` 或 `reserved`。
5. 先备份生产数据库，再执行修复；执行后再次运行 dry-run，差异必须为零。

### 3.4 验收标准

SKU `AI-BAG-BROWN-05` 在马来仓库必须同时显示：

```text
采购来源：150
调拨来源：95
在途库存：245
来源合计：245
可用库存：7
库存位：252
```

并验证：

- 顶部在途总数同步增加这笔采购 `150`；
- 智能补货显示 `可用 / 在途 = 7 / 245`；
- 补货计算的 `inventory_position = 252`；
- 收货、异常关闭或取消后，上述所有位置一次刷新后同步变化；
- F5 后数据保持一致。

---

## 4. 需求二：修复 ERP 订单取消生产失败

### 4.1 必须先完成真实日志取证

使用诊断编号 `31612395edf2` 查询同一请求的 Gunicorn/Django 日志，记录：

```text
操作时间
订单号和订单 UUID
请求方法和 URL
HTTP 状态码及响应摘要
完整异常类型和堆栈
订单 status、warehouse、fulfillment_override
每条订单行 quantity、quantity_reserved、quantity_shipped
每条有效 StockReservation 的仓库、SKU、数量和状态
对应 StockBalance 的 on_hand、reserved
```

日志和数据库诊断不得输出用户隐私、Token、Cookie 或生产 `.env`。

最终交付必须写明已确认的真实根因；只写“可能是历史脏数据”不能验收。

### 4.2 已确认的历史不一致处理策略

采用“可证明安全时自动修复并取消，否则原子阻止”的方式。

安全自动修复条件必须同时满足：

1. 所有有效 reservation 均属于当前订单的订单行；
2. reservation 的 SKU、仓库和组织与订单行及订单一致；
3. 每个仓库/SKU 的 `StockBalance.reserved` 不小于本订单准备释放的有效 reservation 总量；
4. 释放后 `reserved` 不为负数，且不影响其他订单的有效 reservation；
5. 当前订单尚未出库，订单行 `quantity_shipped = 0`；
6. 不存在跨仓、跨 SKU、孤立 reservation 或无法确定归属的数据。

满足条件时，在同一数据库事务内：

1. 以有效 `StockReservation` 为订单锁库归属的事实依据；
2. 将 `SalesOrderLine.quantity_reserved` 校正为该行有效 reservation 合计；
3. 释放当前订单全部有效 reservation；
4. 同步减少对应 `StockBalance.reserved`；
5. 将 reservation 标记为已释放；
6. 将订单改为 ERP 人工取消状态；
7. 写入包含校正前值、校正后值、释放数量和操作人的审计记录。

任意步骤失败必须完整回滚，不能出现订单已取消但库存未释放，或只释放部分 SKU。

### 4.3 无法安全证明时的处理

若总账也不一致、可能影响其他订单、存在跨仓/跨 SKU、负数风险或已出库数量：

- 不修改订单、订单行、reservation、库存余额或库存流水；
- 返回明确的 4xx 业务错误，不返回 HTTP 500；
- 返回稳定错误码和诊断编号；
- 提示“数据不一致，未改动库存，请联系管理员处理”；
- 提供只读诊断 management command；
- 如需人工修复，必须另做带 dry-run、备份、明确范围和审计记录的命令，不允许页面静默修库存。

### 4.4 正常业务规则保持不变

- ERP 取消只停止 ERP 内部履约，不调用 TikTok、Shopee、Ozon 等平台取消接口。
- 未锁库的 DRAFT/READY 订单可直接取消。
- 已锁库但未出库订单取消时原子释放锁库。
- 已出库订单禁止取消并返回明确 4xx。
- 重复取消必须幂等，不能重复释放库存或重复生成流水。
- 平台重新同步不能自动恢复 ERP 人工取消状态。
- 人工“恢复履约”后清空旧仓库与旧锁库，必须重新选仓、校验并锁库。

### 4.5 前端验收

真实链路必须为：

```text
点击取消
→ 弹出确认
→ 用户确认一次
→ 只发送一次 POST /api/orders/{id}/cancel/
→ 成功后刷新订单与库存状态
```

- 请求处理中禁用取消按钮，防止双击。
- 4xx 展示后端业务错误和诊断编号。
- 500 展示诊断编号，且后台日志可用同一编号找到堆栈。
- 成功后订单立即进入“已取消”，锁定数量同步下降。

---

## 5. 必须新增的回归测试

### 5.1 在途库存

- 老采购单余额未回填时，来源为采购 `150`、调拨 `95`，API 和页面仍统一显示 `245`。
- `inbound_total` 严格等于来源剩余合计。
- 顶部总数、库存列表、来源弹窗、智能补货和 `inventory_position` 使用同一结果。
- 采购部分收货、调拨部分收货、异常关闭和取消后，各位置同步减少且不重复扣减。
- 历史数据诊断命令 dry-run 不写库；修复命令幂等。

### 5.2 订单取消

- 未锁库订单正常取消。
- 订单行汇总与有效 reservation 一致时正常释放。
- 订单行 `quantity_reserved` 错误、但有效 reservation 和仓库总账可证明安全时，自动校正并完成取消。
- `StockBalance.reserved` 可能影响其他订单时，返回 4xx 且所有数据不变。
- 跨仓、跨 SKU、孤立 reservation 返回 4xx 且所有数据不变。
- 已出库订单返回 4xx。
- 重复请求只产生一次释放结果。
- 真实前端链路覆盖：点击、确认、API 一次、释放、状态刷新。
- 测试错误处理器能返回诊断编号，并能在日志记录中关联该编号。

不能只用正则检查函数名称代替前端行为测试。

---

## 6. 最低验证命令

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

如果新增 management command，必须另外执行其 dry-run 测试。还必须在本地浏览器或可控测试环境验证真实点击链路，不能只依赖单元测试。

---

## 7. GitHub 与部署要求

1. 只暂存本次相关文件。
2. 创建新功能分支并实际 commit、push。
3. 创建或更新可审查的 Draft Pull Request，基线为当前生产部署提交所在分支。
4. 未经用户明确授权，不合并 PR、不直接部署生产。
5. 如涉及数据修复，部署文档必须分为：备份、代码更新、dry-run、人工确认、正式修复、验证、回滚。
6. 阿里云命令必须使用最终精确 Commit SHA；只有收到真实服务器输出后才能确认部署成功。

---

## 8. 最终交付格式

```text
Implementation branch:
Final HEAD SHA:
Pull Request:
Production cancel diagnostic ID: 31612395edf2
Confirmed cancel root cause:
Database backup:
Migrations/data repair:
Modified files:
Tests run:
Tests passed/failed:
Browser workflow tests:
Production verification:
Known remaining issues:
Deployment impact:
Rollback impact:
```

逐项报告：

```text
1 在途库存统一为 245：PASS / FAIL
2 ERP 取消订单：PASS / FAIL
```

只要存在以下任一情况，不得写“全部完成”：

- 库存列表显示 `95`，来源弹窗合计 `245`；
- 顶部、列表、补货、库存位或来源明细采用不同口径；
- 取消订单仍返回 HTTP 500；
- 未通过真实日志确认取消失败根因；
- 自动校正可能释放其他订单库存；
- 取消发生部分提交或重复释放；
- 历史数据修复没有 dry-run、备份、幂等和审计；
- 测试没有覆盖真实前端链路。

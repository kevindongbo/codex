# 给 Codex 的实施提示词

请严格实现 `ERP-PROFIT-REQ-20260805-01`，不要根据常识自行扩大范围。

## 仓库与分支

- 仓库：`kevindongbo/codex`
- 基础分支：`codex/implement-erp-requirements-20260804`
- 新建实施分支：`codex/implement-profit-settlement-strategies-20260805`
- 需求文档：`requirements/2026-08-05_0042_UTC+8/PROFIT_CALCULATOR_REQUIREMENTS.md`
- 不要直接改 `main`、`codex/erp-req-20260803-integration` 或文档分支。

## 先审计再修改

开始编码前，逐项定位并记录：

- `profit-calculator.js`
- `index.html`
- `styles.css`
- `app.js`
- `backend/apps/erp/profit_calculator.py`
- `backend/apps/erp/profit_shipping_rates.py`
- `backend/apps/erp/profit_serializers.py`
- `backend/apps/erp/models.py`
- `backend/apps/erp/views.py`
- `backend/apps/erp/urls.py`
- `backend/apps/erp/tests/test_profit_calculator.py`
- `backend/apps/erp/tests/test_api.py`
- `tests/site.test.mjs`
- `tests/domain.test.mjs`

不得只改页面文字；计算公式、API、数据持久化、测试和规则说明必须一致。

## 必须实现

### 1. 买家支付运费

- 配置开关名称：`买家是否支付运费`。
- 开启后显示配送区域，默认西马。
- 当前 Standard 规则：西马 RM2.90、东马 RM8.00。
- 买家支付运费是订单级金额，只加一次，不按 SKU 行数重复。
- 关闭时为 0。
- 删除费用明细中的手工买家运费编辑入口。
- 买家运费不计收入，但进入交易手续费基数，并用于解释平台实际运费与净物流成本。
- 本土发货不套用这份跨境价表，自动运费为 0。

### 2. 交易手续费率调整

- 增加`交易手续费率调整`，按百分点直接加减。
- `最终费率 = max(0, 官方费率 + 调整百分点)`。
- API 返回官方、调整、最终费率和计费基数。
- 不实现真实结算手续费优先。

### 3. 策略保存

- 新增组织级数据库模型和迁移。
- 多套自定义名称策略，同组织名称唯一。
- 保存成功立即设默认，同组织仅一个默认。
- 临时修改未保存不覆盖策略。
- 已加载策略保存时提供`覆盖当前策略`和`另存为新策略`。
- 策略保存计算配置，不保存 SKU 行、广告输入或每日汇率数值。

### 4. LVG

- 跨境售价 <= RM500：`售价 × 10/110`。
- 售价 > RM500：0，并返回“超出 LVG 范围”状态。
- 本土：0。
- LVG 进入总费用、结算金额和广告前/后成本；达人佣金基数仍扣除拆出的 LVG。
- 删除“LVG 仅展示、不计成本”的旧说明与测试。

### 5. 金额汇总

右侧删除蓝色公式框和旧逐项行，只保留：

- 总收入
- 总费用
- 总结算金额
- 广告前总成本合计
- 广告前毛利
- 毛利率
- 广告后总成本合计
- 净利润
- 利润率

公式完全按需求文档。无广告时后三项金额/利润显示未计算，不要显示 0。

### 6. 双币显示

- 一个公共双币格式化函数。
- MYR 主：`RM x ／ ¥ y`；CNY 主时交换。
- 不得显示 `≈`。
- 覆盖顶部 MYR 结果、左侧金额列、右侧金额卡和其他只读 MYR 结果。
- USD CPA 和固定币种输入框保持原单位。

### 7. 费用分组和字体

- 保留已完成的 1 项/多项动态分组规则。
- 展开 `⌄`、收起 `›`。
- 图标与文字、缩进和基线统一。
- 整条分组汇总行可点击，但链接/编辑按钮不能误触发。
- 只在利润页局部把标题、表格正文、右侧汇总字体放大一级，不能破坏布局。

### 8. 采购在途单商品

- 多商品 `<details class="purchase-detail-list">` 结构和样式不能改。
- 单商品增加专用 class，显示 `SKU · 商品名称`。
- 字号/字重对齐多商品 summary 主标题。
- 无箭头、无`共1项`、无展开框。

## 后端汇总字段

后端必须直接返回总收入、总费用、总结算金额、广告前成本/毛利/毛利率、广告后成本/净利润/利润率。前端不得再次拼装财务公式。

## 迁移和并发

- 策略默认切换用数据库事务。
- 使用唯一约束保证同组织策略名称唯一和单默认。
- 对重名、并发保存给出明确错误，不静默覆盖。

## 测试

完整实现需求文档第 16、17 节测试。至少运行并记录：

```bash
cd backend
python manage.py makemigrations --check --dry-run
python manage.py test apps.erp.tests
cd ..
node --check app.js
node --check team.js
node --check profit-calculator.js
node --test tests/site.test.mjs
node --test tests/domain.test.mjs
node --test tests/team.test.mjs
npm run build
```

不得虚构测试通过。失败时保留真实错误和未完成项。

## 提交与 PR

1. 将代码推送到 `codex/implement-profit-settlement-strategies-20260805`。
2. 创建 Draft PR：
   - base：`codex/implement-erp-requirements-20260804`
   - head：`codex/implement-profit-settlement-strategies-20260805`
   - title：`ERP-PROFIT-REQ-20260805: 利润策略、运费与结算汇总完善`
3. PR 描述必须包含：
   - 逐项完成状态；
   - 数据迁移；
   - 公式变化；
   - 测试命令和真实结果；
   - 风险与回滚；
   - 最终精确提交 SHA。
4. 不自动合并，不直接部署。
5. 代码完成并测试后，根据真实最终 SHA 更新阿里云部署文档；不要提前写假的 SHA。

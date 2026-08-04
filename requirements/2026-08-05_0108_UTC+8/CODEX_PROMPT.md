# Codex 实施提示词

请严格执行需求 `ERP-PROFIT-REQ-20260805-01`。

## 仓库和分支

- 仓库：`kevindongbo/codex`
- 基础分支：`codex/implement-erp-requirements-20260804`
- 新建代码分支：`codex/implement-profit-settlement-strategies-20260805`
- 需求文件：`requirements/2026-08-05_0108_UTC+8/PROFIT_CALCULATOR_REQUIREMENTS.md`
- 上传时间：2026-08-05 01:08（UTC+8）

不要直接修改 `main`、`codex/erp-req-20260803-integration` 或文档分支。

## 工作方式

1. 先审计现有实现，再修改代码。
2. 不只修改页面文案；后端公式、序列化、API、数据库迁移、前端、规则说明和测试必须一致。
3. 不扩大需求范围。
4. 不自动合并，不直接部署生产。

## 重点审计文件

- `profit-calculator.js`
- `index.html`
- `styles.css`
- `app.js`
- `team.js`
- `backend/apps/erp/profit_calculator.py`
- `backend/apps/erp/profit_shipping_rates.py`
- `backend/apps/erp/profit_serializers.py`
- `backend/apps/erp/models.py`
- `backend/apps/erp/serializers.py`
- `backend/apps/erp/views.py`
- `backend/apps/erp/urls.py`
- `backend/apps/erp/tests/test_profit_calculator.py`
- `backend/apps/erp/tests/test_api.py`
- `tests/site.test.mjs`
- `tests/domain.test.mjs`
- `tests/team.test.mjs`

## 必须实现

### 1. 买家支付运费

- 增加`买家是否支付运费`开关。
- 开启时显示区域，默认西马。
- Standard：西马 RM2.90，东马 RM8.00。
- 运费为订单级金额，只加入一次，不随 SKU 数量重复。
- 关闭时为 RM0。
- 本土发货不套用跨境规则，返回 RM0。
- 删除费用明细中的手工买家运费编辑入口。
- 买家运费不计总收入，但进入交易手续费基数。

### 2. 交易手续费率调整

- 增加`交易手续费率调整`，单位为百分点。
- `最终费率 = max(0, 官方费率 + 调整百分点)`。
- `+0.20`表示 3.78% → 3.98%，不是乘法。
- 后端返回官方费率、调整值、最终费率、计费基数和金额。
- 不接收真实结算手续费覆盖预测结果。

### 3. 计算策略

- 新增组织级策略模型、迁移、序列化和 API。
- 多套自定义名称策略，同组织名称唯一。
- 保存成功后立即设默认，同组织只能一个默认。
- 临时修改未保存时不得覆盖数据库策略。
- 已加载策略保存时提供`覆盖当前策略`和`另存为新策略`。
- 策略只保存计算配置，不保存 SKU 行、广告输入或每日汇率数值。

### 4. LVG

- 跨境且单件售价 <= RM500：`售价 × 10/110`。
- 售价 > RM500：LVG 为 0，并返回“超出 LVG 范围”。
- 本土：LVG 为 0。
- LVG 进入总费用、结算金额、广告前和广告后成本。
- 达人佣金基数仍扣除拆出的 LVG。
- 删除“LVG 仅展示、不计成本”的旧逻辑、说明和测试。

### 5. 物流

- 跨境段继续按每 10g RM0.15，向上取整。
- `平台实际运费 = 跨境段成本 + 买家支付运费`。
- `净物流成本 = 平台实际运费 - 买家支付运费`。
- 利润实际扣除净物流成本。
- 费用明细可展示买家预测运费作为参考项，但不可编辑，物流分组合计只等于净物流成本。

### 6. 后端金额汇总

后端直接返回：

- 总收入；
- 总费用；
- 总结算金额；
- 广告前总成本；
- 广告前毛利；
- 毛利率；
- 广告后总成本；
- 净利润；
- 利润率。

总费用包含 LVG 和净物流，不包含采购成本和广告费。未填写广告时，广告后总成本、净利润、利润率返回 null，而不是 0。

### 7. 右侧金额明细

- 删除蓝色公式说明框及空白。
- 删除旧逐项汇总行。
- 只保留 9 项：总收入、总费用、总结算金额、广告前总成本合计、广告前毛利、毛利率、广告后总成本合计、净利润、利润率。
- 左侧费用明细继续显示具体费用，不要把删除项机械搬过去。

### 8. 双币显示

- 编写一个公共双币格式化函数。
- MYR 主：`RM 20.69 ／ ¥ 34.13`。
- CNY 主：`¥ 34.13 ／ RM 20.69`。
- 不显示`≈`。
- 覆盖顶部利润金额、费用明细金额列、右侧金额卡和其他只读 MYR 结果。
- USD CPA 以及固定币种输入框保持原单位。

### 9. 费用分组和对齐

- 保留现有六列和`profitBasisToggle`。
- 一个费用项：单行，无汇总、图标和折叠。
- 两项及以上：汇总加明细，默认展开。
- 展开`⌄`，收起`›`。
- 图标固定宽度、文字基线和缩进统一。
- 整条分组汇总行可点击；规则链接和编辑按钮不能误触发。

### 10. 字体

- 仅在利润页作用域内将标题、费用明细正文、右侧金额正文放大一级。
- 不破坏列宽、按钮、金额和响应式布局。

### 11. 采购在途单商品

- 多商品`<details class="purchase-detail-list">`结构和样式完全不改。
- 单商品增加专用 class。
- 显示`SKU · 商品名称`。
- 字号和字重与多商品 summary 主标题一致。
- 无箭头、无`共1项`、无展开框。

## 测试

必须实现需求文档第 16、18 节的测试，并实际运行：

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

不得虚构测试通过。失败时在 PR 中写明真实错误和未完成项。

## GitHub 交付

完成后：

1. 推送分支：`codex/implement-profit-settlement-strategies-20260805`。
2. 创建 Draft PR：
   - base：`codex/implement-erp-requirements-20260804`
   - head：`codex/implement-profit-settlement-strategies-20260805`
   - title：`ERP-PROFIT-REQ-20260805: 利润策略、运费与结算汇总完善`
3. PR 描述必须写明：
   - 逐条完成状态；
   - 数据库迁移；
   - 公式变化；
   - 测试命令和真实结果；
   - 风险和回滚；
   - 最终精确提交 SHA。
4. 不自动合并，不部署生产。

## 阿里云部署文档

代码完成、测试通过并推送后，新增或更新：

```text
docs/deployment/aliyun/ERP-PROFIT-REQ-20260805-01.md
```

部署文档必须基于真实最终提交 SHA，包含：

- 代码和 PostgreSQL 备份；
- 精确 SHA 拉取/检出；
- Python 依赖安装；
- Django migration；
- 静态资源构建和 collectstatic；
- systemd `dongbo-erp` 重启；
- nginx 检查和重载；
- `/api/health/`健康检查；
- 页面人工验收；
- 完整回滚命令。

不要在最终 SHA 未确定前写假的部署 SHA。

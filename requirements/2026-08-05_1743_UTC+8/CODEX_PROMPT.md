# Codex 实施提示词

请严格执行需求：`ERP-PROFIT-UI-REQ-20260805-01`。

## 仓库和分支

- 仓库：`kevindongbo/codex`
- 基础分支：`codex/implement-profit-settlement-strategies-20260805`
- 基础 SHA：`807f207b35a7ea0b5b0b7448627146af4a58f852`
- 新建代码分支：`codex/implement-profit-strategy-ui-fixes-20260805`
- 完整需求：`requirements/2026-08-05_1743_UTC+8/PROFIT_STRATEGY_UI_REQUIREMENTS.md`

不要直接修改`main`、基础分支或文档分支。不要自动合并，不要部署生产。

## 工作要求

1. 先审计当前实现，再修改。
2. 前端、后端 API、权限、事务、审计日志和自动化测试必须同步。
3. 不改变现有利润公式、九项金额汇总、SKU 输入和采购在途逻辑。
4. 不使用浏览器原生`prompt/confirm`实现策略弹窗。
5. 不得虚构测试通过。

## 必须完成

### 1. 计算配置布局

- 删除配置面板里的`计算币种`，保留右上角 MYR/CNY 切换。
- 将`交易手续费调整`放到原计算币种所在的第一行位置。
- `参加 BXP`和`买家是否支付运费`放在同一视觉行。
- 主页面移除`买家收货地区`、策略下拉框、策略名称输入框和旧保存按钮。

### 2. 顶部策略栏

在计算配置面板顶部增加横向策略栏：

```text
[自定义策略名...] [+ 新建计算策略] [保存当前策略] [删除策略]
```

- 显示用户自定义名称；
- 当前默认策略高亮；
- 名称较多时横向滚动；
- 无策略时只显示新建按钮；
- 点击策略直接放弃未保存修改、回填全部配置并在服务器端立即设为默认。

### 3. 新建和保存弹窗

新建弹窗只填写：

- 策略名称；
- 买家收货地区。

其余配置读取主页面当前值。地区默认西马；买家运费关闭时地区置灰并保存西马。

保存当前策略先弹出：

- 覆盖当前策略；
- 另存为新策略；
- 取消。

覆盖：名称只读、地区可修改。另存：名称和地区可填写。

### 4. 同名自动覆盖

同组织新建/另存使用已有名称时，不返回 409，事务内覆盖该同名策略并设为默认。保留数据库唯一约束。新建可返回 201，同名覆盖返回 200。

### 5. 点击即默认和删除

- 建议增加`POST /api/profit-calculator/strategies/{id}/activate/`。
- ViewSet 支持 DELETE。
- 删除前使用项目模态框二次确认。
- 删除后有剩余策略：按列表第一项加载并设默认。
- 删除最后一项：恢复系统默认配置，不自动创建数据库策略。
- 所有操作保持组织隔离并写审计日志。

### 6. 币种显示恢复

修复重复定义`formatMoney`的问题，拆分单币/双币格式化。

- 顶部利润卡：主币大字；下方辅助币小字并带`≈`。
- 左侧费用明细：只显示当前主币种。
- 右侧九项金额明细：保留`主币 ／ 辅助币`同行双币。
- 不得清空顶部辅助币元素。

### 7. 多项费用默认折叠和 SVG 箭头

- 单项费用现有无折叠逻辑保持不变。
- 多项分组初始`aria-expanded=false`，明细 hidden。
- 每次重新计算并渲染结果，全部恢复默认折叠。
- 删除字符`⌄/›`，使用同一个 18–20px 粗线内联 SVG，折叠向右、展开旋转向下。
- 图标与文字垂直居中、固定宽度和间距。
- 整条汇总行可点击；链接和编辑按钮不得误触发；支持 Enter/Space。

## 重点审计文件

- `index.html`
- `profit-calculator.js`
- `styles.css`
- `backend/apps/erp/models.py`
- `backend/apps/erp/serializers.py`
- `backend/apps/erp/views.py`
- `backend/apps/erp/urls.py`
- `backend/apps/erp/tests/test_profit_calculator.py`
- `tests/site.test.mjs`
- `docs/deployment/aliyun/ERP-PROFIT-REQ-20260805-01.md`

## 测试

按完整需求第 15 节增加/修改测试，并实际运行：

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

当前后端测试中“同名创建返回 409”的断言必须改为覆盖成功；当前站点测试中旧策略下拉框和全页面双币断言也必须更新。

## GitHub 交付

完成后：

1. 推送`codex/implement-profit-strategy-ui-fixes-20260805`。
2. 创建 Draft PR：
   - base：`codex/implement-profit-settlement-strategies-20260805`
   - head：`codex/implement-profit-strategy-ui-fixes-20260805`
   - title：`ERP-PROFIT-UI-REQ-20260805: 计算策略弹窗与费用折叠修正`
3. PR 描述写明：逐条完成状态、API 变化、迁移情况、测试真实结果、风险、回滚、最终精确 SHA。
4. 更新`docs/deployment/aliyun/ERP-PROFIT-REQ-20260805-01.md`，把旧的已测试 SHA 替换为本次最终真实 SHA，并补充本次页面验收项。
5. 不自动合并，不部署生产。

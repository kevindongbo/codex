# V4 需求追踪表

时间：2026-08-24 21:43 +08:00

| ID | 需求 | 当前基线状态 | 主要代码位置 | 必须测试 |
|---|---|---|---|---|
| TR-01 | 异常关闭必须保留 idempotency_key | V3 实现已基本完成 | `team.js closeTransferException()` | team + Django 幂等 |
| TR-02 | 异常关闭 reason 可空 | 未完成 | `serializers.py`、`app.js`、view/service | 空/缺省/有值 |
| TR-03 | 结束调拨 reason 可空 | 未完成 | `team.js`、`app.js`、`serializers.py`、view/service | 空 reason + 二次确认 + 幂等 |
| TR-04 | 异常关闭库存语义不变 | 必须回归 | transfer service / ledger | 100→80→20 Case |
| TR-05 | 调拨商品明细真正展开 | 未完成 | `app.js renderTransfers()` | 1/2/7 SKU 浏览器 |
| UI-01 | 商品+数量统一图片组件 | 未完成 | `productMedia()` 及采购/调拨/订单渲染 | site + E2E |
| RP-01 | 商品为第一业务列 | 未完成/需几何复核 | `index.html`、`styles.css`、sticky clone | 1440/1920 |
| RP-02 | 标题“全仓加权日均出库” | 需核对 | `index.html` | site |
| RP-03 | 新增独立“近30天出库来源”列 | 未完成 | `index.html`、`app.js`、API | site + E2E |
| RP-04 | 查看周期明细属于近30天来源列 | 未完成 | `app.js renderReplenishment()` | site + click |
| RP-05 | 详情窗口改为 30 天 | 未完成 | `team.js getReplenishmentDemandDetail()`、`app.js` | API 30 + UI |
| RP-06 | 30天来源不扣退货 | 后端主算法已改，前端旧 fallback 仍冲突 | `replenishment.py`、`app.js normalizeDemandWarehouse()` | 订单/手动/退货/报损 Case |
| RP-07 | 加权总量/加权天数公式 | V3 后端已实现，必须防回归 | `replenishment.py` | V3 Case A |
| RP-08 | 全仓销量 | V3 已部分实现，必须回归 | `replenishment.py`、views | 多仓 Case D |
| RP-09 | 主力仓 SKU Profile | V3 migration 已实现 | `models.py`、`0035...`、views | 无主力仓/切换主力仓 |
| RP-10 | 无主力仓不给正式决策 | 需回归 | recommendation API / UI | no-primary Case |
| RP-11 | 主力仓库存不被其他仓抵扣 | 需回归 | `replenishment.py` | Case E |
| RP-12 | 可售天数不含在途 | 需回归 | `replenishment.py` | available/inbound Case |
| RP-13 | 补货库存位含已确认在途 | 需回归 | inbound snapshot / replenishment | purchase + transfer inbound |
| RP-14 | coverage / safety 两模式互斥 | V3 规则，需回归 | `replenishment.py` | Case F/G/H |
| RP-15 | 未触发 suggested=0 | V3 规则，需回归 | `replenishment.py` | Case F |
| RP-16 | 起订量 nullable | V3 migration 已做，需 UI/API 回归 | profile serializer/view/UI | null / 100 |
| RP-17 | 整箱数 nullable | V3 migration 已做，需 UI/API 回归 | profile serializer/view/UI | null / 50 |
| RP-18 | 起订量后整箱取整 | V3 规则 | `replenishment.py` | Case I/J/K |
| RP-19 | lead 完整收货 P80 > 首次 P80 > 人工 fallback | V3 规则 | `estimate_lead_time()` | 样本优先级 |
| RP-20 | 用户不可编辑 review cycle，后台每日检查 | V3 已有定时文件，需核对 | UI settings + management command/timer | UI 无可编辑 + command |
| RP-21 | 全局补货参数按钮 | 用户实测失败 | `openReplenishmentSettings()` / template | 浏览器 click |
| RP-22 | 重新计算按钮 | 用户实测失败 | bind/action/API | 浏览器 click |
| RP-23 | 批量调整参数 | 用户实测失败 | batch modal / API | 浏览器 click |
| RP-24 | 重新计算所选 | 用户实测失败 | selected set / API | 浏览器 click |
| RP-25 | 生成采购草稿 | 用户实测失败/需检查 async | `openBatchPurchaseDraft()`、`openPurchaseEditor()` | await + E2E |
| RP-26 | 创建采购 | 需运行时回归 | action handler | E2E |
| RP-27 | 调整参数 | 用户实测失败 | `openReplenishmentPolicy()` | E2E |
| RP-28 | 恢复默认 | 需运行时回归 | delete/reset action | E2E |
| RP-29 | 查看周期明细 | 位置/窗口均需改 | `openReplenishmentDemandDetail()` | E2E |
| JS-01 | 消除 `Cannot set properties of null` | 未完成 | 所有补货 modal DOM 写入 | pageerror=0 |
| JS-02 | async modal 先完成再写值 | 需审计 | purchase/replenishment async paths | E2E |
| QA-01 | 不改 main | 强约束 | Git workflow | 最终分支核对 |
| QA-02 | 不自动 merge / 不部署生产 | 强约束 | Git/部署流程 | handoff |
| QA-03 | 自动化 + 浏览器均通过才算完成 | 强约束 | tests / Playwright | 完整报告 |

## 追踪使用规则

Codex 开工前应复制/扩展此表，在实现完成时给每行增加：

- 实际修改 commit；
- 测试名；
- 结果；
- 是否仍有风险。

不能把“代码里有函数”当成“已验证”。

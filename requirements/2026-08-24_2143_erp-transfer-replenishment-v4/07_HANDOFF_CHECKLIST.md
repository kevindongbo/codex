# V4 Codex 完成交接清单

Codex 完成后必须完整返回以下内容，不能只说“已完成”。

## Git 信息

- GitHub 仓库：`kevindongbo/codex`
- 实现分支：`codex/erp-transfer-replenishment-v4-implementation-20260824`
- 开工 HEAD
- 最终 HEAD SHA
- commit SHA / commit message
- `git status` 最终状态
- 是否存在未 push commit

## 修改范围

逐文件列出：

- 文件路径；
- 修改目的；
- 核心逻辑；
- 对应需求编号。

## Migration

- 是否新增 migration；
- migration 文件名；
- 依赖 migration；
- 数据迁移逻辑；
- 升级测试结果；
- 回滚方式；
- 是否需要生产执行 `python manage.py migrate`。

已有 `0035_sku_replenishment_profile_v3.py`，不能忽略其存在。

## 需求完成状态

至少逐项：

- 异常关闭 reason 可空；
- 结束调拨 reason 可空；
- 异常关闭 idempotency 保持；
- 调拨商品明细展开；
- 商品图片/名称/SKU/数量统一；
- 补货表格字段顺序；
- 近30天出库来源；
- 周期明细位置；
- 30 天接口；
- 不扣退货；
- V3 加权公式；
- 主力仓；
- coverage/safety 两模式；
- 起订量/整箱；
- lead P80；
- 补货按钮；
- sticky header；
- 每日后台检查。

每项只能写：

- 已完成且已验证；
- 已实现但未验证；
- 未完成；
- 不适用（说明理由）。

## 自动化测试

逐条粘贴命令和真实结果摘要：

```text
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py test apps.erp.tests --noinput
node --check app.js
node --check team.js
node --test tests/site.test.mjs tests/domain.test.mjs tests/team.test.mjs
node scripts/build-site.mjs
git diff --check
```

以及实际项目新增的测试。

不得写“测试通过”而不写数量/结果。

## 浏览器 E2E

报告：

- 使用的 URL / 测试环境；
- 浏览器；
- viewport；
- 调拨展开结果；
- 空 reason 异常关闭结果；
- 结束调拨空 reason 结果；
- 智能补货 9 类按钮结果；
- 30 天明细结果；
- 生成采购草稿结果；
- 1440×900 sticky header；
- 1920×1080 sticky header；
- `pageerror` 数量；
- `console.error` 数量。

不能运行浏览器时明确写“未验证”。

## 部署影响（只报告，不执行）

- 是否需要 migrate；
- 是否需要 collectstatic；
- 是否需要前端 build；
- 是否改依赖；
- 是否新增/修改 systemd timer / cron / management command；
- 需要重启哪些服务（只有仓库可以确认时才写，不能猜）；
- 新增环境变量（无则写无）。

## 风险与回滚

- 尚存风险；
- 未验证项；
- 回滚到哪个 commit；
- migration 如何回滚；
- 是否存在不可逆数据迁移。

## 禁止事项确认

最后明确确认：

- 没有修改 main；
- 没有 merge；
- 没有生产部署；
- 没有删测试掩盖错误；
- 没有硬编码测试数据绕过公式；
- 已 push 到指定实现分支。

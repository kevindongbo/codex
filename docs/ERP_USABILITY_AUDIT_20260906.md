# ERP 可用性审计与小步优化（2026-09-06）

## 第二轮：输入与权限安全复查

用户追加授权：修复后推送 GitHub，并提供阿里云部署命令（不代为执行生产部署）。

- 已复现并修复：补货批量参数/重新计算接口缺少仓库写权限校验；批量修改同时核验请求仓库、已有主力仓、新主力仓，不能靠传入另一授权仓绕过。
- 已复现并修复：NaN、Infinity、超精度/超范围数值及非法 UUID 导致 500；小数天数被 int() 静默截断。现在用 DRF 字段在写入前拒绝，返回 400。
- 保留空字符串清空覆盖天数、空起订量、三位小数数量、完整权重合计 1 的现有合法输入；不改计算公式。
- 增加 test_replenishment_input_safety.py，测试非法输入不落库、未授权请求不创建任务、授权后合法写入、主力仓绕过防护。
- 新增 deploy/erp-usability-release.sh，使用固定 SHA、脏工作区保护、生产环境加载、迁移只检查、源站资源逐文件 hash 核验和仅代码回滚；禁止恢复数据库。Bash 5.2 语法检查通过，真实 Linux/systemd/Nginx 执行未验证。
- 本次为定向代码审计，不是全系统渗透测试，不保证不存在其他漏洞。
- 第二轮最终结果：后端全量 171/171、前端 60/60、三套浏览器脚本、Django check、migration dry-run、JS 语法、构建与 diff 检查均通过。下文 166 项为第一轮审计结果。

## 基线与范围

- 仓库：kevindongbo/codex。
- 实现分支：codex/erp-usability-audit-20260906。
- 基线：origin/codex/erp-transfer-replenishment-v4-implementation-20260824，3569b836048c6edfa9dd2ac6b9ae38fbb08cca91。
- 保留原本本地 V4 分支；未 reset、未修改 main、未部署生产。
- 读取项目记忆、协作规则、相关记忆主题以及继承 V3 完整需求和 V4 覆盖要求后，审计公共导航、弹窗、表格、前后端适配及 ERP 核心接口。不是每个文件逐行安全审计，也不是生产全业务验收。

## 需求与改动追踪

| 模块/问题 | 代码位置 | 处理 | 验证 |
| --- | --- | --- | --- |
| 数据分析/达人侧栏消失 | styles.css、app.js renderSidebar | 删除遗漏新模块的旧 CSS 白名单，以既有 active 状态显示侧栏 | 六模块 × 三尺寸共 18 组真实浏览器导航 |
| 分析/达人/商品利润表筛选栏裸控件 | styles.css analytics-toolbar | 统一 40px 控件、间距、换行、焦点提示，分析摘要响应式两列 | 桌面截图复核、三尺寸无页面横向溢出 |
| 调拨多 SKU 明细/补货详情链接缺少布局 | styles.css | 为既有 details 和详情按钮补齐样式，不改展开业务数据 | 表格浏览器几何测试；多 SKU 完整操作本轮未验证 |
| 最高紧急度排在后面 | app.js renderReplenishment | 优先级 0 使用空值合并，不再被当成缺省值 | 浏览器固定服务端形状数据，最后一个 urgent SKU 必须排第一 |
| 粘性表头重复 ID/键盘焦点 | app.js updateClonedStickyHeader | 视觉副本移除 ID，标记 inert | 1440×900、1920×1080，11 列左右边界差不超过 2px；横向滚动同步 |
| 弹窗键盘离开、关闭后焦点丢失 | app.js openModal/closeModal/bindEvents | 焦点环、返回打开按钮、最上层弹窗处理；确认栏先于父弹窗关闭 | Tab、Shift+Tab、Escape、确认栏层级与焦点浏览器断言 |
| 补货设置分页无稳定顺序 | backend/apps/erp/views.py | queryset 按 id 排序，不更改组织权限或计算 | 后端全量测试 |
| 旧 API 测试依赖废弃仓库补货策略 | backend/apps/erp/tests/test_api.py | 测试改用现存 SKUReplenishmentProfile；核验零需求不被起订量制造、主力仓隔离、批量仅覆盖指定字段 | 后端 166 项通过 |
| 浏览器缓存混用资源 | index.html、tests/site.test.mjs | 资源版本更新为 20260906-erp-usability-1 | 构建后站点测试 |

## 保持不变

- 后端仍为智能补货唯一计算真值；全仓真实销售需求、SKU 主力仓库存、权重公式、触发点、起订量/整箱顺序均未改动。
- 采购、收货、订单、退货、调拨、StockLedger 的事务、数量、幂等及审计逻辑未修改。
- 利润规则、汇率、达人归因、权限和组织隔离未修改。
- 只修展示排序，不修改建议补货数量或紧急度计算。

## 实际测试

Windows 本地使用 Node 24、捆绑 Python、现存 .codex-python-deps，后端数据库为临时内存 SQLite，DJANGO_DEBUG=true。集成测试使用当次临时生成的 Fernet 测试密钥，不读取生产密钥。

| 命令 | 最终结果 |
| --- | --- |
| python backend/manage.py check | 通过，无问题 |
| python backend/manage.py makemigrations --check --dry-run | 通过，No changes detected |
| python backend/manage.py test apps.erp.tests --noinput | 166/166，通过 |
| node --check app.js | 通过 |
| node --check team.js | 通过 |
| node scripts/build-site.mjs | 通过；站点测试必须在最新构建之后运行 |
| node --test tests/site.test.mjs tests/domain.test.mjs tests/team.test.mjs | 60/60，通过 |
| node tests/browser/erp-usability.test.mjs | 通过：18 组模块/视口；弹窗与确认栏焦点；pageerror=0、console.error=0 |
| node tests/browser/replenishment-sticky.test.mjs | 通过：两尺寸、11列对齐、横向滚动、商品位置、紧急排序；pageerror=0、console.error=0 |
| node tests/browser/profit-workflow.test.mjs | 通过：工作配置防抖/F5、临时 SKU 隔离、保存/重开/重算新版本/另存 |
| git diff --check | 通过 |

浏览器使用本机 Edge + Playwright，展示测试使用明确的接口 fixture；利润工作流同样使用模拟接口，不等于已验证生产后端端到端。截图在本地 .tmp/erp-usability/analytics-desktop.png，不提交临时文件。

审计过程曾出现旧测试与 V3 规则不符、测试密钥缺失、旧 dist 资源与新版本断言不符、动画中读取尺寸导致断言失败，已分别修正测试前置条件/对齐业务断言/先构建/等待动画完成，最终结果以上表为准，未删除测试。

## 未验证与风险

- 未连接生产网站或服务器；公网缓存、Nginx 实际静态目录、CDN 与生产数据一致性未验证。
- PostgreSQL 并发锁/真实生产数据量性能未验证，SQLite 测试不能替代。
- 本轮没有逐个执行所有采购、库存、调拨、达人写入按钮的真实后端浏览器 E2E；相应核心行为由现有后端/适配层自动化回归覆盖，不能声称全部业务完成验收。
- 大型 app.js 的模块拆分可后续按功能分批做，本轮不进行容易引发业务回归的大规模重构。

## 发布与回滚

- 本轮无模型变化、无新 migration、无新依赖、环境变量或定时任务。无需新增 migrate。
- 需要重新构建前端并同步带新资源版本的 HTML/CSS/JS；本轮没有执行部署。
- Django collectstatic 本轮无新增 Django 静态资源要求；实际站点发布是否使用该目录必须按服务器配置核验，不以 collectstatic 成功替代前端发布验证。
- 若发布后端 queryset 修改，需要重启应用服务；如前端由常驻 Node 服务承载，也需要按真实部署方式更新/重启。当前服务器进程配置未验证。
- 回滚本轮代码到上述基线并重新构建/发布同一版本资源；数据库没有本轮结构或数据变化，不要恢复数据库备份，不要使用强推。

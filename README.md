# 东铂跨境 ERP

面向跨境电商团队的商品、采购、多仓库存、订单出库与竞品监控工作台。顶部保留商品中心、仓配中心、竞品监控三个一级模块，左侧按当前模块展示二级功能。

## v2 已实现能力

- 仓库数量不再写死。组织可按实际业务建立马来仓、货代仓、学校仓、国内仓或其他仓库，并维护国家、时区、地址、联系人、是否允许收货/出库和启停状态。
- 库存按“仓库 × SKU”独立核算；仓间调拨采用“草稿 → 调拨在途 → 已收货”流程，发出时扣来源仓，收货时增目标仓，调拨在途计入目标仓的已确认在途。
- 补货建议按每个仓库、每个 SKU 独立计算，结合采购至完整收货的历史周期、近 7/14/30 天实际出库速度、可用库存、采购在途和调拨在途，输出预计缺货日、最晚下单日、建议采购量、提醒等级、信心度和解释原因。
- 普通订单入口只需一次“确认并出库”。服务端在一个数据库事务中完成确认、整单锁库、拣货/复核状态推进、扣减库存、生成出库单和审计记录；任何一步失败都会整单回滚。
- 竞品第一次需要完整基线快照；后续“快速录销量”只提交累计销量和可选采集时间，价格、评分、评论数、上下架状态与原始字段自动继承最近一条快照。

## 业务口径

- 商品中心统一维护本店商品、直接竞品和间接竞品；本店商品可维护一个或多个唯一 SKU，并记录成本、安全库存、供应商、采购链接和便于识别的图片。
- 采购单审核后形成在途，确认收货才增加已在库；草稿和已取消数量不计入在途。
- 普通订单由“一键确认并出库”整单完成；旧的确认、锁库、拣货、复核、出库分步接口仍保留给高级流程和兼容场景。库存不足时不产生部分锁定或部分出库；退货通过独立入库流水处理。
- 库存流水和关键业务状态应采用追加记录与审计日志，不直接覆盖历史结果。

```text
在途 = 有效采购数量 - 已收货数量 - 已取消数量
已在库 = 期初 + 收货 + 盘盈 + 退货入库 - 出库 - 盘亏 - 报损
锁定 = 尚未出库或取消的订单预留数量
可用 = 已在库 - 锁定
库存位置 = 可用 + 已确认采购在途 + 调拨在途
```

补货默认使用以下口径，参数可按仓库、SKU 覆盖：

```text
加权日速度 = 近 7 天日均 × 50% + 近 14 天日均 × 30% + 近 30 天日均 × 20%
安全库存 = max(加权日速度 × 7 天, 人工安全库存)
补货点 = 加权日速度 ×（预测采购周期 + 检查周期）+ 安全库存
目标库存位置 = 加权日速度 ×（预测采购周期 + max(目标覆盖天数, 检查周期)）+ 安全库存
建议采购量 = max(0, 目标库存位置 - 当前库存位置)，再按 MOQ 和整箱数向上取整
最晚下单日 = 预计库存位置耗尽日 - 预测采购周期 - 安全缓冲天数
```

采购周期优先采用同仓库、同 SKU 的完整收货历史 P80；商品配置了默认供应商时还会按该供应商筛选。样本不足时退回首次收货 P80 或人工默认值。最终信心度取采购周期信心度与出库速度信心度中较低者，页面会同时显示样本不足、时间近似和异常样本排除等原因。

## 本地前端开发

```bash
npm run build
npm test
```

构建产物位于 `dist/server/index.js`。GitHub Pages 和公开演示默认使用浏览器 `localStorage`，适合个人试用，但它们不是联网团队版，也不会把数据保存到服务器。Docker/Caddy 部署会通过 `/runtime-config.js` 自动切换到团队模式，由同源 `/api/` 读取 PostgreSQL 数据。团队模式不会读取或回写本机业务数据，连接中断时只读，也不会静默降级到本机模式。

当前仓库提供了完整的自建部署配置，但没有在本文档中承诺任何正式服务器、域名或 PostgreSQL 实例已经上线。只有在实际服务器执行部署、配置域名/HTTPS、创建管理员并通过多人及恢复演练后，才算完成正式联网交付。

## v2 关键 API

所有业务请求都需要 JWT，并携带 `X-Organization-ID`；路径保留末尾斜杠。

```text
GET/POST        /api/warehouses/                         仓库列表/新建
GET/PATCH       /api/warehouses/{id}/                    仓库详情/编辑
GET/POST        /api/stock-transfers/                    调拨单
POST            /api/stock-transfers/{id}/dispatch/      调拨发出
POST            /api/stock-transfers/{id}/receive/       调拨收货
POST            /api/stock-transfers/{id}/cancel/        调拨取消/在途撤回
GET/POST        /api/replenishment-policies/             补货参数列表/新建
GET/PATCH       /api/replenishment-policies/{id}/        补货参数详情/编辑
GET             /api/replenishment/recommendations/      按 warehouse 查询建议
POST            /api/orders/{id}/confirm-and-ship/       一键事务出库
POST            /api/competitor-snapshots/quick-sales/   只录累计销量
POST            /api/local-imports/validate/             本机备份预检
POST            /api/local-imports/commit/               本机备份提交
```

完整资源与动作清单见 `backend/README.md`，业务状态与公式见 `docs/ERP_ARCHITECTURE.md`。

## Docker 自建部署

部署栈包含 Django API、PostgreSQL 16 与 Caddy。PostgreSQL 不暴露公网；Caddy 从同一域名提供前端、`/api/`、`/admin/`、`/static/`、`/media/` 和 `/monitoring-targets.json`，从而避免跨域和 Cookie 配置分裂。当前代码没有缓存队列和文件上传端点，因此不部署闲置的 Redis 或 MinIO；需要任务队列或对象存储时，应在对应业务代码真正接入后再增加服务。

### 1. 准备配置

服务器需安装 Docker Engine 与 Docker Compose v2，并开放 80/443 端口。复制配置模板：

```bash
cp .env.example .env
```

必须替换 `DJANGO_SECRET_KEY`、`POSTGRES_PASSWORD` 和 `DATABASE_URL`。生产模式会拒绝空值、占位值或少于 50 个字符的 Django 密钥。数据库密码应使用 URL 安全字符，并在 `POSTGRES_PASSWORD` 和 `DATABASE_URL` 中保持一致。不要提交 `.env`。

本机 HTTP 测试保持：

```dotenv
APP_SITE_ADDRESS=:80
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CORS_ALLOWED_ORIGINS=http://localhost
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
```

生产环境示例（不要带末尾斜杠）：

```dotenv
APP_SITE_ADDRESS=erp.example.com
DJANGO_ALLOWED_HOSTS=erp.example.com,127.0.0.1
DJANGO_CORS_ALLOWED_ORIGINS=https://erp.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://erp.example.com
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
```

将域名 A/AAAA 记录指向服务器后，Caddy 会自动申请和续期 HTTPS 证书。

### 2. 启动与检查

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl -fsS http://localhost/api/health/
docker compose exec api python manage.py createsuperuser
```

生产域名启用后，将最后一条改为 `https://erp.example.com/api/health/`。查看日志：

```bash
docker compose logs -f --tail=200 api caddy
```

首次启动会自动执行 Django 数据库迁移并收集静态文件。API 健康检查的实际路径是 `GET /api/health/`；JWT 登录与刷新分别是 `POST /api/auth/token/` 和 `POST /api/auth/token/refresh/`，当前用户与组织为 `GET /api/auth/me/`。DRF 资源路径统一位于 `/api/` 下并保留末尾斜杠，例如 `/api/products/`、`/api/purchase-orders/`、`/api/stock-balances/` 和 `/api/orders/`。

创建超级管理员后，在网站右上角打开“数据与团队”并登录。若账号还没有组织，页面会引导创建第一个组织，同时自动建立 `DEFAULT` 默认仓；创建者成为组织管理员。后续业务请求由前端统一携带 `Authorization: Bearer <access>` 与 `X-Organization-ID: <organization-uuid>`。

### 3. 从本机模式迁移

1. 在原浏览器打开“数据与团队”，下载完整 JSON 备份；原数据不会被删除。服务端迁移器接受 v5 与 v6 备份。
2. 登录一个尚无业务数据的新团队组织，选择仓库后点击“导入本机备份”。
3. 先核对预检中的商品、SKU、竞品、快照、期初库存数量和警告，再确认提交。
4. 服务端用事务和幂等键导入商品/SKU、可共享的 HTTPS 图片、竞品、快照，并通过库存流水建立期初在库。

v6 本机状态新增多仓、调拨与补货参数；页面读取 v5 时会保留原业务数据并规范化为 v6，而不是清空重建。服务端安全迁移接受 v5/v6，但当前导入范围仍是商品/SKU、可共享图片、竞品/快照和指定目标仓的期初库存；不会把多仓结构、调拨、补货参数、已闭环采购、销售订单、退货和旧流水转换成可继续过账的团队单据。这些记录仍完整保留在原 JSON 中。若仍有锁定库存、在途/部分收货采购、未出库订单或未完成退货，预检会阻止切换，必须先处理完成；浏览器 Data URL 或非 HTTPS 图片会列入待补图提示。

### 4. 更新与回滚

更新前先备份，然后拉取已验证版本并重建：

```bash
sh deploy/backup.sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

应用容器每次启动都会执行向前兼容的迁移。涉及破坏性数据库变更时，应先在副本演练并准备对应代码版本与数据备份，不能只回滚容器镜像。

## 备份与恢复

备份脚本保存 PostgreSQL 自定义格式转储、本地媒体卷、版本清单和 SHA-256 校验值。默认备份目录位于项目同级的 `dongbo-erp-backups/`，也可指定：

```bash
BACKUP_ROOT=/srv/backups/dongbo-erp sh deploy/backup.sh
```

将备份复制到另一台机器并定期做恢复演练。恢复会覆盖现有数据，脚本要求显式 `--yes`：

```bash
sh deploy/restore.sh /srv/backups/dongbo-erp/20260715T010203Z --yes
docker compose ps
curl -fsS https://erp.example.com/api/health/
```

建议每天自动备份、至少保留 7 个日备份与 4 个周备份，并把副本同步到独立服务器或云对象存储。备份目录包含业务数据和凭据衍生信息，权限应限制为部署管理员可读。

## 运维边界

- PostgreSQL 是商品、采购、库存、订单、退货、权限与审计日志的唯一事实来源。
- `ProductImage` 可保存外部 HTTPS 图片网址，也可保存前端压缩后的受限大小本地图片数据；本地图片会随商品同步并纳入数据库备份。若未来接入 MinIO/S3，需要同时增加上传端点、访问策略、默认存储配置和对象备份，而不是只启动一个存储容器。
- Caddy 从项目目录只读挂载前端入口、样式、脚本和公开的 `monitoring-targets.json`，另以只读卷提供 Django 静态文件与媒体文件；不会把 `.env`、源码目录或备份目录暴露为静态资源。
- 正式上线前还需完成管理员初始化、最小权限角色、操作审计、恢复演练、监控告警和 API 数据迁移验证。

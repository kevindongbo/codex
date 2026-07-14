# 东铂跨境 ERP

面向跨境电商团队的商品、采购、仓库、订单出库与竞品监控工作台。顶部保留商品中心、仓配中心、竞品监控三个一级模块，左侧按当前模块展示二级功能。

## 业务口径

- 商品中心统一维护本店商品、直接竞品和间接竞品；本店商品维护唯一 SKU、成本、安全库存、供应商、采购链接和便于识别的图片。
- 采购单审核后形成在途，确认收货才增加已在库；草稿和已取消数量不计入在途。
- 订单先整单锁定可用库存，拣货、复核、出库后同时扣减已在库与锁定；退货通过独立入库流水处理。
- 库存流水和关键业务状态应采用追加记录与审计日志，不直接覆盖历史结果。

```text
在途 = 有效采购数量 - 已收货数量 - 已取消数量
已在库 = 期初 + 收货 + 盘盈 + 退货入库 - 出库 - 盘亏 - 报损
锁定 = 尚未出库或取消的订单预留数量
可用 = 已在库 - 锁定
```

## 本地前端开发

```bash
npm run build
npm test
```

构建产物位于 `dist/server/index.js`。团队后端 API 已提供，但当前公开页面尚未切换到团队数据访问层，仍使用浏览器 `localStorage`；正式多人使用必须完成前端 API 接入后，以 PostgreSQL、账号权限和审计日志为准。

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

创建超级管理员后可进入 `/admin/` 建立首个组织，也可以用该账号取得 JWT 后调用 `POST /api/organizations/`；创建者会自动成为该组织管理员。后续业务请求需携带 `Authorization: Bearer <access>` 与 `X-Organization-ID: <organization-uuid>`。

### 3. 更新与回滚

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
- 当前 `ProductImage` 保存外部图片 URL，并没有文件上传接口；`/app/media` 卷仅为 Django 后续本地文件字段预留并纳入备份。若未来接入 MinIO/S3，需要同时增加上传端点、访问策略、默认存储配置和对象备份，而不是只启动一个存储容器。
- Caddy 从项目目录只读挂载前端入口、样式、脚本和公开的 `monitoring-targets.json`，另以只读卷提供 Django 静态文件与媒体文件；不会把 `.env`、源码目录或备份目录暴露为静态资源。
- 正式上线前还需完成管理员初始化、最小权限角色、操作审计、恢复演练、监控告警和 API 数据迁移验证。

# ERP operations platform deployment

## Scope

This release adds batch purchase receiving, manual inbound/outbound and reversible stock ledger entries, safe zero-stock balance deletion, data-backed replenishment settings, TikTok Shop OAuth, encrypted OpenAI-compatible AI providers, and formal uploaded-media URLs for competitor images.

## Database migrations

- `0017_erp_operations_platform` creates replenishment settings, ledger reversals, TikTok OAuth state/connections/sync runs, encrypted AI provider configuration/log/recommendation tables; extends competitor URL fields and stock event types.
- `0018_uploadedmediaasset` creates `UploadedMediaAsset` for uploaded image files. It returns `/api/media-assets/<uuid>/content/`, so the database stores a formal URL rather than Base64.
- `0019_alphashopconfig` creates the organization-scoped `AlphaShopConfig` table. It stores Access Key and Secret Key only as Fernet ciphertext, with a one-row-per-organization constraint.
- `0020_tiktok_shop_connections_per_shop` adds shop name/cipher/type metadata and changes TikTok Shop uniqueness from one seller authorization to one row per authorized shop. Existing legacy authorization rows are reused for the first discovered shop, preserving prior sync history.

All migrations are reversible through Django. Use `backend/scripts/rollback_erp_operations.sh` only after restoring the pre-deployment database backup; rolling schema back without restoring a backup discards the newly introduced records. For only this release, use `backend/scripts/rollback_tiktok_multishop.sh` with `CONFIRM_TIKTOK_MULTISHOP_ROLLBACK=YES` after the backup restore.

## Required production environment

Keep these values only in `/opt/dongbo/app/.env` (never in Git, browser storage, logs, or frontend bundles):

```dotenv
INTEGRATION_ENCRYPTION_KEY=<Fernet key generated on the server>
TIKTOK_SHOP_APP_KEY=<Partner Center app key>
TIKTOK_SHOP_APP_SECRET=<Partner Center app secret>
TIKTOK_SHOP_SERVICE_ID=<Partner Center service id>
TIKTOK_SHOP_REDIRECT_URI=https://dongbokeji.com/api/integrations/tiktok-shop/callback/
```

Generate the encryption key once on the server with the production virtual environment:

```bash
/opt/dongbo/venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The TikTok redirect URL must also be registered in TikTok Shop Partner Center. The app must have the relevant Shop authorization scopes approved before a real store can complete OAuth.

For DeepSeek, this application uses the OpenAI-compatible Chat Completions route: set API address to `https://api.deepseek.com` and use a model name enabled for the account. Do not use DeepSeek's `/anthropic` address in this form.

## AI provider administration

The owner can configure providers in **店铺与 AI 接口**. The configuration screen supports create and edit, enabled/disabled state, timeout, retry count, and an optional JSON object of OpenAI-compatible request parameters such as `temperature` and `max_tokens`. Credentials remain write-only: a blank API Key leaves an existing encrypted key unchanged, and the API never returns the saved key. `model`, `messages`, `api_key`, and `authorization` are reserved and cannot be supplied through request parameters. The same page provides four proposal types (inventory forecast, replenishment, product analysis, and copywriting), the latest invocation logs, and confirm/reject actions. Confirming a proposal only writes the operator decision and audit event; it never changes stock automatically. Provider failures are recorded without raw response bodies or credentials.

The same screen shows aggregate successful-call count and token totals from the invocation log. A test call records its result in that log; credentials and response secrets are not displayed there.

## AlphaShop system configuration

After deployment, sign in as the main account and open **智能选品 → 配置选品接口** (or **账号菜单 → 店铺与 AI 接口**). Enter the AlphaShop Access Key, Secret Key, and HTTPS API address there. The browser submits these fields once over the authenticated session; the API encrypts them with `INTEGRATION_ENCRYPTION_KEY` and never returns them again. Internal accounts have neither the configuration button nor API permission.

The old `ALPHASHOP_ACCESS_KEY` and `ALPHASHOP_SECRET_KEY` environment variables remain an emergency compatibility fallback only when no system configuration record exists. A system-saved configuration always takes precedence.

## Deployment sequence

1. Put the site into a maintenance window and record the current Git commit.
2. Back up both code and PostgreSQL before pulling:

   ```bash
   ts=$(date +%Y%m%d-%H%M%S)
   mkdir -p /opt/dongbo/backups/$ts
   git -C /opt/dongbo/app rev-parse HEAD > /opt/dongbo/backups/$ts/code-commit.txt
   # Keep deployment secrets out of the portable code archive. /opt/dongbo/app/.env stays in place.
   tar --exclude=.git --exclude=.venv --exclude=.env -C /opt/dongbo -czf /opt/dongbo/backups/$ts/app.tar.gz app
   sudo -u postgres pg_dump -Fc dongbo_erp > /opt/dongbo/backups/$ts/dongbo_erp.dump
   ```

3. Review `git status --short`; do not overwrite unrelated server changes. Pull the reviewed release commit.
4. Add the required environment variables to `/opt/dongbo/app/.env`, then install locked runtime dependencies and migrate:

   ```bash
   cd /opt/dongbo/app
   /opt/dongbo/venv/bin/pip install -r backend/requirements.txt
   cd backend
   set -a; source ../.env; set +a
   /opt/dongbo/venv/bin/python manage.py migrate
   /opt/dongbo/venv/bin/python manage.py collectstatic --noinput
   systemctl restart dongbo-erp
   nginx -t && systemctl reload nginx
   ```

5. Verify after a short wait:

   ```bash
   systemctl is-active dongbo-erp
   curl -fsS http://127.0.0.1:8000/api/health/
   curl -I https://dongbokeji.com/
   ```

6. Complete the browser acceptance checklist below while logged in as the owner. Only then close the maintenance window.

## Acceptance checklist

- Create one complete product as `启用`; confirm it is active after the first save.
- Create a multi-line purchase order, select it on the receiving page, enter quantities for two lines, and confirm one receipt updates both lines.
- Submit manual inbound and outbound with blank notes; verify outbound cannot exceed available stock.
- Revoke a manual/adjustment ledger record and verify a separate reversal record appears; attempt a second revoke and confirm it is denied.
- Set a balance to zero with no reservation; confirm delete requires the browser confirmation and leaves product/history intact. Confirm non-zero balance deletion is denied.
- Upload a local JPG/PNG/WebP for a competitor and save; confirm the URL is `/api/media-assets/.../content/`, not `data:`.
- Confirm a replenishment recommendation exposes velocity, lead time, safety calculation, inbound position, and alert level.
- In **店铺与 AI 接口**, start TikTok seller authorization, complete Partner Center OAuth, and verify every authorized shop appears separately with its shop name. Refresh/disconnect one shop and confirm neither token nor shop cipher is returned in API responses.
- Add an AI provider with `temperature` and `max_tokens` JSON parameters, edit it with a blank API Key, test it, and inspect the usage summary plus the latest invocation rows. Confirm a malformed parameter object or a reserved key is rejected. Create one proposal, confirm it, create another and reject it; verify the stock ledger has no extra entry and both decisions appear in the audit log.

## API additions

- `POST /api/receipts/` accepts all selected receipt lines in one request.
- `DELETE /api/stock-balances/{id}/` permits only zero on-hand and zero reserved balances.
- `POST /api/stock-balances/manual-inbound/`, `POST /api/stock-balances/manual-outbound/`.
- `POST /api/stock-ledger/{id}/revoke/`.
- `GET/POST/PATCH /api/replenishment-settings/` (organization defaults, editable in **仓库中心 → 智能补货 → 全局补货参数**).
- TikTok: `/api/tiktok-shop-connections/`, `authorize/`, `{id}/refresh/`, `{id}/disconnect/`, `{id}/sync/`, callback `/api/integrations/tiktok-shop/callback/`.
- AI: `GET/POST /api/ai-providers/`, `PATCH /api/ai-providers/{id}/`, `{id}/test/`, `GET /api/ai-invocations/`, `GET/POST /api/ai-recommendations/`, `{id}/confirm/`, `{id}/reject/`.
- Media: `POST /api/media-assets/`, `GET /api/media-assets/{id}/content/`.
- AlphaShop: `GET/PUT /api/alphashop-config/` (main account only; credentials are write-only and encrypted at rest).

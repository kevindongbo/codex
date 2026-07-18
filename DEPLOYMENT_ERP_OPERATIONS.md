# ERP operations platform deployment

## Scope

This release adds batch purchase receiving, manual inbound/outbound and reversible stock ledger entries, safe zero-stock balance deletion, data-backed replenishment settings, TikTok Shop OAuth, encrypted OpenAI-compatible AI providers, and formal uploaded-media URLs for competitor images.

## Database migrations

- `0017_erp_operations_platform` creates replenishment settings, ledger reversals, TikTok OAuth state/connections/sync runs, encrypted AI provider configuration/log/recommendation tables; extends competitor URL fields and stock event types.
- `0018_uploadedmediaasset` creates `UploadedMediaAsset` for uploaded image files. It returns `/api/media-assets/<uuid>/content/`, so the database stores a formal URL rather than Base64.

Both migrations are reversible through Django. Use `backend/scripts/rollback_erp_operations.sh` only after restoring the pre-deployment database backup; rolling schema back without restoring a backup discards the newly introduced records.

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

For DeepSeek, this application uses the OpenAI-compatible Chat Completions route: set API address to `https://api.deepseek.com` and use `deepseek-v4-flash` or `deepseek-v4-pro`. Do not use DeepSeek's `/anthropic` address in this form.

## Deployment sequence

1. Put the site into a maintenance window and record the current Git commit.
2. Back up both code and PostgreSQL before pulling:

   ```bash
   ts=$(date +%Y%m%d-%H%M%S)
   mkdir -p /opt/dongbo/backups/$ts
   git -C /opt/dongbo/app rev-parse HEAD > /opt/dongbo/backups/$ts/code-commit.txt
   tar --exclude=.git --exclude=.venv -C /opt/dongbo -czf /opt/dongbo/backups/$ts/app.tar.gz app
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
- In **店铺与 AI 接口**, start TikTok authorization, complete Partner Center OAuth, refresh/disconnect it, and verify status. Confirm neither token is returned in API responses.
- Add an AI provider, test it, inspect its log, and create a recommendation. Confirm the recommendation remains pending until explicitly confirmed and does not alter stock.

## API additions

- `POST /api/receipts/` accepts all selected receipt lines in one request.
- `DELETE /api/stock-balances/{id}/` permits only zero on-hand and zero reserved balances.
- `POST /api/stock-balances/manual-inbound/`, `POST /api/stock-balances/manual-outbound/`.
- `POST /api/stock-ledger/{id}/revoke/`.
- `GET/PATCH /api/replenishment-settings/`.
- TikTok: `/api/tiktok-shop-connections/`, `authorize/`, `{id}/refresh/`, `{id}/disconnect/`, `{id}/sync/`, callback `/api/integrations/tiktok-shop/callback/`.
- AI: `/api/ai-providers/`, `{id}/test/`, `/api/ai-invocations/`, `/api/ai-recommendations/`, `{id}/confirm/`.
- Media: `POST /api/media-assets/`, `GET /api/media-assets/{id}/content/`.

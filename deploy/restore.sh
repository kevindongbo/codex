#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BACKUP_INPUT=${1:-}
CONFIRM=${2:-}

compose() {
  docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" "$@"
}

if [ -z "$BACKUP_INPUT" ] || [ ! -d "$BACKUP_INPUT" ]; then
  echo "用法：$0 /绝对路径/备份目录 --yes" >&2
  exit 1
fi

BACKUP_DIR=$(CDPATH= cd -- "$BACKUP_INPUT" && pwd)
for required in postgres.dump media.tar.gz SHA256SUMS; do
  if [ ! -e "$BACKUP_DIR/$required" ]; then
    echo "错误：备份缺少 $required" >&2
    exit 1
  fi
done

(
  cd "$BACKUP_DIR"
  sha256sum -c SHA256SUMS
)

if [ "$CONFIRM" != "--yes" ]; then
  echo "恢复会覆盖当前 PostgreSQL 和本地媒体数据。确认后请追加 --yes。" >&2
  exit 1
fi

compose config --quiet
compose stop caddy api >/dev/null 2>&1 || true
compose up -d --wait db

compose exec -T db sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges' < "$BACKUP_DIR/postgres.dump"

compose run --rm --no-deps \
  --user 0:0 \
  -v "$BACKUP_DIR:/restore:ro" \
  --entrypoint /bin/sh api -ec '
    find /app/media -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    tar -C /app/media -xzf /restore/media.tar.gz
    chown -R 10001:10001 /app/media
  '

compose up -d api caddy
echo "恢复完成。请运行 docker compose ps 并检查 /api/health/。"

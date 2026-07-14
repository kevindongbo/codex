#!/usr/bin/env sh
set -eu

umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
BACKUP_ROOT=${BACKUP_ROOT:-"$ROOT_DIR/../dongbo-erp-backups"}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

compose() {
  docker compose --project-directory "$ROOT_DIR" -f "$ROOT_DIR/docker-compose.yml" "$@"
}

command -v docker >/dev/null 2>&1 || {
  echo "错误：未找到 Docker。" >&2
  exit 1
}

mkdir -p "$BACKUP_DIR"
compose config --quiet
compose exec -T db sh -ec 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges' > "$BACKUP_DIR/postgres.dump"

compose run --rm --no-deps \
  --user 0:0 \
  -v "$BACKUP_DIR:/backup" \
  --entrypoint /bin/sh api -ec '
    tar -C /app/media -czf /backup/media.tar.gz .
  '

{
  echo "created_at=$STAMP"
  echo "compose_project=${COMPOSE_PROJECT_NAME:-dongbo-erp}"
  if command -v git >/dev/null 2>&1; then
    echo "git_commit=$(git -C "$ROOT_DIR" rev-parse --verify HEAD 2>/dev/null || echo unknown)"
  fi
} > "$BACKUP_DIR/manifest.txt"

(
  cd "$BACKUP_DIR"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)

echo "备份完成：$BACKUP_DIR"

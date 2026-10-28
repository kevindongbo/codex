#!/usr/bin/env bash
# Preserve and reconcile only the exact one-line emergency edit, before the
# normal backed-up release. Any other local edit stops the operation.
set -Eeuo pipefail
set +x
umask 077
app=/opt/dongbo/app
target=${1:-}
release=${2:-}
[[ "$target" =~ ^[0-9a-f]{40}$ && -f "$release" ]] || exit 1
[[ $EUID == 0 && -d "$app/.git" ]] || exit 1
exec 9>/run/lock/dongbo-erp-release.lock
flock -n 9 || exit 1
cd "$app"
if [[ -z "$(git status --porcelain --untracked-files=no)" ]]; then
  flock -u 9
  exec 9>&-
  exec bash "$release" "$target"
fi
[[ $(git rev-parse HEAD) == 0f814ef9962ad328c53e4d14d05a5117ea85e57c ]] || { echo 'STOP: preserve unknown local edits'; exit 1; }
git diff --cached --quiet || { echo 'STOP: staged edits exist'; exit 1; }
file=backend/apps/erp/serializers.py
[[ $(git diff --name-only) == "$file" ]] || { echo 'STOP: other local edits exist'; exit 1; }
expected=$(git rev-parse "86e63e1ef85668dae76551d7ad8d7d592871f2ed:$file")
[[ $(git hash-object "$file") == "$expected" ]] || { echo 'STOP: edit is not the reviewed emergency correction'; exit 1; }
backup=$(mktemp -d /opt/dongbo/backups/purchase-reconcile-XXXXXXXX)
cp -p "$file" "$backup/serializers.py"
git diff --binary -- "$file" > "$backup/emergency.patch"
git apply --reverse --check "$backup/emergency.patch"
restore_emergency_on_failure() {
  code=$?
  trap - EXIT
  if [[ $code != 0 && $(git rev-parse HEAD) == 0f814ef9962ad328c53e4d14d05a5117ea85e57c ]]; then
    if git apply --check "$backup/emergency.patch"; then
      git apply "$backup/emergency.patch"
      if systemctl is-active --quiet dongbo-erp.service; then systemctl restart dongbo-erp.service; fi
      echo 'Preserved the prior emergency correction after release failure.' >&2
    else echo "STOP: emergency code backup retained at $backup; inspect before restarting." >&2; fi
  fi
  exit "$code"
}
trap restore_emergency_on_failure EXIT
git apply --reverse "$backup/emergency.patch"
[[ -z "$(git status --porcelain --untracked-files=no)" ]]
echo "Exact emergency edit backed up and reconciled: $backup"
flock -u 9
exec 9>&-
bash "$release" "$target"

# Command doubles for an isolated release-script test. Never invoke on a server.
event() { printf '%s\n' "$*" >> "$HARNESS_STATE/events"; }
current_sha() { cat "$HARNESS_STATE/sha"; }
git() {
  event "git $*"
  [[ "${1:-}" != -C ]] || shift 2
  case "${1:-}" in
    status|diff|fetch|merge-base) return 0 ;;
    remote) printf '%s\n' https://github.com/kevindongbo/codex.git ;;
    rev-parse) if [[ "${2:-}" == FETCH_HEAD ]]; then printf '%s\n' "$HARNESS_TARGET"; else current_sha; fi ;;
    ls-files) if [[ "${2:-}" == -z ]]; then printf '%s\0' backend/manage.py app.js scheduling.js; fi ;;
    archive) printf 'fixture archived code:%s\n' "${2:-}" ;;
    switch)
      next=${3:?expected switch target}
      if [[ "$next" == "$HARNESS_TARGET" && "$HARNESS_SCENARIO" == switch ]]; then return 53; fi
      printf '%s' "$next" > "$HARNESS_STATE/sha"
      for asset in index.html app.js team.js styles.css profit-calculator.js scheduling.js scheduling.css; do
        printf 'fixture release:%s asset:%s\n' "$next" "$asset" > "$HARNESS_APP/$asset"
      done
      ;;
    *) printf 'Unsupported Git double: %s\n' "$*" >&2; return 92 ;;
  esac
}
systemctl() {
  event "systemctl $*"
  action=${1:?}; shift
  case "$action" in
    show)
      case "$*" in
        *WorkingDirectory*) printf '%s/backend\n' "$HARNESS_APP" ;;
        *EnvironmentFiles*)
          if [[ "$1" == dongbo-timetable-worker.service && "$HARNESS_SCENARIO" == env-app ]]; then
            printf '%s/scheduling.env (ignore_errors=no)\n' "$HARNESS_ROOT"
          elif [[ "$1" == dongbo-timetable-worker.service && "$HARNESS_SCENARIO" == env-scheduling ]]; then
            printf '%s/.env (ignore_errors=no)\n' "$HARNESS_APP"
          else
            printf '%s/.env (ignore_errors=no) %s/scheduling.env (ignore_errors=no)\n' "$HARNESS_APP" "$HARNESS_ROOT"
          fi ;;
        *User*|*Group*) printf '%s\n' fixtureuser ;;
        *) return 93 ;;
      esac ;;
    is-active) [[ "${1:-}" != --quiet ]] || shift; [[ "$(cat "$HARNESS_STATE/$1")" == active ]] ;;
    stop) for unit in "$@"; do printf inactive > "$HARNESS_STATE/$unit"; done ;;
    restart|start)
      if [[ "$(current_sha)" == "$HARNESS_TARGET" && "$HARNESS_SCENARIO" == restart ]]; then return 57; fi
      for unit in "$@"; do printf active > "$HARNESS_STATE/$unit"; done ;;
    *) return 94 ;;
  esac
}
runuser() {
  event "runuser $*"
  [[ "$1" == -u && "$3" == -- ]] || return 95
  shift 3
  case "$1" in
    test) shift; builtin test "$@" ;;
    # Preserve an external runuser process's failure boundary: ERR belongs to
    # the release caller, not this function's redirected stdout.
    pg_dump) shift; if pg_dump "$@"; then return 0; else return $?; fi ;;
    *) return 96 ;;
  esac
}
pg_dump() { event "pg_dump $*"; [[ "$HARNESS_SCENARIO" != backup ]] || return 47; printf 'fixture database backup\n'; }
pg_restore() { event "pg_restore $*"; [[ "$1" == --list && -s "$2" ]] || return 97; }
nginx() { event "nginx $*"; [[ "$*" == -t ]]; }
flock() { event "flock $*"; return 0; }
install() {
  event "install $*"
  [[ "$1" == -d && "$2" == -m && "$3" == 700 && "$4" == "$HARNESS_ROOT/backups" ]] || return 91
  [[ -d "$4" ]]
}
sleep() { event "sleep $*"; }
sha256sum() {
  "$HARNESS_NODE" -e 'const fs=require("node:fs"),crypto=require("node:crypto"); const path=process.argv[1]; console.log(crypto.createHash("sha256").update(fs.readFileSync(path || 0)).digest("hex")+"  "+(path || "-"));' "${1:-}"
}
node() {
  event "node $*"
  [[ "$*" == scripts/build-site.mjs ]] || return 98
  if [[ "$(current_sha)" == "$HARNESS_TARGET" && "$HARNESS_SCENARIO" == build ]]; then return 61; fi
  printf 'fixture built:%s\n' "$(current_sha)" > "$HARNESS_APP/dist/server/index.js"
}
curl() {
  event "curl $*"
  for url in "$@"; do :; done
  case "$url" in
    http://127.0.0.1:8000/api/health/)
      if [[ "$(current_sha)" == "$HARNESS_TARGET" && "$HARNESS_SCENARIO" == health ]]; then return 22; fi
      [[ "$(cat "$HARNESS_STATE/dongbo-erp.service")" == active ]] || return 22
      printf '%s\n' '{"status":"ok","database":"ok"}' ;;
    https://dongbokeji.com/*)
      if [[ "$(current_sha)" == "$HARNESS_TARGET" && "$HARNESS_SCENARIO" == assets ]]; then printf 'stale frontend bytes'; return 0; fi
      asset=${url#https://dongbokeji.com/}; asset=${asset%%\?*}; asset=${asset:-index.html}
      case "$asset" in index.html|app.js|team.js|styles.css|profit-calculator.js|scheduling.js|scheduling.css) cat "$HARNESS_APP/$asset" ;; *) return 99 ;; esac ;;
    *) printf 'Network denied by fixture\n' >&2; return 99 ;;
  esac
}

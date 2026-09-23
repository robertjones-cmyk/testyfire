#!/usr/bin/env bash
# One-command setup and run for the Torch Camera Fusion prototype.
#
#   ./scripts/run.sh            # set up if needed, then run everything
#   ./scripts/run.sh setup      # set up only
#
# Starts: the dispatch test receiver (8001), the API + ingest worker (8000).
# The API also serves the built frontend, so http://127.0.0.1:8000 is the app.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VENV="$ROOT/.venv"
PYTHON="${PYTHON:-python3}"

log() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

setup() {
  log "Python environment"
  [ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements-dev.txt

  log "Configuration"
  if [ ! -f .env ]; then
    cp .env.example .env
    # A signing secret is required before anything can be dispatched.
    SECRET="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
    "$VENV/bin/python" - "$SECRET" <<'PY'
import pathlib, sys
env = pathlib.Path('.env')
env.write_text(env.read_text().replace('DISPATCH_HMAC_SECRET=REPLACE_ME_WITH_32_RANDOM_BYTES_HEX',
                                       f'DISPATCH_HMAC_SECRET={sys.argv[1]}'))
PY
    echo "  wrote .env with a generated DISPATCH_HMAC_SECRET"
    echo "  NOTE: set MAPBOX_TOKEN in .env (a public pk. token) for the map to render."
  else
    echo "  .env already exists, leaving it alone"
  fi

  log "Replay fixtures (so the demo runs with no network)"
  "$VENV/bin/python" scripts/make_fixtures.py

  log "Frontend"
  if command -v npm >/dev/null 2>&1; then
    (cd web && npm install --no-audit --no-fund --silent && npm run build)
  else
    echo "  npm not found — skipping the frontend build."
    echo "  The API still runs; install Node 20+ and re-run to get the UI."
  fi

  log "Database and admin account"
  if ! "$VENV/bin/python" - <<'PY'
import sys
sys.path.insert(0, '.')
from app import db
from app.config import get_config
config = get_config()
db.configure(config.db_path)
db.init_db()
row = db.query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
sys.exit(0 if row and row["n"] else 1)
PY
  then
    echo "  No admin account yet — creating one now."
    "$VENV/bin/python" -m app create-admin
  else
    echo "  An admin account already exists."
  fi
}

run() {
  # shellcheck disable=SC1091
  set -a; [ -f .env ] && . ./.env; set +a

  log "Starting the dispatch test receiver on 127.0.0.1:8001"
  "$VENV/bin/python" scripts/test_receiver.py &
  RECEIVER_PID=$!
  trap 'kill $RECEIVER_PID 2>/dev/null || true' EXIT

  log "Starting the API and ingest worker"
  echo "  App:  http://127.0.0.1:8000"
  echo "  Stop: Ctrl-C"
  "$VENV/bin/python" -m app run
}

case "${1:-all}" in
  setup) setup ;;
  run) run ;;
  *) setup; run ;;
esac

#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <name> --vault <dir> --db <file> --port <n>" >&2
  exit 2
fi

name=$1
shift
vault=""
db=""
port=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault)
      vault=${2-}
      shift 2
      ;;
    --db)
      db=${2-}
      shift 2
      ;;
    --port)
      port=${2-}
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$vault" || -z "$db" || -z "$port" ]]; then
  echo "usage: $0 <name> --vault <dir> --db <file> --port <n>" >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

export INSTANCE="$name"
export SOURCE_VAULT="$vault"
export SOURCE_DB="$db"

exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/serve_http.py" \
  --vault "$vault" \
  --db "$db" \
  --port "$port"

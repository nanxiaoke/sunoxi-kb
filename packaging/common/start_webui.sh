#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$ROOT/../../requirements.txt" ]; then
  PROJECT_ROOT=$(CDPATH= cd -- "$ROOT/../.." && pwd)
else
  echo "Cannot locate Karpathy KB project root from $ROOT" >&2
  exit 1
fi

VENV="$PROJECT_ROOT/.venv"
ENV_FILE="$PROJECT_ROOT/config/llm.env"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5080}"

if [ -x "$VENV/Scripts/python.exe" ]; then
  VENV_PY="$VENV/Scripts/python.exe"
elif [ -x "$VENV/bin/python" ]; then
  VENV_PY="$VENV/bin/python"
else
  echo "Virtualenv not found. Run ./packaging/common/install_deps.sh first." >&2
  exit 1
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

URL="http://$HOST:$PORT"
echo "Starting Karpathy KB WebUI at $URL"

if command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Start-Process '$URL'" >/dev/null 2>&1 || true
elif command -v cmd.exe >/dev/null 2>&1; then
  cmd.exe /c start "$URL" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || true
fi

cd "$PROJECT_ROOT"
exec "$VENV_PY" "scripts/web_ui.py" "--host" "$HOST" "--port" "$PORT"

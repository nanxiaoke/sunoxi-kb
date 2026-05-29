#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$ROOT/../../requirements.txt" ]; then
  PROJECT_ROOT=$(CDPATH= cd -- "$ROOT/../.." && pwd)
else
  echo "Cannot locate project root from $ROOT" >&2
  exit 1
fi

VENV="$PROJECT_ROOT/.venv"
REQ="$PROJECT_ROOT/requirements.txt"
PYTHON_BIN=${PYTHON_BIN:-python}

if [ ! -f "$REQ" ]; then
  echo "requirements.txt not found: $REQ" >&2
  exit 1
fi

if [ "${1:-}" = "--force" ] && [ -d "$VENV" ]; then
  rm -rf "$VENV"
fi

if [ ! -d "$VENV" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

mkdir -p \
  "$PROJECT_ROOT/raw/articles" \
  "$PROJECT_ROOT/raw/papers" \
  "$PROJECT_ROOT/raw/notes" \
  "$PROJECT_ROOT/raw/codes" \
  "$PROJECT_ROOT/raw/webpages" \
  "$PROJECT_ROOT/raw/wechat_articles" \
  "$PROJECT_ROOT/raw/rss_candidates" \
  "$PROJECT_ROOT/raw/wechat_candidates" \
  "$PROJECT_ROOT/raw/candidate_translations" \
  "$PROJECT_ROOT/wiki/articles" \
  "$PROJECT_ROOT/wiki/concepts" \
  "$PROJECT_ROOT/wiki/people" \
  "$PROJECT_ROOT/wiki/projects" \
  "$PROJECT_ROOT/wiki/technologies" \
  "$PROJECT_ROOT/wiki/notes" \
  "$PROJECT_ROOT/outputs" \
  "$PROJECT_ROOT/reports" \
  "$PROJECT_ROOT/logs" \
  "$PROJECT_ROOT/backups" \
  "$PROJECT_ROOT/config"

if [ -x "$VENV/Scripts/python.exe" ]; then
  VENV_PY="$VENV/Scripts/python.exe"
else
  VENV_PY="$VENV/bin/python"
fi

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r "$REQ"

echo "Dependencies installed in $VENV"

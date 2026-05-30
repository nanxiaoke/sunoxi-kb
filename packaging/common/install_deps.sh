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
EMBEDDINGS_REQ="$PROJECT_ROOT/requirements-embeddings.txt"
PYTHON_BIN=${PYTHON_BIN:-python}
INSTALL_EMBEDDINGS=0
FORCE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --with-embeddings)
      INSTALL_EMBEDDINGS=1
      shift
      ;;
    *)
      echo "Usage: ./packaging/common/install_deps.sh [--force] [--with-embeddings]" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "$REQ" ]; then
  echo "requirements.txt not found: $REQ" >&2
  exit 1
fi

if [ "$FORCE" = "1" ] && [ -d "$VENV" ]; then
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

if [ "$INSTALL_EMBEDDINGS" = "1" ]; then
  if [ ! -f "$EMBEDDINGS_REQ" ]; then
    echo "Optional embeddings requirements not found: $EMBEDDINGS_REQ" >&2
    exit 1
  fi
  "$VENV_PY" -m pip install -r "$EMBEDDINGS_REQ"
fi

echo "Dependencies installed in $VENV"

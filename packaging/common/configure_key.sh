#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$ROOT/../../requirements.txt" ]; then
  PROJECT_ROOT=$(CDPATH= cd -- "$ROOT/../.." && pwd)
else
  echo "Cannot locate project root from $ROOT" >&2
  exit 1
fi

ENV_FILE="$PROJECT_ROOT/config/llm.env"
KEY="${DEEPSEEK_API_KEY:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -k|--key)
      KEY="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: ./packaging/common/configure_key.sh --key YOUR_DEEPSEEK_API_KEY" >&2
      exit 1
      ;;
  esac
done

if [ -z "$KEY" ]; then
  printf "Enter DEEPSEEK_API_KEY: "
  stty -echo 2>/dev/null || true
  read -r KEY
  stty echo 2>/dev/null || true
  printf "\n"
fi

if [ -z "$KEY" ]; then
  echo "DEEPSEEK_API_KEY is empty" >&2
  exit 1
fi

mkdir -p "$(dirname "$ENV_FILE")"
printf "DEEPSEEK_API_KEY=%s\n" "$KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE" 2>/dev/null || true
echo "Wrote key file: $ENV_FILE"

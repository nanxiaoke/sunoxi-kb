#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="${KB_LLM_ENV_DIR:-$HOME/.config/karpathy-kb}"
ENV_FILE="${KB_LLM_ENV_FILE:-$ENV_DIR/llm.env}"
DROPIN_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/karpathy-kb.service.d"
DROPIN_FILE="$DROPIN_DIR/10-llm-env.conf"
SERVICE_NAME="${KB_SERVICE_NAME:-karpathy-kb.service}"

usage() {
  printf 'Usage: DEEPSEEK_API_KEY=sk-... %s\n' "$0"
  printf '       %s --env-only\n' "$0"
}

ENV_ONLY=0
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
elif [[ "${1:-}" == "--env-only" ]]; then
  ENV_ONLY=1
elif [[ -n "${1:-}" ]]; then
  usage >&2
  exit 2
fi

mkdir -p "$ENV_DIR"
chmod 700 "$ENV_DIR"

if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  umask 077
  {
    printf '# Karpathy KB online LLM secrets. Do not commit this file.\n'
    printf 'DEEPSEEK_API_KEY=%q\n' "$DEEPSEEK_API_KEY"
  } > "$ENV_FILE"
elif [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  {
    printf '# Karpathy KB online LLM secrets. Do not commit this file.\n'
    printf '# Fill this value, then run: systemctl --user restart %s\n' "$SERVICE_NAME"
    printf 'DEEPSEEK_API_KEY=\n'
  } > "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

if [[ "$ENV_ONLY" -eq 0 ]]; then
  mkdir -p "$DROPIN_DIR"
  cat > "$DROPIN_FILE" <<EOF
[Service]
EnvironmentFile=$ENV_FILE
EOF
  systemctl --user daemon-reload
  systemctl --user restart "$SERVICE_NAME"
fi

printf 'LLM env file: %s\n' "$ENV_FILE"
printf 'Permissions: %s\n' "$(stat -c '%a' "$ENV_FILE")"
if [[ "$ENV_ONLY" -eq 0 ]]; then
  printf 'systemd drop-in: %s\n' "$DROPIN_FILE"
  systemctl --user is-active "$SERVICE_NAME"
fi

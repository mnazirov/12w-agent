#!/usr/bin/env bash
set -Eeuo pipefail

BRANCH="${1:-main}"
APP_DIR="${APP_DIR:-/opt/12w-agent}"

trim_env_value() {
  local value="$1"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  echo "${value}"
}

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is not installed." >&2
  exit 1
fi

echo "Deploying branch '${BRANCH}' in '${APP_DIR}'"
cd "${APP_DIR}"

COMPOSE_PROFILE_ARGS=()
if [ -f .env ]; then
  NGROK_AUTHTOKEN_VALUE="$(grep -E '^NGROK_AUTHTOKEN=' .env | tail -n1 | cut -d= -f2- || true)"
  NGROK_DOMAIN_VALUE="$(grep -E '^NGROK_DOMAIN=' .env | tail -n1 | cut -d= -f2- || true)"

  NGROK_AUTHTOKEN_VALUE="$(trim_env_value "${NGROK_AUTHTOKEN_VALUE}")"
  NGROK_DOMAIN_VALUE="$(trim_env_value "${NGROK_DOMAIN_VALUE}")"

  if [ -n "${NGROK_AUTHTOKEN_VALUE}" ] && [ -n "${NGROK_DOMAIN_VALUE}" ]; then
    # Normalize common misconfigurations in .env.
    NGROK_DOMAIN_VALUE="${NGROK_DOMAIN_VALUE#http://}"
    NGROK_DOMAIN_VALUE="${NGROK_DOMAIN_VALUE#https://}"
    NGROK_DOMAIN_VALUE="${NGROK_DOMAIN_VALUE%/}"

    if [[ "${NGROK_DOMAIN_VALUE}" == */* ]]; then
      echo "Invalid NGROK_DOMAIN='${NGROK_DOMAIN_VALUE}'. Use host only, e.g. hydrostatic-shirleen-advertently.ngrok-free.dev" >&2
      exit 1
    fi

    # Override environment for compose command with normalized values.
    export NGROK_AUTHTOKEN="${NGROK_AUTHTOKEN_VALUE}"
    export NGROK_DOMAIN="${NGROK_DOMAIN_VALUE}"

    COMPOSE_PROFILE_ARGS=(--profile ngrok)
    echo "Ngrok profile enabled for deploy (NGROK_AUTHTOKEN + NGROK_DOMAIN found: ${NGROK_DOMAIN_VALUE})."
  fi
fi

git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

if ! "${COMPOSE_CMD[@]}" "${COMPOSE_PROFILE_ARGS[@]}" up -d --build; then
  echo "Deploy failed. Docker Compose status:" >&2
  "${COMPOSE_CMD[@]}" ps || true
  echo "----- mcp-server logs (last 200 lines) -----" >&2
  "${COMPOSE_CMD[@]}" logs --tail=200 mcp-server || true
  echo "----- bot logs (last 200 lines) -----" >&2
  "${COMPOSE_CMD[@]}" logs --tail=200 bot || true
  if [ "${#COMPOSE_PROFILE_ARGS[@]}" -gt 0 ]; then
    echo "----- ngrok logs (last 200 lines) -----" >&2
    "${COMPOSE_CMD[@]}" logs --tail=200 ngrok || true
  fi
  exit 1
fi

if [ "${#COMPOSE_PROFILE_ARGS[@]}" -gt 0 ] && command -v curl >/dev/null 2>&1; then
  OAUTH_HEALTH_URL="https://${NGROK_DOMAIN}/oauth/google/health"
  echo "Checking ngrok OAuth health: ${OAUTH_HEALTH_URL}"
  for _ in 1 2 3 4 5; do
    if curl -fsS --max-time 10 "${OAUTH_HEALTH_URL}" >/dev/null; then
      echo "Ngrok OAuth health check passed."
      break
    fi
    sleep 2
  done
fi

echo "Deploy completed."

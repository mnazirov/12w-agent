#!/usr/bin/env bash
set -Eeuo pipefail

BRANCH="${1:-main}"
APP_DIR="${APP_DIR:-/opt/12w-agent}"

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

git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

if ! "${COMPOSE_CMD[@]}" up -d --build; then
  echo "Deploy failed. Docker Compose status:" >&2
  "${COMPOSE_CMD[@]}" ps || true
  echo "----- mcp-server logs (last 200 lines) -----" >&2
  "${COMPOSE_CMD[@]}" logs --tail=200 mcp-server || true
  echo "----- bot logs (last 200 lines) -----" >&2
  "${COMPOSE_CMD[@]}" logs --tail=200 bot || true
  exit 1
fi

echo "Deploy completed."

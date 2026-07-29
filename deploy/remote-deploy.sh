#!/usr/bin/env bash
set -Eeuo pipefail

release_sha="${1:?release SHA is required}"
image="${2:?image is required}"
compose_source="${3:?compose source is required}"
deploy_root="${SRT_DEPLOY_ROOT:-/opt/chenjianru}"
runtime_env="$deploy_root/runtime.env"
compose_target="$deploy_root/app/deploy/compose.yaml"
container_name="chenjianru-app"
hot_api_container_name="chenjianru-hot-api"
health_attempts="${SRT_DEPLOY_HEALTH_ATTEMPTS:-30}"
health_interval_seconds="${SRT_DEPLOY_HEALTH_INTERVAL_SECONDS:-2}"
hot_api_health_attempts="${SRT_DEPLOY_HOT_API_HEALTH_ATTEMPTS:-15}"

if [[ ! "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid release SHA" >&2
  exit 2
fi
if [[ "$image" != "ghcr.io/lxdll/srt-sub-master:sha-$release_sha" ]]; then
  echo "Unexpected deployment image" >&2
  exit 2
fi
if [[ ! -f "$runtime_env" || ! -f "$compose_source" ]]; then
  echo "Deployment inputs are incomplete" >&2
  exit 2
fi

exec 9>"/var/lock/chenjianru-deploy.lock"
flock -x 9

backup_dir="$deploy_root/backups/deploy-$release_sha"
install -d -m 700 "$backup_dir"
cp "$runtime_env" "$backup_dir/runtime.env"
cp "$compose_target" "$backup_dir/compose.yaml"

restore_previous_release() {
  echo "Deployment failed; restoring previous release" >&2
  cp "$backup_dir/runtime.env" "$runtime_env"
  cp "$backup_dir/compose.yaml" "$compose_target"
  docker compose \
    --env-file "$runtime_env" \
    -f "$compose_target" \
    up -d --no-deps --no-build app
}

upsert_env() {
  local key="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "$deploy_root/runtime.env.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 {
      print key "=" value
      found = 1
      next
    }
    { print }
    END {
      if (!found) {
        print key "=" value
      }
    }
  ' "$runtime_env" > "$temporary"
  chmod 600 "$temporary"
  chown root:root "$temporary"
  mv "$temporary" "$runtime_env"
}

install -m 644 "$compose_source" "$compose_target"
upsert_env "SRT_APP_IMAGE" "$image"

if ! docker compose \
  --env-file "$runtime_env" \
  -f "$compose_target" \
  pull hot-api; then
  echo "Warning: could not pull the hot-rank service; trying the cached image" >&2
fi

hot_api_started=false
if docker compose \
  --env-file "$runtime_env" \
  -f "$compose_target" \
  up -d --no-deps --no-build hot-api; then
  for _ in $(seq 1 "$hot_api_health_attempts"); do
    hot_api_health="$(
      docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$hot_api_container_name" 2>/dev/null || true
    )"
    if [[ "$hot_api_health" == "healthy" ]]; then
      hot_api_started=true
      break
    fi
    sleep "$health_interval_seconds"
  done
fi

if [[ "$hot_api_started" != "true" ]]; then
  echo "Warning: hot-rank service is unavailable; deployment will continue with the fallback provider and saved snapshots" >&2
  docker logs --tail 50 "$hot_api_container_name" >&2 || true
fi

if ! docker compose \
  --env-file "$runtime_env" \
  -f "$compose_target" \
  pull app; then
  cp "$backup_dir/runtime.env" "$runtime_env"
  cp "$backup_dir/compose.yaml" "$compose_target"
  exit 1
fi

if ! docker compose \
  --env-file "$runtime_env" \
  -f "$compose_target" \
  up -d --no-deps --no-build app; then
  restore_previous_release
  exit 1
fi

healthy=false
for _ in $(seq 1 "$health_attempts"); do
  container_health="$(
    docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$container_name" 2>/dev/null || true
  )"
  if [[ "$container_health" == "healthy" ]]; then
    healthy=true
    break
  fi
  sleep "$health_interval_seconds"
done

if [[ "$healthy" != "true" ]]; then
  docker logs --tail 100 "$container_name" >&2 || true
  restore_previous_release
  exit 1
fi

hot_rank_check="$(
  docker exec "$container_name" python -c '
import asyncio
import json
import sys

from server.app.hot_ranks import hot_rank_service

result = asyncio.run(hot_rank_service.get_hot_ranks(refresh=True))
summary = [
    {
        "platform": platform["platform"],
        "status": platform["status"],
        "source": platform["source"],
        "items": len(platform["items"]),
    }
    for platform in result["platforms"]
]
print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
sys.exit(0 if len(summary) == 3 and all(item["items"] == 10 for item in summary) else 1)
' 2>&1
)" && hot_rank_check_passed=true || hot_rank_check_passed=false

if [[ "$hot_rank_check_passed" == "true" ]]; then
  echo "Hot-rank providers returned ten items for all platforms: $hot_rank_check"
else
  echo "Warning: post-deployment hot-rank verification is incomplete: $hot_rank_check" >&2
fi

printf '%s\n' "$release_sha" > "$deploy_root/current-release"
chmod 600 "$deploy_root/current-release"
echo "Production deployment is healthy: $release_sha"

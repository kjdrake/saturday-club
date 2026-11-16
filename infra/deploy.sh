#!/usr/bin/env bash
set -euo pipefail
umask 077
source /opt/saturday-club/config.env
export AWS_REGION
export AWS_DEFAULT_REGION="$AWS_REGION"
export DOMAIN
sha=${1:?Pass the Git commit SHA to deploy}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid image tag' >&2; exit 1; }
exec 8>/run/saturday-club-deploy.lock
flock -w 900 8
# Initial user-data installation must finish before an SSM deployment proceeds.
test -f /opt/saturday-club/ready
release="/opt/saturday-club/releases/$sha"
image="$ECR_REPOSITORY:$sha"
previous=$(cat /opt/saturday-club/current-sha 2>/dev/null || true)
registry=${ECR_REPOSITORY%%/*}
aws ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
docker pull "$image"
mkdir -p "$release"
# Release-specific compose/Caddy configuration travels inside the tested app image.
container=$(docker create "$image")
docker cp "$container:/app/ops/compose.prod.yaml" "$release/compose.prod.yaml"
docker cp "$container:/app/ops/Caddyfile" "$release/Caddyfile"
docker rm "$container" >/dev/null
aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text | python3 -c '
import json, pathlib, re, sys
secret=json.load(sys.stdin)
lines=[]
for key in ("ADMIN_EMAIL", "ADMIN_NAME", "ADMIN_PASSWORD", "ODDS_API_KEY", "APP_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FACEBOOK_CLIENT_ID", "FACEBOOK_CLIENT_SECRET", "SES_FROM_EMAIL"):
    value=secret.get(key, "")
    if not isinstance(value,str) or "\n" in value or "\r" in value:
        raise ValueError("Invalid runtime secret value")
    # Single-quoted dotenv values do not expand dollar signs.
    value=value.replace("\\", "\\\\").replace("\x27", "\\\x27")
    lines.append(key+"=\x27"+value+"\x27")
p=pathlib.Path("/opt/saturday-club/runtime.env")
p.write_text("\n".join(lines)+"\n");p.chmod(0o600)
'
compose() {
  local tag=$1; shift
  APP_IMAGE="$ECR_REPOSITORY:$tag" docker compose --project-name saturday-club --env-file /opt/saturday-club/runtime.env --file "/opt/saturday-club/releases/$tag/compose.prod.yaml" "$@"
}
if [[ -n "$previous" ]]; then
  /opt/saturday-club/backup.sh
fi
healthy() {
  compose "$sha" up -d --wait --wait-timeout 150 &&
  curl --fail --silent --show-error --retry 5 --retry-delay 3 --retry-all-errors --max-time 10 http://127.0.0.1:8000/api/health >/dev/null &&
  curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health" >/dev/null
}
if healthy; then
  printf '%s\n' "$sha" > /opt/saturday-club/current-sha
  echo "Deployment healthy: $sha"
else
  echo "Deployment failed: $sha" >&2
  if [[ -n "$previous" ]]; then
    compose "$previous" up -d --wait --wait-timeout 150
    echo "Rolled back app and score worker to $previous. Database preserved." >&2
  else
    compose "$sha" down
    echo 'Initial deployment failed; containers stopped. Persistent data preserved.' >&2
  fi
  exit 1
fi
# Only remove dangling images; keep versioned releases available for rollback.
docker image prune -f >/dev/null

#!/usr/bin/env bash
set -euo pipefail
source /opt/saturday-club/config.env
export AWS_DEFAULT_REGION="$AWS_REGION"
exec 9>/run/saturday-club-backup.lock
flock -w 60 9
if ! docker inspect -f '{{.State.Running}}' saturday-club-app 2>/dev/null | grep -qx true; then
  echo 'No running app to back up.' >&2
  exit 1
fi
filename=$(docker exec saturday-club-app python /app/ops/backup.py)
[[ "$filename" =~ ^club-[0-9TZ]+\.db$ ]] || { echo 'Unexpected backup filename' >&2; exit 1; }
aws s3 cp "/srv/saturday-club/league/backups/$filename" "s3://$BACKUP_BUCKET/database/$filename" --sse AES256 --only-show-errors
rm -f "/srv/saturday-club/league/backups/$filename"
echo 'Database backup stored in encrypted S3.'

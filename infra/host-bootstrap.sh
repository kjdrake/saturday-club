
#!/usr/bin/env bash
set -euo pipefail
umask 077

# Called by CloudFormation user data with non-secret configuration in the environment.
: "${AWS_REGION:?}" "${SOURCE_COMMIT:?}" "${SOURCE_REPOSITORY:?}" "${DATA_VOLUME_ID:?}"

dnf install -y docker git python3 util-linux curl-minimal awscli-2
systemctl enable --now docker amazon-ssm-agent

# AL2023 packages Docker Engine. Install a fixed Compose plugin release.
mkdir -p /usr/local/lib/docker/cli-plugins

curl -fsSL --retry 5 \
  https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose

curl -fsSL --retry 5 \
  https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64.sha256 \
  -o /tmp/compose.sha256

# Verify the downloaded binary against the published SHA-256 checksum.
expected_hash=$(awk 'NR==1 {print $1}' /tmp/compose.sha256)
echo "$expected_hash  /usr/local/lib/docker/cli-plugins/docker-compose" | sha256sum --check -

chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose

# Wait for the separate encrypted data volume attachment; never format the root device.
serial=${DATA_VOLUME_ID//-/}
device=''

for _ in $(seq 1 120); do
  device=$(lsblk -ndo NAME,SERIAL | awk -v serial="$serial" '$2==serial {print "/dev/"$1;exit}')
  [[ -n "$device" ]] && break
  sleep 2
done

[[ -b "$device" ]] || { echo 'Data volume did not attach' >&2; exit 1; }

if ! blkid "$device" >/dev/null 2>&1; then
  mkfs.ext4 "$device"
fi

[[ $(blkid -s TYPE -o value "$device") == ext4 ]] || {
  echo 'Unexpected data filesystem' >&2
  exit 1
}

mkdir -p /srv/saturday-club
uuid=$(blkid -s UUID -o value "$device")

grep -q "UUID=$uuid " /etc/fstab || \
  printf 'UUID=%s /srv/saturday-club ext4 defaults,nofail 0 2\n' "$uuid" >> /etc/fstab

mount /srv/saturday-club

mkdir -p \
  /srv/saturday-club/league \
  /srv/saturday-club/caddy-data \
  /srv/saturday-club/caddy-config

chown 10001:10001 /srv/saturday-club/league

mkdir -p /opt/saturday-club/releases

python3 - <<'PY'
import os
import shlex
from pathlib import Path

keys = [
    'AWS_REGION',
    'ECR_REPOSITORY',
    'SECRET_ARN',
    'DOMAIN',
    'BACKUP_BUCKET',
    'SOURCE_REPOSITORY'
]

p = Path('/opt/saturday-club/config.env')
p.write_text(
    ''.join(
        k + '=' + shlex.quote(os.environ[k]) + '\n'
        for k in keys
    )
)
p.chmod(0o600)
PY

for script in deploy backup; do
  curl -fsSL --retry 5 \
    "https://raw.githubusercontent.com/$SOURCE_REPOSITORY/$SOURCE_COMMIT/infra/$script.sh" \
    -o "/opt/saturday-club/$script.sh"

  chmod 700 "/opt/saturday-club/$script.sh"
done

cat > /etc/systemd/system/saturday-club-backup.service <<'UNIT'
[Unit]
Description=Back up Saturday Club SQLite to encrypted S3
After=docker.service network-online.target

[Service]
Type=oneshot
ExecStart=/opt/saturday-club/backup.sh
UNIT

cat > /etc/systemd/system/saturday-club-backup.timer <<'UNIT'
[Unit]
Description=Daily Saturday Club database backup

[Timer]
OnCalendar=*-*-* 07:00:00 UTC
RandomizedDelaySec=900
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now saturday-club-backup.timer

touch /opt/saturday-club/ready

echo 'Saturday Club host is ready for its first GitHub deployment.'

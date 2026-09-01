#!/usr/bin/env bash
set -euo pipefail
# Supply these two values before using this as cloud-init user data.
AIBA_RELEASE_URL="{{AIBA_RELEASE_URL}}"
AIBA_RELEASE_SHA256="{{AIBA_RELEASE_SHA256}}"
if [[ "$AIBA_RELEASE_URL" == *'{{'* || "$AIBA_RELEASE_SHA256" == *'{{'* ]]; then echo 'Configure the AIBA release URL and SHA-256 first.';exit 1;fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip curl unzip
install -d -m 0750 /opt/aiba-agent
curl --fail --location --proto '=https' --tlsv1.2 "$AIBA_RELEASE_URL" -o /tmp/aiba.zip
echo "$AIBA_RELEASE_SHA256  /tmp/aiba.zip" | sha256sum --check --strict
unzip -q /tmp/aiba.zip -d /tmp/aiba-release
source_dir=$(find /tmp/aiba-release -maxdepth 2 -type f -name VERSION -printf '%h\n' | head -1)
test -n "$source_dir"
cp -a "$source_dir"/. /opt/aiba-agent/
cd /opt/aiba-agent
python3 -m venv .venv
.venv/bin/python -m pip install '.[api]'
.venv/bin/python setup_cli.py --no-browser
cp deployment/aiba.service /etc/systemd/system/aiba-agent.service
systemctl daemon-reload
systemctl enable --now aiba-agent
echo 'AIBA installed. Put it behind HTTPS before exposing port 8765 publicly.'

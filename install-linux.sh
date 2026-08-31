#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
echo
echo "AIBA Agent Linux Installer"
echo "Checking your system..."
command -v python3 >/dev/null || { echo "ERROR: Python 3.11+ is missing. Install python3, python3-venv, and python3-pip."; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,11)' || { echo "ERROR: Python 3.11 or newer is required."; exit 1; }
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install '.[api]'
.venv/bin/python setup_cli.py --no-browser
.venv/bin/python main.py --doctor
[ "${AIBA_INSTALL_NO_LAUNCH:-false}" = true ] && { echo "Headless installation certification passed."; exit 0; }
echo
echo "Installation complete. Start AIBA with: ./start-aiba-linux.sh"
if command -v xdg-open >/dev/null; then
  token=$(sed -n 's/^AIBA_API_TOKEN=["'"']\{0,1\}\([^"'"']*\)["'"']\{0,1\}$/\1/p' .env | head -1)
  nohup .venv/bin/python aiba_launcher.py --serve >agent_system/logs/server.log 2>&1 &
  for attempt in $(seq 1 30); do .venv/bin/python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/ready',timeout=2)" >/dev/null 2>&1 && break; sleep 1; done
  .venv/bin/python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/ready',timeout=2)" >/dev/null || { echo 'AIBA did not become ready. See agent_system/logs/server.log'; exit 1; }
  xdg-open "http://127.0.0.1:8765/#token=$token" >/dev/null 2>&1 || true
fi

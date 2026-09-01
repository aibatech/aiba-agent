#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "AIBA is not installed. Run ./install-linux.sh first."; exit 1; }
exec .venv/bin/python aiba_launcher.py --serve

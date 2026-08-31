#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "AIBA is not installed. Run Install-AIBA-macOS.command first."; read -r; exit 1; fi
token=$(sed -n 's/^AIBA_API_TOKEN=["'"']\{0,1\}\([^"'"']*\)["'"']\{0,1\}$/\1/p' .env | head -1)
open "http://127.0.0.1:8765/#token=$token" &
exec .venv/bin/python aiba_launcher.py --serve

#!/usr/bin/env bash
set -euo pipefail
python -m pip install --disable-pip-version-check pip-audit bandit
python -m pip_audit --strict -r requirements.txt --cache-dir .audit-cache
bandit -q -lll -r . -x './tests,./.venv,./build'
python scripts/secret_scan.py

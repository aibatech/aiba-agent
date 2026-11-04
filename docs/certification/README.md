# Retained development evidence

Generated on 2026-10-15 in an isolated Linux/Python 3.12 environment.

- `linux-x86_64.json`: compile, full tests and clean-profile startup. The script's `certified` field means these local checks passed, not that the product is production certified.
- `api-smoke.json`: real management API through ASGI TestClient, authentication, readiness, metrics, backup verification.
- `runtime-load.json`: real isolated HTTP runtime, 25 clients, 30 seconds, at least 1,000 requests. This is a short load run, not a one-hour soak or model latency benchmark.

Reproduce with `scripts/certify_install.py`, `tests/api_smoke.py`, and `scripts/certify_runtime.py --soak-seconds 30`. All fixtures use temporary profiles. Live providers, signing, physical devices, complete data restoration, and long-running memory leak observation remain unverified.

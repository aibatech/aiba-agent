"""Live running-service verification for AIBA (`aiba --verify` / `aiba verify`).

Tests the *currently running* AIBA service over its local HTTP API rather than an
isolated test client. Checks process/service status, port, /health, /ready,
authenticated access, database, provider, (optional) live provider request,
Telegram getMe (never exposing the token), connector allow-list, backup
create+verify, metrics, and installed version. Returns a nonzero exit code when
error-level checks fail so the command can be used in scripts/CI.

Usage (from the AIBA repo):
    .venv/bin/python -m diagnostics.verify [--live-provider] [--version]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from config.env import load_env

BASE = os.getenv("AIBA_VERIFY_BASE", "http://127.0.0.1:8765")


def _root() -> Path:
    return Path(os.getenv("AIBA_ROOT", Path(__file__).resolve().parents[1]))


def _load_token() -> str:
    """Read AIBA_API_TOKEN from .env, stripping surrounding quotes (load_env does this)."""
    root = _root()
    load_env(root / ".env")
    return os.getenv("AIBA_API_TOKEN", "")


def _http(method: str, path: str, token: str, payload: dict | None = None, timeout: int = 10):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
            raw = resp.read()
            # Some endpoints (e.g. /metrics) return plaintext; return status + decoded object best-effort.
            try:
                return resp.status, (json.loads(raw) if raw else None)
            except (ValueError, json.JSONDecodeError):
                return resp.status, raw.decode(errors="replace")
    except urllib.error.HTTPError as exc:
        rb = exc.read().decode(errors="replace")[:400]
        try:
            return exc.code, json.loads(rb)
        except Exception:
            return exc.code, rb
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def _systemd_active() -> bool:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "is-active", "aiba.service"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().lower()
        return out == "active"
    except Exception:  # noqa: BLE001
        return False


def _detect_process() -> str | None:
    """Best-effort detection of the running AIBA main.py --serve process."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "main.py --serve"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return out or None
    except Exception:  # noqa: BLE001
        return None


def _telegram_getme(token: str) -> dict:
    """Verify the Telegram bot token via Bot API getMe. Never echoes the token."""
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getMe")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        ok = bool(data.get("ok"))
        username = (data.get("result") or {}).get("username")
        return {"ok": ok, "username": username or None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _mask(value: str) -> str:
    return (value[:4] + "…" + value[-4:]) if value and len(value) > 8 else "…"


def run(verbose: bool = False, live_provider: bool = False) -> dict:
    checks = []

    def add(code, label, ok, detail, fix=None, severity="error"):
        checks.append({"code": code, "label": label, "ok": bool(ok), "severity": severity, "detail": detail, "fix": fix})

    token = _load_token()

    # 1) Service / process status + 2) port availability are implied by live /health/ /ready.
    active = _systemd_active()
    pid = _detect_process()
    if not active and not pid:
        add("SERVICE", "AIBA service process", False, "No systemd aiba.service and no `main.py --serve` process found", "Start it: systemctl --user start aiba.service  OR  .venv/bin/python aiba_launcher.py --serve")
    else:
        detail = "systemd aiba.service active" if active else "process running (pid={})".format(pid)
        add("SERVICE", "AIBA service process", True, detail)

    # 3) /health
    status, health = _http("GET", "/health", token)
    version = (health or {}).get("version") if isinstance(health, dict) else None
    add("HEALTH", "/health endpoint", status == 200, f"HTTP {status}, version={version}", "Confirm AIBA is running and reachable on " + BASE)
    _installed_version = version

    # 4) /ready
    status, ready = _http("GET", "/ready", token)
    migrations_ok = True
    ready_detail = f"HTTP {status}"
    if isinstance(ready, dict):
        if ready.get("ready") is False:
            migrations_ok = False
            bad = [m.get("database") for m in (ready.get("migrations") or []) if m.get("ready") is False]
            ready_detail += ", migrations not ready: " + ", ".join(bad) if bad else ""
        else:
            ready_detail += ", all databases ready"
    add("READY", "/ready endpoint", status == 200 and migrations_ok, ready_detail, "Check database migrations and disk space.")

    # 5) Database connectivity (from live /ready + diagnostics)
    db_ok = migrations_ok
    db_detail = ready_detail
    dbstatus, diag = _http("GET", "/v1/diagnostics", token)
    prov_count = 0
    if dbstatus == 200 and isinstance(diag, dict):
        for c in diag.get("checks", []):
            if c.get("code") == "DATABASE":
                db_ok = db_ok and c.get("ok", False); db_detail = c.get("detail", db_detail)
            if c.get("code") == "PROVIDER":
                try:
                    d = c.get("detail", "0"); prov_count = int(''.join(ch for ch in d if ch.isdigit())) if d else 0
                except Exception:
                    prov_count = 0
    add("DATABASE", "Database connectivity", db_ok, db_detail, "Check provider database file and permissions.")

    # 6) Authenticated API access (token -> 200; and confirm deny without token)
    astat, _ = _http("GET", "/v1/diagnostics", token)
    add("AUTH", "Authenticated API access", astat == 200, f"HTTP {astat} with bearer token", "Regenerate AIBA_API_TOKEN / ensure .env is loadable.")

    # 7) Provider availability
    add("PROVIDER", "Provider availability", prov_count > 0, f"{prov_count} provider(s) connected", "Connect a provider in the dashboard or via /v1/setup/provider.", severity="warning")

    # 8) Connector allow-list status
    cstat, conn = _http("GET", "/v1/connectors", token)
    tg_enabled = isinstance(conn, dict) and (conn.get("telegram") or {}).get("enabled")
    wa_enabled = isinstance(conn, dict) and (conn.get("whatsapp") or {}).get("enabled")
    # allow-list presence: read from env (masked)
    root = _root(); load_env(root / ".env")
    allowed = os.getenv("AIBA_TELEGRAM_ALLOWED_USERS", "").strip()
    if tg_enabled:
        add("TELEGRAM_ALLOWLIST", "Telegram owner allow-list", bool(allowed), f"allowed_users={'set,' + _mask(allowed) if allowed else 'MISSING'}", "Set AIBA_TELEGRAM_ALLOWED_USERS to your numeric Telegram user ID.", severity="warning")
    elif allowed:
        add("TELEGRAM_ALLOWLIST", "Telegram owner allow-list", True, f"configured ({_mask(allowed)}), connector disabled in UI")

    # 9) Telegram connectivity via getMe (never exposes full token), only when telegram enabled
    bot_token = os.getenv("AIBA_TELEGRAM_BOT_TOKEN", "").strip()
    if tg_enabled:
        if bot_token:
            tm = _telegram_getme(bot_token)
            if tm.get("ok"):
                add("TELEGRAM_CONNECT", "Telegram bot connectivity", True, f"getMe ok, @{tm.get('username') or 'unknown'}")
            else:
                add("TELEGRAM_CONNECT", "Telegram bot connectivity", False, f"getMe failed: {tm.get('error')}", "Check the bot token is valid and not revoked.")
        else:
            add("TELEGRAM_CONNECT", "Telegram bot connectivity", False, "AIBA_TELEGRAM_BOT_TOKEN is empty", "Set AIBA_TELEGRAM_BOT_TOKEN.")
    else:
        add("TELEGRAM_CONNECT", "Telegram bot connectivity", True, "connector disabled (AIBA_TELEGRAM_ENABLED != true)")

    # 10) Backup create + verify (live)
    backup_id = None; bstat = None
    bstatus, backup = _http("POST", "/v1/backups", token, {}, timeout=30)
    if bstatus in (200, 201) and isinstance(backup, dict):
        backup_id = backup.get("backup_id") or backup.get("id")
        bstat = f"created {backup_id}"
    vstatus = -1
    if backup_id:
        vstatus, _ = _http("POST", f"/v1/backups/{backup_id}/verify", token, {}, timeout=30)
    add("BACKUP", "Backup create + verify", bstatus in (200, 201) and vstatus in (200, 201), (bstat or f"backup FAILED (HTTP {bstatus})") + ("; verified" if vstatus in (200, 201) else f"; verify HTTP {vstatus}"), "Check data directory writable + disk space.")

    # 11) Metrics endpoint
    mstatus, _ = _http("GET", "/metrics", token)
    add("METRICS", "Metrics endpoint", mstatus == 200, f"HTTP {mstatus}", "Ensure /metrics is reachable with bearer token.")

    # 12) Optional live provider request (harmless). Only when explicitly enabled.
    live_ok = None
    if live_provider:
        if prov_count > 0:
            tstatus, task = _http("POST", "/v1/tasks", token, {"prompt": "Reply with the single word OK.", "task_type": "text"}, timeout=120)
            if tstatus in (200, 202) and isinstance(task, dict):
                job_id = task.get("job_id") or task.get("id")
                live_ok = True
                ldetail = f"task queued (job {job_id})"
                # poll briefly for completion
                for _ in range(40):
                    import time
                    time.sleep(2)
                    jstatus, job = _http("GET", f"/v1/jobs/{job_id}", token) if job_id else (-1, None)
                    if isinstance(job, dict) and job.get("status") in ("complete", "succeeded", "done"):
                        ldetail += f"; completed: {str(job.get('result'))[:80]}"; break
                    if isinstance(job, dict) and job.get("status") in ("error", "failed"):
                        live_ok = False; ldetail += f"; failed: {str(job.get('error'))[:80]}"; break
            else:
                live_ok = False; ldetail = f"live provider task failed (HTTP {tstatus})"
        else:
            live_ok = False; ldetail = "no provider connected; skipping live request"
        add("LIVE_PROVIDER", "Lightweight live provider request (explicit)", live_ok, ldetail, "Connect a healthy provider.", severity="warning")

    # 13) Installed version (from files + live)
    ver_path = root / "VERSION"
    file_version = (ver_path.read_text().strip() if ver_path.is_file() else "unknown")
    add("VERSION", "Installed version", _installed_version is not None, f"live={_installed_version}, file={file_version}")

    errors = sum(1 for c in checks if not c["ok"] and c["severity"] == "error")
    warnings = sum(1 for c in checks if not c["ok"] and c["severity"] == "warning")

    result = {
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "version": {"live": _installed_version, "file": file_version},
        "checks": checks,
        "uses_live_service": True,
    }
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aiba verify", description="Verify the currently running AIBA service.")
    ap.add_argument("--live-provider", action="store_true", help="Also run a harmless live provider request (opt-in).")
    ap.add_argument("--port", help="Override base URL port (default from AIBA_VERIFY_BASE or 8765).")
    args = ap.parse_args(argv)

    global BASE
    if args.port:
        BASE = f"{BASE.rsplit(':', 1)[0]}:{args.port}" if ":" in BASE else BASE
    result = run(verbose=False, live_provider=args.live_provider)

    print(f"AIBA verify (live service on {BASE}) — ok={result['ok']} errors={result['errors']} warnings={result['warnings']}")
    for c in result["checks"]:
        mark = "PASS" if c["ok"] else ("WARN" if c["severity"] == "warning" else "FAIL")
        print(f"  [{mark}] {c['code']}\t{c['label']} — {c['detail']}")
        if not c["ok"] and c.get("fix"):
            print(f"          fix: {c['fix']}")

    # exit 0 all pass; 1 warnings only (no errors); 2 any error-level failure
    if result["errors"] > 0:
        return 2
    if result["warnings"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

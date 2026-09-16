# AIBA update publishing

Set `AIBA_UPDATE_MANIFEST_URL` to an HTTPS JSON document:

```json
{"version":"1.6.2","url":"https://example.com/AIBA-Agent-v1.6.2.zip","sha256":"64 lowercase hexadecimal characters"}
```

AIBA requires HTTPS, validates semantic version syntax, verifies SHA-256, rejects archive traversal and symlinks, and requires the archive `VERSION` to match the manifest. It stages updates under `agent_system/updates`; `aiba_launcher.py` applies a staged update at the next restart and retains the previous source under `agent_system/update-backups`.

## User-facing update prompts

AIBA now defaults to a prompt-first update flow. When the background checker discovers a newer version, Telegram shows **Update** and **Later** buttons. **Update** downloads the release, verifies its checksum and archive safety, and stages it. The staged release is applied by `aiba_launcher.py` on the next restart. AIBA preserves `.env`, `agent_system` data/memory, `.venv`, and `.git` during application and retains the previous source as a rollback backup.

Set `AIBA_AUTO_UPDATE=true` only if you explicitly want unattended staging. The default is `false`. `AIBA_UPDATE_INTERVAL_SECONDS` controls the check interval (default: 86400 seconds / 24 hours).

Container deployments should be updated through the container image lifecycle rather than in-place application.

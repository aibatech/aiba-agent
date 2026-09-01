# AIBA update publishing

Set `AIBA_UPDATE_MANIFEST_URL` to an HTTPS JSON document:

```json
{"version":"1.3.1","url":"https://example.com/AIBA-Agent-v1.3.1.zip","sha256":"64 lowercase hexadecimal characters"}
```

AIBA requires HTTPS, validates semantic version syntax, verifies SHA-256, rejects archive traversal and symlinks, and requires the archive `VERSION` to match the manifest. It stages updates under `agent_system/updates`; `aiba_launcher.py` applies a staged update at the next restart and retains the previous source under `agent_system/update-backups`.

Set `AIBA_AUTO_UPDATE=false` to check without staging. Container deployments should be updated through the container image lifecycle.

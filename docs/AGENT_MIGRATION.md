# Migrating existing agents into AIBA

AIBA provides explicit operator CLI imports:

- `aiba claw migrate --dry-run [--source PATH] [--preset user-data|full]`
- `aiba hermes migrate --dry-run [--source PATH] [--preset user-data|full]`

Without `--yes`, migration remains preview-only even if `--dry-run` is
omitted. This intentionally makes accidental writes harder.

The default `user-data` preset discovers compatible persona/profile/context
files and skills. `full` currently has the same conservative import boundary;
it exists so additional reviewed mappings can be added without changing CLI
shape. **Neither preset imports secrets.** AIBA will not import `.env`, API
keys, authentication profiles, gateway/device credentials, MCP/plugin launch
configuration, hooks, cron jobs, channel bindings, or remote-execution settings.
Those cross separate trust boundaries and require explicit operator setup.

Existing destinations are treated as conflicts and are not overwritten. Skills
are copied under `skills/claw-imports/` or `skills/hermes-imports/` for
subsequent Skills Guard/manual review; migration does not activate or grant
permissions to imported content. Unsupported context documents are archived
under `agent_system/migration/<source>/archive/` for manual review.

OpenClaw's format changes over time, and Hermes documents a broader OpenClaw
migration surface including optional secret migration. AIBA deliberately does
not mirror secret migration because its security model treats credentials and
infrastructure as separate operator configuration.

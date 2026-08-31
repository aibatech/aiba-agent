# Operations and observability

- `/health`: public liveness without secrets.
- `/ready`: public readiness and schema state.
- `/metrics`: bearer-authenticated Prometheus text metrics.
- `/v1/operations`: bearer-authenticated migration, backup, and metric summary.
- `agent_system/logs/crashes.jsonl`: local structured crash reports with IDs returned to users.
- `agent_system/logs/audit.jsonl`: security and tool audit events.

Crash reports remain local and may contain task context or stack traces. Restrict log access and define retention. AIBA does not send telemetry to AIBA Nexus unless a future managed integration is explicitly enabled.

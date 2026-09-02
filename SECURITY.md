# Security policy

## Supported release

AIBA v1.5 receives security fixes. Do not expose older developer-preview releases.

## Required controls

1. Generate a unique 256-bit-or-stronger `AIBA_API_TOKEN`; never use an example value.
2. Generate and back up a separate `AIBA_MASTER_KEY`. Losing it makes dashboard-stored provider keys unrecoverable; changing it requires re-entering those keys.
3. Terminate HTTPS at a maintained reverse proxy and keep port 8765 on a private interface.
4. Keep browser, desktop, vision, shell, Python, and **internal subagent** (`delegate_task`) tools disabled until explicitly reviewed. Subagents are additionally governed by `AIBA_SUBAGENTS_ENABLED` (default `false`) and `config/permissions.json` `delegate_task.enabled` (default `false`) — both must be enabled together. When enabled, workers are bounded background executors only: AIBA stays the single user-facing assistant, a worker can never spawn a further worker (recursion depth zero), each worker is confined to the parent's explicitly allowed tool subset with step/time/cost budgets and global+per-parent concurrency caps, and only a concise result summary (never raw prompts, transcripts, or chain-of-thought) returns to the planner.
5. Use Docker sandbox mode for all model-authored code. Local command execution is refused.
6. Back up `agent_system/`, restrict its filesystem permissions, and encrypt the host volume.
7. Rotate provider keys, the AIBA token, and affected stored credentials after suspected exposure.
8. Review `agent_system/logs/audit.jsonl` and container logs; never send secrets in prompts.

## Threat boundaries

Prompt injection is treated as untrusted input. It cannot override the tool policy or workspace boundary. Browser SSRF defenses block non-global IP destinations, but operators should also enforce outbound network policy. Desktop control acts with the privileges of its operating-system session and should use a dedicated low-privilege account. Internal subagent workers are non-user-facing, non-recursive and cannot exceed their parent's own tool privileges: they only ever receive the exact subset of tools the delegating task explicitly listed and that the shared policy enables, so a compromised worker cannot escalate to spawn further workers or reach desktop/process/shell/browser capability that its parent delegation did not grant. Worker objectives, prompts, and transcripts are never written to the subagent store or audit log — only status, allowed-tool names, budget counters, and a concise result summary are persisted, so no prompt-injected content survives in durable storage beyond that summary.

## Reporting

Report vulnerabilities privately to the project owner. Include the release, reproduction steps, impact, and suggested mitigation. Do not include real credentials or personal data.

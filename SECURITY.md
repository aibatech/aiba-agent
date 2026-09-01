# Security policy

## Supported release

AIBA v1.5 receives security fixes. Do not expose older developer-preview releases.

## Required controls

1. Generate a unique 256-bit-or-stronger `AIBA_API_TOKEN`; never use an example value.
2. Generate and back up a separate `AIBA_MASTER_KEY`. Losing it makes dashboard-stored provider keys unrecoverable; changing it requires re-entering those keys.
3. Terminate HTTPS at a maintained reverse proxy and keep port 8765 on a private interface.
4. Keep browser, desktop, vision, shell, and Python tools disabled until explicitly reviewed.
5. Use Docker sandbox mode for all model-authored code. Local command execution is refused.
6. Back up `agent_system/`, restrict its filesystem permissions, and encrypt the host volume.
7. Rotate provider keys, the AIBA token, and affected stored credentials after suspected exposure.
8. Review `agent_system/logs/audit.jsonl` and container logs; never send secrets in prompts.

## Threat boundaries

Prompt injection is treated as untrusted input. It cannot override the tool policy or workspace boundary. Browser SSRF defenses block non-global IP destinations, but operators should also enforce outbound network policy. Desktop control acts with the privileges of its operating-system session and should use a dedicated low-privilege account.

## Reporting

Report vulnerabilities privately to the project owner. Include the release, reproduction steps, impact, and suggested mitigation. Do not include real credentials or personal data.

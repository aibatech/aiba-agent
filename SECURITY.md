# Security policy

## Supported release

Security fixes target the current maintained AIBA release line. Historical
developer-preview releases must not be exposed as services. Version labels and
CI results are not production certification; target evidence is governed by
`PRODUCTION_GATE.md`.

## 1. Trust model

### 1.1 Glossary

**Agent process** — the AIBA Python process, its model-facing orchestration,
tool registry, connectors, and in-process policy code.

**Input surface** — any path by which data or instructions enter the agent:
local/API chat, Telegram/WhatsApp, web pages, uploaded documents, MCP responses,
skills, model/provider output, browser content, and computer-node responses.

**Trust envelope** — the OS account, container/VM, filesystem mounts, network
policy, credentials, and explicitly paired external nodes within which an AIBA
process is allowed to act. Crossing this envelope requires a separately
authenticated and authorized interface.

**Stance** — the declared deployment posture for a capability: disabled,
read-only, isolated execution, operator-approved mutation, or break-glass.
Stance is configuration plus an operational promise; it is not inferred from
what a model asks to do.

### 1.2 The load-bearing boundary

**The only real containment boundary for adversarial model-authored code or
hostile tool input is OS-level isolation plus enforceable network/filesystem
policy.** AIBA therefore requires Docker isolation for model-authored shell and
Python execution and recommends a dedicated low-privilege OS account,
restricted mounts, and outbound network controls.

The following are important defense-in-depth **heuristics and policy checks,
not isolation boundaries**: the approval manager, `permissions.json`, feature
flags, capability manifests, owner allowlists, URL/SSRF checks, the browser
egress proxy, audit/redaction, MCP schemas, document/media validators, Skills
Guard/scanners, prompt-injection detection, budgets, and model instructions.
A bypass of one of these can matter, but none should be treated as equivalent
to a VM/container/OS security boundary.

### 1.3 Trust-envelope rules

AIBA starts from least privilege. High-risk surfaces are disabled unless their
feature flag and permission row are both enabled. A capability may not silently
expand the envelope of another capability. For example, enabling MCP does not
enable arbitrary MCP servers; pairing a computer node does not grant clipboard
or process control; a messaging allowlist does not grant memory administration.

Uploaded documents, browser pages, remote messages, skills, MCP data, and
computer-node results are untrusted data even when they come from an
authenticated source. Authentication answers *who sent it*, not *whether its
instructions are safe*.

### 1.4 Break-glass stance

Any documented break-glass or sensitive-mode flag is an explicit operator
choice that weakens a normal guard for a bounded purpose. It must be visible,
auditable, default-off, and must not be represented as preserving the stronger
stance. Break-glass does not disable OS-level containment requirements.

## 2. Required controls

1. Generate a unique 256-bit-or-stronger `AIBA_API_TOKEN`; never use an example value.
2. Generate and back up a separate `AIBA_MASTER_KEY`. Losing it makes dashboard-stored provider keys unrecoverable; changing it requires re-entering those keys.
3. Terminate HTTPS at a maintained reverse proxy and keep port 8765 on a private interface.
4. Keep browser, desktop, vision, shell, Python, internal subagents, MCP, remote-node transports, and future third-party extension surfaces disabled until explicitly reviewed. New high-risk capabilities require both a default-off feature gate and a disabled permission row.
5. Use Docker sandbox mode for all model-authored code. Local command execution is refused as a production containment posture.
6. Back up `agent_system/`, restrict filesystem permissions, and encrypt the host volume.
7. Rotate provider keys, the AIBA token, and affected stored credentials after suspected exposure.
8. Review `agent_system/logs/audit.jsonl` and container logs; never send secrets in prompts.
9. Treat workspace documents as untrusted. `media_extract` never evaluates spreadsheet formulas, macros, or links and never modifies source files. OCR/ASR/TTS/image generation remain unavailable until reviewed backends and tests exist.
10. Enforce host/container outbound policy in addition to application SSRF controls.

## 3. Capability trust boundaries

### 3.1 Subagents

`delegate_task` is default-off through `AIBA_SUBAGENTS_ENABLED` and
`permissions.json`. Workers are bounded, non-recursive executors. They receive
only the parent's explicitly permitted tool subset and budgets. Delegation
approval never approves a later consequential tool action. Only concise results,
not private chain-of-thought, return to the planner.

### 3.2 Browser and network

Chromium traffic is routed through AIBA's loopback egress proxy. Each
destination is resolved by the proxy, any non-global answer is refused, and the
upstream socket is opened to the approved IP. Static URL checks, DNS filtering,
and the proxy are application-layer controls; operators should still enforce
outbound network policy at the host/container boundary.

### 3.3 Computer nodes

The local `ComputerNodeGate` controls pairing, capabilities, emergency stop,
and budgets. Remote transport is a separate trust boundary: when explicitly
configured it requires HTTPS plus HMAC-signed timestamped/nonced requests and
may pin the TLS certificate. Pairing/authentication is not desktop isolation;
the remote node must run under an appropriately restricted OS account.

### 3.4 MCP

MCP is default-off on independent axes: `AIBA_MCP_ENABLED`, the
`mcp_call` permission row, and an operator allowlisted server/tool catalog.
Stdio launches use explicit argv rather than a shell. Remote HTTP requires its
separate remote flag, HTTPS, SSRF policy, and no redirects. Enabled tools require
operator-maintained input schemas and calls are validated before transport.
Secrets are forwarded by allowlisted environment-variable name, not embedded
in config. MCP schema validation and allowlists are supply-chain guards, not
process isolation. AIBA never auto-installs or auto-trusts an MCP server.

### 3.5 Messaging / external surfaces

Every external messaging surface must authorize at the boundary and fail closed
when no owner allowlist is configured. Remote messages run with the
non-interactive posture: tools requiring interactive approval remain denied.
Session IDs are routing handles, not authentication credentials. Principals
inside one configured allowlist are equally trusted for that connector unless a
stronger per-user policy is explicitly implemented. Any inbound HTTP listener
must bind loopback by default unless deployment documentation specifies an
authenticated reverse-proxy boundary.

Chat authorization and memory administration are separate. Connector
allowlists do not imply `AIBA_MEMORY_OWNER_USERS` membership.

New adapters implement the `MessagingAdapter` boundary contract. Discord and Slack are disabled unless their connector-specific enable flag is set and refuse startup without an explicit owner allowlist. Discord ignores bot-authored messages and accepts only allowlisted principals. Slack requires a verified signing-secret signature with a five-minute replay window before event processing and accepts only allowlisted principals. Outbound Slack messages disable rich-text interpretation by default. Neither adapter grants interactive approvals, changes tool permissions, or expands memory-admin scope. Discord gateway delivery and Slack HTTP routing remain deployment surfaces: any Slack listener must follow the loopback/reverse-proxy rule above, and production connector claims require target evidence under `PRODUCTION_GATE.md`.

### 3.6 Plugins and skills

Installed skill/plugin content is **code or instructions from another trust
domain**. Future third-party ecosystems must therefore be opt-in and default-off.
Installation and activation are separate decisions: downloaded content must be
reviewable before activation, versioned, attributable to a source, and subject
to static scanning. A scanner may identify suspicious injection, hidden
instructions, executable payloads, unexpected network references, or permission
requests, but it is a review aid—not a security boundary.

A skill/plugin may not grant itself tools, credentials, filesystem mounts,
network access, persistence, or approval. Effective privileges are the
intersection of the host stance, feature flags, `permissions.json`, tool
policy, and OS/container envelope. Self-modifying or self-evolving skills require
a separate threat-model/design review and are not implicitly authorized by the
ordinary skill system. AIBA accepts the portable Agent Skills SKILL.md core format
but deliberately does not treat its experimental allowed-tools metadata as an
authorization grant. Imported packages are statically reviewed by Skills Guard;
findings require explicit reviewed import, symlinks are not preserved, and a
clean scan never upgrades package trust. See docs/AGENT_SKILLS_SECURITY.md.

### 3.7 Terminal execution backends

Terminal execution is default-off at the tool-policy layer. Docker remains the recommended containment posture for model-authored shell/Python. SSH and remote Docker Compose additionally require `AIBA_TERMINAL_BACKENDS_ENABLED=true` and an explicit `AIBA_SANDBOX_MODE` selection. SSH uses argv-based OpenSSH invocation, BatchMode, mandatory host-key checking, an operator-selected remote workspace, and optional explicit key/known-hosts paths. It isolates execution from the AIBA host but **does not sandbox commands on the remote host**; confinement there is the remote OS account, filesystem permissions, container/VM policy, and network policy. Remote Compose executes inside an already operator-provisioned service and does not create or secure the Docker daemon, mounts, Compose network, or credentials. These backends isolate only terminal/backend-file operations routed through them; they do **not** isolate MCP subprocesses, browser processes, connector processes, plugin/skill loading, or the AIBA process itself.

### 3.8 Untrusted documents and media

Parsers operate read-only on source files and do not execute macros, evaluate
spreadsheet formulas, or follow embedded links. Parser libraries still process
attacker-controlled bytes, so patched dependencies and OS isolation are required
for hostile documents at scale. Capability probes must report unavailable
features honestly rather than simulating OCR/ASR/TTS/image-generation success.

## 4. Vulnerability disclosure scope

Report vulnerabilities privately to the project owner with release/commit,
reproduction steps, impact, and suggested mitigation. Never include real
credentials or personal data.

### In scope

- Escape from a declared OS/container/filesystem/network isolation posture.
- Unauthorized access across an external surface or owner/identity boundary.
- Credential/key/token exfiltration caused by AIBA code or a bypass that reaches
  a consequential sink.
- Authentication, replay, signature, or authorization bypass in computer-node,
  API, connector, or MCP transport.
- A default-off capability becoming reachable without the documented gates.
- A trust-model/documentation violation where implementation materially provides
  broader privilege than the documented stance.
- Supply-chain behavior that executes or enables unreviewed third-party code
  outside the declared trust envelope.

### Normally out of scope by itself

- Bypassing an in-process heuristic (scanner, prompt filter, redaction pattern,
  schema lint, or model instruction) without a chained security consequence.
- Prompt injection that only changes model text and does not cross an
  authorization, confidentiality, integrity, or isolation boundary.
- Behavior explicitly enabled by a documented break-glass flag when it stays
  within the weakened stance the operator selected.
- Denial of service requiring the operator to deliberately grant the attacking
  principal equivalent local/owner access, absent a boundary escape.

An out-of-scope primitive becomes in scope when it chains into an in-scope
impact. Severity follows the achieved boundary crossing, not the name of the
heuristic that failed.

## 5. Release evidence

Source review, unit tests, CI, and this policy do not certify a deployment.
Clean-install, live-provider, connector, remote-host, soak, backup/restore,
upgrade, and platform evidence must be produced and retained as required by
`PRODUCTION_GATE.md`. Agents and contributors must describe missing evidence
as missing rather than inferring it from passing source tests.

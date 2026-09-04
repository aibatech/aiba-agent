# Changelog

## 1.6.0 — 2026-09-04 (v1.6.0-rc.1)

Capability-parity release. See `docs/PLAN_v1.6_capability_parity.md` for the full
engineering plan, capability matrix, and release gates. Highlights:

- Full-stack capability parity for the agent loop: web search/extract, patch_file,
  archive extract (zip-slip-safe), safe computer control + paired-node gate, bounded
  internal subagents, session store with FTS, media/document text extraction, optional
  MCP client gateway (`mcp_call`, off by default), memory maintenance + editing, skills
  with versioning/rollback, capability-management CLI + dashboard, and the `clarify`
  tool with inline-button UX on Telegram.
- Security hardening across the release: SSRF-safe URL policy shared by browser_fetch
  and the interactive browser session; connect-time DNS-peer enforcement for the
  interactive Playwright driver (refuses non-global/rebinding peers on the main frame);
  desktop screenshot workspace-confinement; per-user memory isolation with
  identity-derived ownership (operator scoped to shared/legacy; any second principal
  strictly limited to its own rows); audit/approval-surface secret scrubbing; subagent
  cancel/timeout-at-boundary + safe shutdown; permission-enabled tooling is policy-gated
  and require-approval, never auto-enabled.
- Persisting ownership model: memory rows carry an `owner`; a fresh `aiba.db` migrates to
  schema v2 idempotently at startup (legacy reflections backfilled to `shared`, visible
  only to the primary operator scope — matching the owner decision, never a second-user
  scope).
- Non-goals deferred and recorded as EXCLUDED for this release (not passed tests):
  remote computer-node pairing over a network, real OCR/ASR/TTS/image-generation
  backends (tested document extraction ships; unsupported backends report unavailable),
  and remote MCP over HTTPS (local stdio MCP ships; remote stays disabled/experimental).
  Stable-production certification and full third-party (Hermes/OpenClaw) parity are not
  claimed.

## 1.5.0 — 2026-09-01

- Added a version-controlled `SOUL.md` character contract for AIBA's warm, playful,
  plain-language voice.
- Added private per-user profiles with human-readable local `*-USER.md` mirrors and a safe
  repository example (`USER.example.md`); real profiles live only in the gitignored
  `agent_system/profiles/` directory with 0600 permissions.
- Added resumable, one-question-at-a-time onboarding wired into the Telegram and WhatsApp
  connectors.
- Added user-level tone, detail, initiative, humor, and memory settings.
- Added `/profile`, `/memory pause`, `/memory resume`, and `/skip` conversation controls.
- Injected AIBA's soul and the correct private user profile into model conversations without
  exposing chain-of-thought, hidden prompts, credentials, or internal deliberation.

## 1.4.1 — 2026-09-01

- Discovery-aware, atomic provider onboarding: the setup flow now queries the provider's live
  model-discovery endpoint before choosing a default model, so it registers a currently-available
  model instead of a hardcoded (possibly deprecated) one.
- Idempotent provider/model registration (`upsert_provider` / `upsert_model`): existing providers
  and models are reused, and repeated calls never create duplicates.
- Safe fallback plus sanitized `discovery_error` when discovery is unavailable; provider API keys
  are redacted (`[REDACTED]`) and never printed or logged.
- New `aiba --verify` command that verifies the **live running service** (process/port, /health,
  /ready, authenticated API, database, provider, Telegram getMe + allow-list, backup create+verify,
  metrics, installed version) and returns nonzero exit codes on failure.
- Hardened `.gitignore` so the local data dir (`agent_system/`), `.venv`, build artifacts, and
  certification output can never be accidentally committed.

## 1.1.0 — 2026-08-03

- Added unlimited persistent provider connections and model definitions.
- Added encrypted API-key storage with environment-key alternatives.
- Added presets for 15 major cloud, local, and compatible provider types.
- Added remote model discovery and provider connection tests.
- Added automatic task classification and Balanced, Quality, Cost, Latency, and Manual routing.
- Added capability filtering, preferred models, cost ceilings, passive health states, and automatic failover.
- Added token, estimated-cost, latency, success, and error accounting.
- Added authenticated provider, model, routing, route-preview, discovery, and usage APIs.
- Rebuilt the dashboard around Auto/Manual model selection and provider management.

## 1.0.0 — 2026-08-03

- Replaced simulated model tooling with native OpenAI, Anthropic, Ollama, and OpenAI-compatible tool calls.
- Made task, job, skill, and event APIs bearer-authenticated.
- Added rate limiting, request bounds, authenticated WebSockets, CORS allowlisting, and safe non-loopback startup checks.
- Added SSRF defenses for browser navigation, redirects, DNS resolution, and subresources.
- Refused local model-authored shell/Python execution; Docker isolation is now required.
- Added tool-argument validation, exception containment, serialized agent execution, and clean shutdown.
- Hardened Docker/Compose with a non-root user, read-only root filesystem, dropped capabilities, health checks, and required secrets.
- Added a usable queue-and-poll dashboard, deployment/security runbooks, and v1.0 tests.
# 1.2.0

- Added Windows, macOS, Linux, and Docker guided installers.
- Added automatic local security-key generation and a first-run provider wizard.
- Added structured diagnostics with actionable fixes in CLI, API, and dashboard.
- Added checksum-verified native automatic updates with staging and backups.
- Added VPS console launch buttons and verified cloud-init generation.
# 1.3.0

- Added explicit SQLite schema migrations with checksums and integrity checks.
- Added consistent online backups, verification, guarded restore, and automatic pre-restore safety snapshots.
- Added local crash IDs, Prometheus-format metrics, readiness checks, security headers, and operations status.
- Added Windows/macOS/Linux certification plus Docker, security, live-provider, load, concurrency, and failover test tooling.
- Added credential-gated Authenticode and macOS signing jobs with build provenance and checksums.
- Added portable Markdown skill discovery while preventing instruction-only skills from directly executing tools.
- Hardened installers to fail on diagnosis errors and wait for readiness.
# v1.4.0-rc.1

- Added owner-allowlisted Telegram Bot API long-polling connector.
- Added signed Meta WhatsApp Cloud API webhook and outbound replies.
- Added duplicate WhatsApp delivery protection and bounded message splitting.
- Added authenticated connector status API and connector diagnostics.
- Preserved deny-by-default behavior for approval-requiring remote actions.

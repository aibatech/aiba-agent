# Changelog

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

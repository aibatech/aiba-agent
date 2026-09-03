# AIBA Agent v1.5 Release Candidate

AIBA is a self-hosted autonomous-agent runtime designed as a deployable alternative to OpenClaw and Hermes. It provides bounded model/tool reasoning, durable memory, workspace operations, human approvals, persistent jobs, schedules, reusable skills, an authenticated API, live events, a dashboard, Telegram and WhatsApp communication, and optional browser, vision, and desktop adapters.

## Soul and personal profiles

`SOUL.md` defines AIBA's shared character: warm, concise, capable, playful, honest, and nontechnical by default. Each Telegram or WhatsApp user receives a separate private profile in `agent_system/profiles/`. A human-readable `*-USER.md` mirror makes the remembered preferences inspectable while the JSON file provides reliable runtime state. The entire profiles directory is excluded from Git.

On first contact, AIBA asks one short question at a time to learn the user's name, work, main goal, and communication preference. Onboarding resumes after restarts. Use `/profile` to review the profile, `/memory pause` or `/memory resume` to control learning, and `/skip` to defer onboarding. `USER.example.md` documents the format without containing personal information.

## Telegram and WhatsApp

Telegram uses long polling, so it can run from a computer behind a home router without opening a public port. Create a bot with Telegram's official `@BotFather`, add its token and the numeric owner ID to `.env`, and then either run `python main.py --telegram` or set `AIBA_TELEGRAM_ENABLED=true` while running `python main.py --serve`.

```env
AIBA_TELEGRAM_ENABLED=true
AIBA_TELEGRAM_BOT_TOKEN=replace_me
AIBA_TELEGRAM_ALLOWED_USERS=123456789
```

WhatsApp uses Meta's official WhatsApp Cloud API. Configure a Meta app and business phone number, route an HTTPS webhook to `/v1/connectors/whatsapp/webhook`, subscribe it to WhatsApp `messages`, and use the same value for Meta's webhook verification token and `AIBA_WHATSAPP_VERIFY_TOKEN`.

```env
AIBA_WHATSAPP_ENABLED=true
AIBA_WHATSAPP_ACCESS_TOKEN=replace_me
AIBA_WHATSAPP_PHONE_NUMBER_ID=replace_me
AIBA_WHATSAPP_VERIFY_TOKEN=replace_with_a_long_random_value
AIBA_WHATSAPP_APP_SECRET=replace_me
AIBA_WHATSAPP_ALLOWED_NUMBERS=15551234567
```

Both connectors accept private text only from explicit owner allowlists. WhatsApp webhooks require Meta's `X-Hub-Signature-256`, duplicate message IDs are ignored, connector secrets remain in the local `.env`, and replies are sent without rich-text parsing. Remote messages use AIBA's non-interactive security posture: approval-requiring tools remain denied rather than being automatically approved.

## Production posture

v1.4 includes the v1.3 production-gate automation plus owner-authenticated Telegram and WhatsApp communication. Its operational foundation includes versioned database migrations, verified backup/restore, local crash reports and metrics, readiness checks, cross-platform certification, opt-in live-provider tests, load/soak testing, security scanning, portable skill contracts, and credential-gated signed releases.

The repository is release-candidate capable, not automatically Certified. `PRODUCTION_GATE.md` is authoritative. A platform or provider receives a Certified label only after its generated evidence passes on the actual target. Code-signing workflows intentionally fail when owner-controlled certificates are absent.

## Install

- **Windows:** double-click `Install-AIBA-Windows.bat` (Python 3.11+ required).
- **macOS:** right-click `Install-AIBA-macOS.command`, choose Open, and approve it (Python 3.11+ required).
- **Linux:** run `chmod +x install-linux.sh && ./install-linux.sh` (Python 3.11+ required).
- **Docker:** run `install-aiba-docker.sh`, or double-click `Install-AIBA-Docker.bat` on Windows (Docker Desktop/Engine required).

Every installer creates a private API token and credential-encryption key, performs a health diagnosis, starts AIBA, and opens the first-run provider wizard. Secrets remain on the installation.

## Updates and VPS deployment

Native installs can periodically check an HTTPS update manifest, verify the archive SHA-256, stage it, and apply it safely on restart while retaining a local backup. Configure `AIBA_UPDATE_MANIFEST_URL`; set `AIBA_AUTO_UPDATE=false` for notify-only mode.

The dashboard includes launch buttons for major VPS providers. After publishing a release, set `AIBA_RELEASE_URL` and `AIBA_RELEASE_SHA256` to enable a downloadable cloud-init installer. Docker installations update by rebuilding or pulling the image, preserving the data volume.

Run `python main.py --doctor` at any time for clear, machine-readable errors and suggested fixes.

## Model Provider Manager

Users can add unlimited provider connections and models from the dashboard or API. Supported presets include OpenAI, Anthropic, Google Gemini, xAI, OpenRouter, Groq, Mistral, DeepSeek, Together AI, Perplexity, Azure OpenAI, AWS Bedrock, Ollama, LM Studio, and custom OpenAI-compatible endpoints.

- API keys can be read from environment variables or encrypted in `providers.db` with `AIBA_MASTER_KEY`.
- Plaintext stored keys are never returned by the API or dashboard.
- Models carry capabilities such as `text`, `tools`, `code`, and `vision`, context-window metadata, priorities, and per-million-token prices.
- Auto routing classifies coding, research, vision, creative, reasoning, and general tasks.
- Routing strategies include Balanced, Quality, Lowest Cost, Lowest Latency, and Manual.
- Rules support required capabilities, preferred model order, and cost ceilings.
- Failed requests automatically fall through to the next eligible model.
- Provider health moves through unknown, healthy, degraded, and unhealthy states.
- Usage records capture provider, model, task type, tokens, estimated cost, latency, success, and errors.
- Provider connection tests, remote model discovery, route previews, and 1–365 day usage summaries are available through authenticated endpoints.

### Discovery-aware, atomic provider onboarding

Connecting a provider via the dashboard (`POST /v1/setup/provider`) or the onboarding
helper (`onboarding.providers.connect_provider_atomically`) is now **idempotent and
discovery-aware**:

- Before a default model is chosen, AIBA calls the provider's **live model-discovery
  endpoint** (`/v1/providers/{id}/discover-models`) and registers a model that is
  **currently available**, rather than relying on a hardcoded model id that may have
  been deprecated by the vendor.
- The provider is **reused when already present** and created only when absent; models
  are likewise upserted by `provider_id + model_id`. Repeated calls never create
  duplicate provider or model rows.
- If discovery is unavailable (offline, bad credentials, empty result) AIBA falls back
  to a safe, per-kind default model and reports `used_fallback` and a sanitized
  `discovery_error` to the caller.
- A requested `preferred_model` is honoured **only if** it appears in the live discovery
  list; otherwise an available model is selected.
- **Provider API keys are never printed or logged** — any key echoed back inside a
  discovery error string is redacted to `[REDACTED]`.

The Community Runtime has no artificial provider or model limits. It remains a single-owner, self-hosted AIBA runtime; multi-tenant organization policy belongs in the separate private AIBA Nexus platform.

## Security foundation

- bearer authentication is mandatory for every task, job, skill, and event endpoint;
- non-loopback API binding is rejected without a token;
- WebSockets authenticate before accepting a connection;
- API rate limits and prompt-size limits are enforced;
- browser requests reject credentials, local addresses, private networks, and unsafe redirect/subresource targets;
- document/text extraction (`media_extract`) is read-only and workspace-confined: file size and page/sheet/row/return counts are bounded, and document contents are treated as untrusted data — spreadsheet formulas are never evaluated, links and macros are never followed or run, and originals are never modified;
- shell and Python execution require the isolated Docker sandbox;
- tool arguments are validated and tool failures are contained;
- OpenAI, Anthropic, Ollama, and OpenAI-compatible providers receive native tool schemas;
- **internal subagents are disabled by default** (`AIBA_SUBAGENTS_ENABLED` + `permissions.json` `delegate_task` `enabled:false`); when enabled they are bounded background workers only — never user-facing, never recursive, each confined to an explicitly allowed tool list, step/time/cost budgets and global+per-parent concurrency, and returning only a concise result summary (no raw prompts/transcripts/CoT);
- the container runs as a non-root user with dropped capabilities and a read-only root filesystem;
- data, tasks, jobs, schedules, reflections, and audit records survive restarts.

No autonomous agent can be declared secure for every environment without an operator threat model. Before public deployment, put AIBA behind TLS, use a secrets manager, review `config/permissions.json`, keep computer control disabled unless needed, and run untrusted code only with `AIBA_SANDBOX_MODE=docker` on a host configured for nested containers.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[api]'
cp .env.example .env
export AIBA_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export AIBA_MASTER_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python main.py --serve
```

Open `http://127.0.0.1:8765`. The dashboard asks for the token in-memory and queues tasks through `/v1/tasks`.

For model reasoning:

```bash
export AIBA_PROVIDER=openai
export AIBA_MODEL=gpt-4.1-mini
export OPENAI_API_KEY=...
python main.py --prompt "Inspect the workspace and summarize it"
```

Legacy environment configuration still supports `local`, `openai`, `anthropic`, `openai_compatible`, and `ollama`. After startup, add any number of provider accounts and models from the dashboard. Local mode supports `/files`, `/remember TEXT`, and `/recall QUERY` without external services.

## Docker deployment

```bash
cd deployment
export AIBA_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export AIBA_MASTER_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose up --build -d
```

Compose binds to localhost by default. Terminate TLS at a trusted reverse proxy before exposing it publicly.

## API

```bash
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/v1/tasks \
  -H "Authorization: Bearer $AIBA_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"List the workspace files","background":true}'
```

Poll `/v1/jobs/{job_id}`. Live authenticated events are available at `/v1/events`.

Provider management endpoints are available under `/v1/providers`, `/v1/models`, `/v1/routing/rules`, `/v1/routing/preview`, and `/v1/usage`. When an API token is configured, interactive OpenAPI documentation is available at `/docs`.

## Execution and approvals

File access is constrained to `agent_system/workspace`. Sensitive tools require approval by default. Non-interactive API jobs deny approval-requiring actions; this is intentional. Create reviewed skills or adjust the permissions policy for narrowly defined unattended workflows.

`delegate_task` (internal subagents) is disabled by default. To enable it, set `AIBA_SUBAGENTS_ENABLED=true` **and** flip `config/permissions.json` `delegate_task.enabled` to `true` — both must be on, mirroring the browser/computer gate posture. When enabled, AIBA remains the single assistant you talk to; the workers it spawns are invisible, bounded, non-recursive internal workhorses that return only a concise result summary for AIBA to fold into its reply.

Docker sandbox mode mounts only the workspace, disables networking by default, and applies CPU/memory limits. Do not mount the host root or a Docker socket into the AIBA application container.

## Media and document extraction

AIBA can read the readable text out of common document formats so the model can inspect files dropped into its workspace — as **read-only, bounded, workspace-confined** extraction:

- **Formats:** PDF, DOCX, XLSX, PPTX (via the optional `[media]` extra: pypdf / python-docx / openpyxl / python-pptx), plus CSV, plain text / markdown, and common image metadata (Pillow). All are pure-Python; the base `pip install -e '.[api]'` install stays lightweight and does not require them.
- **Install:** `pip install -e '.[media]'` (or `'.[all]'`) to enable binary-format parsing. CSV / text / markdown always work; a missing optional library returns a clear "install optional support" diagnostic rather than a partial parse.
- **Tool:** `media_extract` — read-only, registered through the capability manifest, permissions, the `AIBA_MEDIA_ENABLED` feature flag (default on), diagnostics, and audit. It requires no approval and never writes.
- **Posture:** every read is confined to the approved workspace; file size, page/sheet/slide/row and returned-character counts are bounded; document content is treated strictly as **untrusted data** — spreadsheet formulas are never evaluated, links and macros are never followed or run, and source files are never modified.
- **Not (yet) functional:** OCR, audio transcription, text-to-speech, and image generation. AIBA surfaces these honestly as capability probes that report not-available until a real backend and its tests are wired in — it does not pretend to offer them.

## Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
```

The suite covers path isolation, blocked commands, memory sync/retrieval, task persistence, token storage, queue recovery, scheduling, skills, model-native tool calls, argument validation, and private-network browser blocking.

See `SECURITY.md`, `DEPLOYMENT.md`, and `VALIDATION.md` for the operational checklist and release evidence.

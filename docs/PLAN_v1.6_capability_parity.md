# AIBA v1.6 — Capability Parity: Engineering Plan + Capability Matrix + Timeline

**Status:** PLANNING (approved by Josh — no implementation yet)
**Branch:** `feat/aiba-v1.6-capability-parity` (created, empty — code unchanged from v1.5.0)
**Live install:** v1.5.0 untouched. Not restarted, not modified.
**Date:** 2026-09-01

---

## 0. Executive summary

Bring AIBA to practical Hermes/OpenClaw capability parity while preserving AIBA's existing strengths
(personality + soul, per-user private profiles, provider routing, memory, Telegram/WhatsApp, approvals,
backups, verification). This document:

1. Defines the **capability matrix** (Current AIBA vs Hermes vs OpenClaw vs v1.6 target) with per-phase evidence.
2. Lays out the **engineering plan** per phase (files, approach, tests, gates).
3. Gives a **realistic timeline** and a **milestone cut** for PRs.

**Ground rule (from the brief):** No parity claim is made until a capability has a working implementation
**and** passing tests. This plan explicitly marks each item as `implemented / partial / not-started` — and
currently **all** v1.6 phase items are `not-started` except where AIBA already has partial functionality.

---

## 1. Baseline: What AIBA has today (v1.5.0)

Audited directly from source (`main`, `config/settings.py`, `agent/loop.py`, `reasoning/engine.py`,
`connectors/`, `tools/`, `computer/`, `skills/`, `memory/`, `security/`).

### Registered tools (18 total, in `AgentLoop._register_tools`)
| Tool | Notes |
|---|---|
| `list_files`, `read_file`, `write_file`, `delete_file` | File ops (sandbox-scoped) |
| `run_shell`, `run_python` | Sandbox exec (local or docker backend) |
| `remember`, `search_memory` | Durable memory put/get |
| `browser_fetch` | Playwright render-to-text, **SSRF-guarded already** (`_public_url`) |
| `desktop_screenshot`, `desktop_click`, `desktop_type` | Computer control — **disabled by default** (`AIBA_DESKTOP_ENABLED`) |
| `vision_analyze` | Image analysis |
| `list_skills`, `skill_instructions`, `run_skill` | Skills (reviewed portable skills) |
| `enqueue_task`, `schedule_task` | Background queue + scheduler |

### Existing infrastructure (usable, must preserve)
- **Personality**: SOUL.md shared soul + per-user opaque private profiles, `/memory pause`, numbered-style onboarding.
- **Provider routing**: `providers.db` (providers/models/rules/usage), IntelligentRouter, failover, encrypted creds.
- **Memory**: `MemoryVault` (SQLite + vault dir), RetrievalEngine (semantic), DreamEngine (reflections).
- **Security**: SecurityPolicy (path/command/tool checks + approval), AuditLog (JSONL), encrypted credential store,
  approvals manager, sandbox (local/docker).
- **Ops**: backups (create/verify/restore + integrity), migrations (checksummed, idempotent), crash reporter,
  metrics, doctor, verify (11-check production gate).
- **Connectors**: Telegram (long polling, allowlist, `/start` onboarding) + WhatsApp (webhook, allowlisted).
- **Update mgmt**: staged verified updates, systemd unit, `aiba_launcher.py`.
- **Vision**: `VisionAnalyzer` (model-backed image analysis).

### Confirmed gaps (drives the matrix)
- **No web search tool** (`web_search` absent — nothing in `tools/`).
- **No `web_extract`/page-extraction tool** (only Playwright `browser_fetch`).
- **No browser session model** (persistent nav, snapshot/accessibility, downloads, domain allow/deny lists, per-action approval). Only a single-shot render.
- **Computer control is exactly 3 tools** (screenshot/click/type) and **disabled by default** — no accessibility tree, no window mgmt, no keyboard/scroll/drag/clipboard, no paired remote node, no kill-switch/max-actions audit.
- **No MCP client** (nothing in `tools/`, `models/`, or `connectors/`).
- **No media/document processing** beyond `vision_analyze` (no PDF/DOCX/XLSX/PPTX, no OCR, no audio transcription, no TTS, no image generation).
- **No session history / cross-session search / memory edit-delete-export / memory suggestions.**
- **Skills**: create/list/import/execute exist, but **no auto-creation from repeated work** (there's a SkillImprover proposal path), no versioning/rollback.
- **No real subagents**: `delegate` in `reasoning/engine.py` is a **simulated lane** (one runtime, no separate model calls / isolation / parallelism / budgets).
- **No visible work-protocol events** (plan/progress/tool_started/etc.). Reasoning is a single loop; results only at the end.
- **No clarify tool** (clarification is forced through unstructured `final` responses).
- **No capability CLI** (`aiba tools/nodes/mcp/sessions/subagents` don't exist) and no capability dashboard sections.

---

## 2. Capability Matrix

Legend: `A=AIBA v1.5 today` · `H=Hermes Agent` · `O=OpenClaw` · `T=v1.6 target`. Status: ✅ implemented · ◑ partial · ❌ absent/not-in-sources · **→** planned in v1.6.

### PHASE 1 — Telegram experience
| Capability | A | H | O | T | Evidence / notes |
|---|---|---|---|---|---|
| Clean text renderer (strip raw `**`/`###`) | ❌ | ◑ | ✅ | **→** | AIBA sends raw model text; no PostProcess. Hermes/OpenClaw render markdown to clean messages. |
| Short natural messaging system prompt | ❌ | ✅ | ✅ | **→** | Rewrite `reasoning.SYSTEM` for Telegram, keep CLI/structure mode. |
| Typing indicator (`sendChatAction typing`, ~4s refresh) | ❌ | ✅ | ✅ | **→** | Bot API `sendChatAction`; status lasts ≤5s → refresh loop. |
| Accurate media actions (`upload_document/photo/voice`) | ❌ | ◑ | ✅ | **→** | Map to `sendPhoto`/`sendDocument`/`sendVoice`. |
| Safe response streaming / draft | ❌ | ◑ | ◑ | **→** | **Public Bot API has NO `sendMessageDraft`.** Implement typing-heartbeat by default; optional edit-Message-as-progress on supported clients. Correct the brief's terminology in plan. |
| `stop-generation` handling + fallback | ❌ | ◑ | ◑ | **→** | Button → cancel flag → fallback to heartbeat. |
| Inline buttons (clarify/approve/onboarding/cancel/retry) | ❌ | ✅ | ✅ | **→** | `InlineKeyboardMarkup` + `answerCallbackQuery`. Keep numbered-text fallback. |

### PHASE 2 — Visible reasoning (no CoT leak)
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Work-protocol events (plan/clarify/progress/tool_* /result/warning/failure) | ❌ | ◑ | ◑ | **→** | Neither Hermes nor OpenClaw expose this exact event protocol. AIBA can lead with a clean implementation. |
| Single transient progress message (edit, not spam) | ❌ | ◑ | ✅ | **→** | Bot API `editMessageText`. |
| Detailed trace → audit log; summary → user | ◑ | ✅ | ✅ | **→** | AIBA already audits `tool_start/end`; add user-facing summaries. |
| No raw CoT / hidden prompts / reasoning tokens exposed | ✅ | ◑ | ◑ | **→** | AIBA already forbids CoT in SYSTEM; add event-filtered safe summaries + tests. |

### PHASE 3 — Real subagents
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Supervisor/Worker real separate model calls | ❌ | ✅ | ✅ | **→** | Replace simulated `delegate`. |
| Isolated context + parallel independent tasks | ❌ | ✅ | ✅ | **→** | Thread/process pool + isolated prompt/task state. |
| Roles researcher/builder/reviewer | ❌ | ◑ | ◑ | **→** | Role templates. |
| Max workers (default 3) | ❌ | ✅ | ◑ | **→** | Configurable, default 3. |
| Token/time/cost budgets | ❌ | ◑ | ◑ | **→** | Budget guards per worker + global. |
| Cancellation & timeout | ❌ | ✅ | ◑ | **→** | 
| Recursion depth limit | ❌ | ✅ | ✅ | **→** | Cap depth (matches openclaw depth limits). |
| No secret access unless granted | ❌ | ✅ | ✅ | **→** | Inherit policy; explicit grants. |
| Supervisor verifies consequential results | ◑ | ◑ | ◑ | **→** | Partial existing "verify" ethos; formalize. |
| Full audit trail + failure recovery | ◑ | ✅ | ✅ | **→** | Reuse `AuditLog` + crash reporter. |

### PHASE 4 — Web + browser tools
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| `web_search` (configurable provider; title/url/snippet/date/source) | ❌ | ✅ | ✅ | **→** | Provider abstraction (duckduckgo/brave/tavily/searx) + normalized result shape. |
| `web_extract` / page extraction | ❌ | ✅ | ✅ | **→** | readability/Playwright text+markdown extraction. |
| Browser persistent sessions | ❌ | ✅ | ✅ | **→** | Context storage/index on disk. |
| Text/accessibility snapshot | ❌ | ◑ | ✅ | **→** | aria/accessibility snapshot where supported. |
| Vision fallback | ◑ | ✅ | ✅ | **→** | Reuse `vision_analyze`. |
| Download management | ❌ | ◑ | ✅ | **→** | Downloads dir + wait/list. |
| Timeouts & cancellation | ◑ | ✅ | ✅ | **→** | AIBA has a 30s goto timeout; generalize. |
| SSRF protection (block private/localhost by default) | ✅ | ✅ | ✅ | **→** | AIBA `_public_url` already blocks; keep + test. |
| Domain allow/deny lists | ❌ | ✅ | ◑ | **→** | Policy lists. |
| Approval before login/submit/purchase/delete/consequential | ◑ | ✅ | ✅ | **→** | Reuse `approvals`; extend to web actions. |
| Don't leak cookies/credentials to model | ◑ | ✅ | ✅ | **→** | Redact from browser output. |

### PHASE 5 — Computer control + paired node
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Full desktop toolset (screen/accessibility/windows/click/type/key/hotkeys/scroll/drag/clipboard) | ◑ | ◑ | ✅ | **→** | Upgrade 3→ full set; disable by default. |
| Disabled by default + setup wizard + per-tool perms | ◑ | ◑ | ✅ | **→** | AIBA has `AIBA_DESKTOP_ENABLED` default off. |
| Approval before consequential, emergency stop, max-action count | ◑ | ◑ | ◑ | **→** | Add e-stop + budget + audit. |
| Screen/clipboard privacy + secret-field detection | ◑ | ◑ | ◑ | **→** | Redact fields; never read password managers. |
| Paired AIBA Node (Win/macOS/Linux): mutual auth, short-code pairing, revocable identity, encrypted WS/HTTPS, Tailscale, heartbeat+capability, local kill switch | ❌ | ◑ | ✅ | **→** | OpenClaw has node pairing; Hermes no native generic desktop. **Large subproject.** |
| Clearly say when no GUI/node available | ◑ | ◑ | ◑ | **→** | Message when disabled/unavailable. |

### PHASE 6 — Terminal / file / process parity
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Terminal: local + Docker + SSH backends | ◑ | ✅ | ✅ | **→** | AIBA has local+docker; add SSH. |
| Persistent working directory | ◑ | ✅ | ◑ | **→** | Sandbox holds cwd; make persistent. |
| Process lifecycle (start/list/poll/logs/wait/input/terminate) | ◑ | ◑ | ✅ | **→** | AIBA has queue/scheduler but not process tools. |
| PTY support | ❌ | ◑ | ✅ | **→** | 
| File ops parity (move/copy/patch/search/tree/archive/checksum) | ◑ | ✅ | ✅ | **→** | Add patch/move/copy/search/archive/checksum. |
| Mutations require policy review; destructive require approval | ✅ | ✅ | ✅ | **→** | Already policy-gated; formalize + extend. |
| Local-model tool calls can't escape sandbox | ✅ | ✅ | ◑ | **→** | AIBA sandbox enforces. Keep + verify. |

### PHASE 7 — MCP client
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| stdio servers | ❌ | ✅ | ✅ | **→** | JSON-RPC 2.0 stdio. |
| Remote HTTP/Streamable HTTP (SSE deprecated→keep legacy) | ❌ | ✅ | ✅ | **→** | MCP 2025-03-26 streamable HTTP; legacy SSE support. |
| Tool/resource/prompt discovery | ❌ | ✅ | ✅ | **→** | `tools/list`, `resources/list`, `prompts/list`. |
| Per-server include/exclude filters | ❌ | ✅ | ◑ | **→** | 
| Per-tool approval policies | ❌ | ✅ | ✅ | **→** | Reuse `approvals`. |
| Startup health checks + reconnection + timeouts | ❌ | ✅ | ✅ | **→** | 
| OAuth/token config via encrypted store | ❌ | ✅ | ✅ | **→** | Reuse encrypted cred store. |
| Dashboard + CLI management + audit logging | ❌ | ✅ | ✅ | **→** | 
| Never auto-install/trust arbitrary MCP servers (source review + approval) | ❌ | ◑ | ◑ | **→** | Hard requirement; explicit approval gate. |

### PHASE 8 — Media & documents
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| PDF / DOCX / XLSX / presentation extraction | ❌ | ✅ | ✅ | **→** | `pypdf`/`python-docx`/`openpyxl`/`python-pptx` optional. |
| CSV reading | ◑ | ✅ | ✅ | **→** | stdlib `csv`. |
| OCR | ❌ | ✅ | ✅ | **→** | tesseract (optional). |
| Image analysis | ✅ | ✅ | ✅ | **→** | AIBA has `vision_analyze`. |
| Audio transcription | ❌ | ✅ | ✅ | **→** | Whisper (optional). |
| Voice-note input from Telegram | ❌ | ✅ | ✅ | **→** | getFile + transcribe. |
| Text-to-speech | ❌ | ✅ | ✅ | **→** | TTS (optional; e.g. edge). |
| Image generation | ❌ | ✅ | ✅ | **→** | optional image-gen endpoint. |
| Telegram doc/photo/audio send+receive | ◑ | ✅ | ✅ | **→** | sendPhoto/Document/Voice + receive file. |
| Optional deps + clear capability diagnosis | ◑ | ✅ | ◑ | **→** | doctor reports missing optional deps. |

### PHASE 9 — Memory / skills / sessions
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Session history | ❌ | ✅ | ✅ | **→** | task store exists; add session log table. |
| Cross-session search | ◑ | ✅ | ✅ | **→** | FTS over tasks + audit; or session store. |
| User-scoped memory retrieval | ✅ | ✅ | ✅ | **→** | AIBA has per-user profile; add user-scoped memory rows. |
| Memory editing & deletion | ❌ | ✅ | ✅ | **→** | vault update/delete. |
| Memory export | ❌ | ◑ | ◑ | **→** | 
| Automatic memory suggestions (with confirmation) | ❌ | ✅ | ◑ | **→** | DreamEngine→vault suggestions requiring approval. |
| Skills auto-created from repeated/successful work | ◑ | ✅ | ✅ | **→** | SkillImprover exists; formalize creation. |
| Skill review, versioning, rollback | ◑ | ◑ | ◑ | **→** | version field exists; add review+rollback. |
| Per-user memory isolation (no cross-user leak) | ✅ | ◑ | ✅ | **→** | AIBA opaque per-user profiles already isolate. |

### PHASE 10 — Clarify tool
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Focused clarify action | ❌ | ✅ | ✅ | **→** | dedicated tool returning a structured question state. |
| 2–3 mutually exclusive options, recommended first, tradeoffs | ❌ | ◑ | ◑ | **→** | 
| Free-text alternative | ❌ | ✅ | ✅ | **→** | 
| Telegram inline buttons | ❌ | ✅ | ✅ | **→** | 
| Timeout/cancellation + resumable state | ❌ | ◑ | ◑ | **→** | 

### PHASE 11 — Capability management (CLI + dashboard)
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| `aiba tools/list/enable/disable/doctor`, `nodes`, `mcp`, `sessions`, `subagents` | ❌ | ✅ | ✅ | **→** | new CLI subcommands + argparse wiring. |
| Dashboard: available tools, enable/disable, deps, permissions, nodes, MCP, active sessions, workers, recent tool activity | ◑ | ✅ | ✅ | **→** | extend existing `/v1/*` API + dashboard (minimal, no redesign). |
| Don't redesign unrelated dashboard areas | ✅ | ✅ | ✅ | **→** | preserve existing look. |

### PHASE 12 — Testing / release
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Complete unit suite | ◑ | ✅ | ✅ | **→** | currently 60 tests (59 pass +1 platform-skip). |
| API smoke | ✅ | ✅ | ✅ | **→** | `tests/api_smoke.py` runs in CI. |
| Connector tests | ✅ | ✅ | ✅ | **→** | telegram+whatsapp tests exist. |
| Security scan / dependency audit / container scan | ✅ | ✅ | ✅ | **→** | pip-audit, bandit, secret_scan, trivy in CI. |
| Load & concurrency tests | ◑ | ◑ | ◑ | **→** | `load_test.py` exists. |
| Windows/macOS/Linux CI | ✅ | ✅ | ✅ | **→** | 9-OS/Py matrix existing. |
| Temporary Telegram bot tests | ◑ | ✅ | ✅ | **→** | optional; needs a throwaway bot token. |
| Computer-node integration on real targets | ❌ | ◑ | ✅ | **→** | requires real machines. |
| CAPABILITY_PARITY.md evidence per claim | ❌ | — | — | **→** | this plan seeds it; final populated at release. |
| Version → **1.6.0 RC** | ❌ | — | — | **→** | bump VERSION/pyproject/API/CLI to `1.6.0` at release. |

---

## 3. Engineering plan (per phase — approach, files, tests, gates)

General:
- All new modules optional-imported; `doctor` reports missing optional deps (Phase 8/9 pattern).
- Reuse existing `security` (policy/audit/approvals), `tools.registry`, `connectors`, `memory`, `skills`, `operations`.
- Every phase adds `tests/test_<phase>.py`; run locally before commit; CI gate runs the full matrix.

### Phase 1 (Telegram) — foundation, low risk, do first
- New `connectors/telegram_render.py`: plain-text renderer (strip `**`, `###`, keep lists/URLs/code, guard width).
- Rewrite `reasoning/engine.py` SYSTEM to a **mode-aware** prompt (Telegram short/natural; CLI/API structured). Keep under test.
- New `connectors/telegram_typing.py`: `sendChatAction` heartbeat thread (~4s) with start/stop, media-action mapping, non-fatal on errors.
- `telegram.py`: integrate renderer + heartbeat; add inline-keyboard helper + `answerCallbackQuery`; correct streaming approach (heartbeat default; edit-draft fallback only where supported).
- Tests: formatting conversion (no raw `**`), heartbeat start/stop, heartbeat-failure-doesn't-fail-task, media-action accuracy, fallback, no-CoT leak.

### Phase 2 (Visible reasoning)
- New `reasoning/protocol.py`: event model `plan|clarification|progress|tool_started|tool_completed|delegated|waiting_for_approval|result|warning|failure`.
- `engine.py` emits events to an `EventSink`; loop builds a single transient message (editMessageText) on Telegram; full detail → AuditLog.
- Safe-summary filter: never forward raw tool args/secrets/CoT; only human-readable summaries.
- Tests: event sequence, single-message (no spam), no raw CoT/secrets in user-facing summary, audit still has detail.

### Phase 3 (Subagents)
- New `agent/subagents.py`: `Supervisor` + `Worker`. Worker = isolated `AgentLoop`-style engine on its own model call, own prompt/task context, optional temp workspace, own budget. Config: `AIBA_MAX_WORKERS` (default 3), `AIBA_MAX_DELEGATION_DEPTH`, budget knobs. Cancellation via shared stop flag. Parallel via `ThreadPoolExecutor`.
- `registry` gains `delegate`/`spawn_subagent` tool(s) wired to Supervisor.
- Role templates (researcher/builder/reviewer) as prompt presets.
- Supervisor verifies consequential tool results; all audit via existing AuditLog.
- Tests: **real separate model calls** (mock provider records distinct calls), parallel execution, budgets enforced, recursion capped, secrets not passed, failure/partial-result handling.

### Phase 4 (Web + browser)
- New `tools/web_search.py`: provider abstraction + `web_search` + `web_extract` (configurable provider; normalized result: title/url/snippet/date/source).
- Extend `tools/browser.py` → `tools/web.py`: persistent session (on-disk storage), navigation, snapshot/accessibility, vision fallback (reuse vision_analyze), downloads dir, timeout/cancel, **SSRF guard (keep `_public_url`, now tested)**, domain allow/deny from policy, approval for consequential actions, cookie/credential redaction.
- Tests: SSRF blocks localhost/private, approval enforced, domain lists, download flow, no-credential-leak.

### Phase 5 (Computer + Node) — largest, split into two steps
- 5a (local): expand `computer/controller.py` to full toolset (screen_snapshot, accessibility_tree, list/focus windows, click/double/right/type/keypress/hotkey/scroll/drag/move_pointer, clipboard read/write, wait_for_element, locate_text). Keep disabled-by-default; per-tool perms; **emergency stop**, **max-action count**, screen/clipboard privacy + secret-field detection; never read password/credential fields; full audit. `doctor` tells user when no GUI session.
- Tests: disabled-by-default, per-tool perm, e-stop, max-actions, secret-field detection, audit.
- 5b (Node): new `node/` — **paired AIBA Node** (Win/macOS/Linux). Mutual auth (short-lived pairing code → signed device identity), revocable identity, encrypted WebSocket or mutually-authenticated HTTPS, Tailscale/local-network support, **no unauthenticated public endpoint**, heartbeat + capability discovery, user-visible indicator, local kill switch. Executes screen/accessibility actions on the paired computer.
- Tests: pairing auth, revocation, no-unauth-endpoint, heartbeat; node integration marked `manual/CI-optional` (needs real targets).

### Phase 6 (Terminal/file/process)
- `tools/process.py`: process start/list/poll/logs/wait/input/terminate + PTY (`pty`), persistent cwd.
- New `agent/sandbox` backends: add `ssh` backend (paramiko optional; doctor-gated).
- `tools/file.py`: move/copy/patch/search/content-search/tree/archive-create/extract/checksum.
- Enforce: mutations policy-reviewed; destructive (delete/archive-extract/overwrite) approval.
- Tests: lifecycle, PTY I/O, persistent cwd, archive round-trip, checksum, approval on destructive, sandbox-escape prevention.

### Phase 7 (MCP)
- New `mcp/` package: `client.py` (JSON-RPC 2.0 stdio + streamable HTTP + legacy SSE), `server_manager.py`, `discovery.py` (tools/resources/prompts), `security.py` (include/exclude filters, per-tool approval, **no auto-trust: source-review + explicit approval required**), `audit.py` (MCP calls logged).
- Config in `config/permissions.json`-style + encrypted token store (reuse credential crypto) for OAuth/token.
- CLI: `aiba mcp list/add/remove/status`; dashboard sections; startup health check + reconnection + timeouts.
- Tests: stdio discovery+filtering, streamable-HTTP (mock server), approval enforcement, no-trust-by-default, reconnection, timeout, audit.

### Phase 8 (Media/docs)
- New `media/` package: `extract.py` (PDF/DOCX/XLSX/PPTX/CSV), `ocr.py`, `audio.py` (transcribe), `speech.py` (TTS), `imagegen.py`. All optional imports; `doctor` reports availability.
- Extend Telegram: receive file (voice/photo/doc), `sendPhoto/Document/Voice`.
- Tests: each extractor on small fixtures, optional-dep diagnosis, voice-note input mapping.

### Phase 9 (Memory/skills/sessions)
- `sessions` storage: new `agent/sessions.py` (SQLite session log + FTS search).
- Memory: vault edit/delete/export tools; user-scoped memory rows (opaque profile isolation retained); auto-suggestions requiring confirmation (DreamEngine→proposal→approval→commit).
- Skills: formalize auto-creation from repeated success; versioning + review + rollback.
- Tests: session history + search, memory edit/delete/export, user-scope isolation (no cross-user leak), suggestion-confirmation, skill version/rollback.

### Phase 10 (Clarify)
- New `tools/clarify.py`: first-class action (one question, 2–3 exclusive options, recommended-first, tradeoff each, free-text alt, timeout/cancel, resumable state). Telegram inline buttons via Phase 1 helper; numbered fallback.
- Loop integration: when engine needs input, emits `clarification` + suspends with a resumable state; resumed on answer.
- Tests: option shape/order, free-text, timeout/cancel, resumable after restart, inline-button mapping.

### Phase 11 (Capability mgmt)
- `main.py` argparse: `tools`, `nodes`, `mcp`, `sessions`, `subagents` subcommands with list/enable/disable/doctor.
- `aiba tools` reads registry + permissions; `aiba nodes` lists paired nodes; `aiba mcp`; `aiba sessions`; `aiba subagents`.
- Dashboard: minimal additions to existing `/v1/*` + dashboard components showing tool states, deps, perms, nodes, MCP servers, active sessions, workers, recent tool activity. No redesign of unrelated areas.
- Tests: CLI parse/list/enable/disable; dashboard data endpoints.

### Phase 12 (Release)
- Bump version to **1.6.0** everywhere (VERSION, pyproject, API, CLI, dashboard labels).
- Populate `CAPABILITY_PARITY.md` with the matrix **+ test evidence for every `implemented` claim** (file + test name + result).
- Gates: full unit suite + api_smoke + connector tests + security scan + pip-audit + trivy container + bandit + secret_scan + load/concurrency tests + full CI matrix (Win/macOS/Linux × 3.11/3.12/3.13). Optional: temporary Telegram bot tests; computer-node integration on real targets (manual where machines unavailable).
- Merge policy: **no auto-merge**; open PR, report matrix/files/tests/commit/PR URL.

---

## 4. Realistic timeline & PR milestones

Total effort is **large** (realistically multiple focused sessions). Recommend **incremental PRs**, each green on the existing CI gate before the next:

| Milestone | Scope | Estimated effort | Gate |
|---|---|---|---|
| **M1** | Branch + planning docs (this) + version pin as groundwork | ~done | local tests still green |
| **PR-1** | Phase 1 (Telegram UX) + Phase 2 (visible reasoning) + Phase 10 (clarify) | 1 focused session | unit+connector+CI |
| **PR-2** | Phase 4 (web_search/web_extract + browser security/session) | 1-2 sessions | +SSRF tests |
| **PR-3** | Phase 6 (terminal/file/process parity) + Phase 8 (media/docs) | 1-2 sessions | optional-dep doctor |
| **PR-4** | Phase 3 (real subagents) | 1-2 sessions (hard) | parallel+budget tests |
| **PR-5** | Phase 7 (MCP client) | 2 sessions (hard) | stdio+http tests |
| **PR-6** | Phase 9 (sessions/memory/skills parity) | 1-2 sessions | isolation tests |
| **PR-7** | Phase 5 (computer control + paired node) | 2-3 sessions (largest) | disabled-by-default + node tests |
| **PR-8** | Phase 11 (CLI + dashboard) + Phase 12 (release, v1.6.0-RC) | 1-2 sessions | full matrix + CAPABILITY_PARITY.md |

**Estimate: 10–16 focused sessions to complete all 12 phases to the "implementation + tests" bar.** Tightened/shrunk if you want to de-scope (e.g., defer paired-node 5b, defer optional media, or defer MCP).

**Recommended cut for THIS next step:** Start with **PR-1** (Telegram UX + visible reasoning + clarify) — it's the highest user-visible value, fully self-contained, directly testable, and exercises the exact interfaces (connector, engine, registry) the later phases build on. It also unlocks inline-button approval/clarify that the follow-on phases rely on.

---

## 5. Risks & constraints
- **Simulated `delegate` must be replaced carefully** — it's referenced in the SYSTEM prompt and in `engine.py`; changing it must not break existing tests.
- **Telegram has no public `sendMessageDraft`** — I will implement typing-heartbeat as the safe default and an optional edit-progress path, and correct that in the brief rather than fake a non-existent API.
- **Public Bot API `sendChatAction` lasts ≤5s** → refresh ~4s is correct; failures must not abort the task.
- **Paired-node (5b) and real-machine computer tests** can't run inside this Linux VPS's CI; those tests will be clearly marked `manual/CI-optional` and the matrix will say so honestly.
- **No parity claim without implementation + passing test** — items stay `not-started` until proven.
- Live v1.5 install **not modified/restarted** throughout.

---

## 6. Files changed so far (this plan)
- `capability_matrix.md`? → this document committed as **`docs/PLAN_v1.6_capability_parity.md`**.
- Branch `feat/aiba-v1.6-capability-parity` created off `76da680`. No code changes.

# AIBA v1.6 — Capability Parity: Engineering Plan + Capability Matrix + Timeline

**Status:** IN PROGRESS — Phases 1, 2, 3, 4, 4b, 5, 6, 8, 10, 11 implemented and tested. Phase 9 sessions/memory/skills substantially implemented (session store+search, vault edit/delete/list/export, skill versioning/rollback, model tools in parity) — a few parity matrix rows (auto-suggestion confirmation, per-user vault-row isolation, skill-review formalization) remain outstanding. Phase 8 media extraction core implemented (PDF/DOCX/XLSX/PPTX/CSV/txt/markdown + image metadata, `media_extract` tool, honest per-format diagnostics; OCR/ASR/TTS/imagegen probe-only). Phase 11 capability-management CLI + dashboard data endpoint implemented (see §"Implementation Status Log").
**Branch:** `feat/aiba-v1.6-capability-parity` (07 commits + growing)
**Live install:** v1.5.0 untouched. Not restarted, not modified.
**Date:** 2026-09-02

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

### PHASE 3 — Real subagents ✅
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Supervisor/Worker real separate model calls | ❌ | ✅ | ✅ | ✅ | `agent/subagents.py` pool issues real per-worker provider calls over the shared router |
| Isolated context + parallel independent tasks | ❌ | ✅ | ✅ | ✅ | `SubagentPool` (ThreadPoolExecutor) + isolated per-worker objective/toolset; barrier-proven overlap test |
| Roles researcher/builder/reviewer | ❌ | ◑ | ◑ | ◑ | single generic worker prompt; role templates future |
| Max workers (default 3) | ❌ | ✅ | ◑ | ✅ | global `global_concurrency` + per-parent `per_parent` caps (settings-default) |
| Token/time/cost budgets | ❌ | ◑ | ◑ | ✅ | step cap + wall-clock timeout hard; **best-effort cost cap** when provider reports usage |
| Cancellation & timeout | ❌ | ✅ | ◑ | ✅ | cooperative cancel at loop boundaries + queued-cancel; wall-clock timeout |
| Recursion depth limit | ❌ | ✅ | ✅ | ✅ | recursion depth zero: no delegate/spawn/clarify tool on worker surface |
| No secret access unless granted | ❌ | ✅ | ✅ | ✅ | tool-narrowing + explicit consent; audit redacts objectives/secrets/transcripts |
| Supervisor verifies consequential results | ◑ | ◑ | ◑ | ◑ | worker instructed to verify consequential results; no hard gate yet |
| Full audit trail + failure recovery | ◑ | ✅ | ✅ | ✅ | SQLite store: interrupts→timed_out recovery; audit events; failure isolation |

### PHASE 4 — Web + browser  *(4b = opt-in browser session; ✅ implemented)*
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| `web_search` (configurable provider; title/url/snippet/date/source) | ❌ | ✅ | ✅ | **→** | Provider abstraction (duckduckgo/brave/tavily/searx) + normalized result shape. |
| `web_extract` / page extraction | ❌ | ✅ | ✅ | **→** | readability/Playwright text+markdown extraction. |
| Browser persistent sessions | ❌ | ✅ | ✅ | **→** | ✅ 4b `tools/browser_session.py` — persistent opt-in Playwright session. |
| Text/accessibility snapshot | ❌ | ◑ | ✅ | **→** | ✅ 4b `browser_page_text` + `browser_state` (URL/title). |
| Vision fallback | ◑ | ✅ | ✅ | **→** | Reuse `vision_analyze`. |
| Download management | ❌ | ◑ | ✅ | **→** | ✅ 4b `browser_download` → saved into workspace only. |
| Timeouts & cancellation | ◑ | ✅ | ✅ | **→** | ✅ 4b bounded timeouts (`timeout_ms`, default 20s). |
| SSRF protection (block private/localhost by default) | ✅ | ✅ | ✅ | **→** | ✅ 4b — shared `security.urlguard` policy (identical to computer control). |
| Domain allow/deny lists | ❌ | ✅ | ◑ | **→** | Policy lists. |
| Approval before login/submit/purchase/delete/consequential | ◑ | ✅ | ✅ | **→** | ✅ 4b — mutations `requires_approval` + sensitive-page gate. |
| Don't leak cookies/credentials to model | ◑ | ✅ | ✅ | **→** | ✅ 4b — secrets refused by default + never logged. |

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

### PHASE 8 — Media & documents ◑ *(extraction core implemented; OCR/ASR/TTS/imagegen honest probes only)*
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| PDF / DOCX / XLSX / presentation extraction | ❌ | ✅ | ✅ | ✅ | `media/extract.py` — genuine lazy-optional parsing via pypdf/python-docx/openpyxl/python-pptx under the `[media]` extra; per-format fixture-tested. |
| CSV reading | ◑ | ✅ | ✅ | ✅ | stdlib `csv` in `media/extract.py`; formula cells returned as literal text, never evaluated. |
| OCR | ❌ | ✅ | ✅ | ❌ | Honest capability probe only — not claimed functional until a backend + tests exist. |
| Image analysis | ✅ | ✅ | ✅ | ✅ | AIBA `vision_analyze` + `media/extract.py` image-metadata (PIL, dims/format/mode). |
| Audio transcription | ❌ | ✅ | ✅ | ❌ | Honest capability probe only. |
| Voice-note input from Telegram | ❌ | ✅ | ✅ | ❌ | Not in this phase. |
| Text-to-speech | ❌ | ✅ | ✅ | ❌ | Honest capability probe only. |
| Image generation | ❌ | ✅ | ✅ | ❌ | Honest capability probe only. |
| Telegram doc/photo/audio send+receive | ◑ | ✅ | ✅ | ◑ | Not in this phase. |
| Optional deps + clear capability diagnosis | ◑ | ✅ | ◑ | ✅ | In-tool "install optional support" diagnostics + `media/capabilities.py` `media_capability_probe()` surfacing per-format readiness. |

### PHASE 9 — Memory / skills / sessions ◑ *(substantially implemented; see status log)*
| Capability | A | H | O | T | Evidence |
|---|---|---|---|---|---|
| Session history | ❌ | ✅ | ✅ | ✅ | `agent/sessions.py` session log table + AgentLoop per-turn auto-log (`kind='turn'`, per-user, closed on completion). |
| Cross-session search | ◑ | ✅ | ✅ | ✅ | FTS5 over session store, user-scoped `session_search` tool + store `search`. |
| User-scoped memory retrieval | ✅ | ✅ | ✅ | ◑ | vault wide (not per-user-row yet); `list`/`search` by category. Per-user vault rows outstanding. |
| Memory editing & deletion | ❌ | ✅ | ✅ | ✅ | vault `update`/`remove` + `update_memory`/`delete_memory` tools (destructive gated). |
| Memory export | ❌ | ◑ | ◑ | ✅ | vault `export(category)` + `export_memories` tool → sandbox-confined markdown. |
| Automatic memory suggestions (with confirmation) | ❌ | ✅ | ◑ | **→** | DreamEngine→vault suggestion w/ approval not yet implemented. Outstanding. |
| Skills auto-created from repeated/successful work | ◑ | ✅ | ✅ | ◑ | SkillImprover proposal path (unchanged this phase); formalization outstanding. |
| Skill review, versioning, rollback | ◑ | ◑ | ◑ | ◑ | versioning + rollback added (revisions/<ver>.json, restore); review workflow outstanding. |
| Per-user memory isolation (no cross-user leak) | ✅ | ◑ | ✅ | ◑ | sessions user-scoped (tested); vault rows not user-tagged yet. Outstanding. |

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

### Phase 4b (Opt-in automated browser session)
- New `security/urlguard.py`: extract the SSRF/safe-URL policy out of `computer/controller.py` into the single authoritative module, and make computer control delegate to it — so browser navigation and computer control can never drift apart in their protections.
- New `tools/browser_session.py`: a persistent, opt-in browser surface on Playwright behind an injectable `Driver` (the real driver opens a **headless** Chromium; automated tests inject fakes — never launch a real browser on CI). Capability family:
  - read-only: `browser_open` (SSRF-guarded to public http(s)), `browser_state`, `browser_page_text`, `browser_screenshot`, `browser_wait`, `browser_status`
  - mutations (approval required): `browser_scroll`, `browser_click`, `browser_type`, `browser_select`, `browser_submit`, `browser_download`, `browser_upload`
- Disabled by default (feature flag `AIBA_BROWSER_ENABLED` + manifest `default_enabled:false` + `permissions.json` all `enabled:false`). Mutations additionally `requires_approval` and refuse on sensitive (auth/payment/checkout/account/purchase) pages unless the owner opts into `sensitive_actions`; secret-bearing typed text is refused by default and never logged (length + redacted flag only). Downloads land only in the approved workspace (basename sanitised); uploads read only files already in the workspace; all navigation and every subresource request is routed through the shared URL guard (forbidden targets aborted); bounded timeouts; full audit.
- Keep `browser_fetch` registered for backwards compatibility alongside the new family.
- Tests: same-policy-as-computer-control, blocked/allowed target lists, disabled-by-default registration/denial at the AgentLoop layer (13 tools registered, hidden from model schemas, clear denial on direct execute, feature flag AND permissions each independently block), read/mutation separation, sensitive-page refusal, secret handling (refused by default + never logged; allowed-then-still-redacted when opted in), upload/download workspace containment.

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
- New `media/` package: `extract.py` (PDF/DOCX/XLSX/PPTX/CSV via lazy-optional pypdf/python-docx/openpyxl/python-pptx under the `[media]` extra; plus txt/markdown and image metadata via PIL), `capabilities.py` (honest per-format availability probes). OCR/ASR/TTS/imagegen are surfaced ONLY as capability probes that report not-available — no hollow placeholders claiming functionality without a backend + tests. `doctor`/in-tool diagnostics report missing optional deps.
- Read-only security posture: workspace-confined reads (Sandbox policy), bounded size/page/sheet/slide/row/return limits, content always treated as untrusted data (never executed; spreadsheet formulas/links/macros never evaluated or run), originals never modified. Exports stay behind the existing approval-gated `write_file` space — the media surface writes nothing.
- Optional `[media]` deps folded into the `[all]` extra and requirements.txt (supply-chain audited); base `[api]` install stays lightweight and unchanged.
- A single model tool, `media_extract`, registered through manifest/permissions/feature-flag (`AIBA_MEDIA_ENABLED`, default on)/diagnostics/audit, read-only (no approval).
- Not in this phase: Telegram doc/photo/audio send+receive, OCR, ASR, TTS, image generation (all honest-probe-only or deferred).
- Tests: each extractor on small fixtures, boundary/limits, path-confinement, formula-not-evaluated, NUL handling, optional-dep diagnosis, loop registration + feature-flag gating.

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

---

## 7. Implementation Status Log (append-only, updated as phases land)

Ground rule upheld: a phase is only marked **implemented** once its code is committed
**and** passing tests exist on the v1.6 branch. Live v1.5 install untouched throughout.

| Phase | Status | What actually shipped | Tests |
|---|---|---|---|
| **1 — Telegram UX** | ✅ Implemented | `connectors/ux/render.py` (markdown renderer, smart chunker, inline keyboards, typing-heartbeat); `connectors/telegram.py` typing heartbeat start/stop per task, `send_keyboard`/`send_payload`, callback-query routing + `on_callback` hook, `getUpdates` now accepts `callback_query` | `tests/test_ux.py` (16) |
| **2 — Visible reasoning** | ✅ Implemented | `reasoning/protocol.py` — typed/versioned `aiba.reasoning` event envelope, 5 sanitised kinds (plan/tool/result/final/error), secret redaction + output truncation (no CoT leak); wired into `reasoning/engine.py` + `agent/loop.py` → emits to the existing `EventBus` on every task | `tests/test_protocol.py` (10) |
| **3 — Real subagents** | ✅ Implemented (internal subagents, disabled by default) | `agent/subagents.py` (worker engine: SQLite-backed `SubagentStore` with thread-safe per-call connections/transactions/bounded queries/recovery; `SubagentPool` bounded `ThreadPoolExecutor` with global + per-parent concurrency; `_worker_loop` with step cap, wall-clock timeout and **best-effort cost cap** — binds only when the provider reports per-call usage — plus permission-narrowing, audit redaction and secrets-free persistence) + `agent/subagent_manager.py` (facade: `delegate`/`run_many`/`cancel`/`status`/`list_for_parent`/`synthesize`; `_collect_terminated` returns only terminal-state rows). Wired into `agent/loop.py`: `AIBA_SUBAGENTS_ENABLED` runtime flag (default off), `SubagentManager` construction, safe/idempotent `close()`, and a single model-visible **`delegate_task`** tool — **disabled by default**, gated by the feature flag AND `permissions.json` (`enabled:false`, `requires_approval:true`). AIBA remains the only user-facing assistant; subagents are bounded internal workers (tool-narrowed to the parent's explicit allowed list, run through the shared policy, cannot recurse — recursion depth zero, admin/spawn/clarify surfaces never offered, browser/desktop/process/shell capabilities withheld unless separately enabled AND explicitly consented). Only a concise structured synthesis returns to the planner; no raw prompts/transcripts/CoT. | `tests/test_subagents.py` (31) + `tests/test_subagents_loop.py` (8) |
| **4 — Web + browser** | ✅ Implemented (web tools) | `tools/web.py` — `web_search` (DuckDuckGo no-API-key backend, fixed allowlisted host → no SSRF from query) + `web_extract` (up to 5 pages, reuses `_public_url` guard → blocks private/loopback/credential URLs); `AIBA_WEB_ENABLED` setting; registered in loop. Browser *session* model shipped as **Phase 4b** below | `tests/test_web.py` (13) |
| **4b — Opt-in browser automation** | ✅ Implemented | `security/urlguard.py` — single shared SSRF/safe-URL policy (schemes: only http(s); blocks loopback/link-local/RFC-1918 private/CGNAT/multicast/reserved + numeric/hex/octal/flat-int IPv4 aliases + IPv6 loopback/link-local/ULA + `localhost`/`*.localhost`/`metadata.google.internal`/`*.local`), extracted from `computer/controller.py` which now delegates to it so **browser navigation and computer control share one policy**. `tools/browser_session.py` — persistent opt-in Playwright session behind injectable `Driver` (real headless Chromium; subresource requests to forbidden targets aborted via `page.route`): read-only family (`browser_open`/`_state`/`_page_text`/`_screenshot`/`_wait`/`_status`) is separated from site-altering mutations (`_scroll`/`_click`/`_type`/`_select`/`_submit`/`_download`/`_upload`). Defaults: disabled (feature flag `AIBA_BROWSER_ENABLED` + manifest `default_enabled:false` + `permissions.json` all `enabled:false`); mutations `requires_approval:true`; sensitive-page guard refuses mutations on auth/payment/checkout/account pages unless owner opts `sensitive_actions`; secret-like typed text refused by default and **never logged** (length only, `redacted` flag); downloads saved into workspace with basename sanitisation; uploads read only files already inside the workspace; bounded timeouts; full audit. `browser_fetch` kept for backward compatibility. | `tests/test_browser_security.py` (19) + `tests/test_capability_integration.py` Phase4b wiring (5) |
| **5 — Computer control + nodes** | ✅ Implemented (5a local gate+node; 5b remote-node manual) | `computer/node.py` — `ComputerNodeGate` (pair-only-digest, enable/disable, emergency stop persisted across reload, revoke, max-action budget, clipboard/process opt-in), `computer/controller.py` — full opt-in safe toolset (screen/move/click/drag/scroll/key/hotkey/type/open_url/clipboard/process) behind the gate; argv-only dispatch (no shell strings), SSRF-safe `_forbidden_open_target` (loopback/RFC-1918/metadata/aliases/non-http), clipboard returns length marker not content, secret-typed text never logged; `computer/__init__.py` `make_computer(settings, audit)`; 13 `desktop_*` tools registered in loop, all disabled by default (feature-flag + `permissions.json` master gate + gate refuses until paired+enabled); CLI `--computer-pair/status/enable/disable/stop/reset-budget`. Pairing of a real remote node (5b) remains manual/CI-optional — needs a real target machine. | `tests/test_computer.py` (22) + `tests/test_capability_integration.py` Phase5 wiring (4) |
| **6 — Term/file/process parity** | ✅ Implemented (file additions) | `tools/sandbox.py` — `patch_file` (atomic find-and-replace + diff, block ambiguous/missing), `archive` (zip/tar/gztar, written inside workspace), `extract_archive` (zip/tar, **zip-slip blocked**); registered in loop. Terminal/process lifecycle (SSH, process mgmt) still future | `tests/test_sandbox.py` (10) |
| **7 — MCP client** | ✅ Implemented (optional, disabled-by-default) | `mcp_client/` package — real MCP **client** only (never a server) built on the official `mcp` SDK v2 (pinned `>=2.1,<3`, optional `[mcp]` extra folded into `[all]`; base `[api]`/container unchanged). Exposure is ONE static, manifest-backed AIBA tool **`mcp_call(server_id, tool, arguments)`** — no dynamic per-server AIBA tool names (they can't be policy-gated), so per-server remote-tool allow/deny + approval live in the operator-owned `config/mcp_servers.json`, never on the model surface. `mcp_client/config.py` — validated, no-secrets config model (https-only + `security.urlguard.forbidden_open_target` for remote urls; stdio `command`+`argv` only, shell-metachar/`--` rejected via `policy.assert_safe_argv`; `working_dir` confined to the config tree; env **by allowlisted NAME only**, secret-looking names refused). `mcp_client/client.py` `MCPClientController.execute()` — fail-closed order: master-switch (settings/`AIBA_MCP_ENABLED`) → SDK-present → server/tool name validation → config valid → server exists → server enabled → per-tool allowlist → operator approval (**same `ApprovalManager` as AIBA's own dangerous tools**) → remote-transport gated by **`AIBA_MCP_REMOTE`** (off by default); then sync→async bridge on a dedicated fresh event loop with startup/call timeouts + output-byte cap + process-group teardown (SDK). Redirect-following disabled for remote (SSRF) via a custom non-following httpx client. Every argument scrubbed before audit. Disabled by default on **three independent axes** (settings flag + `permissions.json enabled:false` + manifest feature-flag off + no enabled server in config). Loop wiring in place; manifest/permissions grown **55→56 in lockstep** (risk `process_execution`, approval-gated, `optional_dependency:python:mcp`). `config/mcp_servers.example.json` ships inert (no real creds/urls). | `tests/test_mcp.py` (18) — config validation, scrubber, allowlist, fail-closed execute ordering, manifest/permissions consistency, real-SDK stdio spawn smoke (`/bin/false`) |
| **8 — Media/document processing** | ◑ Extraction core delivered | `media/extract.py` — genuine read-only PDF (`pypdf`)/DOCX (`python-docx`)/XLSX (`openpyxl`)/PPTX (`python-pptx`)/CSV (stdlib)/txt+markdown + image-metadata (PIL) extraction, workspace-confined via the Sandbox policy, bounded (size/page/sheet/slide/row/return limits), content treated as untrusted data (formulas never evaluated, links/macros never run, originals never written). `media/capabilities.py` honest per-format probes. Optional `[media]` deps folded into `[all]` + requirements.txt; base `[api]` unchanged. Single `media_extract` tool registered through manifest/permissions/feature-flag (`AIBA_MEDIA_ENABLED`, default on)/diagnostics/audit, read-only no-approval. Config manifest+permissions **54→55 lockstep**. OCR/ASR/TTS/imagegen remain honest probe-only (not claimed functional without backend+tests); Telegram media send/receive deferred. | `tests/test_phase8_media.py` (16) |
| **9 — Memory/skills/sessions** | ◑ Substantially delivered (see note) | `agent/sessions.py` — `SessionStore` (SQLite + FTS5, external-content triggers kept in sync; per-user rows; `open_session`/`append`/`close_session`/`delete`/`get`/`list_by_user`/`search`/`recover_interrupted`). `memory/vault.py` — added `get`/`update`/`remove`/`list`/`export` (FTS stays in sync via triggers). `skills` SkillManager — `revisions()`/`rollback()` snapshot-archive versioning (`revisions/<ver>.json`). `agent/loop.py` — SessionStore construction + per-turn session auto-log in `_handle` (best-effort, concise sanitised title/summary, closed on completion, no deliberation stored); 6 new model tools registered: `update_memory`, `delete_memory`, `list_memories`, `export_memories`, `session_search`, `session_history`. `config/capability_manifest.json` + `config/permissions.json` both grown **48→54 in lockstep** (destructive/`local_mutation` approval-gated; read-only no-approval). **Open rows for full phase completion:** per-user memory-*row* isolation inside the vault (sessions are user-scoped today), automatic memory suggestions requiring confirmation (DreamEngine→approval), skill auto-creation formalization + review workflow. Those are honestly recorded as outstanding rather than overclaimed. | `tests/test_sessions.py` (7) + `tests/test_memory_edit.py` (6) + `tests/test_skills_versioning.py` (5) + `tests/test_phase9_loop.py` (8) |
| **10 — Clarify tool** | ✅ Implemented | `tools/clarify.py` — focused questions with choices + tradeoffs, blocking (`answer_source`) and async **pending** flow (`ClarificationRequested`, `on_pending` → `clarify.pending` bus event); registered `clarify` tool; Telegram inline-button answering via `clar:<qid>:<choice>` callbacks + `connect_clarify()` | `tests/test_clarify.py` (11) |
| **11 — CLI + dashboard** | ✅ Implemented | `diagnostics/capability_state.py` — single canonical collector (tools_report/flag_state/nodes_state/sessions_state/subagents_state/mcp_state/recent_activity/snapshot + pure atomic `set_tool_permission`/`tool_now_enabled` permission gate, preserves curated key order → minimal 1-line diff). `cli/capability.py` — argparse subparsers + handlers: `aiba tools [list|enabled|doctor|enable <t>|disable <t>]`, `nodes status`, `mcp status[|add]`, `sessions`, `subagents status` (JSON default, `--human` optional; AgentLoop built with `start_worker=False`). `main.py` early-routing: argv[0] in {tools,nodes,mcp,sessions,subagents} → capability CLI before the flat parser; legacy flags untouched. `api/server.py` GET `/v1/capabilities` (auth-gated). `dashboard/index.html` minimal Capabilities card + `loadCapabilities()` (read-only). MCP honestly reports unavailable until Phase 7. | `tests/test_phase11_cli.py` (12) — order-preserving writer + handlers + snapshot + dashboard endpoint |
| **12 — Test + release** | 🔶 Partial | Full local suite **320 tests pass** (1 platform skip) across test modules incl. computer/node-gate, browser-session security, internal subagents, Phase9 sessions/memory/skills modules + AgentLoop wiring, Phase8 media extraction + loop gating, Phase11 capability CLI/dashboard, and Phase7 MCP `mcp_call` client; `scripts/certify_install.py` certified:true (321 tests OK); CI matrix/version bump still pending | `tests/*` |

**Suite report (this branch):** `unittest` → **320 tests, OK (1 platform skip)**, covering connectors, ux, protocol,
clarify, sandbox, web, computer/node-gate, **browser-session security**, **internal subagents (store/pool/manager 31 + AgentLoop wiring 8)**,
**Phase 9 (sessions store 7, memory edit 6, skills versioning 5, phase9 AgentLoop wiring 8)**, **Phase 8 media (extraction + boundary/confinement + loop gating 16)**, **Phase 11 capability CLI/dashboard (order-preserving writer, handlers, snapshot, endpoint 13)**, **Phase 7 MCP client (config validation, scrubber, allowlist, fail-closed execute, manifest/permissions consistency, real-SDK stdio spawn smoke 18)**, capability wiring (incl. Phase3/Phase4b/Phase5),
personality, providers, onboarding, and v02–v13 regressions.

**Remaining to reach full 12-phase bar:** with Phase 7 (MCP client) now delivered as an optional, disabled-by-default
`mcp_call` gateway, all 12 phases are at least substantially implemented. Phase 9 is **substantially delivered** — the sessions store/search, vault
edit/delete/list/export and skill versioning/rollback rows are implemented and tested; the remaining Phase 9 rows
(per-user vault-row isolation, automatic memory suggestions with confirmation, skill auto-creation/review
formalization) are deliberately left open and honest rather than overclaimed. Phase 8's **extraction core** (PDF/DOCX/
XLSX/PPTX/CSV/txt/markdown + image metadata, `media_extract` tool, config 54→55 in parity) is implemented and tested;
OCR/ASR/TTS/imagegen and Telegram media send+receive remain honest probe-only / deferred (not claimed functional
without a real backend + tests, per scope). Phase 7's **remote (http) MCP transport** is engineered and gated behind the
off-by-default `AIBA_MCP_REMOTE` flag + https/SSRF policy but is not exercised against a real third-party remote
server in CI (only stdio is smoke-tested end-to-end); no arbitrary remote server is auto-trusted. Phase 5b's real
remote-node pairing, container/CI evidence and the
version bump to v1.6.0-RC remain for the release milestone. Per the ground rule a phase is only marked fully
**implemented** once its matrix rows are done with passing tests — nothing claimed beyond that.

**Commits landed (chronological):** `921421c` plan doc → `d7ce497` P1 → `6eb8ad1` P2 →
`21afe9a` P10 → `6ee0608` P10b → `163ed22` P6 → `3dd9db8` P4 → `00ef452` CI/capabilities determinism → `061c6e2` P5 → `f8660c7` P4b (opt-in browser session + SSRF guard) → `c85fa9e` P3 (internal subagents, CI-green 12/12) → `6f0c58a` P9a (SessionStore + AgentLoop session auto-log) → `481cd7c` P9b (vault memory maintenance + skill versioning/rollback) → `365acf5` P9c (session/memory model tools + AgentLoop session auto-log, manifest/permissions 48→54, CI-green 12/12) → `c7c762c` P8 (read-only media/document extraction core, manifest/permissions 54→55, CI-green 12/12) → `194f355` P11 (capability-management CLI + dashboard data endpoint: `aiba tools/nodes/mcp/sessions/subagents`, order-preserving permission writer, `GET /v1/capabilities`, 13 tests, local gate 302 pass/1 skip) → `86a60b8` P7 (optional MCP client gateway `mcp_call`, manifest/permissions 55→56, 18 tests, local gate 320 pass/1 skip, certify `certified:true`) → `6ab7644` P7 doc follow-up → `8129f1b` P7 CI-fix (force `sdk_available` in MCP policy-gate tests so they are deterministic without the optional `mcp` SDK in the base CI env; **all 12 CI jobs green** on GitHub run `33809984662`). See §8 below.

---

## §8 — Release milestone checkpoint (2026-09-03, authoritative live-state + completion checklist)

This section is the persistent checkpoint for the **v1.6.0-rc.1 release task**. It was verified
firsthand this session (see inline evidence) and MUST be re-read at the start of every future
session on this branch. Resume from the checklist; do not re-derive from conversation history.

### 8.1 Verified live installation state (current v1.5.0 — DO NOT modify/restart until §6 cutover)
- **systemd**: USER unit `~/.config/systemd/user/aiba.service` (enabled; `default.target.wants`).
  - `ExecStart=/home/jay/aiba-agent/.venv/bin/python aiba_launcher.py --serve`
  - `WorkingDirectory=/home/jay/aiba-agent`; `Type=simple`; `Restart=on-failure`; restart-sec 5;
    `NoNewPrivileges=true`; NOT network-exposed (`127.0.0.1`, no TCPListen for remote).
- **Live process**: Main PID 2465933, running since **2026-09-01 05:07:53 EDT** (2+ days), under
  `user@1000.service / app.slice / aiba.service`. On-disk code = whatever was checked out at launch;
  module image is resident in memory (python import-at-startup). **Restart would load the CURRENT
  checkout**, which is the v1.6 feature branch — so DO NOT restart until the release tree is in place.
- **Health (verified 2026-09-03)**: `GET /health` → `{"ok":true,"version":"1.5.0","provider":"local",
  "sandbox":"local","managed_models":1}`; `GET /ready` → `{"ready":true,...}` all migrations current
  (providers/jobs/tasks/schedules …). Config/health env confirmed via `/proc/2465933/environ`:
  `AIBA_REQUIRE_APPROVAL=true`, `AIBA_API_HOST=127.0.0.1`, `AIBA_API_PORT=8765`, provider=local,
  worker+telegram enabled, `AIBA_TELEGRAM_ALLOWED_USERS=8352755584`. Credentials/keys NOT stored here.
- **Data + paths** (all defaults under `data_dir=<root>/agent_system`, overridable via `AIBA_DATA_DIR`):
  `agent_system/` = aiba.db, tasks.db, jobs.db, schedules.db, auth.db, providers.db (verified Feb layout),
  plus (newer) sessions.db, subagents.db, computer_node.json, profiles/ (0600; 2 files for hashed user),
  backups/, logs/. `.env` at repo root holds operator secrets (0600, gitignored). `VERSION`/pyproject/API
  all read `1.5.0`.
- **Deployment template** `deployment/aiba.service` targets `/opt/aiba-agent` (container/VPS); the live
  install uses the per-user unit above at `/home/jay/aiba-agent`. They differ. `BACKUP_AND_RESTORE.md`
  documents the vault/agent_system drill.

### 8.2 CRITICAL SAFETY FINDING — dev/live data dir coupling (must fix before more work)
- Development and tests run from the SAME checkout `/home/jay/aiba-agent` AND default to the SAME
  `data_dir=/home/jay/aiba-agent/agent_system` as the live service (`AIBA_DATA_DIR` unset in dev shell).
- Consequence already observed: `sessions.db`/`subagents.db` (v1.6-only tables, not in v1.5 `main`)
  were created in the LIVE data dir on 2026-09-03 05:41 by local test runs during Phase 9/11 dev.
  The shared core live DBs (aiba.db Sep-01 09:12, schedules Sep-01, tasks Sep-01) were NOT touched by
  later test runs, but the coupling is real and unacceptable for release work.
- **Mandate going forward**: every dev command, test run, and local smoke MUST export a private
  `AIBA_DATA_DIR` (and `AIBA_ROOT` if a scratch checkout) so nothing writes into the live
  `agent_system/`. Rehearsal/soak/restore drills use a throwaway dir + a git **worktree** or a scratch
  clone so dev is fully separate from the running install, per the task brief's section 1.
- Live `.env` and secret stores must never be committed or staged. `.gitignore` already excludes
  `agent_system/`, `.venv`, build artifacts, certification output.

### 8.3 Release gates status (audited 2026-09-03)
- **CI workflow `Production Gate`**: 4 jobs — `test` (9-matrix: ubuntu/windows/macos × 3.11/3.12/3.13:
  pip install `.[api]` + platform installer + `certify_install.py` + `tests/api_smoke.py`),
  `security` (pip-audit --strict + bandit -lll + secret_scan), `capabilities` (builds `.venv`,
  `.[all]`, pyright 1.1.411 + `validate_capabilities.py`), `container` (docker build + trivy + doctor).
  **All 12 jobs green** at v1.6 branch head `8129f1b` (run 33809984662) and doc head `8a47acd`
  (run 33810206003). = 12 jobs, not 9 (3 test + security + capabilities + container).
- **MCP coverage gap in CI (to close, §2)**: CI test matrix installs `.[api]` (base, NO mcp SDK):
  MCP integration tests correctly skip their real-SDK path there. There is currently NO CI job that
  installs `.[all]`/`[mcp]` and RUNS the real protocol tests — only the `capabilities` job installs
  `[all]` but it runs pyright/validate, not the unit suite. → add an `mcp` CI job (or extend matrix)
  that installs `[mcp]` and runs the full suite so real-SDK tests execute (not skip).
- **Branch protection**: `gh api …/branches/main/protection` → **404 "Branch not protected"**. Main has
  NO required-status-checks/review-enforcement. Repo norm = merge via PR (git history: "Merge PR #4",
  "Merge pull request #3"). Planned release path therefore = PR-merge (no auto-merge) relying on the
  Production Gate being the effective gate on the PR, NOT GitHub-enforced branch rules.
- **Prior prerelease precedent**: `gh release list` → only `v1.3.0-rc.1` "AIBA Agent v1.3 Release
  Candidate" (Pre-release, 2026-08-09). No v1.4/v1.5 prereleases. Stale remote branch
  `origin/release/v1.4.0-rc.1` exists unused. Certification dir holds only `api-smoke.json` +
  `linux-x86_64.json` (CI machine artifacts). **No `certification/RELEASE_CANDIDATE.json` exists.**
- **Signing per PRODUCTION_GATE.md**: authenticode/Apple-notarization identities are EXTERNAL
  (AIBA Technologies supply). Not achievable on this host/account → the 1.6.0-rc.1 prerelease must be
  created WITHOUT platform binary signing unless Josh provides credentials; an unsigned artifact must
  NOT be labelled signed. A GitHub Prerelease (not a Production Certified stable tag) is the honest,
  authorized lane here — PRODUCTION_GATE.md reserves "Production Certified" for full evidence incl.
  signing; a Release **Candidate** is permitted before that evidence is complete.
- **Open PRs**: NONE currently open; no PR exists yet for `feat/aiba-v1.6-capability-parity`. The v1.6
  branch is 13k+ lines / 66 files ahead of `main` (`76da680`).

### 8.4 Open documented gaps → work items (task §2 mapping)
1. **Remote computer-node pairing (Phase 5b)** — currently only local `ComputerNodeGate` pair-digest;
   NO real authenticated remote-node transport. Work items: real encrypted/authenticated node comms,
   explicit pairing + revocation, replay protection, owner-bound auth, per-action approvals, persistent
   e-stop, bounded execution, redacted audit; NO public unauthenticated desktop endpoint; test vs a
   separate controlled node. **Blocker to validate honestly**: a separate controlled target machine is
   required; absent one, record as validation blocker (per brief), do NOT claim success.
2. **Memory/skills (Phase 9 open rows)** — per-user vault-ROW isolation (read/write/search/export/
   subagent); auto memory suggestions requiring confirmation + respecting `/memory pause`; skill
   drafting with review-before-activation; generated skills cannot self-grant permissions. Test
   cross-user isolation + prompt-injection. (Sessions ARE user-scoped today; vault rows are not.)
3. **Media/docs (Phase 8 probes)** — replace honest OCR/ASR/TTS/imagegen probes with real optional
   backends (maintained libs or paid APIs). Preserve `media_extract` + doc extraction. Audit the
   originally-requested doc/spreadsheet CREATE+EDIT capability; implement missing parts with workspace
   confinement + overwrite approval. Lazy-load + exact missing-dep diagnostics. **Blocker**: OCR/ASR/
   TTS/imagegen real backends that cost money need an explicit approved budget; local libs (tesseract,
   faster-whisper, etc.) need explicit download-size approval (see brief: don't download large models or
   buy APIs without approval).
4. **MCP (Phase 7 hardening)** — (a) add CI coverage both WITH and WITHOUT the SDK; SDK job must RUN
   the real protocol tests (not skip). (b) test remote transport vs a controlled HTTPS MCP server:
   redirects, SSRF, auth, disconnects, output limits (loopback HTTPS server + real `mcp_call`).
   (c) review the single `mcp_call` gateway vs intended DISCOVERY experience (tools/list, schema
   validation, per-server/per-tool perms+approvals applied); keep only if tests prove discovery+schema+
   perms; else implement discovery/schema integration.
5. **Telegram + usability (Phase 1/2/10 hardening)** — isolated test bot or approved test chat: verify
   typing-indicator refresh/stop, warm/concise/no-excess-markdown, numbered clarify choices, truthful
   progress, authenticated approval replies tied to the exact pending action, document delivery through
   the authorized connector, no hidden reasoning/secrets/prompts.
6. **Security/real-exec review (task §3)** — cancelled/timed-out subagent must not continue tool calls;
   thread timeouts not presented as guaranteed process termination; delegation consent not blanket
   approval; browser redirects/subresources/DNS/downloads can't bypass network+workspace restrictions;
   clipboard/screenshots out of logs; browser/desktop tools actually perform actions in a disposable env
   (not fake backends), harmless reversible fixtures, keep risky capabilities disabled-by-default.

### 8.5 Release-gate evidence to retain (task §4) + publish (§5) + upgrade (§6)
- Full unit+integration suites; clean-install certify; capability validation; CI-matching pyright;
  pip-audit; bandit; secret scan; compileall; diff-check; MCP present + absent env; real isolated
  browser/desktop smoke; backup/restore + upgrade/rollback rehearsal; authenticated API + connector
  tests; 1-hour soak with resource/concurrency monitoring. Inspect EVERY skip — required coverage must
  not silently vanish.
- Publish: bump to **1.6.0-rc.1** on ALL sources (VERSION, pyproject, api/server.py×2, changelog,
  dashboard labels), reconcile with current `main` via PR, re-run checks on the final release tree, build
  downloadable archive from the EXACT release commit, exclude secrets/runtime, verify archive integrity,
  publish SHA-256, signing only if credentials present (never fabricate / mislabel). No "stable"/parity
  comparison claim without evidence.
- Upgrade personal install to the exact rc: record working version+health, consistent verified backup
  (all db/profiles/memory/creds/workspace/config/service settings), preserve keys+file perms, cover NEW
  subsystem data (subagents.db/sessions.db/computer_node.json/vault), rehearse restore + record rollback
  commands, stage code+venv separately, cutover ONLY via `systemctl --user restart aiba` (never pkill),
  preserve telegram/provider config, apply only tested migrations, keep browser/desktop/remote-MCP OFF
  by default, verify health/ready/version/doctor/API/provider/telegram-poling/profile-memory/backup;
  on failure run the tested rollback and report.

### 8.6 Checkpoint / next-action (update this line each session end)
STATE (2026-09-03, session end): Gap **4(a) DONE + CI-verified** — added
`.github/workflows/mcp-integration.yml` (install `.[mcp]` on ubuntu/3.12, run full suite +
isolated MCP tests). Commit `e883e6d`, pushed. Runs on HEAD `e883e6d`: Production Gate
33812996472 (12/12 ✓) + MCP Integration 33812996656 (`mcp-with-sdk` ✓; **321 tests OK,
skipped=7 = platform/optional only; MCP `test_stdio_roundtrip` EXECUTED, not skipped** —
log shows real SDK spawn reaching `/opt/fake/server.py`). So HEAD now green on **13 jobs**.
Checkpoint §8.1/8.2/8.3 verified earlier; committed as `e639574`.
STATUS of remaining gaps (3-delegated read-only audits DONE, no code written yet):
- **Gap 2 (memory/skills/sessions)**: audit confirms `memories` table has NO owner column
  (`memory/vault.py:8-10`); shared singleton AgentLoop carries ambient `self._current_user`
  (`loop.py:53`, set `loop.py:309` per handled turn from `user_id` = `telegram:<id>`); the
  exact per-user pattern to mirror = `SessionStore.user_key` (`agent/sessions.py:41`). 6
  memory tool lambdas at `loop.py:165-172` + `_export_memories`(327) + `RetrievalEngine`
  (`memory/retrieval.py:3`) + `engine.run` context injection (`engine.py:25-27`) ALL
  user-agnostic → per-user-row isolation needs a **real aiba.db schema migration (v1→v2,
  add owner col + FTS triggers)** via `operations/migrations.py`. `/memory pause` lives in
  `personality/experience.py` (`memory_active`, `_memory_writes_allowed` 325, `blocked_tools`
  391-402 returns ONLY `remember`) and only gates the `remember` tool. DreamEngine.reflect
  (`loop.py:322`, user-agnostic) auto-writes memory each task — suggestion/confirmation must
  wrap loop.py:322.
- **Gap 6 (security/real-exec)**: audit verdict per concern = (1) cancel/timeout cooperative,
  in-flight handler runs to completion — tests don't assert "call-count flat after terminal";
  (2) timeout is soft-boundary, NOT process termination, docs honest but no explicit statement;
  (3) delegation consent scoped PER-TOOL and model cannot self-grant (`allow_approved` not in
  schema) — SAFE on main path, but shared main-workspace NOT folder-isolated (recorded
  `workspace` unused); (4) redirects/subresources re-checked per request but Playwright path
  LACKS `socket.getaddrinfo`/`ip.is_global` DNS check that `web_extract`/`browser_fetch` have
  (DNS-rebinding bypass), and `computer/controller.py:screenshot` (250-262) does NOT
  `.relative_to(workspace)` → `../../` escape; (5) clipboard content + screenshot bytes DO stay
  out of logs/streams and are approval-gated, BUT `desktop_type`/`browser_type` typed text is
  logged RAW at the registry `tool_start` (`tools/registry.py:78`); desktop screenshot saved
  into approval-free `read_file` area; (6) browser/desktop tests are fake-driver only with
  honest docstrings; real `_PlaywrightDriver`/`_PyAutoGuiBackend` never exercised → need opt-in
  integration gate.
- **Gap 4(c) (MCP discovery/schema)**: audit confirms NO `tools/list`/schema validation; pure
  call-by-explicit-name through `mcp_call`; `policy.py` has dead `mcp_tool_name`/namespace code
  never called; per-tool allowlist+approval IS operator-static via `config/mcp_servers.json`
  (`McpServerConfig.tools`), fail-closed at `client.py:373-393`. Discovery/schema seam = top of
  `MCPClientController.execute` (client.py:284).
- **Gaps 1,3,4(b),5 = EXTERNAL blockers** needing owner input (see §8.4 notes): remote node
  machine; paid-API/model budget for OCR/ASR/TTS/imagegen; reachable controlled HTTPS MCP
  server + remote-MCP opt-in; isolated Telegram test bot token.
NOT YET touched/done: everything in §8.5 (publish) and §8.5/S6 (live upgrade).
NEXT ACTION when resumed (highest value, unblocked): Gap 6 item (5) hardening (redact
`type_text`-class args at `registry.execute` `tool_start`; make `run_skill` propagate the
model `blocked` set) — small, self-contained, test-first; then Gap 6 item (4) DNS/workspace
confinement tests (some will reveal real gaps to fix); then Gap 2 isolation (needs the
migration decision); then Gap 4(c) MCP discovery (sizing decision). Report external blockers
for gaps 1/3/4(b)/5. Do NOT auto-bump/merge/upgrade without owner go on the §8.5 gates.

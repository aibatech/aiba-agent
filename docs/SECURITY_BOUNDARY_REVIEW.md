# Security boundary review — October 26, 2026

Scope: implementation inspection and deterministic adversarial regression. This is not live-model injection certification or an assertion that every host race is solved.

## Dispatch inventory

| Entry | Dispatch boundary | Evidence and remaining limits |
|---|---|---|
| Main agent | reasoning/engine.py → ToolRegistry.execute | Policy, schema, detached JSON arguments and exact approval before handler; test_security_boundaries.py |
| Product API | api/product_bridge.py → principal/store request_scope → agent | Durable opaque token consumption; test_approval_replay.py and test_product_bridge.py cover restart, principal, changed arguments, expiry and replay |
| Operator API | api/server.py authentication → agent/operator operations | Operator remains privileged; client authentication boundary is not implemented by a bearer service token |
| Scheduled/background | scheduler → queue → Worker → agent_task handler | Fresh principal-bound scope prevents local grant inheritance and terminal prompts; incomplete approved work fails the job |
| Skills | skills/manager.py → registry per step | Reviewed installation grants no execution permission; inherited blocks and recursion restrictions retained |
| Delegation | agent/loop.py _subagent_handler → registry | Captured user context and user blocked-tools checked; test_agent_skills_guard.py and existing subagent tests retained |
| MCP | registry mcp_call → mcp_client/client.py | Master/remote flags and configured server/tool allowlists retained; SDK CI required |
| Terminal/SSH | registered command tools → execution/backends.py | Registry approval precedes backend; live remote host and OS security boundaries remain external certification |

## Diagnostic inventory

| Surface | Current handling | Remaining gap |
|---|---|---|
| Registry audit | Tool, fingerprint, result metadata; all argument payloads withheld | Other event producers still use field-based minimization |
| Task events/checkpoints | Action type/tool/fingerprint; no raw model arguments, final response or plan descriptions | Task inputs/results are intentionally private owner data, not diagnostics; erasure/access controls remain essential |
| Visible tool telemetry | All argument payloads withheld; result/final previews withheld | Public plan summaries and arbitrary extra metadata need a complete field contract |
| Crash reports | Exception type/frame locations; messages, source lines, request paths omitted | Dynamic file/function names are not certified against malicious plugin naming |
| HTTP validation | Generic 400/422; no raw ValueError or Pydantic input echo | Explicit endpoint HTTPException details and successful private response bodies need separate review |
| Metrics | Operational counters and labels | Arbitrary label producer schemas not exhaustively certified |
| Install/CI output | Redirected setup token link withheld | Third-party dependency/tool output is outside the synthetic corpus |
| Queue/session histories | Owner task data and errors retained | Full retention/erasure coverage remains incomplete |

Synthetic leakage corpus includes ordinary private text without credential markers, token-shaped values, URLs with private parameters, nested lists, multiline and Unicode content. It exercises registry denials, visible tool/result/final events and crash reports. HTTP validation runs when API dependencies are installed (required CI job). Injection fixtures deliberately issue unauthorized sensitive and skill-install calls after hostile memory/source content: enforcement must deny those calls regardless of the scripted provider's compliance. The fixture source labels do not certify actual web/file retrieval or model resistance.

## Filesystem guarantees and unresolved platform scope

Prior POSIX ancestor-pinned host mutations/secret transfers and source/destination swap regressions are retained. Secret reads are bounded regular-file reads; atomic replacement avoids modifying existing hard-link targets. Windows atomic replacement alone is not equivalent to descriptor-relative traversal or verified restrictive ACLs. Host tools remain disabled by default. Do not raise Security requirement 7 or claim full Windows race parity from a green Python matrix. Remaining work requires a native Windows handle/ACL implementation and junction/reparse/concurrent-swap tests; no global test skip has been introduced to mask that gap.

## New defects repaired

- Principal or durable-store scopes cannot downgrade to local fingerprint grants, legacy auto approval, or interactive prompts when identity/store binding is incomplete.
- Caller or handler mutation cannot change the detached arguments used for approval, audit fingerprint and postcondition verification.
- Finite JSON validation precedes approvals; unsupported objects and nonfinite numbers fail before dispatch.
- Background entry points clear foreground grants and disallow interactive authorization.
- Arbitrary registry argument names no longer bypass audit redaction.
- Persistent model-action events and HTTP validation no longer duplicate raw private payloads.

No benchmark score increase: the complete security acceptance scope remains open.

Follow-up revocation fix: recheck capability availability and newly required approval immediately before tool dispatch. Regression test revokes the tool during the approval prompt and verifies zero handler calls. Local suite now 499 tests, zero failures, 11 skips. Initial security commit: 0cb28653996b2dcac815ca5cc827e181d1963bf6; initial candidate CI https://github.com/aibatech/aiba-agent/actions/runs/40309758527 (observe status; not presumed passed). Follow-up requires its own CI.

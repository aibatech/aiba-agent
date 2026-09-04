# v1.6 release review — 2026-09-04

This is a source review checkpoint, not production certification. The feature
branch still reports version 1.5.0; no release or live installation upgrade has
been performed by this change. Older PLAN entries describe historical states
and must not be used as proof that later integration paths are secure.

## Fixed in this review

- Connector chat allowlists no longer implicitly grant access to all memory.
  Vault administrators are explicitly listed in `AIBA_MEMORY_OWNER_USERS`.
- User identity is context-local. Worker threads inherit the dispatcher's
  context and tool handlers retain their originating identity when another
  conversation begins. Finishing a handled turn restores its caller's context.
- Subagent handlers now execute through the real registry: feature flags,
  conversation blocks, schema validation, auditing, and action-specific
  approval all apply at dispatch. Delegation consent does not approve arbitrary
  future tool actions.
- Newly queued/scheduled work records the initiating identity and executes as
  that identity instead of the local operator.
- The web fixture suite stubs DNS rather than relying on the machine's external
  DNS. The actual URL guard remains active, including private-address denial.
- The MCP test formerly named `test_stdio_roundtrip` expected a broken server
  to fail. It now starts the real client SDK against a deterministic JSON-RPC
  fixture and requires successful initialization and a returned tool result.
  Server-declared errors and failed transport remain separate negative tests.

## Required upgrade configuration

Set `AIBA_MEMORY_OWNER_USERS` explicitly to the owner's connector-qualified
identity (for example `telegram:123456789`). Do not copy an entire chat allowlist
without reviewing who should be an administrator. Leaving this setting empty
preserves all records but gives remote users only their own rows; legacy/shared
records remain accessible through the local operator/management API.

The bearer-token API remains an **operator management API**, not a multi-user
authentication service. Its token grants administrative access. Do not give it
to ordinary chat users. Existing jobs without a stored `user_id` retain their
legacy operator semantics; inspect and approve, retire, or re-create these jobs
before adding other users. No live records or configuration are changed here.

The owner-approved shared workspace remains shared. Memory-row filtering is
not filesystem isolation: users allowed to read arbitrary shared workspace
files can see exports saved there. Do not claim hostile multi-tenant isolation.

## Still blocking full-scope completion

1. Browser DNS: Python preflight DNS checks do not pin Chromium's connection.
   `tools/browser_session.py` checks only the main-frame peer this way; its
   static subresource guard does not stop hostname rebinding. Actual socket /
   egress enforcement and real-browser tests remain required. This is a code
   gap, not just missing owner test hardware.
2. Remote computer nodes: the current local gate is not an authenticated
   network transport. Implement transport and validate on a controlled second
   host before claiming remote-node capability.
3. MCP: the gateway has no usable discovered/operator-maintained tool-schema
   catalog. Argument object checks alone are not full remote-tool schema
   validation. Discovery or an explicit catalog must be implemented and tested.
   Remote HTTPS integration also needs controlled endpoint validation.
4. Media: OCR/ASR/TTS/image generation are capability probes, not working
   backends. Implementation, exact dependency/model requirements, and approved
   downloads or paid-provider budget are needed. Document creation/editing and
   connector delivery must be checked against the agreed release scope.
5. Memory suggestions, review-before-activation for generated skills, and
   memory-pause behavior across automatic reflection/skill execution remain
   subject to end-to-end review; this patch does not certify them.
6. Telegram UX, real desktop/browser actions, one-hour soak, clean deployment,
   and backup/restore/upgrade rehearsals require release evidence. Unit tests
   are not a substitute for those checks.

Do not merge as a completed release, create a stable tag, or upgrade the live
service while these required gates are open. A reduced release scope would need
an explicit owner decision and accurate disabled/unverified feature labels.

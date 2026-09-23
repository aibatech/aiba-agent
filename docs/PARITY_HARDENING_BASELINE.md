# AIBA parity & hardening baseline

Date: 2026-09-23

This checkpoint records the repository state and guardrails for the Hermes-parity
initiative. It is not release certification and does not replace
`PRODUCTION_GATE.md`.

## Baseline

- Runtime version at initiative start: **1.6.2**.
- The v1.6 review still lists browser DNS/socket enforcement, authenticated
  remote computer-node transport, MCP remote-tool schema validation, and
  media backend status as unresolved full-scope blockers.
- OCR/ASR/TTS/image generation remain unavailable until reviewed backends,
  dependencies, tests, and operator evidence exist.
- Remote computer control is not claimed by the existing in-process node gate.

## Non-negotiable guardrails

1. Fix documented isolation/security gaps before adding parity surface area.
2. New capability surfaces are disabled by default and require both their
   feature flag and their `permissions.json` entry to be enabled.
3. Approval, redaction, allowlists, validators, and prompt/instruction scanners
   are defense-in-depth heuristics. They are not substitutes for OS/process/
   network isolation where an adversarial model or untrusted code is in scope.
4. Model-authored shell/Python execution remains Docker-isolated; local
   execution is not promoted as a production containment posture.
5. External messaging remains owner-allowlisted and non-interactive for
   approval-requiring actions.
6. Untrusted document extraction remains read-only: no formula evaluation,
   macro execution, link following, or source mutation.
7. No code change, PR, CI run, or agent statement may call a target
   "Certified" or "production-ready." Certification requires the retained
   target evidence and operator approval defined by `PRODUCTION_GATE.md`.
8. Every new capability must include tests, a `SECURITY.md` trust-boundary
   entry, and a `CHANGELOG.md` entry before merge.

## Phase order

Phase 1 closes the documented v1.6 blockers first. Later phases cover the
formal trust model, terminal backends, messaging adapters, skills compatibility,
session/memory work, and migration/ecosystem tooling. Incomplete work stays
explicitly tracked as incomplete rather than being advertised for parity.

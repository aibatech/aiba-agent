# Known gaps — v1.7 adversarial verification

This document records what the v1.7 code and automated tests do **not** prove. It is intentionally conservative. A green CI run is regression evidence, not Production Certification.

| Control | Adversarial verification | Status before CI | Evidence / limitation |
|---|---|---|---|
| Browser DNS pin | Rebinding resolver returns public IP first, loopback second; proxy request records the actual dial target and asserts no second resolution occurs. | Pending CI | `tests/test_v17_adversarial.py::test_dns_rebinding_proxy_uses_single_pinned_resolution_per_request` |
| Discord owner allowlist | Non-owner `MESSAGE_CREATE` attempts a dangerous-looking request; test requires zero agent calls and zero replies. Malformed/oversized events are also exercised. | Pending CI | `tests/test_v17_adversarial.py` |
| Remote computer auth | Wrong HMAC credential and replay are rejected by `RemoteNodeRequestVerifier`. | **Not transport-certified** | There is no production remote-node HTTPS listener/controller integration in this repository to prove unauthenticated network traffic is rejected at the server transport boundary. The verifier test is necessary but not sufficient. |
| MCP schema | Type mismatch + unexpected field must be rejected before the async execution bridge is reached. | Pending CI | `test_mcp_schema_mismatch_denied_before_execution` plus existing config-catalog tests. |
| Skills Guard | Plain prompt override must be flagged. Base64-obfuscated prompt override is intentionally asserted as **not detected** to make the heuristic boundary explicit. | Partial / heuristic | Skills Guard is a review aid, not a security boundary. It does not decode arbitrary base64, normalize all Unicode confusables, or reconstruct instructions split across fields. |

## Additional unverified areas

- Discord has an allowlist parser/adapter, but repository evidence does not by itself prove a live Discord Gateway/webhook deployment, startup wiring, delivery deduplication, or production account behavior.
- The external messaging contract relies on the AgentLoop/ApprovalManager non-interactive posture for approval-requiring tools. The allowlist regression proves an unauthorized principal cannot reach `agent.handle`; it does not independently certify every approval path for an authorized remote principal.
- Remote computer transport has a signed HTTPS client and request verifier, but no complete server/listener integration was found in this pass. Do not advertise remote computer-node transport as certified.
- Skills Guard is pattern matching. Obfuscation can bypass it. Reviewed skill execution must continue to rely on sandbox/tool policy and operator review.
- Fuzz-style regression cases are deterministic hostile corpora, not coverage-guided fuzzing. Migration and session-search parsers should eventually be exercised by a dedicated property/coverage-guided fuzz harness.
- Clean OS installs, live providers, soak/load, signed artifacts, and deployment restore drills remain external evidence requirements in `PRODUCTION_GATE.md`.

## Release language

v1.7.0 may be described as containing the hardening implementation. It must not be described as **Production Certified** until every required `PRODUCTION_GATE.md` item has retained evidence for the exact release commit/artifacts.

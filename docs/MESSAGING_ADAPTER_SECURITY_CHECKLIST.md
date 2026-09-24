# Messaging adapter merge checklist

Every new external messaging adapter must satisfy all of these before merge:

- [ ] Connector is disabled by default.
- [ ] Authorization happens at the inbound boundary, before agent dispatch.
- [ ] Missing/empty owner allowlist fails closed.
- [ ] Remote messages use the non-interactive posture; approval-requiring tools are not auto-approved.
- [ ] Session/channel/thread IDs are routing handles, never authentication.
- [ ] Principals inside one allowlist are treated equally unless a separately reviewed policy says otherwise.
- [ ] Connector authorization does not imply memory/vault administration.
- [ ] Bot/self/duplicate events are rejected where the platform can emit them.
- [ ] Rich-text/markup interpretation is disabled by default where practical.
- [ ] Signed-webhook platforms verify signatures and bound replay age before parsing/dispatch.
- [ ] Any inbound HTTP listener binds loopback by default unless deployed behind the documented authenticated reverse-proxy boundary.
- [ ] Secrets are loaded from operator configuration/environment and never emitted to prompts/audit output.
- [ ] Adapter-level tests cover unauthorized, authorized, malformed, and replay/signature paths as applicable.
- [ ] SECURITY.md documents the adapter trust boundary and what it does not protect.
- [ ] Live connector evidence is collected separately under PRODUCTION_GATE.md; source tests do not certify the deployment.

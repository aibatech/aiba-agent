# Contributing to AIBA Agent

AIBA accepts focused, reviewable changes that preserve the repository's
deny-by-default security posture. Passing tests do not by themselves certify a
deployment; see `PRODUCTION_GATE.md`.

## Supply-chain rules

Changes that add or modify dependencies, MCP launches, plugins, skills, remote
execution, installers, update paths, or external process launches require
explicit supply-chain review.

### Dependencies

- Explain why the dependency is needed and why the standard library/current
  dependencies are insufficient.
- Pin or constrain versions according to the project's lock/release practice.
- Review package provenance, maintainer/repository identity, license, release
  history, transitive dependencies, install/build hooks, and known security
  advisories before merge.
- Never add a dependency only to avoid a small auditable implementation.
- Native extensions and packages with install-time code require heightened review.

### MCP and external processes

- Never launch through `shell=True`, shell strings, `eval`, or command
  concatenation. Use explicit argv.
- MCP servers are allowlisted by operator configuration and remain default-off.
- Every enabled remote tool requires an operator-maintained input schema.
- Environment forwarding is allowlist-only; credentials do not belong in config
  files, prompts, logs, migration reports, or committed fixtures.
- A PR adding an MCP server example must document package/source identity and
  pin a reviewed version or immutable source revision where the ecosystem permits.
- No PR may auto-install, auto-enable, or auto-trust an MCP server, plugin, or skill.

### Skills and plugins

Third-party skill/plugin content is untrusted until reviewed. Run Skills Guard,
inspect findings manually, review bundled scripts/resources and license, and do
not treat a clean scan as a security boundary. `allowed-tools` metadata never
grants AIBA permissions. Self-evolving/autonomous skill changes require their own
threat-model review.

## Required capability change set

A new capability must ship with: a default-off feature flag where it expands a
high-risk surface; a disabled permission row where it is a model tool; tests;
a SECURITY.md trust-boundary update; and a CHANGELOG entry. Document incomplete
target evidence rather than claiming production readiness.

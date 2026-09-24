# Agent Skills compatibility and trust review

AIBA supports the portable Agent Skills folder shape documented at agentskills.io:
a directory containing a required `SKILL.md` with YAML frontmatter and optional
`scripts/`, `references/`, `assets/`, or other resources.

## Compatibility decision

AIBA validates the interoperable core before import:

- `name` is required, 1-64 characters, lowercase alphanumeric/hyphen, and must
  match the parent directory.
- `description` is required and limited to 1024 characters.
- `compatibility`, when present, is limited to 500 characters.
- `license`, `metadata`, and experimental `allowed-tools` metadata may be
  retained in the package.

AIBA does **not** interpret `allowed-tools` as an authorization grant. Effective
tools still come from AIBA feature flags, `permissions.json`, ToolRegistry,
approval policy, and the OS/container trust envelope. This deliberately preserves
AIBA's stricter security model while keeping the package portable.

AIBA's legacy `skill.json` executable workflow remains an AIBA-specific format.
An Agent Skills `SKILL.md` package is instruction/resource content and does not
become directly executable merely because it contains scripts.

## License compatibility

The Agent Skills specification/reference repository states that its code is
Apache-2.0 and its documentation is CC-BY-4.0. AIBA does not vendor specification
code or documentation in this implementation; it implements the public format
independently. Individual imported skills retain their own license terms, and the
optional `license` field is surfaced for operator review. Operators are
responsible for confirming that a third-party skill's license permits their use
and redistribution.

## Skills Guard

Before third-party package activation, `SkillsGuard` statically reviews text and
scripts for signals including credential access, destructive commands,
download-and-execute patterns, network access, shell execution, persistence, and
prompt-override language. Symlinks are flagged and are not preserved by import.
Findings require explicit reviewed import.

**Skills Guard is a review aid, not a security boundary.** Pattern matching can
miss obfuscation, indirect execution, dependency behavior, native binaries,
prompt injection, and novel attacks. A clean report does not mean a skill is
safe or trusted.

## Self-evolution exclusion

`SkillImprover` may continue creating local proposals marked
`requires_review`. Phase 5 does not add DSPy, GEPA, autonomous skill rewriting,
automatic activation, automatic dependency installation, or automatic promotion
of generated skills. Any self-evolving skill system requires a separate threat
model covering poisoning, reward hacking, persistence, privilege expansion,
rollback, provenance, evaluation integrity, and data egress before implementation.

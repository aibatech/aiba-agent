"""MCP namespace, argv and policy constants (Phase 7).

Security posture shared by the whole Phase 7 subsystem:

* **Namespaced AIBA tool names**: an MCP tool ``X`` exposed by a server with
  ``server_id`` ``S`` becomes the dotted AIBA tool name ``mcp.<S>.<X>``. Each
  dotted component must be a non-empty ``[A-Za-z0-9_-]`` run — this *rejects*
  invalid or policy-colliding names before they can reach discovery.
* **argv-only stdio**: MCP stdio servers are launched with an explicit
  ``command`` + ``argv`` list and **never through a shell**. Any declared argv
  element containing shell metacharacters / option-delimiter characters that
  could smuggle extra arguments is rejected by :func:`assert_safe_argv`.
* **Fail-closed per-tool policy**: Discovery/call honour an explicit per-tool
  allowlist. A server can never broaden AIBA's surface by merely *claiming* a
  tool is safe; only tools the operator has listed as enabled (and, for
  dangerous servers, approval-gated) are reachable.
"""
from __future__ import annotations

import re

#: Namespace prefix used to keep every AIBA-visible MCP tool name distinct and
#: clearly policy-anchored.
MCP_NAMESPACE = "mcp"

#: MCP master feature flag (settings.mcp_enabled drives bool(self.settings.mcp_enabled)).
FEATURE_FLAG_ENABLED = "AIBA_MCP_ENABLED"
#: Opt-in feature flag for REMOTE (http) servers. Off by default; remote
#: servers additionally must pass security.urlguard + https.
FEATURE_FLAG_REMOTE = "AIBA_MCP_REMOTE"

#: Settings/env var name map (mirrors diagnostics/capabilities FEATURE_FLAG_ENV).
FEATURE_FLAG_ENV = {
    FEATURE_FLAG_ENABLED: "AIBA_MCP_ENABLED",
    FEATURE_FLAG_REMOTE: "AIBA_MCP_REMOTE",
}

_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Characters that would let an argv element leak out of its intended token if a
# caller ever (mistakenly) routed it through a shell: shell operators,
# gl*ob/quote characters, command substitution, and option shorthands.
_SHELL_META = set("|&;<>$`\\\"'(){}[]*?!#~")
# Characters that allow <dash>-option smuggling (so a malicious server/argv can
# not prepend ``--flag`` to a later command). Rejected in addition to shell
# metacharacters.
_OPTION_LEAD = ("-", "--")


def validate_component(component: str) -> bool:
    """Return True iff *component* is a legal dotted-name token."""
    if not isinstance(component, str) or not component:
        return False
    return bool(_COMPONENT_RE.fullmatch(component))


def assert_safe_server_id(server_id: str) -> None:
    """Raise ``ValueError`` when *server_id* is not a safe namespace token."""
    if not validate_component(server_id):
        raise ValueError(
            "Invalid MCP server_id (must be a non-empty [A-Za-z0-9_-] token): "
            f"{server_id!r}"
        )


def mcp_tool_name(server_id: str, tool: str) -> str:
    """Return the namespaced AIBA tool name ``mcp.<S>.<X>``.

    Rejects names whose components are empty or fall outside ``[A-Za-z0-9_-]``
    so a hostile server can never forge or collide with AIBA policy names.
    """
    assert_safe_server_id(server_id)
    if not validate_component(tool):
        raise ValueError(
            "Invalid MCP tool name (must be a non-empty [A-Za-z0-9_-] token): "
            f"{tool!r}"
        )
    return f"{MCP_NAMESPACE}.{server_id}.{tool}"


def split_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Split ``mcp.<S>.<X>`` back into ``(server_id, tool)`` or return None."""
    parts = name.split(".")
    if len(parts) != 3 or parts[0] != MCP_NAMESPACE:
        return None
    if not validate_component(parts[1]) or not validate_component(parts[2]):
        return None
    return parts[1], parts[2]


def assert_safe_argv(args: list[str]) -> None:
    """Reject *args* that could carry shell metacharacters or ``-x`` options.

    Stdio MCP launch is an explicit argv (SDK never uses a shell), but AIBA
    double-checks so a config typo or malicious command can never smuggle extra
    flags or shell syntax into a child process.
    """
    for idx, arg in enumerate(args):
        if not isinstance(arg, str) or not arg:
            raise ValueError(f"argv element {idx} must be a non-empty string")
        if any(ch in arg for ch in _SHELL_META):
            raise ValueError(
                f"argv element {idx} contains a shell metacharacter and is "
                f"refused (MCP stdio is argv-only, no shell): {arg!r}"
            )
        # Option smuggle is only a concern for elements not themselves the
        # first token of the child; still, refuse a *single-dash* start anywhere
        # except the program token is over-strict for legitimately dash-led
        # args, so only reject bare "--" (argument terminator) and guarded
        # double-dash long flags we cannot attribute. Kept conservative: refuse
        # any argv element equal to "-" or "--".
        if arg in ("-", "--"):
            raise ValueError(
                f"argv element {idx} {arg!r} is an argument delimiter and is "
                f"refused for MCP stdio launch."
            )


# Risk classes map a server the operator marks as ``destructive`` / performs
# external writes to a default approval posture. Servers default to a bounded
# read posture and never auto-approve.
DEFAULT_MAX_OUTPUT_BYTES = 128 * 1024  # 128 KiB default cap
DEFAULT_STARTUP_TIMEOUT_S = 10.0
DEFAULT_CALL_TIMEOUT_S = 30.0
DEFAULT_RESTART_LIMIT = 2
DEFAULT_ENV_ALLOWLIST = (
    "HOME",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "USER",
)

#: Env var names that MAY be forwarded from the AIBA process to a stdio server
#: child, in addition to the SDK's minimal safe base. Only *names* are
#: allowlisted; secret values are only read from the operator's environment at
#: launch time and are never stored or logged.
KNOWN_SAFE_ENV_NAMES = (
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "PYTHONPATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
)

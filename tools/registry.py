from __future__ import annotations
from typing import Any
from .base import Tool,ToolResult
import inspect,json
def _valid(value,schema):
    expected=schema.get('type')
    if expected=='string' and not isinstance(value,str):return False
    if expected=='integer' and (not isinstance(value,int) or isinstance(value,bool)):return False
    if expected=='number' and (not isinstance(value,(int,float)) or isinstance(value,bool)):return False
    if expected=='boolean' and not isinstance(value,bool):return False
    if expected=='object' and not isinstance(value,dict):return False
    if expected=='array' and not isinstance(value,list):return False
    if 'enum' in schema and value not in schema['enum']:return False
    if isinstance(value,list) and schema.get('items') and any(not _valid(item,schema['items']) for item in value):return False
    if isinstance(value,dict) and expected=='object':
        props=schema.get('properties',{});required=schema.get('required',[])
        if any(k not in value for k in required):return False
        if schema.get('additionalProperties') is False and any(k not in value for k in props):return False
        if any(k in props and not _valid(v,props[k]) for k,v in value.items()):return False
    return True

# --- Secret redaction for the audit/approval layer (defense in depth) --------------
# The desktop/browser/computer controllers already report typed content only by
# length internally (computer/controller.py `_is_secretish`, tools/browser_session.py
# `_is_secretish`). The registry sits ABOVE them and, before dispatch, records the full
# `arguments` to the audit trail and shows them in the approval prompt. That outer layer
# would otherwise log raw secret-like text even though the inner controller refuses to.
# These helpers redact before auditing/displaying so the "typed secrets are never logged"
# invariant holds end-to-end. Kept self-contained (no import of computer/browser modules,
# which would couple the registry to optional capabilities).

_SECRET_VALUE_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                         "credential", "authorization", "bearer ", "ssn", "cvv",
                         "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY")
# Tools whose `text` argument carries content typed into a UI (may be secret-like).
_TYPED_TEXT_ARG_TOOLS = {"desktop_type", "browser_type", "desktop_clipboard_write"}
# Argument keys whose value is always a secret regardless of tool.
_ALWAYS_SECRET_KEYS = ("password", "token", "api_key", "apikey", "secret",
                       "authorization", "client_secret", "private_key", "passphrase",
                       "access_token", "refresh_token", "bearer")

def _is_secretish_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    low = value.lower().lstrip()
    if not low:
        return False
    return any(m in low for m in _SECRET_VALUE_MARKERS)

def _scrub_args_for_surface(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `arguments` safe for the audit trail / approval prompt.

    Redacts values under known secret key names (any tool) and, for the typed-text
    tool family, any `text` value that looks secretish — mirrored with the inner
    controller's secret-text doctrine. Non-secret typed/screen content is kept so the
    audit stays useful, matching the inner layers' behaviour.
    """
    def marker(value: Any) -> str:
        raw = value if isinstance(value, str) else str(value)
        return f"[REDACTED len={len(raw)}]"
    scrubbed: dict[str, Any] = {}
    for key, val in arguments.items():
        kl = key.lower()
        if any(h in kl for h in _ALWAYS_SECRET_KEYS):
            scrubbed[key] = marker(val)
        elif name in _TYPED_TEXT_ARG_TOOLS and key == "text" and _is_secretish_string(val):
            scrubbed[key] = marker(val)
        else:
            scrubbed[key] = val
    return scrubbed

class ToolRegistry:
    def __init__(self, audit, approvals, policy, feature_flags=None, manifest=None):
        self._tools={}; self.audit=audit; self.approvals=approvals; self.policy=policy
        # feature_flags: dict[str,bool] of runtime env flags (e.g. AGENT_WEB_ENABLED).
        # manifest: dict from config/capability_manifest.json carrying each tool's
        # feature_flag. A tool whose manifest feature flag is off is not advertised
        # (schemas) and is denied (execute) with an actionable reason.
        self.feature_flags=feature_flags or {}
        self.manifest=(manifest or {}).get("tools", {}) if isinstance(manifest, dict) else {}
    def _feature_flag_on(self, name: str) -> bool:
        meta=self.manifest.get(name)
        flag=(meta or {}).get("feature_flag") or ""
        if not flag or flag=="none":
            return True
        return bool(self.feature_flags.get(flag, False))
    def _availability(self, name: str) -> str:
        """Return '' if a tool is safe to advertise/run, else a clear reason."""
        if name not in self._tools:
            return f"Unknown tool: {name}"
        decision=self.policy.check_tool(name)
        if not decision.allowed:
            # Distinguish "not listed in policy" from "listed but disabled"
            perm=self.policy.config.get("tools", {}).get(name)
            if perm is None:
                return f"{name} is registered but unavailable because it is missing from config/permissions.json."
            return decision.reason or f"{name} is disabled in config/permissions.json."
        if not self._feature_flag_on(name):
            meta=self.manifest.get(name, {})
            flag=(meta.get("feature_flag") or "")
            return f"{name} requires feature flag {flag} to be enabled (set {flag}=true)."
        return ""
    def register(self,tool:Tool): self._tools[tool.name]=tool
    def schemas(self, excluded=None):
        excluded=excluded or set()
        return [{'name':t.name,'description':t.description,'parameters':t.parameters}
                for t in self._tools.values()
                if t.name not in excluded and self.policy.check_tool(t.name).allowed and self._feature_flag_on(t.name)]
    def blocked(self, name:str, extra=None):
        return name in (extra or set()) or not self.policy.check_tool(name).allowed or not self._feature_flag_on(name)
    def execute(self,name:str,arguments:dict[str,Any]|None=None,blocked:set[str]|None=None)->ToolResult:
        args=arguments or {}; tool=self._tools.get(name); blocked=blocked or set()
        if name in blocked:
            return ToolResult(False,error=f'{name} is disabled for this conversation')
        reason=self._availability(name)
        if reason:
            return ToolResult(False,error=reason)
        decision=self.policy.check_tool(name)
        if tool is None:
            return ToolResult(False,error=f'Unknown tool: {name}')
        if decision.requires_approval and not self.approvals.approve(name,str(_scrub_args_for_surface(name,args))[:500]):
            self.audit.record('tool_denied',tool=name,arguments=_scrub_args_for_surface(name,args)); return ToolResult(False,error='User approval denied')
        if not isinstance(args,dict):return ToolResult(False,error='Tool arguments must be an object')
        schema=tool.parameters; props=schema.get('properties',{}); required=schema.get('required',[])
        missing=[x for x in required if x not in args]
        unknown=[x for x in args if x not in props] if schema.get('additionalProperties') is False else []
        invalid=[x for x,v in args.items() if x in props and not _valid(v,props[x])]
        if missing or unknown or invalid:return ToolResult(False,error=f'Invalid arguments; missing={missing}, unknown={unknown}, invalid_types={invalid}')
        self.audit.record('tool_start',tool=name,arguments=_scrub_args_for_surface(name,args))
        try:result=tool.run(**args)
        except TypeError as exc:result=ToolResult(False,error=f'Invalid tool arguments: {exc}')
        except Exception as exc:result=ToolResult(False,error=f'{type(exc).__name__}: {exc}')
        if not isinstance(result,ToolResult):result=ToolResult(True,result)
        self.audit.record('tool_end',tool=name,ok=result.ok,error=result.error); return result

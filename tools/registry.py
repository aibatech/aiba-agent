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
        if schema.get('additionalProperties') is False and any(k not in props for k in value):return False
        if any(k in props and not _valid(v,props[k]) for k,v in value.items()):return False
    return True
class ToolRegistry:
    def __init__(self,audit,approvals,policy): self._tools={}; self.audit=audit; self.approvals=approvals; self.policy=policy
    def register(self,tool:Tool): self._tools[tool.name]=tool
    def schemas(self, excluded=None):
        excluded=excluded or set()
        return [{'name':t.name,'description':t.description,'parameters':t.parameters}
                for t in self._tools.values()
                if t.name not in excluded and self.policy.check_tool(t.name).allowed]
    def blocked(self, name:str, extra=None):
        return name in (extra or set()) or not self.policy.check_tool(name).allowed
    def execute(self,name:str,arguments:dict[str,Any]|None=None,blocked:set[str]|None=None)->ToolResult:
        args=arguments or {}; tool=self._tools.get(name); blocked=blocked or set(); decision=self.policy.check_tool(name)
        if not tool:return ToolResult(False,error=f'Unknown tool: {name}')
        if name in blocked:return ToolResult(False,error=f'{name} is disabled for this conversation')
        if not decision.allowed:return ToolResult(False,error=decision.reason)
        if decision.requires_approval and not self.approvals.approve(name,str(args)[:500]):
            self.audit.record('tool_denied',tool=name,arguments=args); return ToolResult(False,error='User approval denied')
        if not isinstance(args,dict):return ToolResult(False,error='Tool arguments must be an object')
        schema=tool.parameters; props=schema.get('properties',{}); required=schema.get('required',[])
        missing=[x for x in required if x not in args]
        unknown=[x for x in args if x not in props] if schema.get('additionalProperties') is False else []
        invalid=[x for x,v in args.items() if x in props and not _valid(v,props[x])]
        if missing or unknown or invalid:return ToolResult(False,error=f'Invalid arguments; missing={missing}, unknown={unknown}, invalid_types={invalid}')
        self.audit.record('tool_start',tool=name,arguments=args)
        try:result=tool.run(**args)
        except TypeError as exc:result=ToolResult(False,error=f'Invalid tool arguments: {exc}')
        except Exception as exc:result=ToolResult(False,error=f'{type(exc).__name__}: {exc}')
        if not isinstance(result,ToolResult):result=ToolResult(True,result)
        self.audit.record('tool_end',tool=name,ok=result.ok,error=result.error); return result

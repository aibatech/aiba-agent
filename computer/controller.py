from __future__ import annotations
from pathlib import Path
from tools.base import ToolResult
class ComputerController:
    def __init__(self,enabled:bool=False):self.enabled=enabled
    def _lib(self):
        if not self.enabled:raise PermissionError('Desktop control is disabled')
        try:import pyautogui;return pyautogui
        except ImportError as exc:raise RuntimeError('Install pyautogui for desktop control') from exc
    def screenshot(self,path:str)->ToolResult:
        try:p=Path(path).resolve();p.parent.mkdir(parents=True,exist_ok=True);self._lib().screenshot(str(p));return ToolResult(True,{'path':str(p)})
        except Exception as exc:return ToolResult(False,error=str(exc))
    def click(self,x:int,y:int)->ToolResult:
        try:self._lib().click(x,y);return ToolResult(True,{'clicked':[x,y]})
        except Exception as exc:return ToolResult(False,error=str(exc))
    def type_text(self,text:str,interval:float=.01)->ToolResult:
        try:self._lib().write(text,interval=interval);return ToolResult(True,{'typed':len(text)})
        except Exception as exc:return ToolResult(False,error=str(exc))

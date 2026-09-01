from __future__ import annotations
import base64,json,os,urllib.request
from pathlib import Path
from tools.base import ToolResult
class VisionAnalyzer:
    def __init__(self,model:str='gpt-4.1-mini'):self.model=model
    def analyze(self,image_path:str,instruction:str='Describe the interface and actionable elements.')->ToolResult:
        key=os.getenv('OPENAI_API_KEY');p=Path(image_path)
        if not p.exists():return ToolResult(False,error='Image not found')
        if not key:return ToolResult(False,error='OPENAI_API_KEY is required for vision analysis')
        mime='image/png' if p.suffix.lower()=='.png' else 'image/jpeg';data=base64.b64encode(p.read_bytes()).decode()
        payload={'model':self.model,'messages':[{'role':'user','content':[{'type':'text','text':instruction},{'type':'image_url','image_url':{'url':f'data:{mime};base64,{data}'}}]}]}
        req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=90) as r:return ToolResult(True,json.loads(r.read())['choices'][0]['message']['content'])
        except Exception as exc:return ToolResult(False,error=f'Vision request failed: {exc}')

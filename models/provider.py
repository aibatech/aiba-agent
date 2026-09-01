from __future__ import annotations
import json,os,urllib.error,urllib.request

class ProviderError(RuntimeError):pass

def _post(url:str,payload:dict,headers:dict,timeout:int=120)->dict:
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json",**headers})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body=exc.read(1000).decode(errors='replace')
        raise ProviderError(f'HTTP {exc.code}: {body}') from exc
    except Exception as exc:raise ProviderError(f'Request failed: {exc}') from exc

class LocalProvider:
    name='local'
    def __init__(self,model='local-v1'):self.model=model
    def complete(self,messages,tools):
        text=messages[-1]['content']; command=text.split('\nRelevant memory:',1)[0].strip()
        if command.startswith('/remember '):answer={'type':'tool_call','tool':'remember','arguments':{'content':command[10:]}}
        elif command.startswith('/recall '):answer={'type':'tool_call','tool':'search_memory','arguments':{'query':command[8:]}}
        elif command=='/files':answer={'type':'tool_call','tool':'list_files','arguments':{}}
        elif text.startswith('Tool result:'):answer={'type':'final','response':text}
        else:answer={'type':'final','response':'Local mode is operational. Configure OpenAI, Anthropic, an OpenAI-compatible endpoint, or Ollama for general agent reasoning.'}
        return json.dumps(answer)

class OpenAIProvider:
    name='openai'
    def __init__(self,model,base_url=None,key_env='OPENAI_API_KEY',api_key=None,extra_headers=None):
        self.model=model;self.base_url=(base_url or os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1')).rstrip('/');self.key_env=key_env;self.api_key=api_key;self.extra_headers=extra_headers or {};self.last_usage={}
    def complete(self,messages,tools):
        key=self.api_key or (os.getenv(self.key_env) if self.key_env else None)
        if self.key_env and not key:raise ProviderError(f'{self.key_env} is not set')
        native=[{'type':'function','function':{'name':t['name'],'description':t['description'],'parameters':t['parameters']}} for t in tools]
        headers={**self.extra_headers}
        if key:headers['Authorization']=f'Bearer {key}'
        data=_post(self.base_url+'/chat/completions',{'model':self.model,'messages':messages,'tools':native,'tool_choice':'auto','temperature':0},headers)
        self.last_usage=data.get('usage') or {}
        msg=data['choices'][0]['message']
        if msg.get('tool_calls'):
            call=msg['tool_calls'][0];return {'type':'tool_call','tool':call['function']['name'],'arguments':json.loads(call['function'].get('arguments') or '{}')}
        content=msg.get('content') or ''
        try:return json.loads(content)
        except json.JSONDecodeError:return {'type':'final','response':content}

class OpenAICompatibleProvider(OpenAIProvider):
    name='openai_compatible'
    def __init__(self,model):super().__init__(model,os.getenv('OPENAI_COMPATIBLE_BASE_URL','http://localhost:1234/v1'),'OPENAI_COMPATIBLE_API_KEY')

class AnthropicProvider:
    name='anthropic'
    def __init__(self,model,api_key=None,base_url=None):self.model=model;self.api_key=api_key;self.base_url=(base_url or 'https://api.anthropic.com').rstrip('/');self.last_usage={}
    def complete(self,messages,tools):
        key=self.api_key or os.getenv('ANTHROPIC_API_KEY')
        if not key:raise ProviderError('ANTHROPIC_API_KEY is not set')
        system='\n'.join(m['content'] for m in messages if m['role']=='system')
        chat=[m for m in messages if m['role']!='system']
        native=[{'name':t['name'],'description':t['description'],'input_schema':t['parameters']} for t in tools]
        data=_post(self.base_url+'/v1/messages',{'model':self.model,'max_tokens':4096,'system':system,'messages':chat,'tools':native},{'x-api-key':key,'anthropic-version':'2023-06-01'})
        self.last_usage=data.get('usage') or {}
        for block in data.get('content',[]):
            if block.get('type')=='tool_use':return {'type':'tool_call','tool':block['name'],'arguments':block.get('input',{})}
        text=''.join(x.get('text','') for x in data.get('content',[]) if x.get('type')=='text')
        return {'type':'final','response':text}

class OllamaProvider:
    name='ollama'
    def __init__(self,model,base_url=None):self.model=model;self.base_url=(base_url or os.getenv('OLLAMA_BASE_URL','http://localhost:11434')).rstrip('/');self.last_usage={}
    def complete(self,messages,tools):
        native=[{'type':'function','function':{'name':t['name'],'description':t['description'],'parameters':t['parameters']}} for t in tools]
        data=_post(self.base_url+'/api/chat',{'model':self.model,'messages':messages,'tools':native,'stream':False},{})
        self.last_usage={'prompt_tokens':data.get('prompt_eval_count',0),'completion_tokens':data.get('eval_count',0)}
        msg=data['message']
        if msg.get('tool_calls'):
            call=msg['tool_calls'][0]['function'];return {'type':'tool_call','tool':call['name'],'arguments':call.get('arguments',{})}
        content=msg.get('content','')
        try:return json.loads(content)
        except json.JSONDecodeError:return {'type':'final','response':content}

class BedrockProvider:
    name='aws_bedrock'
    def __init__(self,model,config=None):self.model=model;self.config=config or {};self.last_usage={}
    def complete(self,messages,tools):
        try:import boto3
        except ImportError as exc:raise ProviderError('Install boto3 for AWS Bedrock') from exc
        client=boto3.client('bedrock-runtime',region_name=self.config.get('region') or os.getenv('AWS_REGION','us-east-1'))
        system=[{'text':m['content']} for m in messages if m['role']=='system'];chat=[{'role':m['role'],'content':[{'text':m['content']}]} for m in messages if m['role']!='system']
        tool_config={'tools':[{'toolSpec':{'name':t['name'],'description':t['description'],'inputSchema':{'json':t['parameters']}}} for t in tools]}
        try:data=client.converse(modelId=self.model,messages=chat,system=system,toolConfig=tool_config)
        except Exception as exc:raise ProviderError(f'Bedrock request failed: {exc}') from exc
        self.last_usage=data.get('usage') or {};blocks=data['output']['message']['content']
        for b in blocks:
            if 'toolUse' in b:return {'type':'tool_call','tool':b['toolUse']['name'],'arguments':b['toolUse'].get('input',{})}
        return {'type':'final','response':'\n'.join(b.get('text','') for b in blocks)}

def build_managed_provider(provider:dict,model:dict,api_key:str|None):
    kind=provider['kind'];base=provider.get('base_url');config=provider.get('config') or {}
    if kind=='anthropic':return AnthropicProvider(model['model_id'],api_key,base)
    if kind=='ollama':return OllamaProvider(model['model_id'],base)
    if kind=='aws_bedrock':return BedrockProvider(model['model_id'],config)
    headers=config.get('headers') or {}
    if kind=='openrouter':headers={**headers,'HTTP-Referer':config.get('site_url','https://aibanexus.com'),'X-Title':config.get('app_name','AIBA Agent')}
    if kind=='azure_openai':
        if not base:raise ProviderError('Azure OpenAI requires a deployment chat-completions base URL')
        return OpenAIProvider(model['model_id'],base,'AZURE_OPENAI_API_KEY',api_key,{'api-key':api_key or ''})
    key_env={'openai':'OPENAI_API_KEY','google':'GEMINI_API_KEY','xai':'XAI_API_KEY','openrouter':'OPENROUTER_API_KEY','groq':'GROQ_API_KEY','mistral':'MISTRAL_API_KEY','deepseek':'DEEPSEEK_API_KEY','together':'TOGETHER_API_KEY','perplexity':'PERPLEXITY_API_KEY','lmstudio':'','custom':''}.get(kind,'OPENAI_API_KEY')
    return OpenAIProvider(model['model_id'],base,key_env,api_key,headers)

def discover_managed_models(provider:dict,api_key:str|None):
    kind=provider['kind'];base=(provider.get('base_url') or '').rstrip('/');headers={}
    if kind=='aws_bedrock':
        try:import boto3
        except ImportError as exc:raise ProviderError('Install boto3 for AWS Bedrock') from exc
        client=boto3.client('bedrock',region_name=(provider.get('config') or {}).get('region') or os.getenv('AWS_REGION','us-east-1'))
        return [{'id':x['modelId'],'name':x.get('modelName',x['modelId'])} for x in client.list_foundation_models().get('modelSummaries',[])]
    if kind=='ollama':
        data=_get(base+'/api/tags',{});return [{'id':x['name'],'name':x['name']} for x in data.get('models',[])]
    if not base:raise ProviderError('Provider base URL is required for model discovery')
    if api_key:
        if kind=='anthropic':headers={'x-api-key':api_key,'anthropic-version':'2023-06-01'}
        elif kind=='azure_openai':headers={'api-key':api_key}
        else:headers={'Authorization':f'Bearer {api_key}'}
    data=_get(base+'/v1/models' if kind=='anthropic' else base+'/models',headers)
    return [{'id':x['id'],'name':x.get('display_name') or x.get('name') or x['id']} for x in data.get('data',[])]

def _get(url:str,headers:dict,timeout:int=30)->dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=timeout) as response:return json.loads(response.read())
    except Exception as exc:raise ProviderError(f'Model discovery failed: {exc}') from exc

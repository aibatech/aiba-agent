from __future__ import annotations
import re,time,uuid
from .provider import ProviderError,build_managed_provider,discover_managed_models

TASK_PATTERNS={
 'coding':(r'\b(code|coding|debug|bug|repository|python|javascript|typescript|sql|api)\b',['text','tools','code']),
 'vision':(r'\b(image|photo|screenshot|visual|vision|diagram)\b',['text','vision']),
 'research':(r'\b(research|latest|sources|web|compare|market|news)\b',['text','tools']),
 'creative':(r'\b(write|creative|story|caption|script|brand|marketing)\b',['text']),
 'reasoning':(r'\b(analyze|plan|strategy|reason|decide|evaluate)\b',['text','tools']),
}

def classify_task(messages)->str:
    text=' '.join(str(m.get('content','')) for m in messages if m.get('role')=='user').lower()
    for task,(pattern,_) in TASK_PATTERNS.items():
        if re.search(pattern,text):return task
    return 'default'

class IntelligentRouter:
    def __init__(self,store,legacy=None):self.store=store;self.legacy=legacy;self.last_route=None
    def candidates(self,task_type='default',manual_model_id=None):
        models=self.store.list_models(enabled_only=True);rule=self.store.get_rule(task_type)
        required=set() if manual_model_id else set(rule.get('required_capabilities') or [])
        if not manual_model_id and not required and task_type in TASK_PATTERNS:required=set(TASK_PATTERNS[task_type][1])
        if manual_model_id:models=[m for m in models if m['id']==manual_model_id or m['model_id']==manual_model_id]
        models=[m for m in models if required.issubset(set(m['capabilities'])) and (bool(manual_model_id) or m['provider_health']!='unhealthy')]
        ceiling=rule.get('max_cost_per_million')
        if ceiling is not None and not manual_model_id:models=[m for m in models if (m['price_input']+m['price_output'])/2<=ceiling]
        preferred=rule.get('preferred_models') or [];strategy='manual' if manual_model_id else rule.get('strategy','balanced')
        performance=self.store.performance()
        def score(m):
            pref=preferred.index(m['id']) if m['id'] in preferred else len(preferred)+1
            avg_cost=(m['price_input']+m['price_output'])/2
            health=0 if m['provider_health']=='healthy' else 25;perf=performance.get((m['provider_id'],m['model_id']),{});latency=perf.get('avg_latency_ms') or 1_000_000;reliability=1-(perf.get('success_rate') if perf.get('success_rate') is not None else .5)
            if strategy=='cost':return (avg_cost,pref,m['priority'],health)
            if strategy=='quality':return (pref,m['priority'],health,avg_cost)
            if strategy=='latency':return (health,latency,reliability,pref,m['priority'])
            return (pref,m['priority']+m['provider_priority']+health,reliability,avg_cost,latency)
        return sorted(models,key=score)
    def complete(self,messages,tools,task_type=None,manual_model_id=None):
        task_type=task_type or classify_task(messages);request_id=str(uuid.uuid4());errors=[]
        candidates=self.candidates(task_type,manual_model_id)
        for model in candidates:
            provider=self.store.get_provider(model['provider_id'],True);started=time.monotonic()
            try:
                adapter=build_managed_provider(provider,model,provider.get('api_key') or self.store.get_key(provider['id']))
                result=adapter.complete(messages,tools);latency=int((time.monotonic()-started)*1000);usage=getattr(adapter,'last_usage',{}) or {}
                input_tokens=int(usage.get('prompt_tokens',usage.get('input_tokens',0)) or 0);output_tokens=int(usage.get('completion_tokens',usage.get('output_tokens',0)) or 0)
                cost=(input_tokens*model['price_input']+output_tokens*model['price_output'])/1_000_000
                self.store.health(provider['id'],True);self.store.record_usage(request_id=request_id,task_type=task_type,provider_id=provider['id'],model_id=model['model_id'],status='success',input_tokens=input_tokens,output_tokens=output_tokens,estimated_cost=cost,latency_ms=latency,error=None)
                self.last_route={'request_id':request_id,'task_type':task_type,'provider':provider['name'],'model':model['model_id'],'latency_ms':latency,'estimated_cost':cost};return result
            except Exception as exc:
                latency=int((time.monotonic()-started)*1000);self.store.health(provider['id'],False,exc);self.store.record_usage(request_id=request_id,task_type=task_type,provider_id=provider['id'],model_id=model['model_id'],status='failed',input_tokens=0,output_tokens=0,estimated_cost=0,latency_ms=latency,error=str(exc)[:1000]);errors.append(f"{provider['name']}/{model['model_id']}: {exc}")
        if self.legacy and not candidates:return self.legacy.complete(messages,tools)
        raise ProviderError('No healthy eligible model completed the request. '+'; '.join(errors))
    def test_provider(self,provider_id):
        provider=self.store.get_provider(provider_id,True);models=[m for m in self.store.list_models() if m['provider_id']==provider_id and m['enabled']]
        if not models:raise ValueError('Add and enable at least one model first')
        started=time.monotonic()
        try:
            adapter=build_managed_provider(provider,models[0],provider.get('api_key') or self.store.get_key(provider_id));adapter.complete([{'role':'user','content':'Reply with OK.'}],[]);latency=int((time.monotonic()-started)*1000);self.store.health(provider_id,True);return {'ok':True,'latency_ms':latency,'model':models[0]['model_id']}
        except Exception as exc:self.store.health(provider_id,False,exc);return {'ok':False,'error':str(exc)}
    def discover_models(self,provider_id):
        provider=self.store.get_provider(provider_id,True);return discover_managed_models(provider,provider.get('api_key') or self.store.get_key(provider_id))

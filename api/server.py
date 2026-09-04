import asyncio,hmac,time,json,os
from collections import defaultdict,deque
from pathlib import Path

def create_app(agent):
    try:
        from fastapi import BackgroundTasks,FastAPI,Header,HTTPException,Request,WebSocket,WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import HTMLResponse,JSONResponse,PlainTextResponse,Response
        from pydantic import BaseModel,Field
    except ImportError as exc:raise RuntimeError('Install API dependencies: pip install -e .[api]') from exc
    app=FastAPI(title='AIBA Agent API',version='1.6.0',docs_url='/docs' if agent.settings.api_token else None)
    telegram=None;whatsapp=None
    if os.getenv('AIBA_TELEGRAM_ENABLED','false').lower() in {'1','true','yes','on'}:
        from connectors import TelegramConnector;telegram=TelegramConnector(agent)
    if os.getenv('AIBA_WHATSAPP_ENABLED','false').lower() in {'1','true','yes','on'}:
        from connectors import WhatsAppConnector;whatsapp=WhatsAppConnector(agent)
    @app.on_event('startup')
    def start_connectors():
        if telegram:telegram.start()
    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse(status_code=404,content={'detail':'Resource not found'})
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse(status_code=400,content={'detail':str(exc)})
    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        crash_id=agent.crashes.capture(exc,{'method':request.method,'path':request.url.path});agent.metrics.increment('http_errors_total',status='500');return JSONResponse(status_code=500,content={'detail':'Internal error','crash_id':crash_id})
    if agent.settings.allowed_origins:
        app.add_middleware(CORSMiddleware,allow_origins=list(agent.settings.allowed_origins),allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
    hits:dict[str,deque]=defaultdict(deque)
    class TaskIn(BaseModel):
        prompt:str=Field(min_length=1,max_length=100_000)
        background:bool=True
        task_type:str|None=None
        model_id:str|None=None
    class ProviderIn(BaseModel):
        name:str=Field(min_length=1,max_length=100);kind:str;base_url:str|None=None;api_key:str|None=None;api_key_env:str|None=None;enabled:bool=True;priority:int=Field(default=100,ge=0,le=10000);config:dict={}
    class ProviderPatch(BaseModel):
        name:str|None=None;base_url:str|None=None;api_key:str|None=None;api_key_env:str|None=None;enabled:bool|None=None;priority:int|None=Field(default=None,ge=0,le=10000);config:dict|None=None
    class ModelIn(BaseModel):
        provider_id:str;model_id:str=Field(min_length=1,max_length=200);display_name:str|None=None;capabilities:list[str]=['text','tools'];context_window:int|None=None;price_input:float=Field(default=0,ge=0);price_output:float=Field(default=0,ge=0);enabled:bool=True;priority:int=Field(default=100,ge=0,le=10000);metadata:dict={}
    class ModelPatch(BaseModel):
        model_id:str|None=None;display_name:str|None=None;capabilities:list[str]|None=None;context_window:int|None=None;price_input:float|None=Field(default=None,ge=0);price_output:float|None=Field(default=None,ge=0);enabled:bool|None=None;priority:int|None=Field(default=None,ge=0,le=10000);metadata:dict|None=None
    class RuleIn(BaseModel):
        strategy:str='balanced';required_capabilities:list[str]=[];preferred_models:list[str]=[];max_cost_per_million:float|None=Field(default=None,ge=0)
    class SetupProviderIn(BaseModel):
        name:str=Field(min_length=1,max_length=100);kind:str;api_key:str|None=None;base_url:str|None=None;model_id:str=Field(min_length=1,max_length=200);display_name:str|None=None;capabilities:list[str]=['text','tools','code']
    def valid_token(value:str|None)->bool:
        configured=agent.settings.api_token
        return bool(configured and value and value.startswith('Bearer ') and hmac.compare_digest(value[7:],configured))
    def authorize(value:str|None):
        if not valid_token(value):raise HTTPException(401,'Valid bearer token required',headers={'WWW-Authenticate':'Bearer'})
    @app.middleware('http')
    async def limits(request:Request,call_next):
        started=time.monotonic()
        if request.url.path not in {'/health'}:
            key=request.client.host if request.client else 'unknown';now=time.monotonic();q=hits[key]
            while q and q[0]<now-60:q.popleft()
            if len(q)>=agent.settings.rate_limit_per_minute:raise HTTPException(429,'Rate limit exceeded')
            q.append(now)
        response=await call_next(request);agent.metrics.increment('http_requests_total',method=request.method,status=str(response.status_code),path=request.url.path);agent.metrics.set('last_http_latency_ms',round((time.monotonic()-started)*1000,3));response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='no-referrer';return response
    @app.on_event('shutdown')
    def shutdown():
        if telegram:telegram.stop()
        agent.close()
    @app.get('/v1/connectors')
    def connector_status(authorization:str|None=Header(default=None)):
        authorize(authorization);return {'telegram':{'enabled':bool(telegram),'mode':'long_polling'},'whatsapp':{'enabled':bool(whatsapp),'mode':'cloud_api_webhook'}}
    @app.get('/v1/connectors/whatsapp/webhook')
    def whatsapp_verify(request:Request):
        if not whatsapp:raise HTTPException(404,'WhatsApp connector is disabled')
        challenge=whatsapp.verify_webhook(request.query_params.get('hub.mode',''),request.query_params.get('hub.verify_token',''),request.query_params.get('hub.challenge',''))
        if challenge is None:raise HTTPException(403,'Webhook verification failed')
        return Response(content=challenge,media_type='text/plain')
    @app.post('/v1/connectors/whatsapp/webhook')
    async def whatsapp_webhook(request:Request,background_tasks:BackgroundTasks,x_hub_signature_256:str|None=Header(default=None)):
        if not whatsapp:raise HTTPException(404,'WhatsApp connector is disabled')
        body=await request.body()
        if not whatsapp.valid_signature(body,x_hub_signature_256):raise HTTPException(401,'Invalid webhook signature')
        try:payload=json.loads(body)
        except json.JSONDecodeError:raise HTTPException(400,'Invalid JSON')
        for sender,text,_ in whatsapp.extract_messages(payload):background_tasks.add_task(whatsapp.process,sender,text)
        return {'received':True}
    @app.get('/health')
    def health():return {'ok':True,'version':'1.6.0','provider':agent.settings.provider,'sandbox':agent.settings.sandbox_mode,'managed_models':len(agent.providers.list_models(enabled_only=True))}
    @app.get('/ready')
    def ready():
        migrations=agent.migrations.status();ready=all(x['ready'] for x in migrations);return JSONResponse(status_code=200 if ready else 503,content={'ready':ready,'migrations':migrations})
    @app.get('/metrics',response_class=PlainTextResponse)
    def metrics(authorization:str|None=Header(default=None)):authorize(authorization);return PlainTextResponse(agent.metrics.prometheus(),media_type='text/plain; version=0.0.4')
    @app.get('/v1/setup/status')
    def setup_status():return agent.setup.status(len(agent.providers.list_providers()))
    @app.post('/v1/setup/provider',status_code=201)
    def setup_provider(body:SetupProviderIn,authorization:str|None=Header(default=None)):
        authorize(authorization)
        from onboarding.providers import connect_provider_atomically
        result=connect_provider_atomically(agent.providers,agent.engine.provider,body.kind,body.api_key,body.base_url,body.model_id,body.capabilities,None,body.display_name)
        model=next((m for m in agent.providers.list_models() if m['id']==result['model_row_id']),None)
        return {'provider':agent.providers.get_provider(result['provider_id']),'model':model,'discovery':{'available':result['discovered'],'model_count':result['discovery_model_count'],'selected_model':result['model_id'],'used_fallback':result['used_fallback'],'error':result['discovery_error']}}
    @app.post('/v1/setup/complete')
    def setup_complete(authorization:str|None=Header(default=None)):
        authorize(authorization)
        if not agent.providers.list_providers():raise HTTPException(400,'Connect at least one provider before finishing setup')
        return agent.setup.complete()
    @app.get('/v1/diagnostics')
    def diagnostics(authorization:str|None=Header(default=None)):authorize(authorization);return agent.doctor.run(check_port=False)
    @app.get('/v1/capabilities')
    def capabilities(session_user:str='default',session_limit:int=30,activity_limit:int=25,authorization:str|None=Header(default=None)):
        """Capability-management overview for the dashboard (Phase 11).

        One bounded, read-only snapshot: per-tool readiness (registry +
        permissions + feature flags + optional deps), feature-flag state,
        computer-node state, recent sessions, internal subagent (worker)
        counts, MCP availability, and a small recent tool-activity tail.
        """
        authorize(authorization)
        from diagnostics.capability_state import snapshot
        return snapshot(
            agent,
            user=session_user or 'default',
            session_limit=max(1, min(int(session_limit), 200)),
            activity_limit=max(1, min(int(activity_limit), 200)),
        )
    @app.get('/v1/operations')
    def operations(authorization:str|None=Header(default=None)):authorize(authorization);return {'migrations':agent.migrations.status(),'backups':agent.backups.list(),'metrics':agent.metrics.snapshot()}
    @app.post('/v1/backups',status_code=201)
    def create_backup(authorization:str|None=Header(default=None)):authorize(authorization);return agent.backups.create('API backup')
    @app.post('/v1/backups/{backup_id}/verify')
    def verify_backup(backup_id:str,authorization:str|None=Header(default=None)):authorize(authorization);return agent.backups.verify(backup_id)
    @app.get('/v1/updates')
    def update_status(authorization:str|None=Header(default=None)):authorize(authorization);return agent.updates.status()
    @app.post('/v1/updates/check')
    def update_check(authorization:str|None=Header(default=None)):authorize(authorization);return agent.updates.check()
    @app.post('/v1/updates/stage')
    def update_stage(authorization:str|None=Header(default=None)):authorize(authorization);return agent.updates.stage()
    @app.get('/v1/deploy/options')
    def deploy_options(authorization:str|None=Header(default=None)):
        authorize(authorization);path=agent.settings.root_dir/'deployment'/'vps.json';options=json.loads(path.read_text());release_url=os.getenv('AIBA_RELEASE_URL','');release_sha=os.getenv('AIBA_RELEASE_SHA256','');configured=bool(release_url and release_sha)
        for item in options:item['ready']=configured;item['cloud_init_url']='/v1/deploy/cloud-init' if configured else None
        return {'configured':configured,'options':options,'message':None if configured else 'Set AIBA_RELEASE_URL and AIBA_RELEASE_SHA256 after publishing the GitHub Release to enable one-click VPS user-data.'}
    @app.get('/v1/deploy/cloud-init',response_class=PlainTextResponse)
    def cloud_init(authorization:str|None=Header(default=None)):
        authorize(authorization);release_url=os.getenv('AIBA_RELEASE_URL','');release_sha=os.getenv('AIBA_RELEASE_SHA256','')
        if not release_url or not release_sha:raise HTTPException(409,'Release URL and checksum are not configured')
        template=(agent.settings.root_dir/'deployment'/'cloud-init.sh').read_text();return PlainTextResponse(template.replace('{{AIBA_RELEASE_URL}}',release_url).replace('{{AIBA_RELEASE_SHA256}}',release_sha),headers={'Content-Disposition':'attachment; filename="aiba-cloud-init.sh"'})
    @app.post('/v1/tasks',status_code=202)
    def task(body:TaskIn,authorization:str|None=Header(default=None)):
        authorize(authorization)
        if body.background:return {'job_id':agent.queue.enqueue('agent_task',{'prompt':body.prompt,'task_type':body.task_type,'manual_model_id':body.model_id}),'status':'queued'}
        return {'status':'complete','result':agent.handle(body.prompt,task_type=body.task_type,manual_model_id=body.model_id),'route':agent.engine.provider.last_route}
    @app.get('/v1/jobs/{job_id}')
    def job(job_id:str,authorization:str|None=Header(default=None)):
        authorize(authorization);item=agent.queue.get(job_id)
        if not item:raise HTTPException(404,'Not found')
        return item
    @app.get('/v1/tasks/{task_id}')
    def task_status(task_id:str,authorization:str|None=Header(default=None)):
        authorize(authorization);item=agent.tasks.get(task_id)
        if not item:raise HTTPException(404,'Not found')
        return item
    @app.get('/v1/skills')
    def skills(authorization:str|None=Header(default=None)):authorize(authorization);return agent.skills.list()
    @app.get('/v1/providers/presets')
    def provider_presets(authorization:str|None=Header(default=None)):authorize(authorization);return agent.providers.presets()
    @app.get('/v1/providers')
    def providers(authorization:str|None=Header(default=None)):authorize(authorization);return agent.providers.list_providers()
    @app.post('/v1/providers',status_code=201)
    def add_provider(body:ProviderIn,authorization:str|None=Header(default=None)):
        authorize(authorization);i=agent.providers.add_provider(**body.model_dump());return agent.providers.get_provider(i)
    @app.patch('/v1/providers/{provider_id}')
    def update_provider(provider_id:str,body:ProviderPatch,authorization:str|None=Header(default=None)):
        authorize(authorization);agent.providers.update_provider(provider_id,**body.model_dump(exclude_unset=True));return agent.providers.get_provider(provider_id)
    @app.delete('/v1/providers/{provider_id}',status_code=204)
    def delete_provider(provider_id:str,authorization:str|None=Header(default=None)):authorize(authorization);agent.providers.delete_provider(provider_id)
    @app.post('/v1/providers/{provider_id}/test')
    def test_provider(provider_id:str,authorization:str|None=Header(default=None)):authorize(authorization);return agent.engine.provider.test_provider(provider_id)
    @app.get('/v1/providers/{provider_id}/discover-models')
    def discover_models(provider_id:str,authorization:str|None=Header(default=None)):authorize(authorization);return agent.engine.provider.discover_models(provider_id)
    @app.get('/v1/models')
    def models(authorization:str|None=Header(default=None)):authorize(authorization);return agent.providers.list_models()
    @app.post('/v1/models',status_code=201)
    def add_model(body:ModelIn,authorization:str|None=Header(default=None)):
        authorize(authorization);i=agent.providers.add_model(**body.model_dump());return next(x for x in agent.providers.list_models() if x['id']==i)
    @app.patch('/v1/models/{model_id}')
    def update_model(model_id:str,body:ModelPatch,authorization:str|None=Header(default=None)):
        authorize(authorization);agent.providers.update_model(model_id,**body.model_dump(exclude_unset=True));return next(x for x in agent.providers.list_models() if x['id']==model_id)
    @app.delete('/v1/models/{model_id}',status_code=204)
    def delete_model(model_id:str,authorization:str|None=Header(default=None)):authorize(authorization);agent.providers.delete_model(model_id)
    @app.get('/v1/routing/rules')
    def rules(authorization:str|None=Header(default=None)):authorize(authorization);return agent.providers.list_rules()
    @app.put('/v1/routing/rules/{task_type}')
    def set_rule(task_type:str,body:RuleIn,authorization:str|None=Header(default=None)):
        authorize(authorization);agent.providers.set_rule(task_type,**body.model_dump());return agent.providers.get_rule(task_type)
    @app.get('/v1/routing/preview')
    def route_preview(task_type:str='default',model_id:str|None=None,authorization:str|None=Header(default=None)):
        authorize(authorization);return {'task_type':task_type,'candidates':[{k:m[k] for k in ('id','provider_name','model_id','capabilities','price_input','price_output','provider_health')} for m in agent.engine.provider.candidates(task_type,model_id)]}
    @app.get('/v1/usage')
    def usage(days:int=30,authorization:str|None=Header(default=None)):authorize(authorization);return agent.providers.usage_summary(max(1,min(days,365)))
    @app.get('/',response_class=HTMLResponse)
    def dashboard():
        status=agent.setup.status(len(agent.providers.list_providers()));name='index.html' if status['complete'] else 'setup.html';return (agent.settings.root_dir/'dashboard'/name).read_text(encoding='utf-8')
    @app.websocket('/v1/events')
    async def events(ws:WebSocket):
        token=ws.headers.get('authorization') or ('Bearer '+ws.query_params.get('token','') if ws.query_params.get('token') else None)
        if not valid_token(token):await ws.close(code=4401);return
        await ws.accept();q:asyncio.Queue=asyncio.Queue(maxsize=100);loop=asyncio.get_running_loop()
        def handler(event):
            def put():
                if not q.full():q.put_nowait(event)
            loop.call_soon_threadsafe(put)
        agent.events.subscribe('*',handler)
        try:
            while True:await ws.send_json(await q.get())
        except WebSocketDisconnect:return
    return app

def run_server(agent,host=None,port=None):
    try:import uvicorn
    except ImportError as exc:raise RuntimeError('Install API dependencies: pip install -e .[api]') from exc
    host=host or agent.settings.api_host;port=port or agent.settings.api_port
    if host not in {'127.0.0.1','localhost','::1'} and not agent.settings.api_token:raise RuntimeError('AIBA_API_TOKEN is required when exposing the API beyond localhost')
    uvicorn.run(create_app(agent),host=host,port=port,proxy_headers=False,server_header=False)

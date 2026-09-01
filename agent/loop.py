from __future__ import annotations
from pathlib import Path
from config.settings import Settings
from security.audit import AuditLog
from security.policy import SecurityPolicy
from approvals.manager import ApprovalManager
from tools.base import Tool,ToolResult
from tools.sandbox import Sandbox
from tools.browser import browser_fetch
from tools.clarify import Clarify, ClarifyToolFactory
from tools.web import WebTools, build_web_tools
from tools.registry import ToolRegistry
from memory.vault import MemoryVault
from memory.retrieval import RetrievalEngine
from memory.dream import DreamEngine
from models.router import ModelRouter
from models.management import ProviderStore
from models.intelligent_router import IntelligentRouter
from reasoning.engine import ReasoningEngine
from agent.tasks import TaskStore
from runtime import EventBus,JobQueue,Worker,Scheduler,SchedulerRunner
from skills import SkillManager,SkillImprover
from computer import ComputerController
from vision import VisionAnalyzer
from threading import RLock
from onboarding import SetupManager
from diagnostics import Doctor
from updates import UpdateManager,UpdateChecker
from operations import BackupManager,MigrationManager,CrashReporter,Metrics
from personality import PersonalExperience
class AgentLoop:
    def __init__(self,settings=None,interactive=True,auto_approve=False,start_worker=True):
        self.settings=settings or Settings.load();self.audit=AuditLog(self.settings.logs_dir/'audit.jsonl');self.events=EventBus();self._run_lock=RLock();self.metrics=Metrics();self.crashes=CrashReporter(self.settings.logs_dir)
        self.approvals=ApprovalManager(interactive,auto_approve);self.policy=SecurityPolicy(self.settings.workspace_dir,self.settings.permissions_path,self.settings.require_approval)
        self.sandbox=Sandbox(self.settings.workspace_dir,self.settings.command_timeout,self.policy,self.settings.sandbox_mode,self.settings.docker_image,self.settings.docker_memory,self.settings.docker_cpus,self.settings.sandbox_network)
        self.vault=MemoryVault(self.settings.db_path,self.settings.vault_dir);self.tasks=TaskStore(self.settings.tasks_db_path);self.tasks.recover_interrupted()
        self.personal=PersonalExperience(self.settings.root_dir,self.settings.data_dir)
        self.queue=JobQueue(self.settings.jobs_db_path);self.scheduler=Scheduler(self.settings.schedules_db_path,self.queue)
        self.skills=SkillManager(self.settings.skills_dir);self.improver=SkillImprover(self.skills,self.settings.vault_dir/'skill_proposals')
        self.computer=ComputerController(self.settings.desktop_enabled);self.vision=VisionAnalyzer(self.settings.vision_model)
        self.clarify=Clarify(on_pending=self._on_clarify_pending)
        self.web_tools=build_web_tools(search_enabled=self.settings.web_enabled)
        from diagnostics.capabilities import load_manifest
        _mf=None
        try:_mf=load_manifest(self.settings.root_dir/'config'/'capability_manifest.json')
        except Exception:_mf=None
        self.manifest=_mf
        # Single authoritative runtime feature-flag map, built from Settings
        # booleans (never strings). Passed to the registry, capability_report,
        # and any readiness/doctor reporting so execution and reporting always
        # resolve the same flag state. For each flag listed in the manifest but
        # without a dedicated Settings bool, derive from the closest real
        # setting (e.g. AIBA_VISION_ENABLED from the configured vision model).
        self.runtime_flags: dict[str, bool] = {
            'AIBA_WEB_ENABLED': bool(self.settings.web_enabled),
            'AIBA_BROWSER_ENABLED': bool(self.settings.browser_enabled),
            'AIBA_DESKTOP_ENABLED': bool(self.settings.desktop_enabled),
            'AIBA_VISION_ENABLED': bool(self.settings.vision_model),
        }
        self.registry=ToolRegistry(self.audit,self.approvals,self.policy,feature_flags=self.runtime_flags,manifest=self.manifest);self._register_tools()
        legacy=ModelRouter(ModelRouter.build(self.settings.provider,self.settings.model),ModelRouter.build(self.settings.fallback_provider,self.settings.fallback_model));self.providers=ProviderStore(self.settings.providers_db_path);self.setup=SetupManager(self.settings.root_dir,self.settings.data_dir);self.doctor=Doctor(self.settings,self.providers);self.updates=UpdateManager(self.settings.root_dir,self.settings.data_dir);self.update_checker=UpdateChecker(self.updates);self.migrations=MigrationManager(self.settings.data_dir);self.migrations.apply();self.backups=BackupManager(self.settings.data_dir)
        self._seed_legacy_provider();router=IntelligentRouter(self.providers,legacy)
        self.engine=ReasoningEngine(router,self.registry,RetrievalEngine(self.vault),self.tasks,self.settings.max_steps);self.dream=DreamEngine(self.settings.vault_dir/'reflections',self.vault)
        self.worker=Worker(self.queue,{'agent_task':lambda payload:{'result':self.handle(payload['prompt'],propose_skill=False,task_type=payload.get('task_type'),manual_model_id=payload.get('manual_model_id'))}});self.scheduler_runner=SchedulerRunner(self.scheduler)
        if start_worker and self.settings.worker_enabled:self.worker.start();self.scheduler_runner.start();self.update_checker.start()
        self.events.subscribe('*',lambda e:self.audit.record('event',**e))
    def _on_clarify_pending(self, q):
        """A clarify question went pending awaiting async delivery. Publish it
        on the event bus so any connector can render it (e.g. Telegram inline
        buttons) and answer via ``self.clarify.answer(id, choice)``."""
        try:
            self.events.publish(
                "clarify.pending",
                question_id=q.id,
                question=q.question,
                options=q.options,
            )
            self.audit.record("clarify_pending", question_id=q.id, question=q.question)
        except Exception:
            pass

    def _register_tools(self):
        self.registry.register(Tool('list_files','List workspace files.',self.sandbox.list_files,{'type':'object','properties':{'path':{'type':'string'}},'additionalProperties':False}))
        self.registry.register(Tool('read_file','Read workspace text.',self.sandbox.read_file,{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}))
        self.registry.register(Tool('write_file','Write workspace text.',self.sandbox.write_file,{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content'],'additionalProperties':False}))
        self.registry.register(Tool('delete_file','Delete workspace file.',self.sandbox.delete_file,{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}))
        self.registry.register(Tool('patch_file','Apply a find-and-replace edit to a workspace text file, atomically, and return the diff.',self.sandbox.patch_file,{'type':'object','properties':{'path':{'type':'string'},'old':{'type':'string'},'new':{'type':'string'},'replace_all':{'type':'boolean'}},'required':['path','old','new'],'additionalProperties':False}))
        self.registry.register(Tool('archive','Create a zip or tarball of a workspace path, written inside the workspace.',self.sandbox.archive,{'type':'object','properties':{'path':{'type':'string'},'format':{'type':'string'},'name':{'type':'string'}},'required':['path'],'additionalProperties':False}))
        self.registry.register(Tool('extract_archive','Extract a zip/tar archive into a workspace destination, blocking zip-slip.',self.sandbox.extract_archive,{'type':'object','properties':{'path':{'type':'string'},'dest':{'type':'string'}},'required':['path'],'additionalProperties':False}))
        self.registry.register(Tool('run_shell','Run command in sandbox.',self.sandbox.run_shell,{'type':'object','properties':{'command':{'type':'string'}},'required':['command'],'additionalProperties':False}))
        self.registry.register(Tool('run_python','Run Python in sandbox.',self.sandbox.run_python,{'type':'object','properties':{'code':{'type':'string'}},'required':['code'],'additionalProperties':False}))
        for wt in self.web_tools:self.registry.register(wt)
        self.registry.register(Tool('remember','Store durable memory.',lambda content,category='general',importance=.5:ToolResult(True,{'memory_id':self.vault.add(content,category,importance)}),{'type':'object','properties':{'content':{'type':'string'},'category':{'type':'string'},'importance':{'type':'number'}},'required':['content'],'additionalProperties':False}))
        self.registry.register(Tool('search_memory','Search memory.',lambda query,limit=5:ToolResult(True,self.vault.search(query,int(limit))),{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query'],'additionalProperties':False}))
        self.registry.register(Tool('browser_fetch','Fetch rendered webpage text.',browser_fetch,{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_screenshot','Capture desktop screenshot.',lambda path='desktop.png':self.computer.screenshot(str(self.settings.workspace_dir/path)),{'type':'object','properties':{'path':{'type':'string'}},'additionalProperties':False}))
        self.registry.register(Tool('desktop_click','Click screen coordinates.',self.computer.click,{'type':'object','properties':{'x':{'type':'integer'},'y':{'type':'integer'}},'required':['x','y'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_type','Type text into active window.',self.computer.type_text,{'type':'object','properties':{'text':{'type':'string'},'interval':{'type':'number'}},'required':['text'],'additionalProperties':False}))
        self.registry.register(Tool('vision_analyze','Analyze a workspace image.',lambda image_path,instruction='Describe actionable interface elements.':self.vision.analyze(str(self.sandbox.resolve(image_path)),instruction),{'type':'object','properties':{'image_path':{'type':'string'},'instruction':{'type':'string'}},'required':['image_path'],'additionalProperties':False}))
        self.registry.register(Tool('list_skills','List reusable skills.',lambda:ToolResult(True,self.skills.list()),{'type':'object','properties':{},'additionalProperties':False}))
        self.registry.register(Tool('skill_instructions','Read a reviewed portable skill instruction contract.',lambda name:ToolResult(True,self.skills.instructions(name)),{'type':'object','properties':{'name':{'type':'string'}},'required':['name'],'additionalProperties':False}))
        self.registry.register(Tool('run_skill','Run a reviewed reusable skill.',lambda name,variables=None:ToolResult(True,self.skills.execute(name,self.registry,variables or {})),{'type':'object','properties':{'name':{'type':'string'},'variables':{'type':'object'}},'required':['name'],'additionalProperties':False}))
        self.registry.register(ClarifyToolFactory.make(self.clarify))
        self.registry.register(Tool('enqueue_task','Queue a background task.',lambda prompt:ToolResult(True,{'job_id':self.queue.enqueue('agent_task',{'prompt':prompt})}),{'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt'],'additionalProperties':False}))
        self.registry.register(Tool('schedule_task','Schedule a recurring task.',lambda name,prompt,interval_seconds:ToolResult(True,{'schedule_id':self.scheduler.add_interval(name,'agent_task',{'prompt':prompt},int(interval_seconds))}),{'type':'object','properties':{'name':{'type':'string'},'prompt':{'type':'string'},'interval_seconds':{'type':'integer'}},'required':['name','prompt','interval_seconds'],'additionalProperties':False}))
    def _seed_legacy_provider(self):
        if self.providers.list_providers() or self.settings.provider=='local':return
        kind='custom' if self.settings.provider=='openai_compatible' else self.settings.provider
        provider_id=self.providers.add_provider(kind.title(),kind,api_key_env={'openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY','ollama':''}.get(kind,''))
        self.providers.add_model(provider_id,self.settings.model,capabilities=['text','tools','code'],priority=100)
        self.providers.set_rule('default','balanced',['text','tools'],[self.providers.list_models()[0]['id']])
    def handle(self,text,propose_skill=True,task_type=None,manual_model_id=None,user_id=None,onboard=False):
        if not isinstance(text,str) or not text.strip():raise ValueError('Task prompt cannot be empty')
        if len(text)>100_000:raise ValueError('Task prompt exceeds 100,000 characters')
        if onboard and user_id:
            intercepted=self.personal.intercept(user_id,text)
            if intercepted is not None:return intercepted
        with self._run_lock:return self._handle(text.strip(),propose_skill,task_type,manual_model_id,user_id)
    def start_conversation(self,user_id):return self.personal.start_conversation(user_id)
    def _handle(self,text,propose_skill=True,task_type=None,manual_model_id=None,user_id=None):
        from reasoning.protocol import VisibleReasoning
        task_id=self.tasks.create(text);self.events.publish('task_started',task_id=task_id,task=text)
        self.engine._reasoning=VisibleReasoning(self.events.publish,task_id)
        self.engine._reasoning.plan(f"Task accepted: {text[:80]}", steps=self.engine.max_steps)
        try:answer,used=self.engine.run(task_id,text,task_type,manual_model_id,self.personal.prompt_context(user_id),blocked_tools=self.personal.blocked_tools(user_id));self.tasks.finish(task_id,answer);status='complete'
        except Exception as exc:
            crash_id=self.crashes.capture(exc,{'task_id':task_id});self.metrics.increment('task_failures_total',error=type(exc).__name__);answer=f'AIBA task failed [{crash_id}]: {type(exc).__name__}: {exc}';used=[];status='failed';self.tasks.finish(task_id,answer,status)
        ref=self.dream.reflect(task_id,text,answer,used);proposal=self.improver.propose(task_id,text,used,answer) if propose_skill and used else None
        self.metrics.increment('tasks_total',status=status);self.events.publish('task_finished',task_id=task_id,status=status,tools=used,reflection=str(ref),skill_proposal=str(proposal) if proposal else None);return answer
    def capability_report(self, runtime_flags=None):
        """Return a live per-tool capability report (see diagnostics/capabilities).

        Merges the manifest, the run-time permissions policy, and the live
        registry so callers can see, for every tool: registered / listed /
        enabled / approval / feature flag / ready + the actionable reason it
        is unavailable. Never silently advertises a dormant tool.

        The report resolves feature flags from the same authoritative runtime
        map used by the registry (self.runtime_flags), so reporting and
        execution always agree. ``runtime_flags`` overrides that map for
        tests; it must carry booleans.
        """
        from diagnostics.capabilities import build_report
        perm = self.policy.config
        registered = set(self.registry._tools.keys())
        flags = dict(self.runtime_flags)
        if runtime_flags:
            flags.update(runtime_flags)
        return build_report(self.manifest, perm, registered, flag_overrides=flags)

    def close(self):
        self.worker.stop();self.scheduler_runner.stop();self.update_checker.stop()
    def run(self):
        print(f'AIBA Agent v1.5 | routing=auto | sandbox={self.settings.sandbox_mode} | /exit to quit')
        while True:
            try:text=input('You> ').strip()
            except (EOFError,KeyboardInterrupt):print();break
            if text in {'/exit','/quit'}:break
            if text:print('AIBA>',self.handle(text))
        self.close()

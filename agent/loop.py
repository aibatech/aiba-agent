from __future__ import annotations
from pathlib import Path
from contextvars import ContextVar
from config.settings import Settings
from security.audit import AuditLog
from security.policy import SecurityPolicy
from approvals.manager import ApprovalManager
from tools.base import Tool,ToolResult
from tools.sandbox import Sandbox
from tools.browser import browser_fetch
from tools.browser_session import BrowserSession, build_browser_tools
from tools.clarify import Clarify, ClarifyToolFactory
from tools.web import WebTools, build_web_tools
from tools.media import MediaExtraction, build_media_tools
from tools.registry import ToolRegistry
from memory.vault import MemoryVault, SHARED
from memory.retrieval import RetrievalEngine
from memory.dream import DreamEngine
from models.router import ModelRouter
from models.management import ProviderStore
from models.intelligent_router import IntelligentRouter
from reasoning.engine import ReasoningEngine
from agent.tasks import TaskStore
from runtime import EventBus,JobQueue,Worker,Scheduler,SchedulerRunner
from skills import SkillManager,SkillImprover
from computer import ComputerController, make_computer
from vision import VisionAnalyzer

# Phase 7 MCP optional client. Safe to import unconditionally: the PyPI `mcp`
# SDK is only ever imported lazily inside mcp_client.client methods, so a base
# install without the [mcp] extra remains unaffected. The package name
# ``mcp_client`` (underscore) intentionally does not shadow the ``mcp`` SDK.
from mcp_client.client import MCPClientController
from threading import RLock
from onboarding import SetupManager
from diagnostics import Doctor
from updates import UpdateManager,UpdateChecker
from operations import BackupManager,MigrationManager,CrashReporter,Metrics
from personality import PersonalExperience
from agent.subagent_manager import SubagentManager
from agent.sessions import SessionStore
class AgentLoop:
    @property
    def _current_user(self):
        return self._user_context.get()

    @_current_user.setter
    def _current_user(self, value):
        self._user_context.set(value or 'default')

    def __init__(self,settings=None,interactive=True,auto_approve=False,start_worker=True):
        self.settings=settings or Settings.load();self.audit=AuditLog(self.settings.logs_dir/'audit.jsonl');self.events=EventBus();self._run_lock=RLock();self.metrics=Metrics();self.crashes=CrashReporter(self.settings.logs_dir)
        self.approvals=ApprovalManager(interactive,auto_approve);self.policy=SecurityPolicy(self.settings.workspace_dir,self.settings.permissions_path,self.settings.require_approval)
        self.sandbox=Sandbox(self.settings.workspace_dir,self.settings.command_timeout,self.policy,self.settings.sandbox_mode,self.settings.docker_image,self.settings.docker_memory,self.settings.docker_cpus,self.settings.sandbox_network)
        self.vault=MemoryVault(self.settings.db_path,self.settings.vault_dir);self.tasks=TaskStore(self.settings.tasks_db_path);self.tasks.recover_interrupted()
        # Session history (Phase 9): per-user chronological log with FTS search,
        # auto-populated as top-level handled turns complete. DB lives under
        # data_dir unless settings.sessions_db_path overrides it (tests do).
        self.sessions=SessionStore(self.settings.sessions_db_path or (self.settings.data_dir/'sessions.db'))
        # Ambient user for session-search read tools (set per handled turn). The
        # session/memory read tools scope to whoever last drove a handled turn.
        self._user_context=ContextVar('aiba_user', default='default')
        self._current_user='default'
        # Authorized single-owner/admin identity keys for the memory vault.
        # Only these (plus the unnamed 'default'/'None' operator) act unscoped
        # (full view incl 'shared'/legacy records); every other authenticated
        # identity is scoped strictly to its OWN rows and never sees 'shared'.
        self._owner_users = getattr(self.settings, 'memory_owner_users', None) or frozenset({'default'})
        self._owner_users = frozenset(self._owner_users) | {'default'}
        self.personal=PersonalExperience(self.settings.root_dir,self.settings.data_dir)
        self.queue=JobQueue(self.settings.jobs_db_path);self.scheduler=Scheduler(self.settings.schedules_db_path,self.queue)
        self.skills=SkillManager(self.settings.skills_dir);self.improver=SkillImprover(self.skills,self.settings.vault_dir/'skill_proposals')
        self.computer_node, self.computer = make_computer(self.settings, self.audit)  # gate + controller
        self.vision=VisionAnalyzer(self.settings.vision_model)
        self.clarify=Clarify(on_pending=self._on_clarify_pending)
        self.web_tools=build_web_tools(search_enabled=self.settings.web_enabled)
        # Read-only document/text extraction (Phase 8). Reads workspace files
        # confined through the Sandbox; optional [media] libs enable PDF/DOCX/
        # XLSX/PPTX parsing, otherwise each returns an "install optional
        # support" diagnostic. Never writes. Registry advertises/denies based
        # on the AIBA_MEDIA_ENABLED feature flag below.
        self.media=MediaExtraction(self.sandbox)
        # Opt-in persistent browser automation. Disabled until AIBA_BROWSER_ENABLED
        # is true; downloads/uploads are confined to the workspace. Mutations
        # (click/type/select/submit/download/upload) carry requires_approval in
        # permissions.json and are further gated off sensitive pages.
        self.browser=BrowserSession(
            enabled=bool(self.settings.browser_enabled),
            workspace=self.settings.workspace_dir,
            audit=self.audit,
            sensitive_actions=False,
            secret_typing=False,
        )
        # Phase 7 MCP optional client (single gated `mcp_call` tool). Disabled
        # by default on three independent axes (settings flag / permissions.json
        # / manifest feature flag), inert until an operator opts in AND lists an
        # enabled, allowlisted server in config/mcp_servers.json. Per-remote-tool
        # operator approvals route through the same ApprovalManager as AIBA's
        # own dangerous tools.
        self.mcp=MCPClientController(
            enabled=bool(self.settings.mcp_enabled),
            root_dir=self.settings.root_dir,
            audit=self.audit,
            approver=self.approvals.approve,
        )
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
            'AIBA_SUBAGENTS_ENABLED': bool(self.settings.subagents_enabled),
            'AIBA_MEDIA_ENABLED': bool(self.settings.media_enabled),
            'AIBA_MCP_ENABLED': bool(self.settings.mcp_enabled),
        }
        self.registry=ToolRegistry(self.audit,self.approvals,self.policy,feature_flags=self.runtime_flags,manifest=self.manifest);self._register_tools()
        legacy=ModelRouter(ModelRouter.build(self.settings.provider,self.settings.model),ModelRouter.build(self.settings.fallback_provider,self.settings.fallback_model));self.providers=ProviderStore(self.settings.providers_db_path);self.setup=SetupManager(self.settings.root_dir,self.settings.data_dir);self.doctor=Doctor(self.settings,self.providers);self.updates=UpdateManager(self.settings.root_dir,self.settings.data_dir);self.update_checker=UpdateChecker(self.updates);self.migrations=MigrationManager(self.settings.data_dir);self.migrations.apply();self.backups=BackupManager(self.settings.data_dir)
        self._seed_legacy_provider();self.router=IntelligentRouter(self.providers,legacy)
        self.engine=ReasoningEngine(self.router,self.registry,RetrievalEngine(self.vault),self.tasks,self.settings.max_steps);self.dream=DreamEngine(self.settings.vault_dir/'reflections',self.vault)
        # Opt-in bounded internal subagents (Phase 3). Disabled until
        # AIBA_SUBAGENTS_ENABLED; workers are permission-narrowed, non-recursive
        # and budgeted. Uses the same registry (tool metadata/handlers), policy,
        # audit, event bus and provider router as the main agent.
        self.subagents=SubagentManager(
            self.settings.subagents_db_path or (self.settings.data_dir/'subagents.db'),
            enabled=bool(self.settings.subagents_enabled),
            audit=self.audit,
            events=self.events,
            resolve_tools=self._subagent_resolve_tools,
            call_provider=self._subagent_call_provider,
            policy_allows=self._subagent_policy_allows,
            global_concurrency=int(self.settings.subagent_global_concurrency),
            per_parent_concurrency=int(self.settings.subagent_per_parent_concurrency),
            step_cap_default=int(self.settings.max_steps),
            time_limit_default=int(max(self.settings.command_timeout*4, 120)),
        )
        self.worker=Worker(self.queue,{'agent_task':lambda payload:{'result':self.handle(payload['prompt'],propose_skill=False,task_type=payload.get('task_type'),manual_model_id=payload.get('manual_model_id'),user_id=payload.get('user_id'))}});self.scheduler_runner=SchedulerRunner(self.scheduler)
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

    # -- memory ownership (identity-derived scope; v1.6 Gap 2) ---------------
    def _is_operator(self, user_key: str | None) -> bool:
        """Whether an authenticated identity is the authorized single-owner /
        admin. None / 'default' (local API/CLI/queued work) is always operator;
        beyond that only keys that appear in the explicit memory-admin list
        (Settings.memory_owner_users) are operators. Consumers determine the
        acting identity; it is never trusted from a model tool argument."""
        key = user_key or self._current_user or 'default'
        return key == 'default' or key in getattr(self, '_owner_users', frozenset({'default'}))

    def _memory_scope(self, user_key: str | None = None) -> str | None:
        """Resolve the vault read scope from the authenticated identity always.
        Operator/admin -> None (unscoped full view incl 'shared'/legacy).
        Any other (non-operator) identity -> its OWN key only (strict isolation;
        'shared' and other users' rows are never visible)."""
        if self._is_operator(user_key):
            return None
        return user_key or self._current_user or 'default'

    def _memory_writer_owner(self, user_key: str | None = None) -> str:
        """Resolve the owner tag for a WRITE from the authenticated identity.
        Operator writes land in 'shared' (operator-global, matching legacy
        reflections so single-operator memory never fragments across channels);
        a non-operator write is tagged to that identity's key only."""
        return SHARED if self._is_operator(user_key) else (self._memory_scope(user_key) or SHARED)

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
        # Read-only document/text extraction (Phase 8). Availability (advertised
        # or denied) follows the AIBA_MEDIA_ENABLED manifest feature flag; each
        # format parser reports an "install optional support" diagnostic when a
        # needed [media] library is absent.
        for mt in build_media_tools(self.media):self.registry.register(mt)
        # Memory tools derive OWNERSHIP from the authenticated identity
        # (self._current_user, set in _handle from the connector/API user), NOT
        # from any model-supplied argument. Operators/admin act unscoped
        # (full view incl 'shared'/legacy); a distinct non-operator identity is
        # confined to its own rows for reads and mutations alike — it can never
        # read, search, export, update or delete 'shared'/another user's memory.
        self.registry.register(Tool('remember','Store durable memory.',lambda content,category='general',importance=.5:ToolResult(True,{'memory_id':self.vault.add(content,category,importance,owner=self._memory_writer_owner())}),{'type':'object','properties':{'content':{'type':'string'},'category':{'type':'string'},'importance':{'type':'number'}},'required':['content'],'additionalProperties':False}))
        self.registry.register(Tool('search_memory','Search memory.',lambda query,limit=5:ToolResult(True,self.vault.search(query,int(limit),as_user=self._memory_scope())),{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query'],'additionalProperties':False}))
        # --- Memory maintenance + session search (Phase 9) ---
        # Memory edits/mutations mirror write_file/delete_file approval posture.
        self.registry.register(Tool('update_memory','Edit an existing memory row by id.',lambda memory_id,content=None,category=None,importance=None:ToolResult(True,self.vault.update(int(memory_id),content,category,None if importance is None else float(importance),as_user=self._memory_scope())),{'type':'object','properties':{'memory_id':{'type':'integer'},'content':{'type':'string'},'category':{'type':'string'},'importance':{'type':'number'}},'required':['memory_id'],'additionalProperties':False}))
        self.registry.register(Tool('delete_memory','Delete a memory row by id (destructive).',lambda memory_id:ToolResult(self.vault.remove(int(memory_id),as_user=self._memory_scope())),{'type':'object','properties':{'memory_id':{'type':'integer'}},'required':['memory_id'],'additionalProperties':False}))
        self.registry.register(Tool('list_memories','List stored memories, optionally filtered by category.',lambda limit=50,category=None:ToolResult(True,self.vault.list(int(limit),category,as_user=self._memory_scope())),{'type':'object','properties':{'limit':{'type':'integer'},'category':{'type':'string'}},'additionalProperties':False}))
        self.registry.register(Tool('export_memories','Export memories (optionally one category) to a markdown file in the workspace.',lambda filename='memories_export.md',category=None:ToolResult(True,self._export_memories(str(filename),category,self._memory_scope())),{'type':'object','properties':{'filename':{'type':'string'},'category':{'type':'string'}},'additionalProperties':False}))
        self.registry.register(Tool('session_search','Search past AIBA task/session history (this user only); never returns internal deliberation.',lambda query,limit=10:ToolResult(True,self.sessions.search((self._current_user or 'default'),query,int(limit))),{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query'],'additionalProperties':False}))
        self.registry.register(Tool('session_history','List recent AIBA sessions for this user.',lambda limit=20:ToolResult(True,self.sessions.list_by_user((self._current_user or 'default'),int(limit))),{'type':'object','properties':{'limit':{'type':'integer'}},'additionalProperties':False}))
        self.registry.register(Tool('browser_fetch','Fetch rendered webpage text.',browser_fetch,{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False}))
        for bt in build_browser_tools(self.browser):self.registry.register(bt)
        def _desktop_screenshot(path: str = "desktop.png") -> ToolResult:
            # Confine the screenshot target inside the sandbox workspace using the
            # same policy-authorized resolution as read/write_file, so a `..` or
            # absolute path from the model can never escape the workspace. Return a
            # clean denial rather than raising through the registry.
            try:
                dest = self.sandbox.resolve(str(path))
            except Exception as exc:
                return ToolResult(False, error=f"Workspace-confined path required for screenshot: {exc}")
            return self.computer.screenshot(str(dest))
        self.registry.register(Tool('desktop_screenshot','Capture desktop screenshot into the workspace.',_desktop_screenshot,{'type':'object','properties':{'path':{'type':'string'}},'additionalProperties':False}))
        self.registry.register(Tool('desktop_click','Click screen coordinates.',self.computer.click,{'type':'object','properties':{'x':{'type':'integer'},'y':{'type':'integer'},'button':{'type':'string'},'clicks':{'type':'integer'}},'required':['x','y'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_type','Type text into active window (secret-like text is not logged).',self.computer.type_text,{'type':'object','properties':{'text':{'type':'string'},'interval':{'type':'number'}},'required':['text'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_screen_size','Report the desktop screen size in pixels.',lambda: self.computer.screen_size(),{'type':'object','properties':{},'additionalProperties':False}))
        self.registry.register(Tool('desktop_move','Move the pointer to screen coordinates.',self.computer.move,{'type':'object','properties':{'x':{'type':'integer'},'y':{'type':'integer'},'duration':{'type':'number'}},'required':['x','y'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_drag','Drag between two points.',self.computer.drag,{'type':'object','properties':{'from_x':{'type':'integer'},'from_y':{'type':'integer'},'to_x':{'type':'integer'},'to_y':{'type':'integer'},'duration':{'type':'number'},'button':{'type':'string'}},'required':['from_x','from_y','to_x','to_y'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_scroll','Scroll the focused window.',self.computer.scroll,{'type':'object','properties':{'clicks':{'type':'integer'},'x':{'type':'integer'},'y':{'type':'integer'}},'required':['clicks'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_key','Press a single key.',self.computer.keypress,{'type':'object','properties':{'key':{'type':'string'}},'required':['key'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_hotkey','Press a modifier hotkey (e.g. ctrl+c).',lambda keys:self.computer.hotkey(*keys),{'type':'object','properties':{'keys':{'type':'array','items':{'type':'string'}}},'required':['keys'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_open_url','Open an http(s) URL in the default browser.',lambda url:self.computer.open_url(url),{'type':'object','properties':{'url':{'type':'string'}},'required':['url'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_clipboard_read','Read clipboard (opt-in).',lambda: self.computer.clipboard_read(),{'type':'object','properties':{},'additionalProperties':False}))
        self.registry.register(Tool('desktop_clipboard_write','Set clipboard to a string.',lambda text:self.computer.clipboard_write(text),{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}))
        self.registry.register(Tool('desktop_node_status','Report node pairing + remaining budget.',lambda: ToolResult(True,self.computer_node.status()),{'type':'object','properties':{},'additionalProperties':False}))
        self.registry.register(Tool('vision_analyze','Analyze a workspace image.',lambda image_path,instruction='Describe actionable interface elements.':self.vision.analyze(str(self.sandbox.resolve(image_path)),instruction),{'type':'object','properties':{'image_path':{'type':'string'},'instruction':{'type':'string'}},'required':['image_path'],'additionalProperties':False}))
        self.registry.register(Tool('list_skills','List reusable skills.',lambda:ToolResult(True,self.skills.list()),{'type':'object','properties':{},'additionalProperties':False}))
        self.registry.register(Tool('skill_instructions','Read a reviewed portable skill instruction contract.',lambda name:ToolResult(True,self.skills.instructions(name)),{'type':'object','properties':{'name':{'type':'string'}},'required':['name'],'additionalProperties':False}))
        self.registry.register(Tool('run_skill','Run a reviewed reusable skill.',lambda name,variables=None:ToolResult(True,self.skills.execute(name,self.registry,variables or {})),{'type':'object','properties':{'name':{'type':'string'},'variables':{'type':'object'}},'required':['name'],'additionalProperties':False}))
        self.registry.register(ClarifyToolFactory.make(self.clarify))
        self.registry.register(Tool('enqueue_task','Queue a background task.',lambda prompt:ToolResult(True,{'job_id':self.queue.enqueue('agent_task',{'prompt':prompt,'user_id':self._current_user})}),{'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt'],'additionalProperties':False}))
        self.registry.register(Tool('schedule_task','Schedule a recurring task.',lambda name,prompt,interval_seconds:ToolResult(True,{'schedule_id':self.scheduler.add_interval(name,'agent_task',{'prompt':prompt,'user_id':self._current_user},int(interval_seconds))}),{'type':'object','properties':{'name':{'type':'string'},'prompt':{'type':'string'},'interval_seconds':{'type':'integer'}},'required':['name','prompt','interval_seconds'],'additionalProperties':False}))
        # Internal subagents (Phase 3): the ONLY model-advertised entry point.
        # It spawns bounded, permission-narrowed, non-recursive background
        # workers in parallel, waits (bounded), and returns concise structured
        # results + a synthesis. Unsafe status/cancellation operations are kept
        # OFF the model surface (internal API: self.subagents). Gated by feature
        # flag AIBA_SUBAGENTS_ENABLED + permissions.json.
        self.registry.register(Tool('delegate_task','Run bounded internal background workers in parallel for research/verification/planning/review. Provide a list of concrete, self-contained objectives.',
            lambda objectives, tools=None, allow_approved=False, wait_s=120: self._delegate_subagents(objectives, allowed_tools=tools, allow_approved=bool(allow_approved), wait_s=float(wait_s)),
            {'type':'object','properties':{'objectives':{'type':'array','items':{'type':'string'}},'tools':{'type':'array','items':{'type':'string'}},'wait_s':{'type':'number'}},'required':['objectives'],'additionalProperties':False}))
        # Phase 7 MCP optional client: single gated `mcp_call` gateway tool.
        # Not advertised/callable until AIBA_MCP_ENABLED is set (settings +
        # manifest feature flag) AND `mcp_call` is enabled in permissions.json
        # AND an allowlisted server exists in config/mcp_servers.json. The
        # controller fail-closes on every one of those before any process or
        # network is touched; remote (http) servers additionally need
        # AIBA_MCP_REMOTE. Remote tool allow/deny never ships to the model here —
        # the model sees one tool, server_id, tool name + args.
        self.registry.register(Tool('mcp_call','Call a tool on an operator-configured external MCP server. Pass server_id (the configured server key), tool (the server-side tool name), and arguments (a JSON object). Only servers and tools the operator has allowlisted are reachable; MCP is off by default.',self.mcp.execute,{'type':'object','properties':{'server_id':{'type':'string'},'tool':{'type':'string'},'arguments':{'type':'object'}},'required':['server_id','tool'],'additionalProperties':False}))
    # -- internal subagent bridges -------------------------------------------
    def _subagent_policy_allows(self, name: str) -> bool:
        """Apply the same availability and conversation policy as the parent."""
        try:
            return not self.registry._availability(name) and not self.registry.blocked(
                name, self.personal.blocked_tools(self._current_user))
        except Exception:
            return False

    def _subagent_resolve_tools(self, names: list[str]):
        """Expose registered tool metadata + handlers for a worker's narrowed
        set. Only tools already registered on the MAIN registry are returned, so
        a worker can never broaden beyond the main agent's own tool surface."""
        out = {}
        for name in names:
            tool = self.registry._tools.get(name)
            if tool is None or not self._subagent_policy_allows(name):
                continue
            req = False
            try:
                req = bool(self.policy.check_tool(name).requires_approval)
            except Exception:
                req = True
            out[name] = {
                "description": tool.description,
                "parameters": tool.parameters,
                # Delegation consent permits offering a tool, not approving
                # every future action. Recheck policy, schema, and the actual
                # action's approval at dispatch, including after policy changes.
                "handler": self._subagent_handler(name),
                "requires_approval": req,
            }
        return out

    def _subagent_handler(self, name):
        user_key = self._current_user
        def run(**arguments):
            token = self._user_context.set(user_key)
            try:
                return self.registry.execute(name, arguments,
                    blocked=self.personal.blocked_tools(user_key))
            finally:
                self._user_context.reset(token)
        return run

    def _subagent_call_provider(self, messages, schemas) -> str:
        """Run one provider call for a worker through the shared router."""
        try:
            return str(self.router.complete(messages, schemas or []))
        except Exception as exc:
            return f"provider_error: {type(exc).__name__}: {exc}"

    def _delegate_subagents(self, objectives, allowed_tools=None,
                            allow_approved=False, wait_s: float = 120.0):
        """Create + run N internal workers in parallel and return concise
        structured results + a synthesis text (used by the delegate_task tool)."""
        if isinstance(objectives, str):
            objectives = [objectives]
        objectives = [o for o in (objectives or []) if isinstance(o, str) and o.strip()]
        if not objectives:
            return ToolResult(False, error="No subagent objectives provided.")
        effective_tools = list(allowed_tools or []) if allowed_tools else None
        out = self.subagents.run_many(
            objectives,
            parent_task_id=None,
            allowed_tools=effective_tools or [],
            allow_approved=bool(allow_approved),
            wait_s=float(wait_s),
        )
        results = out.get("results", [])
        pending = out.get("pending", [])
        synthesis = self.subagents.synthesize(results)
        # Emit a concise structured payload so the main AIBA can form its final
        # synthesis. No prompts / transcripts / internal deliberation included.
        summary = {
            "worker_count": len(results),
            "worker_results": results,
            "still_pending": pending,
            "synthesis": synthesis,
        }
        self.subagents._audit_record("synthesis", worker_count=len(results),
                                     pending=len(pending))
        if pending:
            summary["note"] = ("Some workers were still running when the wait "
                               "budget elapsed; check them via status.")
        return ToolResult(True, summary)

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
        with self._run_lock:
            token = self._user_context.set(user_id or 'default')
            try:
                return self._handle(text.strip(),propose_skill,task_type,manual_model_id,user_id)
            finally:
                self._user_context.reset(token)
    def start_conversation(self,user_id):return self.personal.start_conversation(user_id)
    def _handle(self,text,propose_skill=True,task_type=None,manual_model_id=None,user_id=None):
        from reasoning.protocol import VisibleReasoning
        task_id=self.tasks.create(text);self.events.publish('task_started',task_id=task_id,task=text)
        # Session history (Phase 9): best-effort per-turn log row. Never stores
        # deliberation; a concise sanitised title/summary only. Failures to
        # persist must never break the handled task.
        user_key=(user_id or 'default')
        self._current_user=user_key
        # Scope model-context memory retrieval to the authenticated identity so
        # injected 'Relevant memory' can never cross into another principal's
        # rows or 'shared' unless this IS the authorized single-owner/admin.
        engine_scope = self._memory_scope(user_id)
        try:
            if getattr(self.engine, 'retrieval', None) is not None:
                self.engine.retrieval.scope = engine_scope
        except Exception:
            pass
        _sid=None
        try:_sid=self.sessions.open_session(user_key,title=(text[:120] or ''),kind='turn')
        except Exception:_sid=None
        self.engine._reasoning=VisibleReasoning(self.events.publish,task_id)
        self.engine._reasoning.plan(f"Task accepted: {text[:80]}", steps=self.engine.max_steps)
        try:answer,used=self.engine.run(task_id,text,task_type,manual_model_id,self.personal.prompt_context(user_id),blocked_tools=self.personal.blocked_tools(user_id));self.tasks.finish(task_id,answer);status='complete'
        except Exception as exc:
            crash_id=self.crashes.capture(exc,{'task_id':task_id});self.metrics.increment('task_failures_total',error=type(exc).__name__);answer=f'AIBA task failed [{crash_id}]: {type(exc).__name__}: {exc}';used=[];status='failed';self.tasks.finish(task_id,answer,status)
        # Best-effort session close/status: complete/failed both map to closed.
        if _sid is not None:
            try:self.sessions.append(_sid,summary=(answer[:400] or ''));self.sessions.close_session(_sid)
            except Exception:pass
        ref=self.dream.reflect(task_id,text,answer,used);proposal=self.improver.propose(task_id,text,used,answer) if propose_skill and used else None
        self.metrics.increment('tasks_total',status=status);self.events.publish('task_finished',task_id=task_id,status=status,tools=used,reflection=str(ref),skill_proposal=str(proposal) if proposal else None);return answer
    def _export_memories(self, filename, category=None, as_user=None):
        """Export memories (optionally one category) to a markdown doc in the
        workspace (sandbox-confined). as_user restricts the export to the acting
        identity's OWN rows (operator passes None => whole view is not exported
        unless they are the explicit single-owner/admin). Returns an ok summary
        dict or error str."""
        rows = self.vault.export(category, as_user=as_user) if hasattr(self.vault, 'export') else []
        lines=[f"# AIBA memory export{(' — '+category) if category else ''}\n"]
        for r in rows:
            lines.append(f"- `{r.get('id','')}` [{r.get('category','general')}] ({r.get('created_at','')}): {r.get('content','')}")
        md='\n'.join(lines)+'\n'
        try:
            result=self.sandbox.write_file(str(filename),md)
            return {'file':str(filename),'count':len(rows)} if getattr(result,'ok',True) else {'error':getattr(result,'error','write failed')}
        except Exception as exc:
            return {'error':f'{type(exc).__name__}: {exc}'}
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
        # Shut down bounded internal subagents (idempotent + safe even if the
        # manager failed to construct earlier in __init__).
        subagents=getattr(self,'subagents',None)
        if subagents is not None:
            try:subagents.close()
            except Exception:pass
    def run(self):
        print(f'AIBA Agent v1.5 | routing=auto | sandbox={self.settings.sandbox_mode} | /exit to quit')
        while True:
            try:text=input('You> ').strip()
            except (EOFError,KeyboardInterrupt):print();break
            if text in {'/exit','/quit'}:break
            if text:print('AIBA>',self.handle(text))
        self.close()

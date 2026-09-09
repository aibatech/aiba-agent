from __future__ import annotations

import uuid

from agent.conversation_store import ConversationStore, default_conversation_id
from agent.loop import AgentLoop as BaseAgentLoop
from memory.learner import AutoLearner


class AgentLoop(BaseAgentLoop):
    """Production-facing AgentLoop with durable dialogue continuity and learning.

    The original runtime treated every handled message as an isolated task. That
    made AIBA look capable in single-turn tests while feeling forgetful in a real
    Linux/Telegram conversation. This subclass keeps the proven tool/security
    runtime and adds a bounded persistent conversation context plus conservative
    automatic durable learning.
    """

    def __init__(self, *args, **kwargs):
        requested_start = kwargs.pop("start_worker", True)
        # Prevent a background job from calling the overridden handle() before
        # the new conversation/learning stores exist.
        super().__init__(*args, start_worker=False, **kwargs)
        self.conversations = ConversationStore(self.settings.data_dir / "conversations.db")
        self.learner = AutoLearner(self.vault)
        self._cli_conversation_id = default_conversation_id("default")
        if requested_start and self.settings.worker_enabled:
            self.worker.start();self.scheduler_runner.start();self.update_checker.start()

    @staticmethod
    def _history_context(history: list[dict[str, str]]) -> str:
        if not history:
            return ""
        lines = ["Recent conversation (use this for continuity; do not repeat it back unless useful):"]
        for item in history:
            who = "User" if item.get("role") == "user" else "AIBA"
            lines.append(f"{who}: {item.get('content', '')}")
        return "\n".join(lines)

    def handle(self, text, propose_skill=True, task_type=None, manual_model_id=None,
               user_id=None, onboard=False, conversation_id=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Task prompt cannot be empty")
        if len(text) > 100_000:
            raise ValueError("Task prompt exceeds 100,000 characters")
        if onboard and user_id:
            intercepted = self.personal.intercept(user_id, text)
            if intercepted is not None:
                return intercepted

        user_key = user_id or "default"
        cid = self.conversations.ensure(user_key, conversation_id)
        history = self.conversations.recent(user_key, cid, limit=28, char_budget=18000)

        with self._run_lock:
            token = self._user_context.set(user_key)
            try:
                return self._handle_with_continuity(
                    text.strip(), propose_skill, task_type, manual_model_id,
                    user_id, cid, history,
                )
            finally:
                self._user_context.reset(token)

    def _handle_with_continuity(self, text, propose_skill=True, task_type=None,
                                manual_model_id=None, user_id=None,
                                conversation_id=None, history=None):
        from reasoning.protocol import VisibleReasoning

        task_id = self.tasks.create(text)
        self.events.publish("task_started", task_id=task_id, task=text)
        user_key = user_id or "default"
        self._current_user = user_key
        engine_scope = self._memory_scope(user_id)
        try:
            if getattr(self.engine, "retrieval", None) is not None:
                self.engine.retrieval.scope = engine_scope
        except Exception:
            pass

        sid = None
        try:
            sid = self.sessions.open_session(user_key, title=(text[:120] or ""), kind="turn")
        except Exception:
            pass

        personal_context = self.personal.prompt_context(user_id)
        continuity = self._history_context(history or [])
        prompt_context = "\n\n".join(x for x in (personal_context, continuity) if x)

        self.conversations.append(user_key, conversation_id, "user", text)
        self.engine._reasoning = VisibleReasoning(self.events.publish, task_id)
        self.engine._reasoning.plan(
            "Received request; using recent conversation, durable memory, and available tools.",
            steps=self.engine.max_steps,
        )

        try:
            answer, used = self.engine.run(
                task_id,
                text,
                task_type,
                manual_model_id,
                prompt_context,
                blocked_tools=self.personal.blocked_tools(user_id),
            )
            self.tasks.finish(task_id, answer)
            status = "complete"
        except Exception as exc:
            crash_id = self.crashes.capture(exc, {"task_id": task_id})
            self.metrics.increment("task_failures_total", error=type(exc).__name__)
            answer = f"AIBA task failed [{crash_id}]: {type(exc).__name__}: {exc}"
            used = []
            status = "failed"
            self.tasks.finish(task_id, answer, status)

        self.conversations.append(user_key, conversation_id, "assistant", answer)

        if sid is not None:
            try:
                self.sessions.append(sid, summary=(answer[:400] or ""))
                self.sessions.close_session(sid)
            except Exception:
                pass

        learned_ids = []
        try:
            memory_paused = bool(user_id and "remember" in self.personal.blocked_tools(user_id))
            if not memory_paused and status == "complete":
                learned_ids = self.learner.learn(
                    text,
                    owner=self._memory_writer_owner(user_id),
                    as_user=self._memory_scope(user_id),
                    source=f"conversation:{conversation_id}",
                )
        except Exception:
            learned_ids = []

        ref = self.dream.reflect(task_id, text, answer, used)
        proposal = self.improver.propose(task_id, text, used, answer) if propose_skill and used else None
        self.metrics.increment("tasks_total", status=status)
        self.events.publish(
            "task_finished",
            task_id=task_id,
            status=status,
            tools=used,
            reflection=str(ref),
            learned_memories=learned_ids,
            conversation_id=conversation_id,
            skill_proposal=str(proposal) if proposal else None,
        )
        return answer

    def run(self):
        print(f"AIBA Agent v1.6 | persistent conversation | routing=auto | sandbox={self.settings.sandbox_mode} | /exit to quit")
        print("Tip: /new starts a fresh conversation. Your durable memories remain available.")
        while True:
            try:
                text = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text in {"/exit", "/quit"}:
                break
            if text == "/new":
                self._cli_conversation_id = f"cli-{uuid.uuid4()}"
                self.conversations.ensure("default", self._cli_conversation_id)
                print("AIBA> New conversation started.")
                continue
            if text:
                print("AIBA>", self.handle(text, conversation_id=self._cli_conversation_id))
        self.close()

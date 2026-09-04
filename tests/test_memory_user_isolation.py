"""Item-2 integration tests: cross-user memory isolation THROUGH the real
AgentLoop tool paths.

These construct a genuine AgentLoop (isolated temp data dir, no network) and
exercise the six model-visible memory tools exactly as a handled turn would
(loop.registry.execute on the registered handlers). Ownership is derived from
the loop's authenticated identity (loop._current_user, which AgentLoop._handle
sets from the connector/API user_id) — never from any tool argument.

Model asserted (items 1 & 3):
  * 'default'/'None' + explicitly configured admins = single-owner/admin:
    full view incl 'shared'/legacy; writes land owner='shared'.
  * any OTHER authenticated identity (user-a vs user-b) is confined to its OWN
    rows — it cannot read/search/list/export/update/delete another user's or
    'shared' memory through these exact tool handlers.
  * legacy 'shared' backfill (the 18 live reflections -> 'shared') stays visible
    to the operator and never to a distinct non-operator user (decision 1b).
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import os
import json
import threading
import time
from unittest.mock import patch
from pathlib import Path

from config.settings import Settings

REPO = Path(__file__).resolve().parents[1]


def make_settings(tmp: Path) -> Settings:
    data = tmp / "data"
    for sub in ("workspace", "vault", "logs", "reflections", "skill_proposals", "providers"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    skills = tmp / "skills"; skills.mkdir(parents=True, exist_ok=True)
    cfg = tmp / "config"; cfg.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "config" / "permissions.json", cfg / "permissions.json")
    shutil.copy(REPO / "config" / "capability_manifest.json", cfg / "capability_manifest.json")
    return Settings(
        root_dir=tmp, data_dir=data, workspace_dir=data / "workspace",
        vault_dir=data / "vault", logs_dir=data / "logs", skills_dir=skills,
        db_path=data / "aiba.db", tasks_db_path=data / "tasks.db",
        jobs_db_path=data / "jobs.db", schedules_db_path=data / "schedules.db",
        auth_db_path=data / "auth.db", providers_db_path=data / "providers.db",
        provider="local", fallback_provider="local", model="local-v1",
        fallback_model="local-v1", max_steps=5, command_timeout=10,
        require_approval=True, sandbox_mode="local",
        docker_image="python:3.12-slim", docker_memory="512m",
        docker_cpus="1.0", sandbox_network=False,
        permissions_path=cfg / "permissions.json", browser_enabled=False,
        desktop_enabled=False, vision_model="", worker_enabled=False,
        api_token="x" * 40, api_host="127.0.0.1", api_port=8765,
        allowed_origins=(), rate_limit_per_minute=60, web_enabled=False,
        computer_node_path=data / "computer_node.json",
        desktop_clipboard_enabled=False, desktop_process_enabled=False,
    )


class CrossUserMemoryIsolationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="aiba_memiso_")
        self.tmp = Path(self._tmp)
        from agent.loop import AgentLoop
        # auto_approve lets the mutation tools (remember/update/delete) execute
        # through the real registry handler path (mirrors a handled turn where
        # the operator approved). No network is ever used.
        self.settings = make_settings(self.tmp)
        self.loop = AgentLoop(settings=self.settings, interactive=False,
                              auto_approve=True, start_worker=False)
        # In this harness 'default' is the sole authorized operator; 'user-a' and
        # 'user-b' are distinct non-operator principals (NOT in an allowlist).
        self.loop._owner_users = frozenset({'default'})

    def tearDown(self):
        self.loop.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _act_as(self, user):
        """Simulate being 'user': mirrors AgentLoop._handle setting _current_user
        from the authenticated connector/API identity."""
        self.loop._current_user = user or 'default'

    def _run(self, name, args):
        res = self.loop.registry.execute(name, args)
        self.assertTrue(res.ok, f"{name} failed: {res.error}")
        out = res.output
        if isinstance(out, dict):
            return out.get('memory_id', out)
        return out

    def _owner_of(self, mid) -> str:
        with sqlite3.connect(self.loop.vault.db_path) as c:
            return c.execute('SELECT owner FROM memories WHERE id=?', (int(mid),)).fetchone()[0]

    def _contents(self, result) -> list:
        rows = result if isinstance(result, list) else []
        return [r.get('content') for r in rows]

    # -- scope resolution ----------------------------------------------------
    def test_scope_resolution(self):
        self.assertIsNone(self.loop._memory_scope(None))
        self.assertIsNone(self.loop._memory_scope('default'))
        self.assertTrue(self.loop._is_operator('default'))
        self.assertEqual(self.loop._memory_scope('user-a'), 'user-a')
        self.assertFalse(self.loop._is_operator('user-a'))
        self.assertEqual(self.loop._memory_writer_owner('default'), 'shared')
        self.assertEqual(self.loop._memory_writer_owner('user-a'), 'user-a')

    def test_chat_allowlists_do_not_grant_vault_admin(self):
        with patch.dict(os.environ, {
            'AIBA_TELEGRAM_ALLOWED_USERS': '111,222',
            'AIBA_WHATSAPP_ALLOWED_NUMBERS': '15551111111,15552222222',
            'AIBA_MEMORY_OWNER_USERS': '',
        }):
            self.assertEqual(Settings._owner_users_from_env(), frozenset({'default'}))

    def test_only_explicit_connector_identity_becomes_admin(self):
        with patch.dict(os.environ, {
            'AIBA_TELEGRAM_ALLOWED_USERS': '111,222',
            'AIBA_MEMORY_OWNER_USERS': 'telegram:111',
        }):
            self.loop._owner_users = Settings._owner_users_from_env()
            self.assertTrue(self.loop._is_operator('telegram:111'))
            self.assertFalse(self.loop._is_operator('telegram:222'))

    def test_invalid_owner_config_fails_closed(self):
        from config.settings import SettingsError
        for value in ('*', 'telegram:*', 'whatsapp:', 'telegram:123:456'):
            with self.subTest(value=value), patch.dict(os.environ, {'AIBA_MEMORY_OWNER_USERS': value}):
                with self.assertRaises(SettingsError):
                    Settings._owner_users_from_env()

    def test_whitespace_identity_never_gets_unscoped_view(self):
        self.assertIsNotNone(self.loop._memory_scope('   '))

    def test_worker_rechecks_feature_flags_after_resolution(self):
        # A parent-listed tool must still obey its feature flag at execution.
        self.loop.policy.config['tools']['web_search']['enabled'] = True
        self.loop.runtime_flags['AIBA_WEB_ENABLED'] = False
        self.assertFalse(self.loop._subagent_policy_allows('web_search'))
        self.assertNotIn('web_search', self.loop._subagent_resolve_tools(['web_search']))
        self.loop.runtime_flags['AIBA_WEB_ENABLED'] = True
        resolved = self.loop._subagent_resolve_tools(['web_search'])['web_search']
        self.loop.runtime_flags['AIBA_WEB_ENABLED'] = False
        result = resolved['handler'](query='never execute')
        self.assertFalse(result.ok)
        self.assertIn('AIBA_WEB_ENABLED', result.error)

    def test_worker_requires_actual_action_approval_and_schema(self):
        resolved = self.loop._subagent_resolve_tools(['write_file'])['write_file']
        with patch.object(self.loop.approvals, 'approve', return_value=False) as approve:
            result = resolved['handler'](path='denied.txt', content='test')
        self.assertFalse(result.ok)
        approve.assert_called_once()
        self.assertFalse((self.settings.workspace_dir / 'denied.txt').exists())
        with patch.object(self.loop.approvals, 'approve', return_value=True):
            invalid = resolved['handler'](path='invalid.txt', content=42)
        self.assertFalse(invalid.ok)
        self.assertFalse((self.settings.workspace_dir / 'invalid.txt').exists())

    def test_worker_pause_rechecked_at_tool_dispatch(self):
        self._act_as('telegram:222')
        resolved = self.loop._subagent_resolve_tools(['remember'])['remember']
        self.loop.personal.intercept('telegram:222', '/memory pause')
        result = resolved['handler'](content='must not persist')
        self.assertFalse(result.ok)
        self.assertEqual(self.loop.vault.list(as_user='telegram:222'), [])

    def test_queued_and_scheduled_work_records_authenticated_user(self):
        self._act_as('telegram:222')
        with patch.object(self.loop.queue, 'enqueue', return_value='job') as enqueue:
            self._run('enqueue_task', {'prompt': 'inspect my memory'})
            self.assertEqual(enqueue.call_args.args[1]['user_id'], 'telegram:222')
        with patch.object(self.loop.scheduler, 'add_interval', return_value='schedule') as schedule:
            self._run('schedule_task', {'name': 'own notes', 'prompt': 'inspect my memory', 'interval_seconds': 60})
            self.assertEqual(schedule.call_args.args[2]['user_id'], 'telegram:222')

    def test_background_job_executes_as_original_user_not_operator(self):
        with patch.object(self.loop, 'handle', return_value='done') as handle:
            self.loop.worker.handlers['agent_task']({'prompt': 'own notes', 'user_id': 'telegram:222'})
            self.assertEqual(handle.call_args.kwargs['user_id'], 'telegram:222')

    def test_background_worker_keeps_original_user_after_next_turn(self):
        self.loop.vault.add('alice-private', owner='user-a')
        self.loop.vault.add('bob-private', owner='user-b')
        self.loop.subagents.enabled = True
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        observed = []
        def provider(messages, schemas):
            if len(messages) == 2:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('test release never arrived')
                return json.dumps({'type': 'tool_call', 'tool': 'list_memories', 'arguments': {}})
            observed.append(messages[-1]['content'])
            finished.set()
            return json.dumps({'type': 'final', 'response': 'done'})
        self.loop.subagents.pool._call_provider = provider
        self._act_as('user-a')
        try:
            batch = self.loop.subagents.run_many(['inspect own memory'], allowed_tools=['list_memories'], wait_s=0.01)
            self.assertTrue(entered.wait(2))
            self.assertTrue(batch['pending'])
            self._act_as('default')  # next turn must not elevate the old worker
            release.set()
            self.assertTrue(finished.wait(3))
            self.assertIn('alice-private', observed[0])
            self.assertNotIn('bob-private', observed[0])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if self.loop.subagents.status_of(batch['pending'][0])['status'] == 'completed':
                    break
                threading.Event().wait(0.01)
        finally:
            release.set()

    # -- writes tag the acting user -----------------------------------------
    def test_remember_tags_the_acting_identity(self):
        self._act_as('user-a')
        mid = self._run('remember', {'content': 'alice only', 'category': 'personal'})
        self.assertEqual(self._owner_of(mid), 'user-a')
        self._act_as(None)
        op = self._run('remember', {'content': 'operator note', 'category': 'general'})
        self.assertEqual(self._owner_of(op), 'shared')

    # -- read/search ---------------------------------------------------------
    def test_user_b_cannot_read_or_search_user_a(self):
        self._act_as('user-a')
        self._run('remember', {'content': "A's private secret xyzzy1", 'category': 'general'})
        self._act_as('user-b')
        self._run('remember', {'content': "B's own note", 'category': 'general'})
        b_list = self._contents(self._run('list_memories', {'limit': 100}))
        self.assertIn("B's own note", b_list)
        self.assertNotIn("A's private secret xyzzy1", b_list)
        self.assertEqual(self._run('search_memory', {'query': 'xyzzy1'}), [])
        self._act_as('user-a')
        self.assertEqual(self._run('search_memory', {'query': "B's own"}), [])

    # -- export --------------------------------------------------------------
    def test_user_b_cannot_export_user_a_but_operator_can(self):
        self._act_as('user-a')
        self._run('remember', {'content': "A top secret katana", 'category': 'research'})
        self._act_as('user-b')
        self._run('export_memories', {'filename': 'b_export.md'})
        self._run('export_memories', {'filename': 'b_export2.md'})
        b_export = (self.tmp / 'data' / 'workspace' / 'b_export2.md').read_text()
        self.assertNotIn('katana', b_export)
        # the authorized single-owner/admin (operator) CAN export A's row
        self._act_as(None)
        self._run('export_memories', {'filename': 'op_export.md'})
        op_export = (self.tmp / 'data' / 'workspace' / 'op_export.md').read_text()
        self.assertIn('katana', op_export)

    # -- update/delete -------------------------------------------------------
    def test_user_b_cannot_update_or_delete_user_a(self):
        self._act_as('user-a')
        mid = self._run('remember', {'content': "A irreplaceable ledger", 'category': 'finance'})
        self._act_as('user-b')
        # B tries to mutate/delete A's row by id (the scoped handler refuses)
        self.loop.registry.execute('update_memory', {'memory_id': mid, 'content': 'B tampered'})
        self.loop.registry.execute('delete_memory', {'memory_id': mid})
        self._act_as('user-a')
        rows = self.loop.vault.list(as_user=self.loop._memory_scope())
        a_row = next(r for r in rows if r['id'] == mid)
        self.assertEqual(a_row['content'], "A irreplaceable ledger")
        # and B cannot reach A's content at all
        self._act_as('user-b')
        self.assertEqual(self.loop.vault.get(mid, as_user=self.loop._memory_scope()), None)

    # -- shared/legacy visibility (decision 1b) -------------------------------
    def test_operator_sees_shared_but_second_user_never_does(self):
        self._act_as(None)
        self._run('remember', {'content': 'shared operator tip', 'category': 'reflections'})
        # simulate the 18 live legacy rows: backfilled to owner='shared'
        sid = self.loop.vault.add('legacy reflection content', 'reflections', 0.7, owner='shared')
        self._act_as(None)
        listed_op = self._contents(self._run('list_memories', {'limit': 200}))
        self.assertIn('shared operator tip', listed_op)
        self.assertIn('legacy reflection content', listed_op)
        self.assertIsNotNone(self.loop.vault.get(sid, as_user=None))
        # a distinct second user never sees any 'shared' row
        self._act_as('user-z')
        listed_z = self._contents(self._run('list_memories', {'limit': 200}))
        self.assertNotIn('shared operator tip', listed_z)
        self.assertNotIn('legacy reflection content', listed_z)
        self.assertIsNone(self.loop.vault.get(sid, as_user=self.loop._memory_scope()))
        self.assertEqual(self.loop._memory_scope(), 'user-z')  # strict, not operator


if __name__ == '__main__':
    unittest.main()

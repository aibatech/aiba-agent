"""Gap 2 regression tests: memory ownership isolation (v1.6).

Covers the concrete isolation contract chosen for the release (decision 1b):

* the aiba.db ``memory-owner-scope`` schema bump is versioned through the
  project migration framework and is idempotent;
* a pre-1.6 database (memories table WITHOUT an owner column) is upgraded
  in place and its legacy rows are backfilled to owner='shared' — records are
  preserved, never dropped;
* reads/writes/search/exports scoped to a concrete second user NEVER surface
  'shared'/legacy records or another user's private rows — the guarantee that
  legacy unowned records are not globally visible to a future second user;
* unscoped (single-operator) access still sees the whole table, exactly the
  pre-v1.6 behaviour — no behavioural regression for the current operator;
* backup/restore preserves the owner column and row contents.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlite_utils import connect

from memory.vault import MemoryVault, SHARED
from operations import BackupManager, MigrationManager

ALICE = 'user-alice'   # primary/operator (unscoped convention)
CAROL = 'user-carol'   # a hypothetical future second user


def _columns(db_path: Path, table: str) -> set[str]:
    with connect(db_path) as c:
        return {r[1] for r in c.execute(f'PRAGMA table_info({table})')}


class LegacyUpgradeTests(unittest.TestCase):
    """A v1.5-style aiba.db (no owner column) upgrades in place + backfills."""

    def _legacy_db(self, db_path: Path):
        # Reproduce the EXACT pre-v1.6 memories DDL (no owner column).
        with connect(db_path) as c:
            c.executescript('''
                CREATE TABLE memories(id INTEGER PRIMARY KEY,content TEXT NOT NULL,
                    category TEXT NOT NULL,importance REAL NOT NULL,source_path TEXT UNIQUE,
                    created_at TEXT NOT NULL,metadata TEXT NOT NULL DEFAULT '{}');
            ''')

    def test_legacy_rows_backfill_to_shared_and_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'aiba.db'
            vault_dir = root / 'vault'
            vault_dir.mkdir()
            self._legacy_db(db)
            with connect(db) as c:
                for i in range(3):
                    c.execute(
                        "INSERT INTO memories(content,category,importance,created_at) "
                        "VALUES(?,?,?,?)",
                        (f'legacy reflection {i}', 'reflections', 0.7, '2026-09-01T00:00:00+00:00'))
                before = c.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
            self.assertEqual(before, 3)
            # Initializing the vault on a legacy DB adds owner + backfills.
            MemoryVault(db, vault_dir)
            self.assertIn('owner', _columns(db, 'memories'))
            with connect(db) as c:
                rows = c.execute('SELECT content,owner FROM memories ORDER BY id').fetchall()
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(o == SHARED for _, o in rows))
                self.assertEqual(rows[0][0], 'legacy reflection 0')  # preserved content

    def test_vault_init_and_migration_are_idempotent_on_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'aiba.db'
            root.joinpath('vault').mkdir()
            self._legacy_db(db)
            with connect(db) as c:
                c.execute(
                    "INSERT INTO memories(content,category,importance,created_at) "
                    "VALUES('legacy','reflections',0.5,'2026-09-01T00:00:00+00:00')")
            # simulate: loop constructs vault then runs the migration manager
            MemoryVault(db, root / 'vault')
            mgr = MigrationManager(root)
            first = mgr.apply()
            second = mgr.apply()   # repeat execution must not error / re-add
            v = next(x for x in mgr.status() if x['database'] == 'aiba.db')
            self.assertTrue(v['ready'])
            self.assertEqual(v['current'], 2)
            self.assertEqual(first, second)
            self.assertIn('owner', _columns(db, 'memories'))
            with connect(db) as c:  # exactly one row still, content + owner intact
                rows = c.execute('SELECT content,owner FROM memories').fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0], ('legacy', SHARED))

    def test_interrupted_migration_recovers_on_retry(self):
        """A migration that never commits (simulated crash) leaves the DB at the
        prior version; a subsequent apply() advances cleanly, so an interrupted
        upgrade cannot strand the database half-way or double-run the DDL."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'aiba.db'
            root.joinpath('vault').mkdir()
            self._legacy_db(db)
            with connect(db) as c:
                c.execute(
                    "INSERT INTO memories(content,category,importance,created_at) "
                    "VALUES('legacy','reflections',0.5,'2026-09-01T00:00:00+00:00')")
            # Interrupt BEFORE the schema work commits: create the schema_migrations
            # tracking table but record no applied version (the crash point), so the
            # vault's guarded owner-add + the migration marker have NOT run yet.
            with connect(db) as c:
                c.executescript('''
                    CREATE TABLE IF NOT EXISTS schema_migrations(
                        version INTEGER PRIMARY KEY,name TEXT NOT NULL,
                        checksum TEXT NOT NULL,applied_at TEXT NOT NULL);
                    PRAGMA user_version=0;
                ''')
                before_cols = {r[1] for r in c.execute('PRAGMA table_info(memories)')}
            self.assertNotIn('owner', before_cols)
            # Retry the full startup sequence (vault init + migrate apply).
            MemoryVault(db, root / 'vault')
            mgr = MigrationManager(root)
            mgr.apply()
            v = next(x for x in mgr.status() if x['database'] == 'aiba.db')
            self.assertEqual(v['current'], 2)
            self.assertIn('owner', _columns(db, 'memories'))
            with connect(db) as c:  # legacy row preserved + backfilled
                rows = c.execute('SELECT content,owner FROM memories').fetchall()
                self.assertEqual(rows, [('legacy', SHARED)])

    def test_partial_apply_is_atomic_and_ready(self):
        """If an apply() is cut off before commit, the row stays at version 0 and
        is NOT marked ready; re-applying is the only way forward (no half state)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'aiba.db'
            root.joinpath('vault').mkdir()
            self._legacy_db(db)
            MemoryVault(db, root / 'vault')          # owner column present now
            # Simulate a crash AFTER creating schema_migrations but before the
            # framework recorded the applied version (BEGIN not committed).
            with connect(db) as c:
                c.executescript('''CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY,name TEXT NOT NULL,
                    checksum TEXT NOT NULL,applied_at TEXT NOT NULL);''')
                c.execute('PRAGMA user_version=0')
            st = next(x for x in MigrationManager(root).status()
                      if x['database'] == 'aiba.db')
            self.assertFalse(st['ready'])
            # Normal re-apply reaches target cleanly.
            MigrationManager(root).apply()
            st2 = next(x for x in MigrationManager(root).status()
                       if x['database'] == 'aiba.db')
            self.assertTrue(st2['ready'])
            self.assertEqual(st2['current'], 2)


class IsolationTests(unittest.TestCase):
    """Concrete second-user scope never surfaces 'shared'/foreign rows."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix='aiba_own_')
        self.root = Path(self._dir)
        self.vault = MemoryVault(self.root / 'aiba.db', self.root / 'vault')

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def _seed(self):
        # global/legacy-style rows (owner=shared) + one primary-specific row
        shared_id = self.vault.add('shared provisioning tip', 'general', 0.6)
        dream_id = self.vault.add('auto reflection note', 'reflections', 0.8)
        alice_private = self.vault.add('alice private plan', 'general', 0.9, owner=ALICE)
        carol_private = self.vault.add('carol private plan', 'general', 0.9, owner=CAROL)
        return shared_id, dream_id, alice_private, carol_private

    def test_second_user_never_sees_shared_or_others(self):
        self._seed()
        # Carol, scoped, sees ONLY her own rows.
        self.assertEqual([r['owner'] for r in self.vault.list(as_user=CAROL)], [CAROL])

    def test_unscoped_primary_view_sees_shared_and_own(self):
        self._seed()
        owners = {r['owner'] for r in self.vault.list()}
        self.assertIn(SHARED, owners)
        self.assertIn(ALICE, owners)
        self.assertEqual(len(self.vault.list()), 4)

    def test_list_category_and_scope_compose(self):
        self._seed()
        # Carol, scoped to category 'general', sees NONE of the general rows
        # (they are shared or alice's), only her own general row — which is
        # present in the seed, so assert owner scoping on the results instead.
        got = self.vault.list(category='general', as_user=CAROL)
        self.assertTrue(all(r['owner'] == CAROL for r in got))
        self.assertEqual([r['owner'] for r in got], [CAROL])

    def test_get_is_scoped(self):
        shared_id, _, alice_private, carol_private = self._seed()
        self.assertIsNone(self.vault.get(shared_id, as_user=CAROL))
        self.assertIsNone(self.vault.get(alice_private, as_user=CAROL))
        self.assertIsNotNone(self.vault.get(carol_private, as_user=CAROL))
        # unscoped can still reach shared + any row
        self.assertIsNotNone(self.vault.get(shared_id))

    def test_search_never_leaks_shared_to_second_user(self):
        self._seed()
        # 'plan' matches shared row, alice's private row AND carol's private row;
        # a carol-scoped search must return ONLY carol's own row (1 hit), never
        # the shared or alice row.
        hits = self.vault.search('plan', as_user=CAROL)
        self.assertEqual(len(hits), 1)
        self.assertTrue(all(h['owner'] == CAROL for h in hits))
        self.assertNotIn(self.vault.get(hits[0]['id'])['content'], ('shared provisioning tip', 'alice private plan'))
        self.assertEqual(self.vault.search('provisioning tip', as_user=CAROL), [])
        # Carol finds her own content
        self.assertEqual(len(self.vault.search('private plan', as_user=CAROL)), 1)
        # unscoped search still sees everything relevant
        self.assertEqual(len(self.vault.search('provisioning tip')), 1)

    def test_update_and_remove_are_scoped(self):
        shared_id, _, alice_private, carol_private = self._seed()
        # carol cannot mutate shared or alice's row
        self.vault.update(shared_id, content='tamper', as_user=CAROL)
        self.assertNotEqual(self.vault.get(shared_id)['content'], 'tamper')
        self.assertEqual(self.vault.remove(shared_id, as_user=CAROL), False)
        self.assertEqual(self.vault.remove(alice_private, as_user=CAROL), False)
        self.assertIsNotNone(self.vault.get(alice_private))
        # carol CAN mutate/remove her own
        self.vault.update(carol_private, content='carol edited', as_user=CAROL)
        self.assertEqual(self.vault.get(carol_private, as_user=CAROL)['content'], 'carol edited')
        self.assertTrue(self.vault.remove(carol_private, as_user=CAROL))
        self.assertIsNone(self.vault.get(carol_private))

    def test_export_scope_excludes_shared_for_second_user(self):
        self._seed()
        exported = self.vault.export(as_user=CAROL)
        self.assertEqual([e['id'] for e in exported],
                         [r['id'] for r in self.vault.list(as_user=CAROL)])
        self.assertTrue(all(self.vault.get(e['id'], as_user=CAROL) for e in exported))
        for e in exported:  # shared must not leak into a carol-scoped export
            self.assertEqual(self.vault.get(e['id'])['owner'], CAROL)


class BackupRestoreOwnerTests(unittest.TestCase):
    def test_backup_and_restore_preserve_owner_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = MemoryVault(root / 'aiba.db', root / 'vault')
            vault.add('shared tip', 'general', owner=SHARED)
            rid = vault.add('alice secret', 'general', owner=ALICE)
            backups = BackupManager(root)
            created = backups.create('owner')
            self.assertTrue(backups.verify(created['backup_id'])['verified'])
            # mutate then restore
            vault.update(rid, content='mutated')
            restored = backups.restore(created['backup_id'], created['backup_id'])
            self.assertTrue(restored['restored'])
            with connect(root / 'aiba.db') as c:
                row = c.execute('SELECT content,owner FROM memories WHERE id=?', (rid,)).fetchone()
            self.assertEqual(row, ('alice secret', ALICE))
            self.assertIn('owner', _columns(root / 'aiba.db', 'memories'))


class ReflectionPauseTests(unittest.TestCase):
    """Dream/reflection auto-rows (owner defaults to 'shared') stay global-only:
    a concrete second user never receives paused/ambient reflections either."""

    def test_auto_reflections_are_shared_and_never_flow_to_second_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = MemoryVault(root / 'aiba.db', root / 'vault')
            # what DreamEngine produces via vault.add(..., default shared)
            rid = vault.add('something the agent dreamt', 'reflections', 0.8)
            self.assertEqual(self.vault_owner(vault, rid), SHARED)
            self.assertEqual(vault.search('dreamt', as_user=CAROL), [])
            self.assertEqual(len(vault.list(as_user=CAROL)), 0)

    @staticmethod
    def vault_owner(vault, rid):
        with connect(vault.db_path) as c:
            return c.execute('SELECT owner FROM memories WHERE id=?', (rid,)).fetchone()[0]


if __name__ == '__main__':
    unittest.main()

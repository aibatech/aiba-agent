"""Tests for memory vault edit/delete/list/export (Phase 9)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from memory.vault import MemoryVault


class VaultEditTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="aiba_mem_")
        self.root = Path(self._dir)
        self.vault = MemoryVault(self.root / "mem.db", self.root / "vault")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_update_refreshes_content_and_fts(self):
        mid = self.vault.add("alpha DB lock root cause", "general", 0.8)
        self.assertTrue(self.vault.search("root cause"))
        self.vault.update(mid, content="alpha WAL lock resolved")
        # old terms gone, new term searchable (FTS stayed in sync via trigger)
        self.assertEqual(self.vault.search("root cause"), [])
        self.assertEqual([r["id"] for r in self.vault.search("WAL")], [mid])
        rec = self.vault.get(mid)
        self.assertIn("WAL", rec["content"])

    def test_update_requires_at_least_one_field(self):
        with self.assertRaises(ValueError):
            self.vault.update(1)

    def test_remove_deletes_and_clears_fts(self):
        mid = self.vault.add("cold start alpha", "general")
        self.assertTrue(self.vault.search("cold"))
        self.assertTrue(self.vault.remove(mid))
        self.assertIsNone(self.vault.get(mid))
        self.assertEqual(self.vault.search("cold"), [])
        self.assertFalse(self.vault.remove(999999))

    def test_category_update_and_filter(self):
        mid = self.vault.add("something", "research")
        self.vault.update(mid, category="personal")
        self.assertEqual([r["id"] for r in self.vault.list(category="personal")],
                         [mid])
        self.assertEqual(self.vault.list(category="research"), [])

    def test_list_bounded_ordering_and_export(self):
        ids = [self.vault.add(f"memory {i}", "research") for i in range(5)]
        listed = self.vault.list(limit=3)
        self.assertEqual(len(listed), 3)
        latest = self.vault.list(limit=1)[0]["id"]
        self.assertEqual(latest, ids[-1])  # newest first
        exported = self.vault.export()
        self.assertEqual(len(exported), 5)
        for item in exported:
            self.assertEqual(set(item), {"id", "content", "category",
                                         "importance", "created_at",
                                         "source_path"})

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.vault.get(123456))


if __name__ == "__main__":
    unittest.main()

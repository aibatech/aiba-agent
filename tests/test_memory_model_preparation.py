"""Artifact preparation mechanics only; real quality is measured in semantic CI."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.prepare_memory_model import prepare, MODEL_ID, REVISION, FILES


class ModelPreparationTests(unittest.TestCase):
    def test_pinned_allowlist_materializes_files_without_executable_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';cache.write_bytes(b'fixture')
            calls=[]
            def download(**kwargs):calls.append(kwargs);return str(cache)
            module=types.ModuleType('huggingface_hub');module.hf_hub_download=download
            with patch.dict('sys.modules',{'huggingface_hub':module}):
                result=prepare(root/'model')
                with self.assertRaises(ValueError):prepare(root/'model')
            self.assertEqual(result['revision'],REVISION)
            self.assertEqual({c['filename'] for c in calls},set(FILES))
            self.assertTrue(all(c['repo_id']==MODEL_ID and c['revision']==REVISION for c in calls))
            self.assertFalse(any(name.endswith(('.py','.bin','.pkl')) for name in FILES))
            self.assertEqual((root/'model'/'model.safetensors').read_bytes(),b'fixture')
            self.assertFalse(any(p.is_symlink() for p in (root/'model').rglob('*')))

    def test_missing_optional_dependency_is_actionable_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'model'
            with patch.dict('sys.modules',{'huggingface_hub':None}):
                with self.assertRaisesRegex(RuntimeError,'semantic'):prepare(target)
            self.assertFalse(target.exists())

import hashlib
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from center_context import apply_edits, read_sources


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='center_context_')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'src').mkdir()
        (self.root / 'src/code.py').write_bytes(b'x = 1\n')

    def test_apply_scoped_model_edit_with_hash_fence(self):
        snapshot = read_sources(self.root, ['src'])
        expected = hashlib.sha256(b'x = 1\n').hexdigest()
        edits = [{'path': 'src/code.py', 'operation': 'write', 'expected_sha256': expected, 'content': 'x = 2\n'},
                 {'path': 'src/new.py', 'operation': 'write', 'expected_sha256': '', 'content': 'y = 3\n'}]
        self.assertEqual(apply_edits(self.root, ['src'], snapshot, edits), ['src/code.py', 'src/new.py'])
        self.assertEqual((self.root / 'src/new.py').read_text(), 'y = 3\n')

    def test_reject_out_of_scope_sensitive_and_stale_edits(self):
        snapshot = read_sources(self.root, ['src'])
        for name in ('outside.py', '../escape.py', 'src/.env'):
            with self.assertRaises(ValueError):
                apply_edits(self.root, ['src'], snapshot, [{'path': name, 'operation': 'write', 'expected_sha256': '', 'content': 'bad'}])
        (self.root / 'src/code.py').write_text('user changed it')
        with self.assertRaisesRegex(ValueError, 'changed'):
            apply_edits(self.root, ['src'], snapshot, [{'path': 'src/code.py', 'operation': 'write', 'expected_sha256': snapshot[0]['sha256'], 'content': 'bad'}])
        self.assertEqual((self.root / 'src/code.py').read_text(), 'user changed it')

    def test_context_limit_and_sensitive_files_block_before_model_call(self):
        with self.assertRaises(ValueError):
            read_sources(self.root, ['src'], limit=2)
        (self.root / 'src/.env').write_text('dummy fixture')
        with self.assertRaises(ValueError):
            read_sources(self.root, ['src'])

    def test_review_material_covers_new_modified_and_deleted_files(self):
        files = read_sources(self.root, ['src'], names=['src/code.py', 'src/deleted.py'])
        self.assertEqual(files[0]['content'], 'x = 1\n')
        self.assertTrue(files[1]['deleted'])

    def test_validate_entire_edit_list_before_writing(self):
        snapshot = read_sources(self.root, ['src'])
        edits = [{'path': 'src/new.py', 'operation': 'write', 'expected_sha256': '', 'content': 'valid'},
                 {'path': '../bad.py', 'operation': 'write', 'expected_sha256': '', 'content': 'bad'}]
        with self.assertRaises(ValueError):
            apply_edits(self.root, ['src'], snapshot, edits)
        self.assertFalse((self.root / 'src/new.py').exists())

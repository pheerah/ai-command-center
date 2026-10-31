"""The project-side HTTP connector: loopback-only, safe patch paths, exclusive writes. No Center or model needed."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('connector_under_test', Path(__file__).resolve().parents[1] / 'connector-template' / 'connector.py')
connector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(connector)


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.original = connector.ROOT
        connector.ROOT = self.root
        self.addCleanup(setattr, connector, 'ROOT', self.original)

    def test_the_token_is_only_ever_sent_to_loopback(self):
        saved = {k: os.environ.get(k) for k in ('CENTER_URL', 'CENTER_TOKEN')}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
        os.environ['CENTER_TOKEN'] = 'cc_x'
        for url in ('http://127.0.0.1:3939', 'http://localhost:3939/'):
            os.environ['CENTER_URL'] = url
            self.assertEqual(connector.connection()[1], 'cc_x')
        for url in ('https://evil.example.com', 'http://10.0.0.5:3939', 'http://127.0.0.1.evil.com'):
            os.environ['CENTER_URL'] = url
            with self.assertRaises(ValueError):
                connector.connection()

    def test_patch_paths_must_be_plain_relative_paths(self):
        self.assertEqual(connector.safe_target('src/a.py'), self.root / 'src' / 'a.py')
        for bad in ('../x.py', 'src/../../x.py', '/etc/passwd', 'C:/x.py', '.git/config', 'src/.git/hooks/x', 'a' + chr(92) + '..' + chr(92) + 'b', ''):
            with self.assertRaises(RuntimeError, msg=bad):
                connector.safe_target(bad)

    def test_new_files_are_created_exclusively(self):
        connector.write_new_file('src/new.py', b'x = 1')
        self.assertEqual((self.root / 'src' / 'new.py').read_bytes(), b'x = 1')
        with self.assertRaises(FileExistsError):
            connector.write_new_file('src/new.py', b'overwrite')
        self.assertEqual((self.root / 'src' / 'new.py').read_bytes(), b'x = 1')

    def test_a_parent_that_escapes_the_project_through_a_link_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in outside.iterdir()] or outside.rmdir())
        link = self.root / 'src'
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are not permitted here')
        with self.assertRaises(RuntimeError):
            connector.write_new_file('src/escape.py', b'x')
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

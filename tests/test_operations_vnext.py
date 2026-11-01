"""Backups/drills/inventory and IDE acceptance checking use no providers."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
from center_operations import maintenance_report, restore_drill, verified_backup
from center_store import Store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('antigravity_acceptance', ROOT / 'scripts/antigravity_acceptance.py')
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class OperationsFixture:
    def __init__(self, state):
        self.store = Store(state)
        self.config = {'storage': 'sqlite', 'providers': {}, 'global_capacity': 1}


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='center_operations_tests_')).resolve()
        self.addCleanup(self.cleanup)
        self.center = OperationsFixture(self.root / 'state')

    def cleanup(self):
        if self.root.parent != Path(tempfile.gettempdir()).resolve() or not self.root.name.startswith('center_operations_tests_'):
            raise ValueError('Unsafe test cleanup')
        shutil.rmtree(self.root)

    def checkpoint_task(self, task_id='checkpointfixture', pointer=None):
        saved = self.center.store.state / 'checkpoints' / task_id / 'snapshot'
        saved.mkdir(parents=True)
        data = {'base_rev': 'fixturebase', 'manifest': []}
        raw_patch = b''
        payload = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        identity = hashlib.sha256(payload + b'\0' + raw_patch).hexdigest()
        data['patch_hash'] = identity
        (saved / 'manifest.json').write_text(json.dumps(data), encoding='utf-8')
        (saved / 'tracked.patch').write_bytes(raw_patch)
        with self.center.store.connection(write=True) as con:
            con.execute('INSERT OR IGNORE INTO projects(id,name,root_path,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                        ('fixture', 'fixture', str(self.root / 'project'), '{}', 'now', 'now'))
            con.execute('INSERT INTO tasks(id,project_id,title,prompt,workspace,requested_provider,status,created_at,updated_at,base_rev,patch_hash,checkpoint) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (task_id, 'fixture', 'Synthetic backup fixture', 'No model call', str(self.root / 'project'), 'codex', 'queued', 'now', 'now', 'fixturebase', identity, str(pointer or saved)))
        return saved

    def test_backup_binds_checkpoint_metadata_hashes_and_reports_corruption(self):
        saved = self.checkpoint_task()
        report = verified_backup(self.center)
        snapshot = report['references'][0]['checkpoint_snapshot']
        self.assertEqual(snapshot['status'], 'verified')
        self.assertEqual(snapshot['manifest_sha256'], hashlib.sha256((saved / 'manifest.json').read_bytes()).hexdigest())
        self.assertEqual(snapshot['tracked_patch_sha256'], hashlib.sha256(b'').hexdigest())
        self.assertEqual(snapshot['verification_scope'], 'manifest_and_tracked_patch_only')
        (saved / 'tracked.patch').write_bytes(b'corrupt fixture bytes')
        corrupted = verified_backup(self.center)
        self.assertEqual(corrupted['integrity'], 'ok')
        self.assertEqual(corrupted['references'][0]['checkpoint_snapshot']['status'], 'corrupt')
        self.assertEqual(corrupted['checkpoint_reference_warnings'][0]['reason'], 'checkpoint_patch_identity_mismatch')

    def test_backup_reports_missing_or_external_checkpoint_without_reading_it(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'manifest.json').write_text('must not read', encoding='utf-8')
        self.checkpoint_task('external', pointer=outside)
        self.checkpoint_task('missing')
        with self.center.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET checkpoint=NULL WHERE id=?', ('missing',))
        original_open = Path.open
        def guard_open(path, *args, **kwargs):
            if path == outside / 'manifest.json':
                raise AssertionError('Read outside owned checkpoint state')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', autospec=True, side_effect=guard_open):
            report = verified_backup(self.center)
        statuses = {row['id']: row['checkpoint_snapshot']['status'] for row in report['references']}
        self.assertEqual(statuses, {'external': 'unsafe', 'missing': 'missing'})

    def test_verified_backup_and_isolated_drill_preserve_live_database(self):
        before = self.center.store.path.read_bytes()
        report = verified_backup(self.center)
        self.assertEqual(report['integrity'], 'ok')
        self.assertTrue(Path(report['manifest_path']).is_file())
        self.assertEqual(len(report['config_sha256']), 64)
        self.assertEqual(self.center.store.path.read_bytes(), before)
        restored = restore_drill(report['backup_path'], self.root / 'drill')
        self.assertEqual(restored['integrity'], 'ok')
        self.assertEqual(restored['counts'], report['counts'])
        self.assertEqual(self.center.store.path.read_bytes(), before)
        self.assertNotEqual(Path(restored['database_path']), self.center.store.path)

    def test_drill_refuses_existing_destination_or_noncenter_database(self):
        report = verified_backup(self.center)
        existing = self.root / 'existing'
        existing.mkdir()
        (existing / 'keep.txt').write_text('untouched', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'already exist'):
            restore_drill(report['backup_path'], existing)
        self.assertEqual((existing / 'keep.txt').read_text(), 'untouched')
        unrelated = self.root / 'unrelated.sqlite3'
        con = sqlite3.connect(unrelated)
        try:
            con.execute('CREATE TABLE other(id INTEGER)')
            con.commit()
        finally:
            con.close()
        with self.assertRaisesRegex(ValueError, 'not a Center'):
            restore_drill(unrelated, self.root / 'refused')
        self.assertFalse((self.root / 'refused').exists())

    def test_inventory_reports_orphans_without_deleting_and_obeys_limits(self):
        orphan = self.center.store.state / 'worktrees/p/missing/attempt-1'
        orphan.mkdir(parents=True)
        (orphan / 'keep.txt').write_bytes(b'preserve')
        (orphan / 'second.txt').write_bytes(b'also preserve')
        with patch('center_operations.MAX_FILES', 1):
            report = maintenance_report(self.center)
        self.assertEqual(report['policy'], 'report_only_no_deletion')
        self.assertEqual(report['worktrees'][0]['classification'], 'orphan_candidate_preserved')
        self.assertFalse(report['scan_complete'])
        self.assertIn('scan_limit_reached', report['warnings'])
        self.assertTrue((orphan / 'keep.txt').is_file())
        self.assertTrue((orphan / 'second.txt').is_file())

    def test_inventory_does_not_descend_linked_state_directory(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.txt').write_text('not read', encoding='utf-8')
        link = self.center.store.state / 'worktrees'
        # Windows commonly denies link creation. Exercise the refusal branch
        # using a reported link instead of skipping or claiming an OS-link test.
        link.mkdir()
        with patch.object(Path, 'is_symlink', autospec=True, side_effect=lambda path: path == link):
            report = maintenance_report(self.center)
        self.assertEqual(report['total_bytes'], 0)
        self.assertIn('linked_state_directory_skipped', report['warnings'])


class AcceptanceCheckTests(unittest.TestCase):
    def fixture(self, complete=False):
        task = {'id': 'sample', 'mode': 'live', 'provider': 'google' if complete else None,
                'status': 'ready_for_human_approval' if complete else 'queued', 'base_rev': 'base', 'patch_hash': 'hash'}
        events = []
        evidence = []
        if complete:
            events = [
                {'event': 'dispatch_recorded', 'detail': json.dumps({'session_id': 'sid', 'provider': 'google', 'adapter': 'handoff', 'role': 'implementation'})},
                {'event': 'worker_started', 'detail': json.dumps({'session_id': 'sid', 'source': 'ide_acknowledgement', 'reference': 'reported-real-ide-session'})},
                {'event': 'handoff_heartbeat_observed', 'detail': json.dumps({'session_id': 'sid'})},
            ]
            evidence = [{'kind': 'review', 'simulated': 0, 'provider': 'claude', 'base_rev': 'base', 'patch_hash': 'hash'}]
        class Fixture:
            def report(self, _task_id):
                return {'task': task, 'events': events, 'evidence': evidence}
            def validate_evidence(self, _task_id):
                if not complete:
                    raise ValueError('No actual evidence')
        return Fixture(), task, events, evidence

    def test_pending_evidence_never_claims_live_verification(self):
        center, _task, _events, _evidence = self.fixture()
        result = acceptance.check(center, 'sample')
        self.assertFalse(result['happy_path_verified'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['overall_status'], 'pending_live_verification')

    def test_happy_path_still_requires_manual_failure_scenarios_and_user_approval(self):
        center, _task, _events, _evidence = self.fixture(True)
        result = acceptance.check(center, 'sample')
        self.assertTrue(result['happy_path_verified'])
        self.assertEqual(result['human_approval'], 'pending_user')
        self.assertEqual(result['overall_status'], 'pending_manual_failure_scenarios')
        self.assertEqual(len(result['pending_manual_scenarios']), 3)

    def test_mock_or_missing_handoff_heartbeat_cannot_pass(self):
        center, _task, events, _evidence = self.fixture(True)
        events[:] = [row for row in events if row['event'] != 'handoff_heartbeat_observed']
        result = acceptance.check(center, 'sample')
        self.assertFalse(result['happy_path_verified'])
        self.assertIn('deterministic_handoff_heartbeat_evidence', result['missing_steps'])
        events.append({'event': 'mock_pipeline_complete', 'detail': '{}'})
        self.assertIn('mock_evidence_cannot_validate_actual_ide', acceptance.check(center, 'sample')['missing_steps'])

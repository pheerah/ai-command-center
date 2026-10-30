import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from center_usage import parse_usage, usage_report


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='center_usage_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.now = datetime(2026, 10, 30, 0, 30, tzinfo=timezone.utc)

    def record(self, base, name, provider='codex', adapter='live', text=None, recorded=None):
        directory = base / 'runs/task' / name
        directory.mkdir(parents=True)
        (directory / 'request.json').write_text(json.dumps({'adapter': adapter, 'provider': provider, 'prompt': 'private prompt must never be returned'}))
        log = directory / 'provider.log'
        log.write_text(text or json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 20, 'cached_input_tokens': 60}}))
        timestamp = (recorded or self.now).timestamp()
        os.utime(log, (timestamp, timestamp))
        return directory

    def test_codex_cache_and_reasoning_are_not_double_counted(self):
        text = json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 60, 'cache_write_input_tokens': 10, 'output_tokens': 20, 'reasoning_output_tokens': 5}})
        result = parse_usage('codex', text)
        self.assertEqual(result['total_tokens'], 120)
        self.assertEqual(result['cached_input_tokens'], 60)

    def test_claude_cache_is_in_total_input_but_nested_iterations_not_added(self):
        result = parse_usage('claude', json.dumps({'type': 'result', 'usage': {'input_tokens': 2, 'output_tokens': 8, 'cache_read_input_tokens': 40, 'cache_creation_input_tokens': 10, 'iterations': [{'input_tokens': 9999}]}, 'modelUsage': {'model': {'inputTokens': 9999}}, 'total_cost_usd': 12}))
        self.assertEqual(result['input_tokens'], 52)
        self.assertEqual(result['total_tokens'], 60)
        self.assertNotIn('cost', result)

    def test_missing_usage_is_unknown_not_zero_and_invalid_counters_rejected(self):
        self.assertIsNone(parse_usage('codex', '{}\nnot JSON'))
        self.assertIsNone(parse_usage('codex', json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': True, 'output_tokens': -1}})))
        result = parse_usage('codex', json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 0, 'output_tokens': 0}}))
        self.assertEqual(result['total_tokens'], 0)

    def test_mock_records_excluded_and_private_content_never_returned(self):
        self.record(self.state, 'real')
        self.record(self.state, 'mock', adapter='mock')
        self.record(self.state, 'missing', text='{"type":"error","message":"not a usage object"}')
        report = usage_report(self.state, self.root, self.now)
        day = report['providers']['codex']['days'][-1]
        self.assertEqual(day['total_tokens'], 120)
        self.assertEqual(day['observed_invocations'], 1)
        self.assertEqual(day['unmeasured_invocations'], 1)
        self.assertNotIn('private prompt', json.dumps(report))
        self.assertEqual(report['quota'], 'unknown')
        self.assertEqual(report['billing'], 'not_calculated')

    def test_bangkok_date_boundary_and_duplicate_source(self):
        recorded = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)  # 01:00 Bangkok, Oct 30
        self.record(self.state, 'once', recorded=recorded)
        (self.state / 'usage-sources.json').write_text(json.dumps({'sources': [{'state_dir': str(self.state), 'kind': 'live_smoke'}]}))
        report = usage_report(self.state, self.root, self.now)
        day = report['providers']['codex']['days'][-1]
        self.assertEqual(day['date'], '2026-10-30')
        self.assertEqual(day['observed_invocations'], 1)

    def test_additional_source_must_be_inside_workspace(self):
        (self.state / 'usage-sources.json').write_text(json.dumps({'sources': [{'state_dir': str(self.root.parent), 'kind': 'live_smoke'}]}))
        report = usage_report(self.state, self.root, self.now)
        self.assertIn('invalid_additional_source', report['warnings'])

    def test_explicit_live_smoke_is_aggregated_and_old_records_excluded(self):
        source = self.root / 'smoke/state'
        self.record(source, 'smoke')
        self.record(source, 'old', recorded=datetime(2025, 1, 1, tzinfo=timezone.utc))
        (self.state / 'usage-sources.json').write_text(json.dumps({'sources': [{'state_dir': str(source), 'kind': 'live_smoke'}]}))
        day = usage_report(self.state, self.root, self.now)['providers']['codex']['days'][-1]
        self.assertEqual(day['workloads']['live_smoke'], 1)
        self.assertEqual(day['total_tokens'], 120)

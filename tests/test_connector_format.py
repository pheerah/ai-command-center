"""Validate the documented discovery format without invoking Google models."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def frontmatter(path):
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---\n'):
        raise ValueError('Missing YAML frontmatter')
    return yaml.safe_load(text.split('---', 2)[1])


class ConnectorDiscoveryTests(unittest.TestCase):
    def test_rules_have_supported_antigravity_trigger(self):
        files = list((ROOT / 'connector-template/.agents/rules').glob('*.md'))
        self.assertTrue(files)
        for file in files:
            self.assertIn(frontmatter(file)['trigger'], ('always_on', 'model_decision', 'glob', 'manual'))

    def test_skill_has_name_and_discovery_description(self):
        metadata = frontmatter(ROOT / 'connector-template/.agents/skills/ai-command-center/SKILL.md')
        self.assertTrue(metadata['name'])
        self.assertTrue(metadata['description'])

"""Deterministic choice of model, reasoning effort and skills for one dispatch.

No model is consulted. The plan depends only on role, complexity, the task text,
the provider's configured model catalog and observed quota pressure. Every choice
carries a short reason so the audit trail explains it.
"""
from __future__ import annotations

import re

import center_quota

TIERS = ('light', 'standard', 'heavy')
EFFORT_ORDER = ('low', 'medium', 'high', 'xhigh', 'max', 'ultra')
# complexity -> (tier, effort); reviews never go below standard/medium unless trivial.
BY_COMPLEXITY = {1: ('light', 'low'), 2: ('light', 'medium'), 3: ('standard', 'medium'), 4: ('heavy', 'high'), 5: ('heavy', 'xhigh')}
LOW_QUOTA = 25.0     # below this, step one tier/effort down to save plan quota
CRITICAL_QUOTA = 10.0

KIND_PATTERNS = (
    ('security', re.compile(r'\b(auth|oauth|token|secret|credential|injection|xss|csrf|permission|security|vulnerab)', re.I)),
    ('bugfix', re.compile(r'\b(bug|fix|crash|regression|broken|error|fails?|failing|exception)\b', re.I)),
    ('refactor', re.compile(r'\b(refactor|cleanup|clean up|simplif|restructure|rename|dedupe)\b', re.I)),
    ('docs', re.compile(r'\b(docs?|readme|documentation|comment|changelog)\b', re.I)),
    ('test', re.compile(r'\b(tests?|coverage|spec)\b', re.I)),
)


def classify_kind(title, prompt):
    """The title states the intent; the prompt is only consulted when the title alone says nothing."""
    for text in (title, f'{title}\n{prompt}'):
        for kind, pattern in KIND_PATTERNS:
            if pattern.search(text):
                return kind
    return 'feature'


def pick_skills(config, role, kind, limit=2):
    """Skills whose roles and kinds match, in catalog order, bounded so context stays small."""
    chosen = []
    for name, skill in (config.get('skills') or {}).items():
        if role in skill.get('roles', ()) and (kind in skill.get('kinds', ()) or 'any' in skill.get('kinds', ())):
            chosen.append(name)
    chosen.sort(key=lambda n: (0 if kind in config['skills'][n].get('kinds', ()) else 1))
    return chosen[:limit]


def _step_down(tier):
    return TIERS[max(0, TIERS.index(tier) - 1)]


def _clip_effort(effort, supported):
    if not supported:
        return None
    if effort in supported:
        return effort
    wanted = EFFORT_ORDER.index(effort)
    lower = [e for e in supported if e in EFFORT_ORDER and EFFORT_ORDER.index(e) <= wanted]
    return max(lower, key=EFFORT_ORDER.index) if lower else min((e for e in supported if e in EFFORT_ORDER), key=EFFORT_ORDER.index, default=None)


def choose_plan(config, task, role, provider, quota=None, explicit_model=None):
    """Return {model, effort, skills, kind, reasons} for a provider dispatch."""
    cfg = config['providers'][provider]
    catalog = cfg.get('models') or []
    reasons = []
    tier, effort = BY_COMPLEXITY.get(int(task['complexity']), ('standard', 'medium'))
    if role == 'review' and tier == 'light' and int(task['complexity']) > 1:
        tier, effort = 'standard', 'medium'
        reasons.append('review_floor_standard')
    reading = (quota or {}).get(provider)
    # Grouped quotas (Google) are judged per model group below; only plain plan windows downshift the whole tier.
    pressure = None if reading and 'groups' in reading else center_quota.remaining(reading)
    if pressure is not None and pressure < LOW_QUOTA:
        tier, effort = _step_down(tier), 'low' if pressure < CRITICAL_QUOTA else _clip_effort(effort, EFFORT_ORDER[:2]) or 'low'
        reasons.append(f'quota_pressure_{pressure:g}pct_downshift')
    model = None
    if explicit_model:
        model = next((m for m in catalog if m['id'] == explicit_model), {'id': explicit_model, 'efforts': []})
        reasons.append('explicit_model')
    else:
        for candidate_tier in (tier, *reversed(TIERS[:TIERS.index(tier)]), *TIERS[TIERS.index(tier) + 1:]):
            for entry in catalog:
                if entry.get('tier') != candidate_tier:
                    continue
                group = entry.get('quota_group')
                group_left = center_quota.remaining(reading, group) if group and reading else None
                if group_left is not None and group_left < LOW_QUOTA:
                    reasons.append(f"skip_{entry['id']}_group_quota_{group_left:g}pct")
                    continue
                model = entry
                break
            if model:
                if candidate_tier != tier:
                    reasons.append(f'tier_{tier}_unavailable_used_{candidate_tier}')
                break
    if model is None:
        return {'model': cfg.get('model'), 'effort': None, 'skills': [], 'kind': None, 'reasons': ['no_model_catalog_use_provider_default']}
    final_effort = _clip_effort(effort, model.get('efforts'))
    kind = classify_kind(task['title'], task['prompt'])
    skills = pick_skills(config, role, kind)
    reasons.append(f"complexity_{task['complexity']}_{role}_{kind}")
    return {'model': model['id'], 'effort': final_effort, 'skills': skills, 'kind': kind, 'reasons': reasons}


def skill_brief(config, names, limit=2400):
    """Instruction text for the selected skills, bounded so it cannot flood the prompt."""
    parts = []
    for name in names:
        skill = config['skills'][name]
        parts.append(f"SKILL {name}: {skill['instruction'].strip()}")
    text = '\n'.join(parts)
    return text[:limit]


def quota_bucket(reading):
    """0 healthy/unknown, 1 low, 2 critical. Unknown is not a penalty and not an endorsement."""
    left = center_quota.remaining(reading, best_group=True)
    if left is None or left >= LOW_QUOTA:
        return 0
    return 2 if left < CRITICAL_QUOTA else 1

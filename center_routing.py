"""Provider routing: who may take a task, and why a task is still waiting."""
from __future__ import annotations

import json
import time

import center_policy
import center_quota
from center_context import source_bytes


LIVE_PROVIDERS = ('codex', 'claude', 'google')


def _codex_context_too_large(task, config, limit):
    """The Codex adapter pre-reads every in-scope file into its prompt (Claude and Google read files themselves).

    Returns the scope size in bytes when it exceeds the limit, else None. Unknown size never excludes Codex.
    """
    try:
        size = source_bytes(task['workspace'], task['base_rev'], json.loads(task['scope_json']), config.get('read_set'))
    except (KeyError, ValueError, TypeError, OSError, AttributeError):
        return None
    return size if size is not None and size > limit else None


class RoutingMixin:
    def candidates(self, task, role, requested=None):
        config = json.loads(task["config_json"])
        health = self.provider_status()
        with self.store.connection() as con:
            authors = {r[0] for r in con.execute("SELECT DISTINCT provider FROM authorship WHERE task_id=?", (task["id"],))}
            counts = {r[0]: r[1] for r in con.execute("SELECT provider,COUNT(*) FROM sessions GROUP BY provider")}
            history = [dict(r) for r in con.execute("SELECT provider,status,error FROM tasks WHERE provider IS NOT NULL AND mode='live' ORDER BY updated_at DESC LIMIT 100")]
            observations = [json.loads(r[0]) for r in con.execute("SELECT detail FROM events WHERE event='provider_result_observed' ORDER BY id DESC LIMIT 100")]
        quality, usage = {}, {}
        for row in history:
            if row['status'] in ('ready_for_human_approval', 'approved', 'failed'):
                good, total = quality.get(row['provider'], (0, 0))
                quality[row['provider']] = (good + int(row['status'] != 'failed'), total + 1)
        for row in observations:
            measured = row.get('usage_observed')
            if isinstance(measured, dict) and type(measured.get('total_tokens')) is int:
                usage[row['provider']] = usage.get(row['provider'], 0) + measured['total_tokens']
        options = []
        quota = self.quota_reader() or {}
        notes = []
        codex_limit = self.config.get('max_model_context_bytes', 2097152)
        codex_size = None
        if self.config.get('codex_context_guard', True) and role == "implementation" and task.get("mode") == "live" and "codex" in config["allowed_providers"]:
            codex_size = _codex_context_too_large(task, config, codex_limit)
            if codex_size is not None and requested == "codex":
                # A pin cannot be honoured: Codex can never take this scope, so waiting would strand the task forever.
                # Fall back to the other allowed providers (they read files themselves) and leave a trail.
                requested = None
                notes.append(f"requested_codex_unfit_scope_{codex_size}_bytes_fell_back_to_other_providers")
        for name in config["allowed_providers"]:
            p = health[name]
            if name == "codex" and codex_size is not None:
                notes.append(f"codex_skipped_scope_{codex_size}_bytes_exceeds_{codex_limit}_context_limit")
                continue
            if requested and name != requested or role == "review" and name in authors:
                continue
            if role not in p.get("roles", []) or task["complexity"] > p.get("max_complexity", 5) or p["capacity"] <= 0:
                continue
            if p["availability"] == "unavailable" or p.get("cooldown_until", 0) > time.time():
                continue
            if task["mode"] == "live" and p.get("entitlement") != "subscription":
                continue
            # Capacity/load informs routing; an unknown quota is never treated as zero usage.
            good, total = quality.get(name, (0, 0))
            failure_rate = (total - good) / total if total else 0
            # Unknown usage never masquerades as zero; compare usage only when
            # every eligible subscription has measurements in the same window.
            reading = quota.get(name)
            bucket = center_policy.quota_bucket(reading)
            above_floor, floor_detail = center_quota.floor_check(reading, self.quota_floors())
            if not above_floor:
                notes.append(f'quota_floor_skipped_{name}_{floor_detail}')
                continue
            left = center_quota.remaining(reading, best_group=True)
            if left is not None and left < 5:
                continue  # effectively exhausted: wait for the reset instead of burning the last of the plan
            options.append((bucket, counts.get(name, 0) / p["capacity"], failure_rate, left is None, -(left or 0.0), name))  # unknown quota sorts after observed-healthy, never as a made-up number
        if notes and isinstance(getattr(self, 'candidate_notes', None), dict):
            if len(self.candidate_notes) > 500:
                self.candidate_notes.clear()
            self.candidate_notes[task['id']] = notes
        measured_all = bool(options) and all(o[5] in usage for o in options)
        return [o[5] for o in sorted(options, key=lambda o: (o[0], o[1], o[2], o[3], o[4], usage[o[5]] if measured_all else 0, o[5]))]

    def scheduling_readiness(self, task_id, role, adapter='live', provider=None):
        """Advisory eligibility. claim repeats mutable checks atomically."""
        task = self.store.task(task_id)
        def waiting(reason):
            return {'ready': False, 'reason': reason, 'provider': None}
        expected = ('queued', 'retry_wait') if role == 'implementation' else ('waiting_for_independent_review',)
        if task['status'] not in expected or task['cancel_requested']:
            return waiting('task_not_dispatchable')
        if task['not_before'] > time.time():
            return waiting('retry_backoff')
        if adapter == 'live' and not self.config['live_execution']:
            return waiting('live_execution_disabled')
        if (adapter == 'mock') != (task['mode'] == 'mock'):
            return waiting('adapter_mode_mismatch')
        if adapter == 'live' and json.loads(task['config_json']).get('hold_for_ide'):
            return waiting('held_for_ide_handoff')
        attempt = task['attempt'] if role == 'implementation' else task['review_attempt']
        if attempt >= task['max_attempts']:
            return waiting('attempt_limit')
        with self.store.connection() as con:
            if con.execute('SELECT 1 FROM sessions WHERE task_id=?', (task_id,)).fetchone():
                return waiting('active_assignment')
            if role == 'implementation':
                for dep in json.loads(task['dependencies_json']):
                    row = con.execute('SELECT status FROM tasks WHERE id=?', (dep,)).fetchone()
                    if not row or row[0] != 'approved':
                        return waiting('dependency_not_approved')
            if con.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] >= self.usable_capacity():
                return waiting('global_capacity')
            project_count = con.execute('SELECT COUNT(*) FROM sessions s JOIN tasks t ON t.id=s.task_id WHERE t.project_id=?', (task['project_id'],)).fetchone()[0]
            if project_count >= self.config.get('project_capacity', self.usable_capacity()):
                return waiting('project_capacity')
            counts = {r[0]: r[1] for r in con.execute('SELECT provider,COUNT(*) FROM sessions GROUP BY provider')}
        requested = provider or (task['requested_provider'] if role == 'implementation' and task['requested_provider'] != 'auto' else None)
        options = self.candidates(task, role, requested)
        if adapter == 'live':
            health = self.provider_status()
            options = [p for p in options if p in LIVE_PROVIDERS and health[p]['availability'] == 'available']
            if options and role == 'implementation':
                # Do not start work that could never be independently reviewed: another allowed provider that has not authored
                # this task must still be able to review it, otherwise the task would stall in waiting_for_independent_review.
                allowed = json.loads(task['config_json']).get('allowed_providers', [])
                with self.store.connection() as con:
                    authors = {r[0] for r in con.execute('SELECT DISTINCT provider FROM authorship WHERE task_id=?', (task_id,))}
                options = [name for name in options if any(
                    p != name and p not in authors and p in LIVE_PROVIDERS and 'review' in self.config['providers'][p].get('roles', [])
                    and health[p]['availability'] == 'available' for p in allowed)]
                if not options:
                    return waiting('no_independent_reviewer_available')
        if not options:
            if any(n.startswith('quota_floor_skipped') for n in self.candidate_notes.get(task_id, [])):
                return waiting('provider_quota_floor')
            return waiting('awaiting_independent_or_human_review' if role == 'review' else 'provider_unavailable_or_handoff_required')
        for name in options:
            if counts.get(name, 0) < self.config['providers'][name]['capacity']:
                return {'ready': True, 'reason': 'eligible_by_capacity_capability_health_quality_and_observed_usage', 'provider': name}
        return waiting('provider_capacity')

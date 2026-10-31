"""Explicit, checkpoint-backed dependency overlays; never commit or merge Git.

An overlay is authorized by dependency_policy=overlay at submission. All inputs
must share the recorded base and fit the consumer's explicit scope. Checkpoints
and current approved worktrees are verified before copying any bytes. Unrelated
dependencies may agree on a file, but conflicting versions fail closed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from center_workspace import EXCLUDED, canonical, git, in_scope, inside, safe_relative, sensitive


def _json_file(path, root, limit):
    path = Path(path)
    if path.is_symlink() or not inside(path, root):
        raise ValueError('Dependency checkpoint aliases or escapes Center state')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Dependency checkpoint metadata exceeds limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Dependency checkpoint metadata must be an object')
    return value


def _dependency_snapshot(center, consumer, dependency):
    if dependency['project_id'] != consumer['project_id'] or dependency['mode'] != consumer['mode']:
        raise ValueError('Dependency must belong to the same project and execution mode')
    if dependency['status'] != 'approved':
        raise ValueError('Dependency is not approved')
    if dependency['base_rev'] != consumer['base_rev']:
        raise ValueError('Dependency base differs; explicitly integrate and submit from a common reviewed base')
    center.validate_evidence(dependency['id'])
    saved = canonical(dependency.get('checkpoint') or '')
    checkpoint_root = canonical(center.store.state / 'checkpoints' / dependency['id'])
    if not dependency.get('checkpoint') or not inside(saved, checkpoint_root):
        raise ValueError('Dependency lacks an owned checkpoint')
    maximum = center.config['max_checkpoint_bytes']
    metadata = _json_file(saved / 'manifest.json', saved, maximum)
    tracked = saved / 'tracked.patch'
    if tracked.is_symlink() or not inside(tracked, saved) or tracked.stat().st_size > maximum:
        raise ValueError('Unsafe dependency tracked patch')
    raw_diff = tracked.read_bytes()
    manifest = metadata.get('manifest')
    if metadata.get('base_rev') != dependency['base_rev'] or not isinstance(manifest, list):
        raise ValueError('Dependency checkpoint base or manifest mismatch')
    payload = json.dumps({'base_rev': metadata['base_rev'], 'manifest': manifest}, sort_keys=True, separators=(',', ':')).encode()
    identity = hashlib.sha256(payload + b'\0' + raw_diff).hexdigest()
    if identity != metadata.get('patch_hash') or identity != dependency.get('patch_hash'):
        raise ValueError('Dependency checkpoint identity mismatch')
    scope = json.loads(consumer['scope_json'])
    root = canonical(dependency['worktree'])
    files, total = {}, len(raw_diff)
    for item in manifest:
        name = safe_relative(item['path'])
        if name in files or sensitive(name) or any(part in EXCLUDED for part in Path(name).parts):
            raise ValueError('Unsafe dependency manifest path')
        if not in_scope(name, scope):
            raise ValueError('Dependency changes exceed task scope; explicitly expand scope or integrate before submission')
        source = saved / 'files' / name if item['untracked'] else root / name
        source_root = saved if item['untracked'] else root
        if source.is_symlink() or not inside(source, source_root):
            raise ValueError('Unsafe dependency source path')
        expected = item.get('sha256')
        if expected is None:
            if source.exists():
                raise ValueError('Dependency deleted file reappeared')
            files[name] = {'content': None, 'sha256': None, 'size': 0, 'executable': 0}
            continue
        if not source.is_file() or source.stat().st_size > maximum:
            raise ValueError('Dependency source missing or exceeds limit')
        with source.open('rb') as stream:
            data = stream.read(maximum + 1)
        total += len(data)
        if total > maximum or len(data) != item['size'] or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Dependency source integrity mismatch')
        files[name] = {'content': data, 'sha256': expected, 'size': len(data), 'executable': source.stat().st_mode & 0o111}
    # A source could change while the snapshot is copied. Recheck the full patch.
    center.validate_evidence(dependency['id'])
    with center.store.connection() as con:
        providers = sorted({row[0] for row in con.execute('SELECT DISTINCT provider FROM authorship WHERE task_id=?', (dependency['id'],))})
    if not providers:
        raise ValueError('Dependency lacks authorship provenance')
    identity_record = {key: dependency[key] for key in ('id', 'base_rev', 'patch_hash')}
    identity_record['task_id'] = identity_record.pop('id')
    return identity_record, files, providers


def _collect(center, task):
    ordered, visiting, visited = [], set(), set()
    ancestors = {}

    def visit(task_id):
        if task_id == task['id'] or task_id in visiting:
            raise ValueError('Cyclic dependency overlay')
        if task_id in visited:
            return
        visiting.add(task_id)
        dependency = center.store.task(task_id)
        parents = json.loads(dependency['dependencies_json'])
        ancestors[task_id] = set()
        for parent in sorted(set(parents)):
            visit(parent)
            ancestors[task_id].update(ancestors[parent] | {parent})
        visiting.remove(task_id)
        visited.add(task_id)
        ordered.append(dependency)

    for task_id in sorted(set(json.loads(task['dependencies_json']))):
        visit(task_id)
    identities, contents, owners, providers = [], {}, {}, set()
    for dependency in ordered:
        identity, files, authors = _dependency_snapshot(center, task, dependency)
        if json.loads(dependency['config_json']).get('dependency_policy') == 'overlay':
            # A descendant checkpoint is a complete composite versus base. An
            # ancestor path absent from that diff was deliberately restored to
            # base (including removing a previously new file), not forgotten.
            for name, owner in list(owners.items()):
                if owner in ancestors[dependency['id']] and name not in files:
                    entry = git(dependency['worktree'], 'ls-tree', '-z', dependency['base_rev'], '--', name)
                    if not entry:
                        files[name] = {'content': None, 'sha256': None, 'size': 0, 'executable': 0}
                    else:
                        mode = entry.split(' ', 1)[0]
                        if mode not in ('100644', '100755'):
                            raise ValueError('Unsupported dependency base file mode')
                        content = git(dependency['worktree'], 'show', dependency['base_rev'] + ':' + name, binary=True)
                        if len(content) > center.config['max_checkpoint_bytes']:
                            raise ValueError('Dependency base content exceeds checkpoint limit')
                        files[name] = {'content': content, 'sha256': hashlib.sha256(content).hexdigest(),
                                       'size': len(content), 'executable': 0o111 if mode == '100755' else 0}
        identities.append(identity)
        providers.update(authors)
        for name, value in files.items():
            previous = owners.get(name)
            if previous and previous not in ancestors[dependency['id']] and contents[name]['sha256'] != value['sha256']:
                raise ValueError('Conflicting unrelated dependency changes; explicit integration is required')
            contents[name] = value
            owners[name] = dependency['id']
    if sum(value['size'] for value in contents.values()) > center.config['max_checkpoint_bytes']:
        raise ValueError('Combined dependency overlay exceeds checkpoint limit')
    manifest = [{'path': name, 'sha256': item['sha256'], 'size': item['size'], 'executable': item['executable']} for name, item in sorted(contents.items())]
    overlay_hash = hashlib.sha256(json.dumps({'dependencies': identities, 'manifest': manifest}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'overlay_hash': overlay_hash, 'dependencies': identities, 'inherited_providers': sorted(providers), 'manifest': manifest}, contents


def verify_dependencies(center, task, expected_deps):
    """Recheck every approved ancestor against the identities captured at prepare."""
    config = json.loads(task['config_json'])
    if config.get('dependency_policy', 'ordering') != 'overlay':
        if expected_deps:
            raise ValueError('Unexpected dependency provenance for ordering-only task')
        return []
    collected, _contents = _collect(center, task)
    if collected['dependencies'] != expected_deps:
        raise ValueError('Dependency approval identity changed; preserve work and explicitly reconcile')
    return collected['dependencies']


def compose_dependencies(center, task, worktree):
    """Apply verified file snapshots to a pristine task checkout, with no commits.

    Retries restore their own composite checkpoint directly and use
    verify_dependencies(); composing twice would double-apply old tracked diffs.
    """
    config = json.loads(task['config_json'])
    if config.get('dependency_policy', 'ordering') != 'overlay':
        return {'overlay_hash': None, 'dependencies': [], 'inherited_providers': [], 'manifest': []}
    worktree = canonical(worktree)
    if git(worktree, 'rev-parse', 'HEAD') != task['base_rev'] or git(worktree, 'status', '--porcelain', '--untracked-files=all', '--ignored'):
        raise ValueError('Dependency overlay requires a pristine checkout at the recorded base')
    result, files = _collect(center, task)
    # Validate every destination before applying any content. Partial I/O failure
    # remains in the task worktree for normal checkpoint/recovery, never reset.
    expected_destinations = {}
    for name in files:
        target = worktree / name
        if target.is_symlink() or not inside(target, worktree) or target.exists() and not target.is_file():
            raise ValueError('Unsafe dependency destination')
        if target.exists():
            with target.open('rb') as stream:
                expected_destinations[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        else:
            expected_destinations[name] = None
    for name, item in sorted(files.items()):
        target = worktree / name
        if target.is_symlink() or not inside(target, worktree):
            raise ValueError('Dependency destination changed while composing')
        actual = None
        if target.exists():
            if not target.is_file():
                raise ValueError('Dependency destination changed while composing')
            with target.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected_destinations[name]:
            raise ValueError('Dependency destination changed while composing; preserve external edits')
        if item['content'] is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as stream:
                stream.write(item['content'])
            target.chmod((target.stat().st_mode & ~0o111) | item['executable'])
    return result

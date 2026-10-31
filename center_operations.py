"""Local recovery tools: bounded inventory, verified backups, non-destructive drills.

No retention deletion, credential discovery, system scheduling or production
restore is performed. A drill always writes a new directory and leaves the
source database and existing worktrees untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile

from center_store import now
from center_workspace import inside, sensitive, valid_id

ROOT = Path(__file__).resolve().parent
MAX_FILES = 10000
MAX_ENTRIES = 500
MAX_BACKUP_CHECKPOINT_BYTES = 64 * 1024 * 1024


def _checkpoint_snapshot(center, reference, budget):
    """Hash owned checkpoint metadata only; never follow legacy/outside pointers.

    This binds the manifest and tracked patch to the backup's recorded patch
    identity. It is not a copy or a full restore verification of source files.
    """
    result = {'status': 'missing', 'verification_scope': 'manifest_and_tracked_patch_only'}
    consumed = 0
    pointer = reference.get('checkpoint')
    if not pointer:
        return {**result, 'reason': 'checkpoint_not_recorded'}, 0
    try:
        task_id = valid_id(reference['id'])
        saved = Path(pointer)
        owned = center.store.state / 'checkpoints' / task_id
        if saved.is_symlink() or not inside(owned, center.store.state) or not inside(saved, owned):
            return {**result, 'status': 'unsafe', 'reason': 'checkpoint_outside_owned_task_state'}, 0
        if not saved.is_dir():
            return {**result, 'reason': 'checkpoint_directory_missing'}, 0
        manifest, tracked = saved / 'manifest.json', saved / 'tracked.patch'
        for path in (manifest, tracked):
            if path.is_symlink() or not inside(path, saved):
                return {**result, 'status': 'unsafe', 'reason': 'checkpoint_metadata_link'}, 0
            if not path.is_file():
                return {**result, 'reason': 'checkpoint_metadata_missing'}, 0
        maximum = min(center.config.get('max_checkpoint_bytes', 10 * 1024 * 1024), MAX_BACKUP_CHECKPOINT_BYTES)
        sizes = manifest.stat().st_size + tracked.stat().st_size
        if sizes > maximum or sizes > budget:
            return {**result, 'status': 'limit', 'reason': 'checkpoint_metadata_scan_limit'}, 0
        with manifest.open('rb') as stream:
            raw_manifest = stream.read(sizes + 1)
        with tracked.open('rb') as stream:
            raw_patch = stream.read(max(0, sizes - len(raw_manifest)) + 1)
        consumed = len(raw_manifest) + len(raw_patch)
        if consumed != sizes:
            return {**result, 'status': 'corrupt', 'reason': 'checkpoint_metadata_changed_while_reading'}, consumed
        result.update({'manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(),
                       'tracked_patch_sha256': hashlib.sha256(raw_patch).hexdigest()})
        metadata = json.loads(raw_manifest)
        if not isinstance(metadata, dict) or not isinstance(metadata.get('manifest'), list):
            return {**result, 'status': 'corrupt', 'reason': 'invalid_checkpoint_manifest'}, consumed
        payload = json.dumps({'base_rev': metadata.get('base_rev'), 'manifest': metadata['manifest']}, sort_keys=True, separators=(',', ':')).encode()
        computed = hashlib.sha256(payload + b'\0' + raw_patch).hexdigest()
        if metadata.get('base_rev') != reference.get('base_rev') or computed != metadata.get('patch_hash') or computed != reference.get('patch_hash'):
            return {**result, 'status': 'corrupt', 'reason': 'checkpoint_patch_identity_mismatch'}, consumed
        return {**result, 'status': 'verified', 'patch_hash': computed}, consumed
    except (OSError, ValueError, KeyError, TypeError):
        return {**result, 'status': 'corrupt', 'reason': 'checkpoint_metadata_unreadable_or_invalid'}, consumed


def _references(center):
    with center.store.connection() as con:
        return [dict(row) for row in con.execute('SELECT id,project_id,status,attempt,worktree,checkpoint,base_rev,patch_hash FROM tasks ORDER BY created_at,id')]


def _inventory(root, remaining):
    size = files = examined = 0
    warnings, pending = [], [root]
    if not root.is_dir() or root.is_symlink():
        return {'bytes': 0, 'files': 0, 'entries_scanned': 0, 'scan_complete': False}, ['linked_or_missing_entry']
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if examined >= remaining:
                        return {'bytes': size, 'files': files, 'entries_scanned': examined, 'scan_complete': False}, warnings + ['scan_limit_reached']
                    examined += 1
                    target = Path(entry.path)
                    if entry.is_symlink() or not inside(target, root):
                        warnings.append('linked_entry_skipped')
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(target)
                    elif entry.is_file(follow_symlinks=False):
                        size += entry.stat(follow_symlinks=False).st_size
                        files += 1
        except OSError:
            warnings.append('unreadable_entry')
    return {'bytes': size, 'files': files, 'entries_scanned': examined, 'scan_complete': not warnings}, warnings


def _owned_entries(base, depth, warnings):
    """Bounded directory walk that rejects links before descending into them."""
    pending, examined = [(base, 0)], 0
    while pending:
        parent, level = pending.pop()
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    examined += 1
                    if examined > MAX_ENTRIES * 4:
                        warnings.append('entry_limit_reached')
                        return
                    path = Path(entry.path)
                    if entry.is_symlink() or not inside(path, base):
                        warnings.append('linked_entry_skipped')
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if level + 1 == depth:
                        yield path
                    else:
                        pending.append((path, level + 1))
        except OSError:
            warnings.append('unreadable_entry')


def maintenance_report(center):
    """Inventory only owned state paths; orphan candidates are never deleted."""
    state = center.store.state.resolve()
    references = _references(center)
    known = {row['id']: row for row in references}
    report = {'state_dir': str(state), 'policy': 'report_only_no_deletion', 'scanned_files': 0, 'scanned_entries': 0,
              'total_bytes': 0, 'scan_complete': True, 'worktrees': [], 'checkpoints': [], 'warnings': []}
    for kind in ('worktrees', 'checkpoints'):
        base = state / kind
        if not base.exists():
            continue
        if base.is_symlink() or not inside(base, state):
            report['warnings'].append('linked_state_directory_skipped')
            report['scan_complete'] = False
            continue
        # Owned layout: worktrees/project/task/attempt, checkpoints/task/snapshot.
        depth = 3 if kind == 'worktrees' else 2
        for entry in _owned_entries(base, depth, report['warnings']):
            if len(report['worktrees']) + len(report['checkpoints']) >= MAX_ENTRIES:
                report['warnings'].append('entry_limit_reached')
                report['scan_complete'] = False
                break
            if entry.is_symlink() or not inside(entry, state):
                report['warnings'].append('linked_entry_skipped')
                report['scan_complete'] = False
                continue
            if not entry.is_dir():
                continue
            task_id = entry.parent.name
            task = known.get(task_id)
            pointer = task.get('worktree' if kind == 'worktrees' else 'checkpoint') if task else None
            classification = 'current' if pointer and Path(pointer).resolve() == entry.resolve() else 'historical_preserved' if task else 'orphan_candidate_preserved'
            stats, warnings = _inventory(entry, max(0, MAX_FILES - report['scanned_entries']))
            report[kind].append({'path': str(entry), 'task_id': task_id, 'classification': classification, **stats})
            report['scanned_files'] += stats['files']
            report['scanned_entries'] += stats['entries_scanned']
            report['total_bytes'] += stats['bytes']
            report['scan_complete'] = report['scan_complete'] and stats['scan_complete']
            report['warnings'].extend(warnings)
    report['warnings'] = sorted(set(report['warnings']))
    if report['warnings']:
        report['scan_complete'] = False
    report['updated_at'] = now()
    return report


@contextmanager
def _readonly(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or sensitive(str(path)) or sensitive(str(path.resolve())):
        raise ValueError('Backup must be an explicit regular SQLite file, not credentials or a link')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        yield connection
    finally:
        connection.close()


def _integrity_and_counts(connection):
    integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok':
        raise ValueError('SQLite integrity check failed; preserve backup for inspection')
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
              for table in ('projects', 'tasks', 'events', 'evidence', 'authorship', 'sessions') if table in existing}
    if 'tasks' not in counts:
        raise ValueError('SQLite file is not a Center backup')
    return integrity, counts


def verified_backup(center):
    """SQLite backup API plus integrity check and reference-only recovery manifest."""
    backup = Path(center.store.backup()).resolve()
    if not inside(backup, center.store.state / 'backups'):
        raise ValueError('Backup path escaped Center state')
    with _readonly(backup) as connection:
        integrity, counts = _integrity_and_counts(connection)
        connection.row_factory = sqlite3.Row
        # Read references from the consistent backup, never a later live state.
        references = [dict(row) for row in connection.execute('SELECT id,project_id,status,attempt,worktree,checkpoint,base_rev,patch_hash FROM tasks ORDER BY created_at,id')]
    config_hash = hashlib.sha256(json.dumps(center.config, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    checkpoint_bytes = 0
    warnings = []
    for reference in references:
        snapshot, consumed = _checkpoint_snapshot(center, reference, MAX_BACKUP_CHECKPOINT_BYTES - checkpoint_bytes)
        reference['checkpoint_snapshot'] = snapshot
        checkpoint_bytes += consumed
        if snapshot['status'] != 'verified':
            warnings.append({'task_id': reference['id'], 'status': snapshot['status'], 'reason': snapshot['reason']})
    result = {'backup_path': str(backup), 'integrity': integrity, 'counts': counts, 'references': references,
              'config_sha256': config_hash, 'created_at': now(), 'checkpoint_metadata_bytes': checkpoint_bytes,
              'checkpoint_reference_warnings': warnings, 'policy': 'database_and_reference_manifest_no_worktree_deletion'}
    manifest = backup.with_suffix('.manifest.json')
    with manifest.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2))
    return {**result, 'manifest_path': str(manifest)}


def restore_drill(backup_path, destination):
    """Copy a backup into a NEW directory using SQLite's backup API.

    Explicit drill destinations are restricted to this workspace or the system
    temporary directory. No active configuration/database pointer is switched.
    Existing paths, including empty directories, are always refused.
    """
    supplied = Path(destination)
    destination = supplied.resolve()
    if supplied.is_symlink() or supplied.exists():
        raise ValueError('Restore drill destination must not already exist')
    if not destination.parent.is_dir():
        raise ValueError('Restore drill parent directory must already exist')
    if not (inside(destination, ROOT) or inside(destination, Path(tempfile.gettempdir()))):
        raise ValueError('Restore drill destination must be inside the workspace or system temporary directory')
    with _readonly(backup_path) as source:
        _integrity_and_counts(source)
        destination.mkdir(exist_ok=False)
        database = destination / 'tasks.sqlite3'
        target = sqlite3.connect(database)
        try:
            source.backup(target)
            integrity, counts = _integrity_and_counts(target)
        finally:
            target.close()
    return {'source_backup': str(Path(backup_path).resolve()), 'destination': str(destination),
            'database_path': str(database), 'integrity': integrity, 'counts': counts,
            'policy': 'isolated_drill_only_active_database_unchanged'}

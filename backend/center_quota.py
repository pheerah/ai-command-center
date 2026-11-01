"""Single owner of plan-quota observation (5-hour / weekly windows) for every provider.

The scheduler refreshes it each minute and writes quota-last.json in the state
directory; routing and the dashboard only read that snapshot. When a source cannot
be read the last good value is kept and marked stale, never replaced by "unknown".

No credential files are read. Sources are each CLI's own local state or output:
Codex session logs, Claude's own CLI (its rate_limit_event), Claude Code's
statusline file, and Antigravity's loopback language server (csrf token from its
daemon file, loopback only). Unknown quota is never treated as zero or as full.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT = 'quota-last.json'
CLAUDE_CLI_INTERVAL = 300.0   # one tiny Haiku call; spends plan tokens, so poll slowly
_lock = threading.Lock()
_claude = {'at': 0.0, 'last': None}
MAX_AGE = {'claude': 2 * CLAUDE_CLI_INTERVAL + 60, 'codex': 6 * 3600.0}  # codex only changes while it runs


def _window(used_percent, minutes, resets_at):
    if used_percent is None:
        return None
    used = min(100.0, max(0.0, float(used_percent)))
    return {'used_percent': round(used, 1), 'remaining_percent': round(100.0 - used, 1), 'window_minutes': minutes, 'resets_at': resets_at}


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00', 'Z') if epoch else None


def _newest_jsonl(root, depth=0):
    best = None
    try:
        entries = list(os.scandir(root))
    except OSError:
        return None
    for entry in entries:
        if entry.is_dir(follow_symlinks=False) and depth < 4:
            found = _newest_jsonl(entry.path, depth + 1)
        elif entry.is_file() and entry.name.endswith('.jsonl'):
            found = (entry.stat().st_mtime, entry.path)
        else:
            continue
        if found and (not best or found[0] > best[0]):
            best = found
    return best


def read_codex(home):
    newest = _newest_jsonl(Path(home) / '.codex' / 'sessions')
    if not newest:
        return None
    try:
        size = os.path.getsize(newest[1])
        with open(newest[1], 'rb') as stream:
            stream.seek(max(0, size - 1048576))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"rate_limits"' not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        limits = (row.get('payload') or {}).get('rate_limits') or row.get('rate_limits')
        if not isinstance(limits, dict) or not isinstance(limits.get('primary'), dict):
            continue

        def win(raw, minutes):
            if not isinstance(raw, dict):
                return None
            return _window(raw.get('used_percent'), raw.get('window_minutes') or minutes, _iso(raw.get('resets_at')))
        return {'five_hour': win(limits['primary'], 300), 'weekly': win(limits.get('secondary'), 10080),
                'observed_at': _iso(newest[0]), 'source': 'codex_session_log'}
    return None


def _claude_statusline(home):
    try:
        data = json.loads((Path(home) / '.claude' / 'usage-monitor-rate-limits.json').read_text(encoding='utf-8'))
        limits = data['rate_limits']

        def win(raw, minutes):
            if not isinstance(raw, dict):
                return None
            reset = raw.get('resets_at')
            if isinstance(reset, str):
                reset = datetime.fromisoformat(reset.replace('Z', '+00:00')).timestamp()
            return _window(raw.get('used_percentage', raw.get('utilization')), minutes, _iso(reset))
        return {'five_hour': win(limits.get('five_hour'), 300), 'weekly': win(limits.get('seven_day'), 10080),
                'observed_at': _iso(data['updatedAt'] / 1000), 'source': 'claude_statusline'}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_claude(home, now=None):
    """Ask Claude's own CLI: every reply carries a rate_limit_event with plan utilisation."""
    now = time.time() if now is None else now
    with _lock:
        if now - _claude['at'] >= CLAUDE_CLI_INTERVAL:
            _claude['at'] = now
            args = ['-p', 'ok', '--model', 'claude-haiku-5-5', '--effort', 'low', '--output-format', 'stream-json', '--verbose']
            command = ['cmd', '/c', 'claude', *args] if os.name == 'nt' else ['claude', *args]
            try:
                from center_process import worker_env
                output = subprocess.run(command, cwd=tempfile.gettempdir(), capture_output=True, timeout=90, env=worker_env(), check=False).stdout
            except (OSError, subprocess.SubprocessError, ValueError):
                output = b''
            for line in output.decode('utf-8', errors='replace').splitlines():
                if 'rate_limit_event' not in line:
                    continue
                try:
                    windows = json.loads(line)['rate_limit_info']['unifiedWindows']
                except (ValueError, KeyError, TypeError):
                    continue

                def win(raw, minutes):
                    if not isinstance(raw, dict) or raw.get('utilization') is None:
                        return None
                    return _window(float(raw['utilization']) * 100.0, minutes, _iso(raw.get('resetsAt')))
                _claude['last'] = {'five_hour': win(windows.get('five_hour'), 300), 'weekly': win(windows.get('seven_day'), 10080),
                                   'observed_at': _iso(now), 'source': 'claude_cli_rate_limit_event'}
                break
        return _claude['last'] or _claude_statusline(home)


def read_google(home):
    daemon = Path(home) / '.gemini' / 'antigravity' / 'daemon'
    try:
        hubs = sorted(daemon.glob('hub_*.json'))
    except OSError:
        return None
    for hub_file in hubs:
        try:
            hub = json.loads(hub_file.read_text(encoding='utf-8'))
            request = urllib.request.Request(
                f"http://127.0.0.1:{int(hub['httpPort'])}/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
                data=b'{}', method='POST',
                headers={'Content-Type': 'application/json', 'Connect-Protocol-Version': '1', 'X-Codeium-Csrf-Token': hub['csrfToken']})
            with urllib.request.urlopen(request, timeout=3) as response:
                summary = json.loads(response.read()).get('response') or {}
        except (OSError, ValueError, KeyError, TypeError):
            continue
        groups = {}
        for group in summary.get('groups', []):
            def bucket(window, minutes):
                found = next((b for b in group.get('buckets', []) if b.get('window') == window), None)
                if not found or found.get('remainingFraction') is None:
                    return None
                return _window(100.0 - float(found['remainingFraction']) * 100.0, minutes, found.get('resetTime'))
            groups[group.get('displayName', 'unknown')] = {'five_hour': bucket('5h', 300), 'weekly': bucket('weekly', 10080)}
        if groups:
            return {'groups': groups, 'observed_at': _iso(time.time()), 'source': 'antigravity_quota_summary'}
    return None


def remaining(reading, group=None, best_group=False):
    """Tightest remaining percent across the known windows, or None when nothing is known.

    For grouped quotas (Google) a named group is used when given; otherwise the tightest group,
    or the most open one with best_group=True (what routing needs: can the provider do any work?).
    """
    if not reading:
        return None
    if 'groups' in reading:
        groups = reading['groups']
        if group in groups:
            reading = groups[group]
        elif groups:
            def tight(g):
                return min((w['remaining_percent'] for w in g.values() if w), default=101)
            reading = (max if best_group else min)(groups.values(), key=tight)
        else:
            return None
    values = [w['remaining_percent'] for w in (reading.get('five_hour'), reading.get('weekly')) if w]
    return min(values) if values else None


def floor_check(reading, floors):
    """(ok, detail): a provider is below the floor when a KNOWN window has less left than that window's floor.

    Unknown quota never blocks. For grouped quotas (Google) the provider is fine when any one group is above both floors,
    because routing can still pick a model from that group.
    """
    if not reading:
        return True, ''
    windows = list(reading['groups'].values()) if 'groups' in reading else [reading]
    first_problems = None
    for group in windows:
        problems = []
        for key in ('five_hour', 'weekly'):
            window = group.get(key)
            if window and window['remaining_percent'] < floors[key]:
                problems.append(f"{key}_{window['remaining_percent']:g}pct_below_{floors[key]:g}")
        if not problems:
            return True, ''
        first_problems = first_problems or problems
    return False, ','.join(first_problems or [])


def _snapshot_path(state):
    return Path(state) / SNAPSHOT


def snapshot(state):
    """Last stored readings {provider: reading|None}; empty when the scheduler has not written any yet."""
    try:
        data = json.loads(_snapshot_path(state).read_text(encoding='utf-8'))
        return {name: data.get(name) for name in ('codex', 'claude', 'google')}
    except (OSError, ValueError):
        return {}


def refresh(state, home=None, readers=None):
    """Read every source once, keep the last good value (marked stale) where a read fails, and persist."""
    home = home or os.environ.get('AI_CENTER_HOME') or os.path.expanduser('~')
    readers = readers or {'codex': read_codex, 'claude': read_claude, 'google': read_google}
    previous = snapshot(state)
    result = {}
    for name, reader in readers.items():
        try:
            fresh = reader(home)
        except Exception:  # an observer must never break scheduling
            fresh = None
        old = previous.get(name)
        if fresh:
            # Fresh unless its own observation is older than twice that source's poll interval.
            age = time.time() - datetime.fromisoformat(fresh['observed_at'].replace('Z', '+00:00')).timestamp() if fresh.get('observed_at') else 0
            result[name] = {**fresh, 'stale': age > MAX_AGE.get(name, 180.0)}
        elif old:
            result[name] = {**old, 'stale': True}
        else:
            result[name] = None
    target = _snapshot_path(state)
    temporary = target.with_suffix('.tmp')
    try:
        Path(state).mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(result), encoding='utf-8')
        temporary.replace(target)
    except OSError:
        pass
    return result

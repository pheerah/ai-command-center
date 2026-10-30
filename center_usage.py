"""Read-only usage meter from Center-owned CLI output, never auth files/APIs.

Token activity is not subscription quota or billing. Logs without a valid
provider usage object remain unmeasured; mock invocations never count as usage.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

BANGKOK = timezone(timedelta(hours=7))
FIELDS = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_tokens', 'total_tokens')


def counter(value):
    return value if type(value) is int and 0 <= value <= 9007199254740991 else None


def parse_usage(provider, text):
    """Only documented completed-result usage; never add nested usage twice."""
    totals = dict.fromkeys(FIELDS, 0)
    observed = False
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if provider == 'codex' and row.get('type') != 'turn.completed':
            continue
        if provider == 'claude' and row.get('type') != 'result':
            continue
        usage = row.get('usage')
        if provider not in ('codex', 'claude') or not isinstance(usage, dict):
            continue
        incoming, outgoing = counter(usage.get('input_tokens')), counter(usage.get('output_tokens'))
        if incoming is None or outgoing is None:
            continue
        cache_read = counter(usage.get('cached_input_tokens' if provider == 'codex' else 'cache_read_input_tokens', 0))
        cache_write = counter(usage.get('cache_write_input_tokens' if provider == 'codex' else 'cache_creation_input_tokens', 0))
        if cache_read is None or cache_write is None:
            continue
        if provider == 'codex':
            # Codex cache counts are subsets of total input, not extra tokens.
            if cache_read + cache_write > incoming:
                continue
        else:
            incoming += cache_read + cache_write
        observed = True
        for field, value in zip(FIELDS, (incoming, outgoing, cache_read, cache_write, incoming + outgoing)):
            totals[field] += value
    return totals if observed else None


def blank_day(day):
    return {'date': day, **dict.fromkeys(FIELDS, 0), 'observed_invocations': 0, 'unmeasured_invocations': 0,
            'workloads': {'tasks': 0, 'audits': 0, 'live_smoke': 0}}


def bounded_json(path, root, maximum=524288):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe usage metadata path')
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Usage metadata too large')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Usage metadata must be an object')
    return value


def usage_report(state, workspace, current_time=None):
    state, workspace = Path(state).resolve(), Path(workspace).resolve()
    timestamp = current_time or datetime.now(timezone.utc)
    today = timestamp.astimezone(BANGKOK).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in reversed(range(30))]
    providers = {name: {'days': [blank_day(day) for day in dates]} for name in ('codex', 'claude', 'google')}
    indices = {name: {d['date']: d for d in p['days']} for name, p in providers.items()}
    sources = [(state, 'tasks', 'runs/*/*/request.json'), (state, 'audits', 'audits/*/request.json')]
    warnings, seen, read_bytes, examined = [], set(), 0, 0
    config_path = state / 'usage-sources.json'
    if config_path.exists():
        try:
            configured = bounded_json(config_path, state).get('sources', [])
            if not isinstance(configured, list) or len(configured) > 16:
                raise ValueError('Invalid usage sources')
            for source in configured:
                root = Path(source['state_dir'])
                root = (workspace / root).resolve() if not root.is_absolute() else root.resolve()
                if not root.is_relative_to(workspace) or source.get('kind') != 'live_smoke':
                    raise ValueError('Additional usage source must be an explicit workspace live-smoke state')
                sources.append((root, 'live_smoke', 'runs/*/*/request.json'))
        except (OSError, ValueError, KeyError, TypeError):
            warnings.append('invalid_additional_source')
    latest = None
    for root, workload, pattern in sources:
        for metadata in root.glob(pattern):
            examined += 1
            if examined > 2000 or read_bytes > 16777216:
                warnings.append('scan_limit_reached')
                break
            log = metadata.parent / 'provider.log'
            try:
                request = bounded_json(metadata, root)
                provider = request.get('provider')
                if request.get('adapter') != 'live' or provider not in providers or not log.exists():
                    continue
                resolved = log.resolve()
                if resolved in seen or log.is_symlink() or not resolved.is_relative_to(root.resolve()):
                    continue
                stat = log.stat()
                recorded = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                day = recorded.astimezone(BANGKOK).date().isoformat()
                if day not in indices['codex']:
                    continue
                seen.add(resolved)
                bucket = indices[provider][day]
                bucket['workloads'][workload] += 1
                maximum = min(2097152, 16777216 - read_bytes)
                if stat.st_size > maximum:
                    bucket['unmeasured_invocations'] += 1
                    warnings.append('log_size_limit')
                    continue
                with log.open('rb') as stream:
                    raw = stream.read(maximum + 1)
                read_bytes += len(raw)
                if len(raw) > maximum:
                    bucket['unmeasured_invocations'] += 1
                    warnings.append('log_size_limit')
                    continue
                usage = parse_usage(provider, raw.decode('utf-8', errors='replace'))
                if usage is None:
                    bucket['unmeasured_invocations'] += 1
                else:
                    bucket['observed_invocations'] += 1
                    for field in FIELDS:
                        bucket[field] += usage[field]
                    latest = max(latest, recorded) if latest else recorded
            except (OSError, ValueError, TypeError, KeyError):
                warnings.append('unreadable_usage_record')
    return {'providers': providers, 'timezone': 'Asia/Bangkok', 'date_source': 'CLI output file modification time',
            'source': 'center_owned_cli_output', 'latest_observed_at': latest.isoformat() if latest else None,
            'warnings': sorted(set(warnings)), 'quota': 'unknown', 'billing': 'not_calculated',
            'scope': 'Center tasks, local code audits and explicitly included live-smoke records; excludes activity outside Center'}

"""Pure provider-failure classifier for Center workers.

Classification reads structured error fields from JSON/JSONL provider output
before falling back to plain-text lines. Digits are never treated as HTTP
statuses unless they sit in an actual status field of an error record or in
clear HTTP text, so session ids, usage counters, prompts and code output
cannot masquerade as failures. Nothing here touches files, credentials or the
network, and nothing from the input is returned except a class label.
"""
from __future__ import annotations

import json
import re

MAX_DEPTH = 6
MAX_TEXTS = 64
MAX_TEXT = 4000
MAX_INPUT = 1048576


def bounded_loads(text):
    """Reject deep/oversized JSON before entering the recursive decoder."""
    if len(text) > MAX_INPUT:
        raise ValueError('Error record exceeds bounded input')
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > 64:
                raise ValueError('Error record exceeds bounded nesting')
        elif char in ']}':
            depth -= 1
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError('Error record exceeds decoder nesting') from exc

TEXT_KEYS = frozenset(("message", "type", "code", "error", "detail", "details", "description",
                       "reason", "title", "error_code", "error_type"))
STATUS_KEYS = frozenset(("status", "status_code", "statuscode", "http_status", "api_error_status"))
RETRY_KEYS = frozenset(("retry_after", "retry_after_seconds", "retryafter"))
ERROR_TYPES = frozenset(("error", "turn.failed", "thread.error", "stream_error", "response.failed", "fatal"))

PATTERNS = (
    ("auth", re.compile(r"unauthori[sz]ed|unauthenticated|not logged in|authentication|invalid (?:x-)?api[ _-]?key"
                        r"|please run /login|login required|(?:oauth )?token (?:has )?expired|expired token", re.I)),
    ("invalid_model", re.compile(r"(?:invalid|unknown|unsupported)[ _]model|model[ _]not[ _]found|model_not_found"
                                 r"|model\b[^.\n]{0,60}\b(?:does not exist|may not exist|is not supported|not available)", re.I)),
    ("quota_exhausted", re.compile(r"usage[_ ]exhausted|usage[_ -]limit|hit (?:your|the) (?:\w+ )?limit"
                                   r"|quota[_ ]?(?:exceeded|exhausted|reached|limit)|(?:exceeded|exhausted|out of)[^.\n]{0,40}quota"
                                   r"|insufficient[_ ]quota|\b\d+[- ]hour limit|\b(?:weekly|daily|monthly|session) (?:usage )?limit"
                                   r"|out of (?:usage|credits)|credit balance is too low", re.I)),
    ("rate_limit", re.compile(r"rate[ _-]?limit|too many requests", re.I)),
    ("config", re.compile(r"unknown option|unknown argument|unrecognized (?:argument|option)s?|invalid configuration|permission denied", re.I)),
)
RANK = {name: i for i, (name, _) in enumerate(PATTERNS)}
STATUS_CLASS = {401: "auth", 403: "auth", 402: "quota_exhausted", 429: "rate_limit"}
HTTP_PREFIX = re.compile(r"\b(?:http(?:/\d(?:\.\d)?)?(?:\s+(?:error|status))?(?:\s+code)?|status[ _]code|http[ _]status|http[ _]error)"
                         r"\s*[:=]?\s*(\d{3})\b", re.I)
HTTP_REASON = re.compile(r"\b(401) unauthorized\b|\b(403) forbidden\b|\b(402) payment required\b|\b(429) too many requests\b", re.I)


class Signal:
    __slots__ = ("texts", "statuses", "retry_after")

    def __init__(self):
        self.texts = []
        self.statuses = []
        self.retry_after = None


def http_status(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 100 <= value <= 599 else None
    if isinstance(value, str) and re.fullmatch(r"\d{3}", value.strip()):
        return int(value)
    return None


def seconds(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and re.fullmatch(r"\d{1,6}", value.strip()):
        value = int(value)
    if isinstance(value, (int, float)) and 0 <= value <= 7 * 86400:
        return int(value)
    return None


def gather(value, signal, depth=0):
    """Collect message-like strings and status fields from an error value."""
    if depth > MAX_DEPTH or len(signal.texts) >= MAX_TEXTS:
        return
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                gather(bounded_loads(text), signal, depth + 1)
                return
            except ValueError:
                pass
        signal.texts.append(text[:MAX_TEXT])
    elif isinstance(value, list):
        for item in value:
            gather(item, signal, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            if name in STATUS_KEYS:
                status = http_status(item)
                if status:
                    signal.statuses.append(status)
            elif name in RETRY_KEYS:
                if signal.retry_after is None:
                    signal.retry_after = seconds(item)
            elif isinstance(item, (dict, list)) or (name in TEXT_KEYS and isinstance(item, str)):
                gather(item, signal, depth + 1)


def own_fields(node, signal):
    for key, item in node.items():
        name = str(key).lower()
        if name in STATUS_KEYS and http_status(item):
            signal.statuses.append(http_status(item))
        elif name in RETRY_KEYS and signal.retry_after is None:
            signal.retry_after = seconds(item)


def classify_text(value):
    for name, pattern in PATTERNS:
        if pattern.search(value):
            return name
    for pattern in (HTTP_PREFIX, HTTP_REASON):
        for match in pattern.finditer(value):
            status = int(next(g for g in match.groups() if g))
            if status in STATUS_CLASS:
                return STATUS_CLASS[status]
    return None


def classify_signal(signal):
    found = classify_text("\n".join(signal.texts))
    if found:
        return found
    for status in signal.statuses:
        if status in STATUS_CLASS:
            return STATUS_CLASS[status]
    return None


def parse_records(text):
    """Return (JSON objects, non-JSON lines)."""
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = bounded_loads(stripped)
            items = parsed if isinstance(parsed, list) else [parsed]
            return [i for i in items if isinstance(i, (dict, list))], []
        except ValueError:
            pass
    records, plain = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                item = bounded_loads(line)
            except ValueError:
                plain.append(line[:MAX_TEXT])
                continue
            if isinstance(item, dict):
                records.append(item)
            continue
        plain.append(line[:MAX_TEXT])
    return records, plain


def findings(records):
    """Split structured failures into explicit error fields and is_error results."""
    explicit, flagged = [], []

    def walk(node, depth):
        if depth > 8:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        # Application output/code/tool payloads are data, even when they have
        # error-shaped keys. Only provider failures can classify an invocation.
        if node.get('is_error') is False or node.get('type') in ('turn.completed', 'response.completed', 'item.completed', 'thread.started', 'item.started'):
            return
        for key in ("error", "errors", "api_error"):
            value = node.get(key)
            if value not in (None, "", [], {}, False):
                signal = Signal()
                gather(value, signal)
                own_fields(node, signal)
                explicit.append(signal)
        kind = node.get("type")
        if isinstance(kind, str) and kind.lower() in ERROR_TYPES:
            signal = Signal()
            gather(node, signal)
            explicit.append(signal)
        if node.get("is_error") is True:
            signal = Signal()
            for key in ("result", "message", "error"):
                if isinstance(node.get(key), str):
                    gather(node[key], signal)
            own_fields(node, signal)
            flagged.append(signal)
        for key, item in node.items():
            if key in ('structured_output', 'usage', 'modelUsage', 'input', 'output', 'arguments', 'content', 'tool_result', 'tool_output', 'prompt'):
                continue
            if isinstance(item, (dict, list)):
                walk(item, depth + 1)

    for record in records:
        walk(record, 0)
    return explicit, flagged


def classify_failure(text):
    """Return {'class', 'source', 'retry_after'}; never any input text."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", errors="replace")
    elif not isinstance(text, str):
        text = "" if text is None else str(text)
    if len(text) > MAX_INPUT:
        return {'class': 'worker_failure', 'source': 'none', 'retry_after': None}
    records, plain = parse_records(text)
    explicit, flagged = findings(records)
    for source, signals in (("structured", explicit), ("envelope", flagged)):
        found = [(c, s) for s in signals for c in [classify_signal(s)] if c]
        if found:
            name, signal = min(found, key=lambda pair: RANK[pair[0]])
            return {"class": name, "source": source, "retry_after": signal.retry_after if name == "rate_limit" else None}
    names = [c for c in (classify_text(line) for line in plain) if c]
    if names:
        return {"class": min(names, key=RANK.__getitem__), "source": "text", "retry_after": None}
    return {"class": "worker_failure", "source": "none", "retry_after": None}


def classify_error(text):
    return classify_failure(text)["class"]

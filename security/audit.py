"""Payload-free audit metadata. Hashes support correlation, not anonymization."""
from __future__ import annotations
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_EVENTS = {'event', 'clarify_pending', 'tool_event', 'tool_start', 'tool_end', 'tool_denied'}
_EVENTS.update('computer_' + item for item in ('requested', 'executed', 'denied', 'failed'))
_EVENTS.update('computer_node_' + item for item in ('paired', 'enabled', 'disabled',
    'emergency_stop', 'revoked', 'clipboard_optin', 'process_optin', 'budget_reset', 'authorized'))
_EVENTS.update('browser_' + item for item in ('nav_denied', 'nav', 'nav_failed', 'screenshot',
    'scroll', 'click', 'type', 'select', 'submit', 'download', 'upload'))
_EVENTS.update('subagent_' + item for item in ('created', 'cancel_requested', 'start',
    'dispatch_rejected', 'cancel', 'failed', 'delegated', 'completed', 'timed_out',
    'failed_budget', 'completed_cancelled', 'synthesis'))
_EVENTS.update('mcp_call_' + item for item in ('denied', 'start', 'error', 'end'))
_IDENTIFIERS = {'tool', 'action', 'server_id', 'task_id', 'parent_task_id', 'subagent_id', 'question_id'}
_FLAGS = {'ok', 'verified', 'enabled', 'redacted'}
_COUNTS = {'steps', 'chars', 'count', 'worker_count', 'argv_len'}


def sanitise_audit(value):
    """Keep only explicitly typed metadata; never retain arbitrary keys or bodies."""
    if not isinstance(value, dict):
        return {'payload': '[REDACTED]'}
    result = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        if key in _IDENTIFIERS and isinstance(item, str):
            result[key + '_sha256'] = hashlib.sha256(item.encode('utf-8')).hexdigest()
        elif key in _FLAGS and type(item) is bool:
            result[key] = item
        elif key in _COUNTS and type(item) is int and 0 <= item <= 2**31 - 1:
            result[key] = item
        elif key == 'fingerprint' and isinstance(item, str) and len(item) == 64 and all(c in '0123456789abcdef' for c in item):
            result[key] = item
    # One fixed marker rather than retaining attacker-controlled field names.
    if value:
        result['payload'] = '[REDACTED]'
    return result


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: str, /, **data: Any) -> None:
        # Positional-only event prevents a bus envelope's event key from colliding.
        label = event if isinstance(event, str) and event in _EVENTS else 'other'
        row = {**sanitise_audit(data), 'timestamp': datetime.now(timezone.utc).isoformat(), 'event': label}
        with self._lock, self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

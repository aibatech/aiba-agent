"""Trusted postconditions. Models cannot provide or override verifier callbacks."""
from __future__ import annotations
import hashlib
from pathlib import Path

# Trusted built-in observations only. Unknown/extension tools are consequential
# until their actual effects have independent verification; model text cannot
# classify a tool as safe to replay.
READ_ONLY_TOOLS = frozenset({
    'list_files','read_file','host_list_files','host_read_file','host_search_files',
    'search_memory','list_memories','session_search','session_history',
    'web_search','web_extract','browser_state','browser_page_text','browser_status',
    'desktop_screen_size','desktop_clipboard_read','desktop_node_status',
    'list_skills','skill_instructions','secret_list_names',
})


def completion_evidence(name, result):
    return result.ok and (result.verified is True or
                         (name in READ_ONLY_TOOLS and result.verified is not False))


def verify_file_write(resolve, arguments, result):
    path = resolve(arguments['path'])
    expected = arguments['content'].encode('utf-8')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk); size += len(chunk)
            if size > len(expected):
                return False
    return size == len(expected) and digest.digest() == hashlib.sha256(expected).digest()


def verify_file_delete(resolve, arguments, result):
    path = resolve(arguments['path'])
    return not path.exists() and not path.is_symlink()

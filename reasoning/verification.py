"""Trusted postconditions. Models cannot provide or override verifier callbacks."""
from __future__ import annotations
import hashlib
from pathlib import Path


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

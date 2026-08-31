from __future__ import annotations

import sqlite3
from contextlib import contextmanager


@contextmanager
def connect(*args, **kwargs):
    """SQLite transaction context that always closes its file handle."""
    database = sqlite3.connect(*args, **kwargs)
    try:
        with database:
            yield database
    finally:
        database.close()

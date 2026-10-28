"""Cooperative cancellation/fencing at provider and tool boundaries."""
from contextvars import ContextVar
from contextlib import contextmanager

_probe = ContextVar('aiba_execution_probe', default=None)

class ExecutionStopped(RuntimeError):
    pass

def checkpoint():
    probe = _probe.get()
    if probe is not None and not probe():
        raise ExecutionStopped('Execution cancelled or worker claim lost; in-flight effects require reconciliation')

@contextmanager
def execution_scope(probe):
    token = _probe.set(probe)
    try:
        checkpoint()
        yield
    finally:
        _probe.reset(token)

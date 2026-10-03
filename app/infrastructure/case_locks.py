from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator


_registry_lock = threading.Lock()
_case_locks: dict[str, threading.RLock] = {}


@contextmanager
def case_mutation_lock(case_id: str) -> Iterator[None]:
    """Serialize filesystem-affecting mutations for one interview case."""
    with _registry_lock:
        lock = _case_locks.setdefault(case_id, threading.RLock())
    with lock:
        yield

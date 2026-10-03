from __future__ import annotations

import queue
import threading
import time

from app.ai.provider import AIProvider
from app.services.ai_task_service import AITaskService


class AITaskWorker:
    def __init__(self, service: AITaskService, provider: AIProvider, *, sleep=time.sleep) -> None:
        self.service = service
        self.provider = provider
        self.sleep = sleep
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="ai-task-worker", daemon=True)
        self._thread.start()

    def submit(self, task_id: str) -> None:
        self._queue.put(task_id)

    def stop(self, timeout: float = 5) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            task_id = self._queue.get()
            try:
                if task_id is None:
                    return
                try:
                    result = self.service.process(task_id, self.provider)
                    if isinstance(result, dict) and result.get("status") == "PENDING_RETRY":
                        self.sleep(min(0.25 * (2 ** result.get("retryCount", 1)), 2.0))
                        self._queue.put(task_id)
                except Exception:
                    # A single unexpected processor/materialization failure must not
                    # terminate the only worker and strand every later queued task.
                    continue
            finally:
                self._queue.task_done()

from __future__ import annotations

import queue
import threading

from app.ai.provider import AIProvider
from app.services.ai_task_service import AITaskService


class AITaskWorker:
    def __init__(self, service: AITaskService, provider: AIProvider) -> None:
        self.service = service
        self.provider = provider
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
                self.service.process(task_id, self.provider)
            finally:
                self._queue.task_done()

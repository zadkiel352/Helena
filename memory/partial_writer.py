from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable


logger = logging.getLogger(__name__)


class ShortTermPartialWriter:
    """Coalesce short-term transcript updates and persist them off the event loop."""

    def __init__(
        self,
        persist: Callable[[dict[str, str]], None],
        debounce_seconds: float = 0.05,
    ) -> None:
        self._persist = persist
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._condition = threading.Condition()
        self._pending: dict[str, str] = {}
        self._last_update = 0.0
        self._writing = False
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run,
            name="helena-short-term-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(
        self,
        *,
        user_partial: str | None = None,
        helena_partial: str | None = None,
    ) -> None:
        updates: dict[str, str] = {}
        if user_partial is not None:
            updates["user_partial"] = user_partial
        if helena_partial is not None:
            updates["helena_partial"] = helena_partial
        if not updates:
            return

        with self._condition:
            if self._stopping:
                raise RuntimeError("Short-term memory writer is closed")
            self._pending.update(updates)
            self._last_update = time.monotonic()
            self._condition.notify_all()

    def flush(self) -> None:
        with self._condition:
            if self._pending:
                self._last_update = 0.0
                self._condition.notify_all()
            while self._pending or self._writing:
                self._condition.wait()

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._thread.join()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait()

                if not self._pending and self._stopping:
                    return

                while self._pending and not self._stopping:
                    remaining = self._debounce_seconds - (
                        time.monotonic() - self._last_update
                    )
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)

                updates = self._pending
                self._pending = {}
                self._writing = True

            try:
                self._persist(updates)
            except Exception:
                logger.exception("Failed to persist short-term transcript updates")
            finally:
                with self._condition:
                    self._writing = False
                    self._condition.notify_all()

"""One in-memory job queue with N workers, so the Pi works on one video at a time.

Jobs that are queued when the bot stops are lost (the DB marks them failed on the
next start); the user can post the link again.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, handler: Callable[[Any], Awaitable[None]], concurrency: int = 1):
        self.handler = handler
        self.concurrency = concurrency
        self.running = 0
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []

    @property
    def waiting(self) -> int:
        return self._queue.qsize()

    @property
    def ahead(self) -> int:
        """Jobs a newly submitted job would wait behind (waiting + running)."""
        return self.waiting + self.running

    def start(self) -> None:
        self._workers = [asyncio.create_task(self._work(), name=f"recipe-worker-{n}")
                         for n in range(self.concurrency)]

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    def submit(self, job: Any) -> None:
        self._queue.put_nowait(job)

    async def join(self) -> None:
        await self._queue.join()

    async def _work(self) -> None:
        while True:
            job = await self._queue.get()
            self.running += 1
            try:
                await self.handler(job)
            except Exception:  # the handler reports its own failures; this keeps the worker alive
                log.exception("Job handler crashed")
            finally:
                self.running -= 1
                self._queue.task_done()

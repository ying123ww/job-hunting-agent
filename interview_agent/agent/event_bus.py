from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TypeAlias, TypeVar, cast


logger = logging.getLogger(__name__)

E = TypeVar("E")
Handler: TypeAlias = Callable[[E], Awaitable[E | None] | E | None]


class EventBus:
    """Typed event bus with intercept, fanout, and queued background delivery."""

    def __init__(self) -> None:
        self._handlers: dict[type[object], list[Handler[object]]] = {}
        self._queue: asyncio.Queue[object] | None = None
        self._queue_task: asyncio.Task[None] | None = None
        self._closed = False

    def on(self, event_type: type[E], handler: Handler[E]) -> None:
        handlers = self._handlers.setdefault(cast(type[object], event_type), [])
        handlers.append(cast(Handler[object], handler))

    async def emit(self, event: E) -> E:
        for raw_handler in self._handlers.get(cast(type[object], type(event)), []):
            handler = cast(Handler[E], raw_handler)
            result = handler(event)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                event = cast(E, result)
        return event

    async def fanout(self, event: object) -> None:
        handlers = list(self._handlers.get(type(event), []))
        if not handlers:
            return
        results = await asyncio.gather(
            *(self._run_observer(event, handler) for handler in handlers)
        )
        failed_count = results.count(False)
        if failed_count:
            logger.warning(
                "event fanout completed with errors: event=%s failed=%d total=%d",
                type(event).__name__,
                failed_count,
                len(handlers),
            )

    def enqueue(self, event: object) -> None:
        if self._closed:
            logger.warning("ignore event after close: %s", type(event).__name__)
            return
        queue = self._ensure_queue()
        queue.put_nowait(event)

    async def drain(self) -> None:
        if self._queue is None:
            return
        self._ensure_queue_task()
        await self._queue.join()

    async def aclose(self) -> None:
        await self.drain()
        self._closed = True
        task = self._queue_task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_observer(self, event: object, handler: Handler[object]) -> bool:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            logger.exception(
                "event observer failed: event=%s handler=%s",
                type(event).__name__,
                getattr(handler, "__qualname__", getattr(handler, "__name__", repr(handler))),
            )
            return False

    def _ensure_queue(self) -> asyncio.Queue[object]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        self._ensure_queue_task()
        return self._queue

    def _ensure_queue_task(self) -> None:
        if self._closed:
            return
        if self._queue_task is not None and not self._queue_task.done():
            return
        self._queue_task = asyncio.create_task(
            self._run_queue(),
            name="interview_agent_event_bus",
        )

    async def _run_queue(self) -> None:
        while True:
            queue = self._queue
            if queue is None:
                return
            event = await queue.get()
            try:
                await self.fanout(event)
            finally:
                queue.task_done()

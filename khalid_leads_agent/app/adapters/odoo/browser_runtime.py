"""Runs async Playwright in a dedicated thread with its own event loop.

Why: on Windows, Playwright needs a Proactor event loop (subprocess support),
while the web server loop may be configured differently. Isolating the browser
in one thread also serializes all browser actions (one visible tab, no races).
"""
from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class BrowserRuntime:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock: asyncio.Lock | None = None

    def _run(self) -> None:
        if sys.platform == "win32":
            loop: asyncio.AbstractEventLoop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._lock = asyncio.Lock()
        self._ready.set()
        loop.run_forever()

    def ensure_started(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="odoo-browser", daemon=True)
        self._thread.start()
        self._ready.wait(10)

    async def submit(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run ``coro`` on the browser loop (serialized) and await its result."""
        self.ensure_started()
        assert self._loop is not None and self._lock is not None
        lock = self._lock

        async def _guarded() -> T:
            async with lock:
                return await coro

        fut = asyncio.run_coroutine_threadsafe(_guarded(), self._loop)
        return await asyncio.wrap_future(fut)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

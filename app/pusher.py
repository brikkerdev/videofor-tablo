import asyncio
import logging
from collections import deque
from datetime import datetime

from .db import Database
from .models import BoardConfig
from .render import BOARD_H, BOARD_W, render_areas
from .render import _alert
from .state import StateCache
from .tablo import TabloClient

logger = logging.getLogger("app.pusher")

TICK_SECONDS = 30
MIN_PUSH_INTERVAL = 2.0
PUSH_LOG_SIZE = 50


class Pusher:
    def __init__(
        self,
        tablo: TabloClient,
        db: Database,
        state: StateCache,
        board: BoardConfig,
        retry_seconds: int,
        width: int = BOARD_W,
        height: int = BOARD_H,
    ):
        self.tablo = tablo
        self.db = db
        self.state = state
        self.board = board
        self.retry_seconds = retry_seconds
        self.width = width
        self.height = height
        self._dirty = asyncio.Event()
        self._last_push_t = 0.0
        self.paused: bool = False
        self.last_ok: bool | None = None
        self.last_error: str = ""
        self.last_push_at = None
        self._threshold_since: dict[str, datetime] = {}
        self._threshold_prev: dict[str, bool] = {}
        self.push_log: deque = deque(maxlen=PUSH_LOG_SIZE)

    def mark_dirty(self) -> None:
        self.paused = False
        self._dirty.set()

    def _clock_running(self) -> bool:
        return self.board.top_panel.enabled and self.board.top_panel.show_clock

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), timeout=TICK_SECONDS)
            except asyncio.TimeoutError:
                self.state.rollover_if_needed()
                if not self._clock_running():
                    continue
            loop = asyncio.get_running_loop()
            wait = MIN_PUSH_INTERVAL - (loop.time() - self._last_push_t)
            if wait > 0:
                await asyncio.sleep(wait)
            self._dirty.clear()
            if self.paused:
                continue
            self.state.rollover_if_needed()
            now = self.state.now()
            online = self.state.is_online(self.board.online_window_seconds)

            for ln in self.board.lines:
                if ln.threshold is None:
                    self._threshold_since.pop(ln.key, None)
                    self._threshold_prev.pop(ln.key, None)
                    continue
                val = self.state.values.get(ln.key, 0)
                duration = ln.threshold.duration_seconds or 0
                is_alert = _alert(ln.threshold, val)
                was_alert = self._threshold_prev.get(ln.key, False)
                self._threshold_prev[ln.key] = is_alert

                if duration == 0:
                    if is_alert:
                        self._threshold_since.setdefault(ln.key, now)
                    else:
                        self._threshold_since.pop(ln.key, None)
                else:
                    if is_alert and not was_alert:
                        self._threshold_since[ln.key] = now
                    since = self._threshold_since.get(ln.key)
                    if since and (now - since).total_seconds() >= duration:
                        self._threshold_since.pop(ln.key, None)

            areas = render_areas(
                self.state.indicators,
                self.state.values,
                self.board,
                now,
                online,
                self.width,
                self.height,
                threshold_since=self._threshold_since,
            )
            try:
                await self.tablo.push_areas(areas)
                await self.db.set_pushed_at()
                self._last_push_t = asyncio.get_running_loop().time()
                self.last_ok = True
                self.last_error = ""
                self.last_push_at = now
                self.push_log.appendleft({"at": now.strftime("%H:%M:%S"), "ok": True, "error": ""})
                logger.info("Состояние доставлено на табло (%d областей)", len(areas))
            except Exception as exc:
                self.last_ok = False
                self.last_error = str(exc)
                self.last_push_at = now
                self.push_log.appendleft({"at": now.strftime("%H:%M:%S"), "ok": False, "error": str(exc)})
                logger.warning("Push на табло не удался: %s", exc)
                self._dirty.set()
                await asyncio.sleep(self.retry_seconds)

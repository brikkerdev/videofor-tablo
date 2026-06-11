import asyncio
import logging

from .db import Database
from .models import BoardConfig
from .render import BOARD_H, BOARD_W, render_areas
from .state import StateCache
from .tablo import TabloClient

logger = logging.getLogger("app.pusher")

TICK_SECONDS = 30
MIN_PUSH_INTERVAL = 2.0


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
            online = self.state.is_online(self.board.online_window_seconds)
            areas = render_areas(
                self.state.indicators,
                self.state.values,
                self.board,
                self.state.now(),
                online,
                self.width,
                self.height,
            )
            try:
                await self.tablo.push_areas(areas)
                await self.db.set_pushed_at()
                self._last_push_t = asyncio.get_running_loop().time()
                self.last_ok = True
                self.last_error = ""
                self.last_push_at = self.state.now()
                logger.info("Состояние доставлено на табло (%d областей)", len(areas))
            except Exception as exc:
                self.last_ok = False
                self.last_error = str(exc)
                self.last_push_at = self.state.now()
                logger.warning("Push на табло не удался: %s", exc)
                self._dirty.set()
                await asyncio.sleep(self.retry_seconds)

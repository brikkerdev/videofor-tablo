import asyncio
import logging

from .db import Database
from .render import render_text
from .state import StateCache
from .tablo import TabloClient

logger = logging.getLogger("app.pusher")

DAY_CHECK_SECONDS = 60


class Pusher:
    """Фоновая доставка состояния на табло.

    Спит на asyncio.Event, БД не опрашивает. Просыпается по событию
    либо раз в минуту для проверки смены календарного дня.
    """

    def __init__(
        self, tablo: TabloClient, db: Database, state: StateCache, retry_seconds: int
    ):
        self.tablo = tablo
        self.db = db
        self.state = state
        self.retry_seconds = retry_seconds
        self._dirty = asyncio.Event()

    def mark_dirty(self) -> None:
        self._dirty.set()

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), timeout=DAY_CHECK_SECONDS)
            except asyncio.TimeoutError:
                if not self.state.rollover_if_needed():
                    continue
            self._dirty.clear()
            self.state.rollover_if_needed()
            text = render_text(self.state.indicators, self.state.values)
            try:
                await self.tablo.push(text, self.state.snapshot())
                await self.db.set_pushed_at()
                logger.info("Состояние доставлено на табло")
            except Exception as exc:
                logger.warning("Push на табло не удался: %s", exc)
                self._dirty.set()
                await asyncio.sleep(self.retry_seconds)

import json
from datetime import date
from pathlib import Path

import asyncpg

from .models import EventIn
from .rules import Rule
from .state import Indicator

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def init_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    async def ping(self) -> bool:
        async with self.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True

    async def load_indicators(self) -> list[Indicator]:
        rows = await self.pool.fetch(
            "SELECT key, display_name, kind, sort_order FROM indicators "
            "WHERE enabled ORDER BY sort_order"
        )
        return [Indicator(**dict(r)) for r in rows]

    async def load_rules(self) -> list[Rule]:
        rows = await self.pool.fetch(
            "SELECT event_type, checkpoint, indicator_key, op FROM event_rules "
            "WHERE enabled"
        )
        return [Rule(**dict(r)) for r in rows]

    async def load_state(self, day: date) -> tuple[dict[str, int], dict[str, int]]:
        """Значения за день и последние значения предыдущих дней.

        Вторые нужны для переноса gauge-показателей после рестарта,
        если за сегодня по ним ещё не было записей.
        """
        today_rows = await self.pool.fetch(
            "SELECT indicator_key, value FROM counter_values WHERE day = $1", day
        )
        prev_rows = await self.pool.fetch(
            "SELECT DISTINCT ON (indicator_key) indicator_key, value "
            "FROM counter_values WHERE day < $1 "
            "ORDER BY indicator_key, day DESC",
            day,
        )
        today_values = {r["indicator_key"]: r["value"] for r in today_rows}
        prev_values = {r["indicator_key"]: r["value"] for r in prev_rows}
        return today_values, prev_values

    async def record_event(
        self, event: EventIn, changes: dict[str, int], day: date
    ) -> None:
        payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO events "
                    "(event_type, event_time, source, object_type, checkpoint, value, payload) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    event.event_type,
                    event.event_time,
                    event.source,
                    event.object_type,
                    event.checkpoint,
                    event.value,
                    payload,
                )
                for key, value in changes.items():
                    await conn.execute(
                        "INSERT INTO counter_values (day, indicator_key, value) "
                        "VALUES ($1, $2, $3) "
                        "ON CONFLICT (day, indicator_key) "
                        "DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                        day,
                        key,
                        value,
                    )

    async def is_dirty(self) -> bool:
        return await self.pool.fetchval(
            "SELECT coalesce("
            "  (SELECT max(updated_at) FROM counter_values) > "
            "  coalesce((SELECT pushed_at FROM push_state WHERE id = 1), "
            "           'epoch'::timestamptz), "
            "  FALSE)"
        )

    async def set_pushed_at(self) -> None:
        await self.pool.execute("UPDATE push_state SET pushed_at = now() WHERE id = 1")

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
            await conn.fetchval("select 1")
        return True

    async def load_indicators(self) -> list[Indicator]:
        rows = await self.pool.fetch(
            "select key, display_name, kind, sort_order from indicators "
            "where enabled order by sort_order"
        )
        return [Indicator(**dict(r)) for r in rows]

    async def load_rules(self) -> list[Rule]:
        rows = await self.pool.fetch(
            "select event_type, checkpoint, indicator_key, op from event_rules "
            "where enabled"
        )
        return [Rule(**dict(r)) for r in rows]

    async def load_state(self, day: date) -> tuple[dict[str, int], dict[str, int]]:
        today_rows = await self.pool.fetch(
            "select indicator_key, value from counter_values where day = $1", day
        )
        prev_rows = await self.pool.fetch(
            "select distinct on (indicator_key) indicator_key, value "
            "from counter_values where day < $1 "
            "order by indicator_key, day desc",
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
                    "insert into events "
                    "(event_type, event_time, source, object_type, checkpoint, value, payload) "
                    "values ($1, $2, $3, $4, $5, $6, $7)",
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
                        "insert into counter_values (day, indicator_key, value) "
                        "values ($1, $2, $3) "
                        "on conflict (day, indicator_key) "
                        "do update set value = excluded.value, updated_at = now()",
                        day,
                        key,
                        value,
                    )

    async def get_config(self, key: str) -> str | None:
        return await self.pool.fetchval(
            "select value from config where key = $1", key
        )

    async def set_config(self, key: str, value: str) -> None:
        await self.pool.execute(
            "insert into config (key, value) values ($1, $2) "
            "on conflict (key) do update set value = excluded.value, updated_at = now()",
            key,
            value,
        )

    async def set_counter_value(self, day: date, key: str, value: int) -> None:
        await self.pool.execute(
            "insert into counter_values (day, indicator_key, value) values ($1, $2, $3) "
            "on conflict (day, indicator_key) "
            "do update set value = excluded.value, updated_at = now()",
            day, key, value,
        )

    async def is_dirty(self) -> bool:
        return await self.pool.fetchval(
            "select coalesce("
            "  (select max(updated_at) from counter_values) > "
            "  coalesce((select pushed_at from push_state where id = 1), "
            "           'epoch'::timestamptz), "
            "  FALSE)"
        )

    async def set_pushed_at(self) -> None:
        await self.pool.execute("update push_state set pushed_at = now() where id = 1")

    # ── Реестр наблюдаемых типов событий ──────────────────────────────

    async def record_observed_event(self, event: EventIn) -> None:
        await self.pool.execute(
            "insert into observed_events "
            "(event_type, object_type, checkpoint, last_value, count) "
            "values ($1, $2, $3, $4, 1) "
            "on conflict (event_type) do update set "
            "  object_type = excluded.object_type, "
            "  checkpoint   = excluded.checkpoint, "
            "  last_value   = excluded.last_value, "
            "  count        = observed_events.count + 1, "
            "  last_seen    = now()",
            event.event_type, event.object_type, event.checkpoint, event.value,
        )

    async def list_observed_events(self) -> list[dict]:
        rows = await self.pool.fetch(
            "select event_type, object_type, checkpoint, last_value, count, "
            "       first_seen, last_seen "
            "from observed_events order by last_seen desc"
        )
        return [dict(r) for r in rows]

    async def delete_observed_event(self, event_type: str) -> None:
        await self.pool.execute(
            "delete from observed_events where event_type = $1", event_type
        )

    # ── Справочники: показатели и правила (полное чтение) ─────────────

    async def load_all_indicators(self) -> list[dict]:
        rows = await self.pool.fetch(
            "select key, display_name, kind, sort_order, enabled "
            "from indicators order by sort_order"
        )
        return [dict(r) for r in rows]

    async def load_all_indicator_keys(self) -> set[str]:
        rows = await self.pool.fetch("select key from indicators")
        return {r["key"] for r in rows}

    async def load_all_rules(self) -> list[dict]:
        rows = await self.pool.fetch(
            "select event_type, checkpoint, indicator_key, op, enabled "
            "from event_rules"
        )
        return [dict(r) for r in rows]

    async def max_sort_order(self) -> int:
        return await self.pool.fetchval(
            "select coalesce(max(sort_order), 0) from indicators"
        )

    # ── Справочники: мутации ──────────────────────────────────────────

    async def create_indicator(
        self, key: str, display_name: str, kind: str, sort_order: int
    ) -> None:
        await self.pool.execute(
            "insert into indicators (key, display_name, kind, sort_order) "
            "values ($1, $2, $3, $4)",
            key, display_name, kind, sort_order,
        )

    async def update_indicator(self, key: str, **fields) -> None:
        allowed = ("display_name", "kind", "sort_order", "enabled")
        sets = [(f, v) for f, v in fields.items() if f in allowed and v is not None]
        if not sets:
            return
        cols = ", ".join(f"{f} = ${i + 2}" for i, (f, _) in enumerate(sets))
        await self.pool.execute(
            f"update indicators set {cols} where key = $1",
            key, *[v for _, v in sets],
        )

    async def delete_indicator(self, key: str) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "delete from event_rules where indicator_key = $1", key
                )
                await conn.execute(
                    "delete from counter_values where indicator_key = $1", key
                )
                await conn.execute("delete from indicators where key = $1", key)

    async def indicator_exists(self, key: str) -> bool:
        return bool(
            await self.pool.fetchval(
                "select 1 from indicators where key = $1", key
            )
        )

    async def create_rule(
        self, event_type: str, checkpoint: str | None, indicator_key: str, op: str
    ) -> None:
        await self.pool.execute(
            "insert into event_rules (event_type, checkpoint, indicator_key, op) "
            "values ($1, $2, $3, $4) "
            "on conflict (event_type, indicator_key) do update set "
            "  checkpoint = excluded.checkpoint, op = excluded.op, enabled = true",
            event_type, checkpoint, indicator_key, op,
        )

    async def delete_rule(self, event_type: str, indicator_key: str) -> None:
        await self.pool.execute(
            "delete from event_rules where event_type = $1 and indicator_key = $2",
            event_type, indicator_key,
        )

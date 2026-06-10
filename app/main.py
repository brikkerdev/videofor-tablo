import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .db import Database
from .models import EventIn
from .pusher import Pusher
from .rules import apply_op, match_rules
from .state import StateCache
from .tablo import TabloClient

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.log_level.upper())
    db = Database(settings.database_url)
    await db.connect()
    await db.init_schema()

    state = StateCache(settings.tz)
    today = state.today()
    today_values, prev_values = await db.load_state(today)
    state.load(await db.load_indicators(), today_values, prev_values, today)

    tablo = TabloClient(settings.tablo_url, settings.tablo_token)
    pusher = Pusher(tablo, db, state, settings.push_retry_seconds)
    if await db.is_dirty():
        pusher.mark_dirty()
    pusher_task = asyncio.create_task(pusher.run())

    app.state.db = db
    app.state.cache = state
    app.state.rules = await db.load_rules()
    app.state.pusher = pusher
    app.state.lock = asyncio.Lock()
    logger.info("Сервис запущен, день %s, пояс %s", today, state.tz)

    yield

    pusher_task.cancel()
    await tablo.close()
    await db.close()


app = FastAPI(title="videofor-tablo integration", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"status": "error", "message": "Invalid request body"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail)},
    )


@app.post("/api/events")
async def receive_event(
    event: EventIn,
    request: Request,
    x_api_key: str | None = Header(default=None),
):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

    cache: StateCache = request.app.state.cache
    matched = match_rules(request.app.state.rules, event.event_type, event.checkpoint)
    if not matched:
        raise HTTPException(status_code=400, detail="Invalid event type")

    if event.event_time.tzinfo is None:
        event.event_time = event.event_time.replace(tzinfo=cache.tz)

    async with request.app.state.lock:
        cache.rollover_if_needed()
        changes: dict[str, int] = {}
        for rule in matched:
            current = changes.get(
                rule.indicator_key, cache.values.get(rule.indicator_key, 0)
            )
            changes[rule.indicator_key] = apply_op(rule.op, current, event.value)
        await request.app.state.db.record_event(event, changes, cache.day)
        cache.values.update(changes)
        cache.updated_at = cache.now()

    request.app.state.pusher.mark_dirty()
    return {
        "status": "success",
        "message": "Data received and displayed",
        "received_at": cache.now().isoformat(timespec="seconds"),
    }


@app.get("/api/state")
async def get_state(request: Request):
    cache: StateCache = request.app.state.cache
    cache.rollover_if_needed()
    return cache.snapshot()


@app.get("/health")
async def health(request: Request):
    await request.app.state.db.ping()
    return {"status": "ok"}

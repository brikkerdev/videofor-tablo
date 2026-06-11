import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .db import Database
from .models import BoardConfig, EventIn, LineConfig
from .pusher import Pusher
from .render import BOARD_H, BOARD_W, render_areas, render_text
from .rules import apply_op, match_rules
from .state import StateCache
from .tablo import TabloClient

logger = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "static"
CONFIG_KEY = "display_config"


def build_board(raw: str | None, indicators) -> BoardConfig:
    if raw:
        try:
            board = BoardConfig.model_validate_json(raw)
        except Exception:
            logger.warning("display_config повреждён, беру значения по умолчанию")
            board = BoardConfig()
    else:
        board = BoardConfig()
    known = {ln.key for ln in board.lines}
    for ind in indicators:
        if ind.key not in known:
            board.lines.append(LineConfig(key=ind.key))
    return board


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

    board = build_board(await db.get_config(CONFIG_KEY), state.indicators)

    tablo = TabloClient(
        settings.tablo_url,
        settings.tablo_token,
        settings.tablo_matrix_ip,
        settings.tablo_matrix_pass,
    )
    tablo.start()
    width, height = BOARD_W, BOARD_H
    for _ in range(16):
        if tablo.connected:
            break
        await asyncio.sleep(0.5)
    if tablo.device:
        width = tablo.device.get("width", width)
        height = tablo.device.get("height", height)

    pusher = Pusher(tablo, db, state, board, settings.push_retry_seconds, width, height)
    if await db.is_dirty():
        pusher.mark_dirty()
    pusher_task = asyncio.create_task(pusher.run())

    app.state.db = db
    app.state.cache = state
    app.state.board = board
    app.state.tablo = tablo
    app.state.rules = await db.load_rules()
    app.state.pusher = pusher
    app.state.lock = asyncio.Lock()
    logger.info("Сервис запущен, день %s, пояс %s, панель %dx%d", today, state.tz, width, height)

    yield

    pusher_task.cancel()
    await tablo.close()
    await db.close()


app = FastAPI(title="videofor-tablo integration", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import os as _os
_frontend = _os.path.join(_os.path.dirname(__file__), "..", "frontend")
if _os.path.isdir(_frontend):
    app.mount("/ui", StaticFiles(directory=_frontend, html=True), name="frontend")


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
        cache.last_event_at = cache.now()

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


@app.get("/api/display/config")
async def get_display_config(request: Request):
    board: BoardConfig = request.app.state.board
    cache: StateCache = request.app.state.cache
    tablo: TabloClient = request.app.state.tablo
    device = tablo.device or {}
    return {
        "board": board.model_dump(),
        "indicators": [
            {"key": ind.key, "display_name": ind.display_name}
            for ind in cache.indicators
        ],
        "device": {
            "width": device.get("width", BOARD_W),
            "height": device.get("height", BOARD_H),
        },
    }


@app.put("/api/display/config")
async def put_display_config(body: BoardConfig, request: Request):
    async with request.app.state.lock:
        request.app.state.board = body
        request.app.state.pusher.board = body
        await request.app.state.db.set_config(CONFIG_KEY, body.model_dump_json())
    request.app.state.pusher.mark_dirty()
    return {"board": body.model_dump()}


@app.get("/api/display/preview")
async def get_display_preview(request: Request):
    cache: StateCache = request.app.state.cache
    board: BoardConfig = request.app.state.board
    tablo: TabloClient = request.app.state.tablo
    device = tablo.device or {}
    width = device.get("width", BOARD_W)
    height = device.get("height", BOARD_H)
    cache.rollover_if_needed()
    online = cache.is_online(board.online_window_seconds)
    areas = render_areas(cache.indicators, cache.values, board, cache.now(), online, width, height)
    return {"areas": areas}


@app.post("/api/display/push")
async def push_display(request: Request):
    request.app.state.pusher.mark_dirty()
    return {"status": "ok"}


@app.post("/api/display/clear")
async def clear_display(request: Request):
    tablo: TabloClient = request.app.state.tablo
    pusher: Pusher = request.app.state.pusher
    pusher.paused = True
    pusher._dirty.clear()
    try:
        await tablo.push_areas([])
    except Exception as exc:
        pusher.paused = False
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ok"}


@app.get("/api/tablo/status")
async def get_tablo_status(request: Request):
    tablo: TabloClient = request.app.state.tablo
    pusher: Pusher = request.app.state.pusher
    reachable = tablo.base_url != ""
    device = tablo.device or {}
    last_push = None
    if pusher.last_push_at is not None:
        last_push = {
            "at": pusher.last_push_at.strftime("%H:%M:%S"),
            "ok": pusher.last_ok,
            "error": pusher.last_error,
        }
    return {
        "reachable": reachable,
        "connected": tablo.connected,
        "url": tablo.base_url,
        "device": {
            "width": device.get("width", BOARD_W),
            "height": device.get("height", BOARD_H),
            "brightness": device.get("brightness", "—"),
        },
        "last_push": last_push,
    }


@app.post("/api/tablo/reconnect")
async def reconnect_tablo(request: Request):
    tablo: TabloClient = request.app.state.tablo
    asyncio.create_task(tablo.reconnect())
    return {"status": "ok"}


class BrightnessIn(BaseModel):
    value: int = Field(ge=0, le=255)


@app.post("/api/tablo/brightness")
async def set_brightness(body: BrightnessIn, request: Request):
    tablo: TabloClient = request.app.state.tablo
    ok = await tablo.set_brightness(body.value)
    async with request.app.state.lock:
        request.app.state.board.screen_brightness = body.value
        await request.app.state.db.set_config(
            CONFIG_KEY, request.app.state.board.model_dump_json()
        )
    return {"status": "ok" if ok else "unreachable", "value": body.value}


class AdjustIn(BaseModel):
    key: str
    delta: int


@app.post("/api/state/adjust")
async def adjust_state(body: AdjustIn, request: Request):
    cache: StateCache = request.app.state.cache
    async with request.app.state.lock:
        cache.rollover_if_needed()
        current = cache.values.get(body.key, 0)
        new_val = max(0, current + body.delta)
        cache.values[body.key] = new_val
        cache.updated_at = cache.now()
        await request.app.state.db.set_counter_value(cache.day, body.key, new_val)
    request.app.state.pusher.mark_dirty()
    return {"key": body.key, "value": new_val}


@app.get("/health")
async def health(request: Request):
    await request.app.state.db.ping()
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/ui/")


app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

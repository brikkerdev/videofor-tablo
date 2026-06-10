import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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
    """Конфигурация вывода из БД, дополненная новыми показателями."""
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
    tablo.start()  # держит SSE открытым, иначе матрица отваливается
    width, height = BOARD_W, BOARD_H
    for _ in range(16):  # дать SSE подняться и войти (параметры панели придут в SSE)
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


# --- Конфигурация вывода на табло ---------------------------------------


@app.get("/api/display/config")
async def get_display_config(request: Request):
    board: BoardConfig = request.app.state.board
    cache: StateCache = request.app.state.cache
    pusher: Pusher = request.app.state.pusher
    return {
        "board": board.model_dump(),
        "indicators": [
            {"key": i.key, "display_name": i.display_name, "kind": i.kind, "sort_order": i.sort_order}
            for i in cache.indicators
        ],
        "device": {"width": pusher.width, "height": pusher.height},
    }


@app.put("/api/display/config")
async def put_display_config(board: BoardConfig, request: Request):
    cache: StateCache = request.app.state.cache
    merged = build_board(board.model_dump_json(), cache.indicators)
    await request.app.state.db.set_config(CONFIG_KEY, merged.model_dump_json())
    request.app.state.board = merged
    request.app.state.pusher.board = merged
    request.app.state.pusher.mark_dirty()
    return {"status": "success", "board": merged.model_dump()}


@app.post("/api/display/push")
async def force_push(request: Request):
    request.app.state.pusher.mark_dirty()
    return {"status": "queued"}


@app.get("/api/display/preview")
async def preview(request: Request):
    cache: StateCache = request.app.state.cache
    board: BoardConfig = request.app.state.board
    pusher: Pusher = request.app.state.pusher
    cache.rollover_if_needed()
    online = cache.is_online(board.online_window_seconds)
    areas = render_areas(
        cache.indicators, cache.values, board, cache.now(), online,
        pusher.width, pusher.height,
    )
    return {
        "areas": areas,
        "text": render_text(cache.indicators, cache.values),
        "online": online,
    }


@app.get("/api/tablo/status")
async def tablo_status(request: Request):
    tablo: TabloClient = request.app.state.tablo
    pusher: Pusher = request.app.state.pusher
    # статус из кэша SSE, без запросов к шлюзу (они сбивают связь)
    return {
        "url": settings.tablo_url,
        "reachable": tablo.sse_alive(),
        "connected": tablo.connected,
        "device": tablo.device,
        "last_push": {
            "ok": pusher.last_ok,
            "error": pusher.last_error,
            "at": pusher.last_push_at.isoformat(timespec="seconds")
            if pusher.last_push_at
            else None,
        },
    }


@app.post("/api/tablo/reconnect")
async def tablo_reconnect(request: Request):
    tablo: TabloClient = request.app.state.tablo
    connected = await tablo.reconnect()
    request.app.state.pusher.mark_dirty()
    return {"connected": connected, "device": tablo.device}


@app.get("/health")
async def health(request: Request):
    await request.app.state.db.ping()
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/ui/")


app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

"""Симулятор табло: принимает push от сервиса и печатает текст в лог.

Временная замена реального табло до получения спецификации его API.
"""

import logging

from fastapi import FastAPI, Request

logging.basicConfig(level="INFO", format="%(asctime)s %(message)s")
logger = logging.getLogger("tablo-sim")

app = FastAPI(title="tablo simulator")


@app.post("/api/display")
async def display(request: Request):
    body = await request.json()
    logger.info("Табло обновлено:\n%s", body.get("text", body))
    return {"status": "ok"}

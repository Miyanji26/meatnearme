from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config
from app.db import init_db
from app.routers import tools, web, webhooks
from app.templating import STATIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=config.APP_NAME, docs_url="/api/docs", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(web.router)
app.include_router(tools.router)
app.include_router(webhooks.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}

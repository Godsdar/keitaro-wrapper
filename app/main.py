from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.keitaro import KeitaroError

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Keitaro wrapper")
app.include_router(router)


@app.exception_handler(KeitaroError)
def keitaro_error(_: Request, exc: KeitaroError):
    # Ошибки самого Keitaro отдаём фронту как 502 с понятным текстом.
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    # Без сборки у файлов нет хэшей в именах — просим браузер сверяться
    # с сервером (ETag), чтобы после обновления не висела старая версия JS.
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")

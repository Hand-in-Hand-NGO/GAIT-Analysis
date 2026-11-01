from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import Base, engine
from .routers import auth_users, distribution, donors, reports
from .seed import ensure_admin

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app() -> FastAPI:
    Base.metadata.create_all(engine)
    ensure_admin()

    app = FastAPI(title="Donations Call Center API", version="1.0.0")
    for r in (auth_users.router, donors.router, distribution.router, reports.router):
        app.include_router(r)

    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()

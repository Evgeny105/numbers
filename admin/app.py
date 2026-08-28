"""The admin dashboard.

A separate process from the bot, sharing its SQLite file. Separate because a
crash in a web handler must not take the bot down with it, and because the two
have different exposure: the bot talks to Telegram through a proxy, the
dashboard listens on the LAN behind HTTP Basic authentication.

It is read-mostly. The only writes it can make are toggling a ban and disabling
a phrase; it has no route that alters recorded history.
"""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bot.config import AdminWebSettings
from bot.logging_setup import log_path, setup_logging, tail
from bot.services.openrouter import OpenRouterService
from bot.storage import phrases as phrase_store
from bot.storage import queries
from bot.storage.db import Database
from bot.texts import CATEGORIES

_LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
security = HTTPBasic()


def create_app(settings: AdminWebSettings | None = None) -> FastAPI:
    settings = settings or AdminWebSettings.from_env()
    setup_logging(settings.log_level, settings.db_path, name="admin.log")

    database = Database(settings.db_path)
    openrouter = OpenRouterService(
        settings.llm_api_key,
        settings.openrouter_base_url,
        settings.http_proxy_url or None,
        settings.balance_cache_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await database.connect()
        _LOGGER.info("admin dashboard ready, database %s", settings.db_path)
        yield
        await database.close()

    app = FastAPI(
        title="Numbers — админка",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.filters["dt"] = _format_datetime
    templates.env.filters["money"] = _format_money
    templates.env.filters["pct"] = _format_percent

    def authenticate(credentials: HTTPBasicCredentials = Depends(security)) -> str:
        """Constant-time credential check, so the dashboard is not a guessing game."""
        user_ok = secrets.compare_digest(credentials.username, settings.admin_web_user)
        password_ok = secrets.compare_digest(credentials.password, settings.admin_web_password)
        if not (user_ok and password_ok):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверные учётные данные",
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username

    def render(request: Request, template: str, **context: Any) -> HTMLResponse:
        context.setdefault("now", time.time())
        return templates.TemplateResponse(request, template, context)

    # -- pages -------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def overview(
        request: Request, days: int = Query(30, ge=1, le=365), _: str = Depends(authenticate)
    ) -> HTMLResponse:
        return render(
            request,
            "overview.html",
            page="overview",
            days=days,
            today=await queries.summary(database, days=1),
            week=await queries.summary(database, days=7),
            period=await queries.summary(database, days=days),
            activity=await queries.daily_activity(database, days=days),
            users=await queries.user_list(database),
        )

    @app.get("/users", response_class=HTMLResponse)
    async def users(request: Request, _: str = Depends(authenticate)) -> HTMLResponse:
        return render(request, "users.html", page="users", users=await queries.user_list(database))

    @app.get("/users/{user_id}", response_class=HTMLResponse)
    async def user_page(
        request: Request, user_id: int, _: str = Depends(authenticate)
    ) -> HTMLResponse:
        detail = await queries.user_detail(database, user_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return render(
            request,
            "user.html",
            page="users",
            user=detail,
            progress=await queries.user_progress(database, user_id),
            attempts=await queries.recent_attempts(database, user_id, limit=100),
            sessions=await queries.user_sessions(database, user_id),
            events=await queries.recent_events(database, user_id, limit=50),
        )

    @app.get("/phrases", response_class=HTMLResponse)
    async def phrases_page(
        request: Request, category: str | None = None, _: str = Depends(authenticate)
    ) -> HTMLResponse:
        selected = category if category in CATEGORIES else next(iter(CATEGORIES))
        return render(
            request,
            "phrases.html",
            page="phrases",
            categories=CATEGORIES,
            overview={row["category"]: row for row in await phrase_store.pool_overview(database)},
            selected=selected,
            phrases=await phrase_store.phrases_in_category(database, selected),
        )

    @app.post("/phrases/{phrase_id}/disable")
    async def disable_phrase(
        phrase_id: int, category: str = Form(...), _: str = Depends(authenticate)
    ) -> RedirectResponse:
        await phrase_store.set_disabled(database, phrase_id, True)
        _LOGGER.warning("phrase %s disabled from the dashboard", phrase_id)
        return RedirectResponse(f"/phrases?category={category}", status_code=303)

    @app.post("/phrases/{phrase_id}/enable")
    async def enable_phrase(
        phrase_id: int, category: str = Form(...), _: str = Depends(authenticate)
    ) -> RedirectResponse:
        await phrase_store.set_disabled(database, phrase_id, False)
        return RedirectResponse(f"/phrases?category={category}", status_code=303)

    @app.get("/moderation", response_class=HTMLResponse)
    async def moderation(request: Request, _: str = Depends(authenticate)) -> HTMLResponse:
        return render(
            request,
            "moderation.html",
            page="moderation",
            banned=await queries.banned_users(database),
            users=await queries.user_list(database),
            events=await queries.recent_events(
                database, kinds=("ban", "unban", "throttled", "oversized_input"), limit=100
            ),
        )

    @app.post("/moderation/ban")
    async def ban(user_id: int = Form(...), reason: str = Form(""), _: str = Depends(authenticate)):
        await database.set_ban(user_id, True, reason=reason or None)
        _LOGGER.warning("user %s banned from the dashboard (%s)", user_id, reason or "no reason")
        return RedirectResponse("/moderation", status_code=303)

    @app.post("/moderation/unban")
    async def unban(user_id: int = Form(...), _: str = Depends(authenticate)):
        await database.set_ban(user_id, False)
        _LOGGER.warning("user %s unbanned from the dashboard", user_id)
        return RedirectResponse("/moderation", status_code=303)

    @app.get("/balance", response_class=HTMLResponse)
    async def balance(
        request: Request, refresh: bool = False, _: str = Depends(authenticate)
    ) -> HTMLResponse:
        return render(
            request,
            "balance.html",
            page="balance",
            report=await openrouter.get(force=refresh),
            configured=openrouter.configured,
        )

    @app.get("/logs", response_class=HTMLResponse)
    async def logs(
        request: Request,
        name: str = Query("bot", pattern="^(bot|admin)$"),
        lines: int = Query(300, ge=50, le=5000),
        _: str = Depends(authenticate),
    ) -> HTMLResponse:
        return render(
            request,
            "logs.html",
            page="logs",
            name=name,
            lines=lines,
            entries=tail(log_path(settings.db_path, f"{name}.log"), lines),
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        """Unauthenticated liveness only — it discloses nothing about users."""
        return {"ok": True}

    return app


def _format_datetime(value: float | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not value:
        return "—"
    return datetime.fromtimestamp(float(value)).strftime(fmt)


def _format_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


app = None  # populated by `main()` / uvicorn factory


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    uvicorn.run(
        "admin.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - published only on the LAN by compose
        port=8080,
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()

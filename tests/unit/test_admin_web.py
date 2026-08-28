"""The dashboard: authentication, rendering, and what it refuses to do."""

from __future__ import annotations

import base64
import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from admin.app import create_app
from bot.config import AdminWebSettings
from bot.storage import phrases as phrase_store
from bot.storage.db import Database

USER = "admin"
PASSWORD = "correct horse"
AUTH = {"Authorization": "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()}


@pytest_asyncio.fixture
async def seeded(tmp_path):
    """A database with one user, some answers, a session and a phrase."""
    path = tmp_path / "admin.sqlite3"
    db = await Database(path).connect()
    await db.upsert_user(42, "kid", "Ребёнок")
    await db.set_user_fields(42, grade_profile="grade4", difficulty=3, score=25)
    session_id = await db.ensure_session(42, 1800)
    for index in range(6):
        await db.record_attempt(
            user_id=42,
            session_id=session_id,
            expression="12 × 3",
            correct_answer=36,
            given_answer="36" if index % 2 else "35",
            attempt_no=1,
            is_correct=bool(index % 2),
            difficulty=3,
            grade_profile="grade4",
            score_after=20 + index,
            ms_to_answer=4200,
            now=time.time() - index * 60,
        )
    await db.record_event(42, "difficulty_change", {"from": 2, "to": 3})
    await phrase_store.add_phrase(db, "correct_1st", "Молодец! 🎉", "stub", "m")
    await db.close()
    return path


@pytest.fixture
def client(seeded):
    settings = AdminWebSettings(
        db_path=seeded,
        admin_web_user=USER,
        admin_web_password=PASSWORD,
        http_proxy_url="",
        llm_api_key="",
        openrouter_base_url="https://openrouter.invalid/api/v1",
        balance_cache_seconds=300,
        log_level="WARNING",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


PAGES = ["/", "/users", "/users/42", "/phrases", "/moderation", "/balance", "/logs"]


class TestAuthentication:
    @pytest.mark.parametrize("path", PAGES)
    def test_every_page_demands_credentials(self, client, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 401
        assert "Ребёнок" not in response.text

    def test_wrong_password_is_refused(self, client) -> None:
        wrong = base64.b64encode(f"{USER}:nope".encode()).decode()
        assert client.get("/", headers={"Authorization": f"Basic {wrong}"}).status_code == 401

    def test_liveness_needs_no_credentials_and_leaks_nothing(self, client) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestPages:
    @pytest.mark.parametrize("path", PAGES)
    def test_pages_render(self, client, path: str) -> None:
        response = client.get(path, headers=AUTH)
        assert response.status_code == 200, response.text[:400]
        assert "<html" in response.text

    def test_overview_shows_the_user_and_the_chart(self, client) -> None:
        response = client.get("/", headers=AUTH)
        assert "Ребёнок" in response.text
        assert 'id="activity"' in response.text

    def test_user_page_charts_progress_and_lists_attempts(self, client) -> None:
        response = client.get("/users/42", headers=AUTH)
        assert 'id="progress"' in response.text
        assert "12 × 3" in response.text
        assert "difficulty_change" in response.text

    def test_unknown_user_is_a_404(self, client) -> None:
        assert client.get("/users/999999", headers=AUTH).status_code == 404

    def test_charts_are_served_locally(self, client) -> None:
        """No CDN: the server reaches the internet only through a proxy."""
        page = client.get("/", headers=AUTH).text
        assert "/static/chart.min.js" in page
        assert "cdn" not in page.lower()
        assert client.get("/static/chart.min.js").status_code == 200


class TestModeration:
    def test_ban_and_unban_round_trip(self, client) -> None:
        client.post("/moderation/ban", data={"user_id": 42, "reason": "тест"}, headers=AUTH)
        assert "тест" in client.get("/moderation", headers=AUTH).text

        client.post("/moderation/unban", data={"user_id": 42}, headers=AUTH)
        assert "Никто не забанен" in client.get("/moderation", headers=AUTH).text


class TestPhrases:
    def test_disable_and_enable_a_phrase(self, client) -> None:
        page = client.get("/phrases?category=correct_1st", headers=AUTH).text
        assert "Молодец! 🎉" in page

        client.post("/phrases/1/disable", data={"category": "correct_1st"}, headers=AUTH)
        assert "отключена" in client.get("/phrases?category=correct_1st", headers=AUTH).text

        client.post("/phrases/1/enable", data={"category": "correct_1st"}, headers=AUTH)
        assert "отключена" not in client.get("/phrases?category=correct_1st", headers=AUTH).text

    def test_unknown_category_falls_back_instead_of_failing(self, client) -> None:
        assert client.get("/phrases?category=nonsense", headers=AUTH).status_code == 200


class TestBalance:
    def test_unreachable_openrouter_does_not_break_the_page(self, client) -> None:
        """The host is deliberately invalid; the page must still render."""
        response = client.get("/balance", headers=AUTH)
        assert response.status_code == 200


class TestSafety:
    def test_no_route_can_alter_recorded_history(self, client) -> None:
        """The dashboard may only touch bans and phrase status."""
        app = client.app
        writable = {
            route.path
            for route in app.routes
            if getattr(route, "methods", None) and route.methods - {"GET", "HEAD", "OPTIONS"}
        }
        assert writable == {
            "/moderation/ban",
            "/moderation/unban",
            "/phrases/{phrase_id}/disable",
            "/phrases/{phrase_id}/enable",
        }

    def test_no_route_deletes_anything(self, client) -> None:
        for route in client.app.routes:
            assert "DELETE" not in (getattr(route, "methods", None) or set())

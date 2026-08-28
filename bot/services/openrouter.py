"""OpenRouter account and key reporting for the admin surface.

A port of the author's `openrouter_balance.py` from `requests` + `rich` to
`aiohttp`, so it can run inside the bot's event loop and inside the dashboard
without blocking either. The endpoints and the fields are the same ones that
script already proved correct.

The result is cached: an administrator refreshing a page should not cost a round
trip through the proxy each time, and a failed call should show the last known
numbers rather than an error.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from bot.config import mask

_LOGGER = logging.getLogger(__name__)


@dataclass
class BalanceReport:
    """What the dashboard and the `/balance` command render."""

    fetched_at: float
    ok: bool
    error: str = ""

    key_label: str = ""
    is_free_tier: bool = False
    limit: float | None = None
    limit_remaining: float | None = None
    usage_daily: float | None = None
    usage_weekly: float | None = None
    usage_monthly: float | None = None
    usage_total: float | None = None
    rate_limit: str = ""
    expires_at: str = ""

    total_credits: float | None = None
    total_usage: float | None = None

    masked_key: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_credits(self) -> float | None:
        if self.total_credits is None or self.total_usage is None:
            return None
        return self.total_credits - self.total_usage

    @property
    def remaining_fraction(self) -> float | None:
        if self.total_credits in (None, 0) or self.remaining_credits is None:
            return None
        assert self.total_credits is not None
        return max(0.0, min(1.0, self.remaining_credits / self.total_credits))

    @property
    def age_seconds(self) -> float:
        return time.time() - self.fetched_at


def _money(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class OpenRouterService:
    """Fetches and caches the OpenRouter balance."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        proxy: str | None = None,
        cache_seconds: int = 300,
        timeout: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._proxy = proxy or None
        self._cache_seconds = cache_seconds
        self._timeout = timeout
        self._cached: BalanceReport | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def _get(self, session: aiohttp.ClientSession, endpoint: str) -> dict[str, Any]:
        async with session.get(
            f"{self._base_url}{endpoint}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            proxy=self._proxy,
            timeout=aiohttp.ClientTimeout(total=self._timeout),
        ) as response:
            if response.status != 200:
                detail = (await response.text())[:200]
                raise RuntimeError(f"{endpoint} returned {response.status}: {detail}")
            payload = await response.json()
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def get(self, force: bool = False) -> BalanceReport:
        """The current report, from cache unless it is stale or `force` is set.

        On failure the last good report is returned with its age, so the caller
        always has numbers to show. Only a failure with nothing cached surfaces
        as a report with `ok=False`.
        """
        if not self.configured:
            return BalanceReport(
                fetched_at=time.time(), ok=False, error="API_KEY_LLM is not configured"
            )

        cached = self._cached
        if cached is not None and not force and cached.age_seconds < self._cache_seconds:
            return cached

        try:
            async with aiohttp.ClientSession() as session:
                key_info = await self._get(session, "/key")
                credits = await self._get(session, "/credits")
        except Exception as exc:  # noqa: BLE001 - any failure falls back to cache
            _LOGGER.info("openrouter balance unavailable: %s", exc)
            if cached is not None:
                return cached
            return BalanceReport(fetched_at=time.time(), ok=False, error=str(exc))

        rate = key_info.get("rate_limit") or {}
        report = BalanceReport(
            fetched_at=time.time(),
            ok=True,
            key_label=str(key_info.get("label") or ""),
            is_free_tier=bool(key_info.get("is_free_tier")),
            limit=_money(key_info.get("limit")),
            limit_remaining=_money(key_info.get("limit_remaining")),
            usage_daily=_money(key_info.get("usage_daily")),
            usage_weekly=_money(key_info.get("usage_weekly")),
            usage_monthly=_money(key_info.get("usage_monthly")),
            usage_total=_money(key_info.get("usage")),
            rate_limit=f"{rate.get('requests', '?')} / {rate.get('interval', '?')}",
            expires_at=str(key_info.get("expires_at") or ""),
            total_credits=_money(credits.get("total_credits")),
            total_usage=_money(credits.get("total_usage")),
            masked_key=mask(self._api_key),
            raw={"key": key_info, "credits": credits},
        )
        self._cached = report
        return report


def format_report(report: BalanceReport) -> str:
    """Render a report as the plain text the bot command sends."""

    def money(value: float | None) -> str:
        return "—" if value is None else f"${value:,.2f}"

    if not report.ok and report.raw == {}:
        return f"Баланс OpenRouter недоступен: {report.error}"

    lines = [
        "<b>OpenRouter</b>",
        f"Ключ: {report.masked_key}" + (" (free tier)" if report.is_free_tier else ""),
        f"Остаток: {money(report.remaining_credits)} из {money(report.total_credits)}",
        f"Потрачено всего: {money(report.total_usage)}",
        f"Сегодня: {money(report.usage_daily)} · "
        f"неделя: {money(report.usage_weekly)} · "
        f"месяц: {money(report.usage_monthly)}",
    ]
    if report.limit is not None:
        lines.append(f"Лимит ключа: {money(report.limit_remaining)} из {money(report.limit)}")
    age = int(report.age_seconds)
    if age > 5:
        lines.append(f"<i>данные {age} с назад</i>")
    if not report.ok:
        lines.append(f"<i>обновить не удалось: {report.error}</i>")
    return "\n".join(lines)

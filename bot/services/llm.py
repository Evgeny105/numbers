"""One OpenAI-compatible client, two providers, tried in order.

LM Studio runs on the author's PC and is free, so it goes first — but that PC is
often off, which is the normal case rather than an error. A short timeout keeps
the fall-through to OpenRouter cheap. OpenRouter is only reachable through the
xray proxy; without it the request comes back `403`.

None of this ever runs on the reply path. It is called by the phrase worker.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from bot.config import Settings

_LOGGER = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No configured provider could answer."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    timeout: float
    proxy: str | None

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.name == "openrouter":
            # OpenRouter asks for these for attribution; they are optional but
            # cheap and make the account's usage page readable.
            headers["HTTP-Referer"] = "https://github.com/Evgeny105/numbers"
            headers["X-Title"] = "Numbers math bot"
        return headers


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str


def build_providers(settings: Settings) -> list[Provider]:
    """The provider chain, in the order it should be tried."""
    providers: list[Provider] = []
    if settings.lmstudio_base_url:
        providers.append(
            Provider(
                name="lmstudio",
                base_url=settings.lmstudio_base_url.rstrip("/"),
                api_key="",
                model=settings.lmstudio_model,
                timeout=settings.lmstudio_timeout,
                # LM Studio is on the LAN; the proxy is for traffic leaving it.
                proxy=None,
            )
        )
    if settings.llm_api_key and settings.openrouter_base_url:
        providers.append(
            Provider(
                name="openrouter",
                base_url=settings.openrouter_base_url.rstrip("/"),
                api_key=settings.llm_api_key,
                model=settings.openrouter_model,
                timeout=settings.openrouter_timeout,
                proxy=settings.http_proxy_url or None,
            )
        )
    return providers


class LLMClient:
    """Calls the first provider that answers."""

    def __init__(self, providers: list[Provider]) -> None:
        self._providers = providers
        self._session: aiohttp.ClientSession | None = None
        self._resolved_models: dict[str, str] = {}

    async def __aenter__(self) -> "LLMClient":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _model_for(self, provider: Provider) -> str:
        """The model to ask for, discovering one from LM Studio if unset.

        The author swaps models in LM Studio freely, so pinning a name in the
        configuration would break every time. When none is configured, ask the
        server which models it has and take the first.
        """
        if provider.model:
            return provider.model
        cached = self._resolved_models.get(provider.name)
        if cached:
            return cached

        session = self._require_session()
        async with session.get(
            f"{provider.base_url}/models",
            headers=provider.headers(),
            proxy=provider.proxy,
            timeout=aiohttp.ClientTimeout(total=provider.timeout),
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        models = [item["id"] for item in payload.get("data", []) if item.get("id")]
        # Embedding models cannot hold a conversation; skip anything that says so.
        chat_models = [name for name in models if "embed" not in name.lower()]
        if not chat_models:
            raise LLMUnavailable(f"{provider.name} reports no usable model")
        self._resolved_models[provider.name] = chat_models[0]
        return chat_models[0]

    async def _complete_with(
        self, provider: Provider, system: str, user: str, temperature: float, max_tokens: int
    ) -> Completion:
        session = self._require_session()
        model = await self._model_for(provider)
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if provider.name == "openrouter":
            # Reasoning models spend the whole budget thinking and hand back a
            # null `content` — measured, not guessed. Ask for the answer only.
            body["reasoning"] = {"enabled": False}
        async with session.post(
            f"{provider.base_url}/chat/completions",
            json=body,
            headers=provider.headers(),
            proxy=provider.proxy,
            timeout=aiohttp.ClientTimeout(total=provider.timeout),
        ) as response:
            if response.status != 200:
                detail = (await response.text())[:200]
                raise LLMUnavailable(f"{provider.name} returned {response.status}: {detail}")
            payload = await response.json()

        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"{provider.name} returned an unexpected payload") from exc
        if not isinstance(text, str) or not text.strip():
            raise LLMUnavailable(f"{provider.name} returned empty content")
        return Completion(text=text.strip(), provider=provider.name, model=model)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 1.0,
        max_tokens: int = 400,
    ) -> Completion:
        """Ask each provider in turn; raise only when all of them fail."""
        if not self._providers:
            raise LLMUnavailable("no LLM provider is configured")

        failures: list[str] = []
        for provider in self._providers:
            try:
                completion = await self._complete_with(
                    provider, system, user, temperature, max_tokens
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, LLMUnavailable) as exc:
                # A provider being off is the expected case, not an incident.
                # `asyncio.TimeoutError` stringifies to nothing, so name it.
                detail = str(exc) or type(exc).__name__
                _LOGGER.info("llm provider %s unavailable: %s", provider.name, detail)
                failures.append(f"{provider.name}: {detail}")
                continue
            _LOGGER.debug("llm completion from %s (%s)", completion.provider, completion.model)
            return completion

        raise LLMUnavailable("; ".join(failures))

"""Async SearXNG client.

Single responsibility: send one well-formed JSON search to a configured
SearXNG instance and return the raw ``results`` list. Everything that can
go wrong on the wire becomes a typed :mod:`sekurvia.errors` exception so
the tool handler can map it to a structured JSON error.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from types import TracebackType
from typing import Any

import httpx

from .config import Settings
from .errors import NetworkError, RemoteError

log = logging.getLogger(__name__)


_VALID_TIME_RANGES = {"", "day", "week", "month", "year"}
_VALID_SAFESEARCH = {0, 1, 2}


class SearxngClient:
    """Thin async wrapper around the SearXNG ``/search`` endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        }
        if settings.auth_token:
            headers["Authorization"] = f"Bearer {settings.auth_token}"

        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_s),
            verify=settings.verify_tls,
            follow_redirects=False,
            headers=headers,
            http2=False,
        )

    async def __aenter__(self) -> SearxngClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(
        self,
        query: str,
        *,
        categories: Iterable[str] | None = None,
        language: str | None = None,
        safesearch: int | None = None,
        time_range: str | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Run a single search; return SearXNG's raw ``results`` list.

        Caller is responsible for sanitization (see :mod:`sekurvia.sanitize`).
        """
        s = self._settings

        if safesearch is None:
            safesearch = s.default_safesearch
        if safesearch not in _VALID_SAFESEARCH:
            safesearch = s.default_safesearch

        if time_range is None:
            time_range = ""
        if time_range not in _VALID_TIME_RANGES:
            time_range = ""

        if not language:
            language = s.default_language

        page = max(1, int(page or 1))

        data: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": str(safesearch),
            "pageno": str(page),
        }
        if time_range:
            data["time_range"] = time_range
        if categories:
            joined = ",".join(c.strip() for c in categories if c and c.strip())
            if joined:
                data["categories"] = joined

        payload = await self._post_with_retries("/search", data)
        results = payload.get("results")
        if not isinstance(results, list):
            raise RemoteError("SearXNG response missing 'results' list")
        return results

    async def _post_with_retries(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        s = self._settings
        attempts = s.retries + 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                return await self._post_once(path, data)
            except NetworkError as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    break
                await asyncio.sleep(s.retry_backoff_s * (2**attempt))
            except RemoteError as exc:
                # Retry server-side 5xx; bail immediately on 4xx.
                last_exc = exc
                status = exc.status_code or 0
                if 500 <= status < 600 and attempt + 1 < attempts:
                    await asyncio.sleep(s.retry_backoff_s * (2**attempt))
                    continue
                raise

        assert last_exc is not None
        raise last_exc

    async def _post_once(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        s = self._settings
        try:
            async with self._client.stream("POST", path, data=data) as response:
                if response.status_code >= 400:
                    snippet = await self._read_capped_text(response)
                    raise RemoteError(
                        f"SearXNG returned HTTP {response.status_code}: {snippet[:200]}",
                        status_code=response.status_code,
                    )
                body = await self._read_capped_bytes(response, s.max_response_bytes)
        except httpx.TimeoutException as exc:
            raise NetworkError(f"SearXNG request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise NetworkError(f"SearXNG transport error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"SearXNG request failed: {exc}") from exc

        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise RemoteError(f"SearXNG returned non-JSON body: {exc}") from exc

        if not isinstance(payload, dict):
            raise RemoteError("SearXNG returned a non-object JSON body")
        return payload

    @staticmethod
    async def _read_capped_bytes(response: httpx.Response, cap: int) -> bytes:
        buf = bytearray()
        async for chunk in response.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > cap:
                raise RemoteError(
                    f"SearXNG response exceeded {cap} bytes; refusing to load",
                    status_code=response.status_code,
                )
        return bytes(buf)

    @staticmethod
    async def _read_capped_text(response: httpx.Response, cap: int = 4096) -> str:
        buf = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > cap:
                    break
        except Exception:
            return ""
        return bytes(buf).decode("utf-8", errors="replace")

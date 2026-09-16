from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class StarIntelError(RuntimeError):
    """StarIntel returned an error response or an invalid payload."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SearchResult:
    documents: tuple[dict[str, Any], ...]
    count: int
    dataset: str | None = None
    tenant_id: str | None = None
    source_dataset: str | None = None


class StarIntelClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "starintel-discord-tool/1.0",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StarIntelError(f"StarIntel request failed: {exc}") from exc

        if response.is_error:
            detail = response.text[:1000]
            try:
                body = response.json()
                if isinstance(body, dict):
                    error = body.get("error")
                    if isinstance(error, dict):
                        detail = str(error.get("message") or error.get("code") or detail)
                    elif error:
                        detail = str(error)
            except ValueError:
                pass
            raise StarIntelError(detail or response.reason_phrase, status_code=response.status_code)

        try:
            body = response.json()
        except ValueError as exc:
            raise StarIntelError("StarIntel returned non-JSON data", status_code=response.status_code) from exc
        if not isinstance(body, dict):
            raise StarIntelError("StarIntel returned a non-object JSON payload", status_code=response.status_code)
        return body

    async def search(
        self,
        query: str,
        *,
        dataset: str | None = None,
        tenant_id: str | None = None,
        source_dataset: str | None = None,
        order_by: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResult:
        params: dict[str, str | int] = {"q": query, "limit": limit, "offset": offset}
        if dataset:
            params["dataset"] = dataset
        if tenant_id:
            params["tenant_id"] = tenant_id
        if source_dataset:
            params["source_dataset"] = source_dataset
        if order_by:
            params["order_by"] = order_by

        body = await self._json("GET", "/api/v1/search", params=params)
        docs = body.get("documents", [])
        if not isinstance(docs, list):
            raise StarIntelError("StarIntel search response has no document array")
        documents = tuple(item for item in docs if isinstance(item, dict))
        count = body.get("count", len(documents))
        try:
            count_int = int(count)
        except (TypeError, ValueError):
            count_int = len(documents)
        return SearchResult(
            documents=documents,
            count=count_int,
            dataset=body.get("dataset") if isinstance(body.get("dataset"), str) else dataset,
            tenant_id=body.get("tenant_id") if isinstance(body.get("tenant_id"), str) else tenant_id,
            source_dataset=(
                body.get("source_dataset") if isinstance(body.get("source_dataset"), str) else source_dataset
            ),
        )

    async def create_target(
        self,
        actor: str,
        target: str,
        *,
        workspace_id: str | None = None,
        dataset: str | None = None,
        kind: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"actor": actor, "target": target}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        if dataset:
            payload["dataset"] = dataset
        if kind:
            payload["kind"] = kind
        if metadata:
            payload["metadata"] = metadata
        return await self._json("POST", "/api/v1/targets", json=payload)

    async def health(self) -> dict[str, Any]:
        for path in ("/api/v1/stats", "/stats"):
            try:
                return await self._json("GET", path)
            except StarIntelError as exc:
                if exc.status_code not in {404, 405}:
                    raise
        raise StarIntelError("StarIntel stats endpoint is unavailable")

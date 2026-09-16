from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .client import StarIntelClient, StarIntelError


@dataclass(frozen=True, slots=True)
class ActorInfo:
    actor_id: str
    actor_type: str | None = None
    operations: tuple[str, ...] = ()


def _actor_from_document(document: dict[str, Any]) -> ActorInfo | None:
    candidates: list[dict[str, Any]] = [document]
    for key in ("data", "manifest", "actor_manifest"):
        value = document.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        actor_id = candidate.get("actor_id") or candidate.get("actor")
        if not isinstance(actor_id, str) or not actor_id.strip():
            continue
        actor_type = candidate.get("actor_type")
        operations = candidate.get("operations", [])
        if not isinstance(operations, list):
            operations = []
        return ActorInfo(
            actor_id=actor_id.strip(),
            actor_type=actor_type if isinstance(actor_type, str) else None,
            operations=tuple(str(item) for item in operations if isinstance(item, str)),
        )
    return None


class ActorCatalog:
    def __init__(
        self,
        client: StarIntelClient,
        fallback_ids: Iterable[str],
        *,
        dataset: str | None,
        tenant_id: str | None,
    ) -> None:
        self.client = client
        self.fallback_ids = tuple(dict.fromkeys(fallback_ids))
        self.dataset = dataset
        self.tenant_id = tenant_id

    async def list(self) -> tuple[ActorInfo, ...]:
        actors: dict[str, ActorInfo] = {
            actor_id: ActorInfo(actor_id) for actor_id in self.fallback_ids
        }
        try:
            result = await self.client.search(
                "actor-manifest",
                dataset=self.dataset,
                tenant_id=self.tenant_id,
                limit=100,
            )
        except StarIntelError:
            return tuple(actors.values())
        for document in result.documents:
            actor = _actor_from_document(document)
            if actor:
                actors[actor.actor_id] = actor
        return tuple(sorted(actors.values(), key=lambda actor: actor.actor_id))

    async def ids(self) -> tuple[str, ...]:
        return tuple(actor.actor_id for actor in await self.list())

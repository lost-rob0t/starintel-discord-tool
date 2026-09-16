from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import discord

from .client import StarIntelClient, StarIntelError
from .formatting import format_document_markdown
from .state import RadarSpec, StateStore, document_key

log = logging.getLogger(__name__)


class ChannelResolver(Protocol):
    def get_channel(
        self,
        channel_id: int,
    ) -> discord.abc.GuildChannel | discord.Thread | None: ...


@dataclass(frozen=True, slots=True)
class RadarSettings:
    poll_seconds: int
    search_limit: int
    max_posts_per_poll: int
    bootstrap_silently: bool


class RadarActor:
    """One mailbox-driven actor owns one configured radar."""

    def __init__(
        self,
        spec: RadarSpec,
        *,
        client: StarIntelClient,
        store: StateStore,
        channel_resolver: ChannelResolver,
        settings: RadarSettings,
    ) -> None:
        self.spec = spec
        self.client = client
        self.store = store
        self.channel_resolver = channel_resolver
        self.settings = settings
        self._mailbox: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        self._task: asyncio.Task[None] | None = None
        self._timer: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._run(),
            name=f"radar-actor-{self.spec.id}",
        )
        self._timer = asyncio.create_task(
            self._tick(),
            name=f"radar-timer-{self.spec.id}",
        )
        self.tell("poll")

    def tell(self, message: str) -> None:
        if not self._mailbox.full():
            self._mailbox.put_nowait(message)

    async def stop(self) -> None:
        for task in (self._timer, self._task):
            if task:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._timer, self._task) if task),
            return_exceptions=True,
        )
        self._task = None
        self._timer = None

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(self.settings.poll_seconds)
            self.tell("poll")

    async def _run(self) -> None:
        while True:
            message = await self._mailbox.get()
            try:
                if message == "poll":
                    await self.poll()
                elif message == "stop":
                    return
            except Exception:
                log.exception("radar actor %s failed", self.spec.id)
            finally:
                self._mailbox.task_done()

    async def poll(self) -> int:
        try:
            result = await self.client.search(
                self.spec.query,
                dataset=self.spec.dataset,
                tenant_id=self.spec.tenant_id,
                limit=self.settings.search_limit,
            )
        except StarIntelError as exc:
            log.warning("radar %s StarIntel query failed: %s", self.spec.id, exc)
            return 0

        new_keys = self.store.remember_documents(self.spec.id, result.documents)
        first_poll = not self.spec.bootstrapped
        if first_poll:
            self.store.mark_bootstrapped(self.spec.id)
            self.spec = RadarSpec(
                id=self.spec.id,
                guild_id=self.spec.guild_id,
                channel_id=self.spec.channel_id,
                query=self.spec.query,
                dataset=self.spec.dataset,
                tenant_id=self.spec.tenant_id,
                source_dataset=None,
                created_by=self.spec.created_by,
                enabled=self.spec.enabled,
                bootstrapped=True,
            )
            if self.settings.bootstrap_silently:
                return 0

        new_docs = [
            doc for doc in result.documents if document_key(doc) in new_keys
        ]
        if not new_docs:
            return 0
        new_docs = list(reversed(new_docs[: self.settings.max_posts_per_poll]))
        channel = self.channel_resolver.get_channel(self.spec.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning(
                "radar %s channel %s is unavailable",
                self.spec.id,
                self.spec.channel_id,
            )
            return 0
        posted = 0
        for document in new_docs:
            await channel.send(
                format_document_markdown(document),
                suppress_embeds=False,
            )
            posted += 1
        return posted


class RadarSupervisor:
    def __init__(
        self,
        *,
        client: StarIntelClient,
        store: StateStore,
        channel_resolver: ChannelResolver,
        settings: RadarSettings,
    ) -> None:
        self.client = client
        self.store = store
        self.channel_resolver = channel_resolver
        self.settings = settings
        self._actors: dict[int, RadarActor] = {}

    async def reconcile(self) -> None:
        specs = {spec.id: spec for spec in self.store.list_radars()}
        for radar_id in tuple(self._actors):
            if radar_id not in specs:
                await self._actors.pop(radar_id).stop()
        for radar_id, spec in specs.items():
            current = self._actors.get(radar_id)
            if current and current.spec == spec:
                continue
            if current:
                await current.stop()
            actor = RadarActor(
                spec,
                client=self.client,
                store=self.store,
                channel_resolver=self.channel_resolver,
                settings=self.settings,
            )
            self._actors[radar_id] = actor
            actor.start()

    def poll_now(self, radar_id: int) -> bool:
        actor = self._actors.get(radar_id)
        if not actor:
            return False
        actor.tell("poll")
        return True

    async def close(self) -> None:
        actors = tuple(self._actors.values())
        self._actors.clear()
        await asyncio.gather(
            *(actor.stop() for actor in actors),
            return_exceptions=True,
        )

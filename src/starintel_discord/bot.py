from __future__ import annotations

import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .actors import ActorCatalog
from .client import StarIntelClient, StarIntelError
from .config import AppConfig
from .formatting import format_document_markdown, format_search_results, parse_metadata_json
from .radar import RadarSettings, RadarSupervisor
from .state import StateStore

log = logging.getLogger(__name__)


def _trim(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class StarIntelBot(commands.Bot):
    def __init__(self, config: AppConfig) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.config = config
        self.state = StateStore(config.radar.state_path)
        self.state.seed_authorized_users(config.discord.authorized_user_ids)
        self.api = StarIntelClient(
            config.starintel.base_url,
            config.starintel.api_key,
            timeout=config.starintel.request_timeout_seconds,
        )
        self.actors = ActorCatalog(
            self.api,
            config.pro_actors.actor_ids,
            dataset=None,
            tenant_id=config.starintel.default_tenant_id,
        )
        self.radars = RadarSupervisor(
            client=self.api,
            store=self.state,
            channel_resolver=self,
            settings=RadarSettings(
                poll_seconds=config.radar.poll_seconds,
                search_limit=config.radar.search_limit,
                max_posts_per_poll=config.radar.max_posts_per_poll,
                bootstrap_silently=config.radar.bootstrap_silently,
            ),
        )
        self._install_commands()

    async def setup_hook(self) -> None:
        if self.config.discord.guild_ids:
            for guild_id in self.config.discord.guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        await self.radars.reconcile()

    async def close(self) -> None:
        await self.radars.close()
        await self.api.close()
        self.state.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")

    def _is_operator(self, interaction: discord.Interaction) -> bool:
        user_id = interaction.user.id
        if user_id in self.config.discord.owner_ids or self.state.is_authorized(user_id):
            return True
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(permissions and permissions.administrator)

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in self.config.discord.owner_ids:
            return True
        permissions = getattr(interaction.user, "guild_permissions", None)
        return bool(permissions and permissions.administrator)

    async def _require_operator(self, interaction: discord.Interaction) -> bool:
        if self._is_operator(interaction):
            return True
        await interaction.response.send_message(
            "Not authorized for StarIntel operations.",
            ephemeral=True,
        )
        return False

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if self._is_admin(interaction):
            return True
        await interaction.response.send_message(
            "Bot owner or Discord administrator required.",
            ephemeral=True,
        )
        return False

    def _install_commands(self) -> None:
        target_group = app_commands.Group(
            name="target",
            description="Dispatch StarIntel targets",
        )
        auth_group = app_commands.Group(
            name="auth",
            description="Manage Discord-side StarIntel authorization",
        )
        radar_group = app_commands.Group(
            name="radar",
            description="Configure document radar feeds",
        )

        @self.tree.command(name="search", description="Search StarIntel datasets")
        @app_commands.describe(
            query="Search query",
            dataset="Optional dataset; omitted searches all authorized datasets in the tenant",
            tenant="Tenant ID; defaults to llm",
            limit="Number of matches to show (1-20)",
        )
        async def search(
            interaction: discord.Interaction,
            query: str,
            dataset: str | None = None,
            tenant: str | None = None,
            limit: app_commands.Range[int, 1, 20] = 10,
        ) -> None:
            if not await self._require_operator(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await self.api.search(
                    query,
                    dataset=_trim(dataset),
                    tenant_id=_trim(tenant) or self.config.starintel.default_tenant_id,
                    limit=int(limit),
                )
            except StarIntelError as exc:
                await interaction.followup.send(
                    f"StarIntel search failed: `{exc}`",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(
                format_search_results(result.documents, total_count=result.count),
                ephemeral=True,
            )

        @self.tree.command(
            name="datasets",
            description="Show dataset/tenant defaults and access model",
        )
        async def datasets(interaction: discord.Interaction) -> None:
            if not await self._require_operator(interaction):
                return
            hints = ", ".join(
                f"`{item}`" for item in self.config.starintel.dataset_hints
            ) or "none"
            await interaction.response.send_message(
                "**StarIntel dataset access**\n"
                "Search default: `all authorized datasets`\n"
                f"Target default dataset: `{self.config.starintel.default_dataset}`\n"
                f"Default tenant: `{self.config.starintel.default_tenant_id or 'credential default'}`\n"
                f"Configured dataset hints: {hints}\n\n"
                "You may pass any dataset to `/search`; the StarIntel API credential is the final "
                "authorization boundary. This bot does not maintain a second dataset ACL.",
                ephemeral=True,
            )

        @self.tree.command(name="actors", description="List dispatchable StarIntel pro actors")
        async def actors(interaction: discord.Interaction) -> None:
            if not await self._require_operator(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            catalog = await self.actors.list()
            lines = ["**StarIntel pro actors**"]
            for actor in catalog:
                suffix = f" — {actor.actor_type}" if actor.actor_type else ""
                ops = f" ({', '.join(actor.operations)})" if actor.operations else ""
                lines.append(f"- `{actor.actor_id}`{suffix}{ops}")
            await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

        async def actor_autocomplete(
            _interaction: discord.Interaction,
            current: str,
        ) -> list[app_commands.Choice[str]]:
            ids = await self.actors.ids()
            needle = current.casefold()
            return [
                app_commands.Choice(name=actor_id, value=actor_id)
                for actor_id in ids
                if needle in actor_id.casefold()
            ][:25]

        @target_group.command(
            name="create",
            description="Create and dispatch a canonical StarIntel target",
        )
        @app_commands.describe(
            actor="Destination actor",
            target="Actor target value",
            dataset="Target dataset; defaults to llm",
            kind="Optional target kind",
            workspace="Optional workspace ID",
            metadata_json="Optional JSON object attached as target metadata",
        )
        @app_commands.autocomplete(actor=actor_autocomplete)
        async def target_create(
            interaction: discord.Interaction,
            actor: str,
            target: str,
            dataset: str | None = None,
            kind: str | None = None,
            workspace: str | None = None,
            metadata_json: str | None = None,
        ) -> None:
            if not await self._require_operator(interaction):
                return
            try:
                metadata = parse_metadata_json(metadata_json)
            except (ValueError, json.JSONDecodeError) as exc:
                await interaction.response.send_message(
                    f"Invalid metadata JSON: `{exc}`",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                response = await self.api.create_target(
                    actor.strip(),
                    target.strip(),
                    dataset=_trim(dataset) or self.config.starintel.default_dataset,
                    kind=_trim(kind),
                    workspace_id=_trim(workspace),
                    metadata=metadata,
                )
            except StarIntelError as exc:
                await interaction.followup.send(
                    f"Target dispatch failed: `{exc}`",
                    ephemeral=True,
                )
                return
            accepted = response.get("accepted", True)
            await interaction.followup.send(
                f"{'✅' if accepted else '⚠️'} target dispatched to `{actor}`: `{target}` "
                f"in `{_trim(dataset) or self.config.starintel.default_dataset}`",
                ephemeral=True,
            )

        @auth_group.command(
            name="add",
            description="Authorize a Discord user to operate StarIntel",
        )
        async def auth_add(interaction: discord.Interaction, user: discord.User) -> None:
            if not await self._require_admin(interaction):
                return
            self.state.add_authorized_user(user.id, interaction.user.id)
            await interaction.response.send_message(
                f"Authorized {user.mention} (`{user.id}`).",
                ephemeral=True,
            )

        @auth_group.command(
            name="remove",
            description="Remove Discord-side StarIntel authorization",
        )
        async def auth_remove(interaction: discord.Interaction, user: discord.User) -> None:
            if not await self._require_admin(interaction):
                return
            removed = self.state.remove_authorized_user(user.id)
            status = "Removed" if removed else "No stored authorization for"
            await interaction.response.send_message(
                f"{status} {user.mention} (`{user.id}`).",
                ephemeral=True,
            )

        @auth_group.command(
            name="list",
            description="List Discord users authorized for StarIntel",
        )
        async def auth_list(interaction: discord.Interaction) -> None:
            if not await self._require_admin(interaction):
                return
            ids = self.state.list_authorized_users()
            body = "\n".join(
                f"- <@{user_id}> (`{user_id}`)" for user_id in ids
            ) or "No persisted users."
            await interaction.response.send_message(
                f"**Authorized users**\n{body}"[:1900],
                ephemeral=True,
            )

        @radar_group.command(
            name="configure",
            description="Post newly matching StarIntel documents to a channel",
        )
        @app_commands.describe(
            channel="Channel that receives radar posts",
            query="StarIntel search query",
            dataset="Optional dataset; omitted watches all authorized datasets in the tenant",
            tenant="Tenant ID; defaults to llm",
        )
        async def radar_configure(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
            query: str,
            dataset: str | None = None,
            tenant: str | None = None,
        ) -> None:
            if not await self._require_operator(interaction):
                return
            if interaction.guild_id is None:
                await interaction.response.send_message(
                    "`/radar configure` must run in a server.",
                    ephemeral=True,
                )
                return
            spec = self.state.upsert_radar(
                guild_id=interaction.guild_id,
                channel_id=channel.id,
                query=query.strip(),
                dataset=_trim(dataset),
                tenant_id=_trim(tenant) or self.config.starintel.default_tenant_id,
                source_dataset=None,
                created_by=interaction.user.id,
            )
            await self.radars.reconcile()
            await interaction.response.send_message(
                f"📡 radar `{spec.id}` configured for {channel.mention}: `{spec.query}` "
                f"on `{spec.dataset or 'all authorized datasets'}`. Existing matches are checkpointed "
                "before new-document posts begin.",
                ephemeral=True,
            )

        @radar_group.command(name="off", description="Disable radar in a channel")
        async def radar_off(
            interaction: discord.Interaction,
            channel: discord.TextChannel,
        ) -> None:
            if not await self._require_operator(interaction):
                return
            if interaction.guild_id is None:
                await interaction.response.send_message(
                    "This command must run in a server.",
                    ephemeral=True,
                )
                return
            disabled = self.state.disable_radar(interaction.guild_id, channel.id)
            await self.radars.reconcile()
            await interaction.response.send_message(
                f"{'Disabled' if disabled else 'No active radar for'} {channel.mention}.",
                ephemeral=True,
            )

        @radar_group.command(
            name="list",
            description="List active radars in this Discord server",
        )
        async def radar_list(interaction: discord.Interaction) -> None:
            if not await self._require_operator(interaction):
                return
            if interaction.guild_id is None:
                await interaction.response.send_message(
                    "This command must run in a server.",
                    ephemeral=True,
                )
                return
            specs = self.state.list_radars(interaction.guild_id)
            lines = ["**Active radars**"]
            for spec in specs:
                lines.append(
                    f"- `{spec.id}` <#{spec.channel_id}> — `{spec.query}` · "
                    f"dataset `{spec.dataset or 'all authorized'}` · "
                    f"tenant `{spec.tenant_id or 'credential'}`"
                )
            if len(lines) == 1:
                lines.append("No active radars.")
            await interaction.response.send_message(
                "\n".join(lines)[:1900],
                ephemeral=True,
            )

        @radar_group.command(name="now", description="Trigger an immediate poll for a radar")
        async def radar_now(interaction: discord.Interaction, radar_id: int) -> None:
            if not await self._require_operator(interaction):
                return
            triggered = self.radars.poll_now(radar_id)
            await interaction.response.send_message(
                f"{'Queued' if triggered else 'Radar not found'}: `{radar_id}`.",
                ephemeral=True,
            )

        @self.tree.command(
            name="document",
            description="Render one search match as radar Markdown",
        )
        async def document(interaction: discord.Interaction, query: str) -> None:
            if not await self._require_operator(interaction):
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await self.api.search(
                    query,
                    dataset=None,
                    tenant_id=self.config.starintel.default_tenant_id,
                    limit=1,
                )
            except StarIntelError as exc:
                await interaction.followup.send(
                    f"Lookup failed: `{exc}`",
                    ephemeral=True,
                )
                return
            if not result.documents:
                await interaction.followup.send("No matching document.", ephemeral=True)
                return
            await interaction.followup.send(
                format_document_markdown(result.documents[0]),
                ephemeral=True,
            )

        self.tree.add_command(target_group)
        self.tree.add_command(auth_group)
        self.tree.add_command(radar_group)


def build_bot(config: AppConfig) -> StarIntelBot:
    return StarIntelBot(config)

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised when required bot configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class DiscordConfig:
    token: str
    owner_ids: frozenset[int] = frozenset()
    authorized_user_ids: frozenset[int] = frozenset()
    guild_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class StarIntelConfig:
    base_url: str
    api_key: str
    default_dataset: str = "llm"
    default_tenant_id: str | None = "llm"
    dataset_hints: tuple[str, ...] = ("llm",)
    request_timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class RadarConfig:
    state_path: Path = Path("./state/starintel-discord.sqlite3")
    poll_seconds: int = 15
    search_limit: int = 100
    max_posts_per_poll: int = 20
    bootstrap_silently: bool = True


DEFAULT_PRO_ACTORS = (
    "bluesky",
    "generate-usernames",
    "melissa",
    "whats-my-name-user-hunt",
    "reddit",
    "youtube",
    "web",
    "crimethinc-podcasts",
    "telegram",
    "user-hunt",
    "x",
    "username-targets",
    "cracked",
    "org-member",
    "kiwifarms",
    "background-report",
)


@dataclass(frozen=True, slots=True)
class ProActorsConfig:
    actor_ids: tuple[str, ...] = DEFAULT_PRO_ACTORS


@dataclass(frozen=True, slots=True)
class AppConfig:
    discord: DiscordConfig
    starintel: StarIntelConfig
    radar: RadarConfig = field(default_factory=RadarConfig)
    pro_actors: ProActorsConfig = field(default_factory=ProActorsConfig)


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    return value


def _ints(value: object, *, field_name: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field_name} must be an array of integer Discord IDs")
    try:
        return tuple(int(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must contain only integer Discord IDs") from exc


def _strings(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ConfigError(f"{field_name} must be an array of non-empty strings")
    return tuple(dict.fromkeys(item.strip() for item in value))


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("STARINTEL_DISCORD_CONFIG", "config.toml"))
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)

    discord_raw = _table(raw, "discord")
    star_raw = _table(raw, "starintel")
    radar_raw = _table(raw, "radar")
    actors_raw = _table(raw, "pro_actors")

    token = os.getenv("STARINTEL_DISCORD_TOKEN", "").strip()
    api_key = os.getenv("STARINTEL_API_KEY", "").strip()
    if not token:
        raise ConfigError("STARINTEL_DISCORD_TOKEN is required")
    if not api_key:
        raise ConfigError("STARINTEL_API_KEY is required")

    base_url = str(
        os.getenv(
            "STARINTEL_SERVER_URL",
            star_raw.get("base_url", "http://127.0.0.1:5000"),
        )
    ).rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError("starintel.base_url must start with http:// or https://")

    default_dataset = str(star_raw.get("default_dataset", "llm")).strip()
    if not default_dataset:
        raise ConfigError("starintel.default_dataset must be non-empty")

    tenant_raw = star_raw.get("default_tenant_id", "llm")
    default_tenant_id = None if tenant_raw in (None, "") else str(tenant_raw).strip()

    hints = _strings(
        star_raw.get("dataset_hints", [default_dataset]),
        field_name="starintel.dataset_hints",
    )
    if default_dataset not in hints:
        hints = (default_dataset, *hints)

    actor_ids = _strings(
        actors_raw.get("actor_ids", list(DEFAULT_PRO_ACTORS)),
        field_name="pro_actors.actor_ids",
    )
    if not actor_ids:
        actor_ids = DEFAULT_PRO_ACTORS

    poll_seconds = int(radar_raw.get("poll_seconds", 15))
    if poll_seconds < 5:
        raise ConfigError("radar.poll_seconds must be >= 5")

    search_limit = int(radar_raw.get("search_limit", 100))
    if not 1 <= search_limit <= 500:
        raise ConfigError("radar.search_limit must be between 1 and 500")

    max_posts = int(radar_raw.get("max_posts_per_poll", 20))
    if not 1 <= max_posts <= 100:
        raise ConfigError("radar.max_posts_per_poll must be between 1 and 100")

    return AppConfig(
        discord=DiscordConfig(
            token=token,
            owner_ids=frozenset(
                _ints(discord_raw.get("owner_ids", []), field_name="discord.owner_ids")
            ),
            authorized_user_ids=frozenset(
                _ints(
                    discord_raw.get("authorized_user_ids", []),
                    field_name="discord.authorized_user_ids",
                )
            ),
            guild_ids=_ints(
                discord_raw.get("guild_ids", []),
                field_name="discord.guild_ids",
            ),
        ),
        starintel=StarIntelConfig(
            base_url=base_url,
            api_key=api_key,
            default_dataset=default_dataset,
            default_tenant_id=default_tenant_id,
            dataset_hints=hints,
            request_timeout_seconds=float(
                star_raw.get("request_timeout_seconds", 30.0)
            ),
        ),
        radar=RadarConfig(
            state_path=Path(
                str(radar_raw.get("state_path", "./state/starintel-discord.sqlite3"))
            ),
            poll_seconds=poll_seconds,
            search_limit=search_limit,
            max_posts_per_poll=max_posts,
            bootstrap_silently=bool(radar_raw.get("bootstrap_silently", True)),
        ),
        pro_actors=ProActorsConfig(actor_ids=actor_ids),
    )

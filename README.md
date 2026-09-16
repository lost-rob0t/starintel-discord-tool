# StarIntel Discord Tool

Python Discord operations client for StarIntel. The old Nim stub is gone; this repo now ships the bot, API client, durable authorization/radar state, tests, and deployment surface.

## What it does

- `/search` — authorized search across StarIntel datasets/tenants. With no dataset argument it searches every dataset authorized in tenant `llm`, covering the full GPT auto-dig corpus by default.
- `/datasets` — shows the configured dataset/tenant defaults and discovery hints. Dataset authorization is deliberately delegated to the StarIntel API credential instead of duplicated in Discord.
- `/target create` — dispatches canonical `POST /api/v1/targets` requests, including pro-actor targets.
- `/actors` — lists the bundled pro-actor catalog and overlays any `actor-manifest` documents discoverable through StarIntel.
- `/auth add|remove|list` — persists Discord-side authorized users. Bot owners and Discord administrators may manage access.
- `/radar configure|off|list|now` — creates durable channel radars. A radar checkpoints existing matches, then posts newly seen documents as Markdown.
- `/document` — previews one result using the same Markdown renderer used by radar.

## StarIntel API contract

The bot talks only to the versioned server contract:

- `GET /api/v1/search` with `q`, `dataset`, `tenant_id`, `source_dataset`, `offset`, `limit`, and `order_by`.
- `POST /api/v1/targets` with `actor`, `target`, optional `workspace_id`, `dataset`, `kind`, and `metadata`.

The API bearer token remains the source of truth for tenant/dataset authorization. Discord authorization is an additional operator gate, not a replacement for StarIntel authorization.

## Configure

```bash
cp config.example.toml config.toml
export STARINTEL_DISCORD_TOKEN='...'
export STARINTEL_API_KEY='star_sk_v1_...'
export STARINTEL_SERVER_URL='https://starintel.example'
starintel-discord
```

Secrets are intentionally not accepted from TOML. `STARINTEL_DISCORD_TOKEN` and `STARINTEL_API_KEY` must come from the environment (or an infra-managed environment file/credential mechanism).

The default config uses:

```toml
[starintel]
default_dataset = "llm"
default_tenant_id = "llm"
dataset_hints = ["llm"]
```

`default_dataset` is the target-dispatch default. Search, `/document`, actor discovery, and `/radar` omit the dataset unless you supply one, so tenant `llm` can see the whole authorized auto-dig corpus. `dataset_hints` is informational; the StarIntel server decides which datasets the API key may access.

## Radar semantics

A radar is unique per Discord guild/channel. Re-running `/radar configure` replaces that channel's query and resets the checkpoint. By default, the first poll records current matching documents without posting them; only documents first observed after configuration are sent. This avoids dumping the historical corpus into a channel.

Radar state and Discord authorization are stored in SQLite (`state/starintel-discord.sqlite3` by default). Each radar is implemented as a mailbox-driven asyncio actor supervised by the bot; polling failures are isolated per radar.

## Pro actors

The fallback catalog is derived from `lost-rob0t/starintel-pro-actors` and includes collectors/enrichers such as `reddit`, `x`, `telegram`, `youtube`, `web`, `user-hunt`, `whats-my-name-user-hunt`, `generate-usernames`, and `username-targets`. `/actors` also looks for current `actor-manifest` documents in StarIntel, so deployed manifests can override the fallback metadata without a bot release.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check .
python -m compileall -q src tests
pytest -q
```

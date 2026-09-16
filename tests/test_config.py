from pathlib import Path

from starintel_discord.config import load_config


def test_defaults_are_llm_scoped(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[discord]\nowner_ids=[1]\n[starintel]\nbase_url='http://server:5000'\n")
    monkeypatch.setenv("STARINTEL_DISCORD_TOKEN", "discord-token")
    monkeypatch.setenv("STARINTEL_API_KEY", "star-key")
    config = load_config(path)
    assert config.starintel.default_dataset == "llm"
    assert config.starintel.default_tenant_id == "llm"
    assert config.discord.owner_ids == frozenset({1})

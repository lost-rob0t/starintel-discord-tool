from pathlib import Path

from starintel_discord.state import StateStore, document_key


def test_auth_and_radar_persist(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "state.sqlite3")
    state.add_authorized_user(100, 1)
    assert state.is_authorized(100)
    radar = state.upsert_radar(guild_id=1, channel_id=2, query="flock", dataset="llm", tenant_id="llm", source_dataset=None, created_by=100)
    assert radar.dataset == "llm"
    assert len(state.list_radars(1)) == 1
    docs = [{"_id": "one"}, {"_id": "two"}]
    assert state.remember_documents(radar.id, docs) == {"id:one", "id:two"}
    assert state.remember_documents(radar.id, docs) == set()
    state.close()


def test_document_key_falls_back_to_content_hash() -> None:
    assert document_key({"title": "x"}) == document_key({"title": "x"})

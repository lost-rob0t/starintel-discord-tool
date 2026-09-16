import pytest

from starintel_discord.client import StarIntelClient, StarIntelError


@pytest.mark.asyncio
async def test_authenticated_search_uses_canonical_document_contract() -> None:
    client = StarIntelClient("https://starintel.example", "test-key")
    calls = []

    async def fake_json(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {
            "total_rows": 2,
            "bookmark": "next-page",
            "rows": [
                {"doc": {"_id": "one", "dataset": "alpha"}},
                {"doc": {"_id": "two", "dataset": "beta"}},
            ],
        }

    client._json = fake_json
    try:
        result = await client.search("flock", tenant_id="llm", limit=20)
    finally:
        await client.close()

    assert calls == [
        (
            "GET",
            "/api/v1/documents/search",
            {"params": {"q": "flock", "limit": 20, "tenant": "llm"}},
        )
    ]
    assert [doc["_id"] for doc in result.documents] == ["one", "two"]
    assert result.count == 2
    assert result.bookmark == "next-page"


@pytest.mark.asyncio
async def test_authenticated_search_forwards_dataset_scope() -> None:
    client = StarIntelClient("https://starintel.example", "test-key")

    async def fake_json(_method, _path, **kwargs):
        assert kwargs["params"]["dataset"] == "ohio"
        assert kwargs["params"]["tenant"] == "llm"
        return {"rows": []}

    client._json = fake_json
    try:
        result = await client.search("columbus", dataset="ohio", tenant_id="llm")
    finally:
        await client.close()

    assert result.documents == ()


def test_search_body_requires_rows_or_documents() -> None:
    with pytest.raises(StarIntelError):
        StarIntelClient._documents_from_search_body({"total_rows": 0})

from starintel_discord.formatting import format_document_markdown, format_search_results, parse_metadata_json


def test_document_markdown_uses_canonical_auto_dig_fields() -> None:
    doc = {"_id": "starintel:test:1", "dataset": "llm", "dtype": "org", "date_updated": "2026-09-16T12:00:00Z", "title": "Example @ org", "summary": "Evidence `summary`", "sources": [{"url": "https://example.com/source"}]}
    output = format_document_markdown(doc)
    assert "### Example ＠ org" in output
    assert "`llm`" in output
    assert "`org`" in output
    assert "[source](https://example.com/source)" in output
    assert "`starintel:test:1`" in output


def test_search_output_is_bounded() -> None:
    docs = [{"_id": f"starintel:test:{index}", "title": "x" * 100} for index in range(30)]
    assert len(format_search_results(docs, total_count=30)) <= 1900


def test_metadata_parser_requires_object() -> None:
    assert parse_metadata_json('{"a": 1}') == {"a": 1}
    try:
        parse_metadata_json("[]")
    except ValueError as exc:
        assert "object" in str(exc)
    else:
        raise AssertionError("expected ValueError")

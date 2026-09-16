from __future__ import annotations

import json
from typing import Any, Iterable


def _string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first(document: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _string(document.get(key))
        if value:
            return value
    return None


def _source_url(document: dict[str, Any]) -> str | None:
    direct = _first(document, "url", "source_url", "canonical_url")
    if direct:
        return direct
    sources = document.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, str) and source.startswith(("http://", "https://")):
                return source
            if isinstance(source, dict):
                for key in ("url", "href", "uri"):
                    value = _string(source.get(key))
                    if value and value.startswith(("http://", "https://")):
                        return value
    return None


def _escape_markdown(text: str) -> str:
    return text.replace("`", "ˋ").replace("@", "＠")


def format_document_markdown(document: dict[str, Any], *, max_chars: int = 1900) -> str:
    title = _first(document, "title", "name") or _first(document, "_id", "id") or "StarIntel document"
    doc_id = _first(document, "_id", "id", "document_id", "uuid")
    dataset = _first(document, "dataset")
    dtype = _first(document, "dtype", "type", "kind")
    date = _first(document, "date_updated", "date_added", "published_at", "created_at", "date")
    summary = _first(document, "summary", "description", "text", "content", "body")
    url = _source_url(document)

    lines = [f"### {_escape_markdown(title)}"]
    meta: list[str] = []
    if dataset:
        meta.append(f"**dataset** `{_escape_markdown(dataset)}`")
    if dtype:
        meta.append(f"**type** `{_escape_markdown(dtype)}`")
    if date:
        meta.append(f"**date** `{_escape_markdown(date)}`")
    if meta:
        lines.append(" · ".join(meta))
    if summary:
        lines.extend(("", _escape_markdown(summary)))
    footer: list[str] = []
    if url:
        footer.append(f"[source]({url})")
    if doc_id:
        footer.append(f"`{_escape_markdown(doc_id)}`")
    if footer:
        lines.extend(("", " · ".join(footer)))

    output = "\n".join(lines)
    if len(output) <= max_chars:
        return output
    suffix = "\n\n… *(truncated)*"
    return output[: max_chars - len(suffix)].rstrip() + suffix


def format_search_results(documents: Iterable[dict[str, Any]], *, total_count: int) -> str:
    docs = list(documents)
    if not docs:
        return "No matching StarIntel documents."
    lines = [f"**StarIntel search:** {total_count} match(es)"]
    for index, doc in enumerate(docs, start=1):
        title = _first(doc, "title", "name", "_id", "id") or "untitled"
        doc_id = _first(doc, "_id", "id")
        dataset = _first(doc, "dataset")
        details = " · ".join(value for value in (dataset, doc_id) if value)
        line = f"{index}. **{_escape_markdown(title)}**"
        if details:
            line += f" — `{_escape_markdown(details)}`"
        lines.append(line)
    output = "\n".join(lines)
    return output if len(output) <= 1900 else output[:1880].rstrip() + "\n…"


def parse_metadata_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None or not raw.strip():
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object")
    return value

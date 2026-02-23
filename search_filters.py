from dataclasses import dataclass, field


@dataclass
class SearchFilters:
    query_text: str = ""
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    artist: str | None = None
    genre: str | None = None
    sort: str = "newest"
    limit: int = 25


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def parse_search_query(raw_query: str, *, default_limit: int = 25, max_limit: int = 50) -> SearchFilters:
    filters = SearchFilters(limit=default_limit)
    text_terms: list[str] = []
    tag_values: list[str] = []

    for token in raw_query.split():
        token = token.strip()
        if not token:
            continue

        lowered = token.lower()

        if lowered.startswith(("cat:", "category:", "type:")):
            value = token.split(":", 1)[1].strip().lower()
            if value in {"video", "music"}:
                filters.category = value
            continue

        if lowered.startswith(("tag:", "tags:")):
            value = token.split(":", 1)[1].strip()
            if value:
                tag_values.extend(value.split(","))
            continue

        if lowered.startswith(("lang:", "language:")):
            value = token.split(":", 1)[1].strip().lower()
            if value:
                filters.language = value
            continue

        if lowered.startswith("artist:"):
            value = token.split(":", 1)[1].strip()
            if value:
                filters.artist = value
            continue

        if lowered.startswith("genre:"):
            value = token.split(":", 1)[1].strip()
            if value:
                filters.genre = value
            continue

        if lowered.startswith("sort:"):
            value = token.split(":", 1)[1].strip().lower()
            if value in {"new", "newest", "desc"}:
                filters.sort = "newest"
            elif value in {"old", "oldest", "asc"}:
                filters.sort = "oldest"
            continue

        if lowered.startswith("limit:"):
            value = token.split(":", 1)[1].strip()
            try:
                parsed_limit = int(value)
                filters.limit = max(1, min(max_limit, parsed_limit))
            except ValueError:
                pass
            continue

        if token.startswith("#") and len(token) > 1:
            tag_values.append(token[1:])
            continue

        text_terms.append(token)

    filters.tags = _dedupe_keep_order(tag_values)
    filters.query_text = " ".join(text_terms).strip()
    return filters


def format_search_filters(filters: SearchFilters) -> str:
    parts: list[str] = []
    if filters.category:
        parts.append(f"cat={filters.category}")
    if filters.tags:
        parts.append(f"tags={','.join(filters.tags)}")
    if filters.language:
        parts.append(f"lang={filters.language}")
    if filters.artist:
        parts.append(f"artist={filters.artist}")
    if filters.genre:
        parts.append(f"genre={filters.genre}")
    if filters.sort:
        parts.append(f"sort={filters.sort}")
    if filters.limit:
        parts.append(f"limit={filters.limit}")
    return " | ".join(parts) if parts else "none"

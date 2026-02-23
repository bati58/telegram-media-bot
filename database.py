import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Optional

from config import ADMIN_IDS, MODERATOR_IDS, MONGODB_DB_NAME, MONGODB_URI

try:
    from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
    from pymongo.errors import DuplicateKeyError
except ImportError as exc:
    raise RuntimeError(
        "pymongo is required for MongoDB support. Install it with: pip install pymongo"
    ) from exc


VALID_ROLES = {"user", "moderator", "admin"}

_client = MongoClient(MONGODB_URI)
_db = _client[MONGODB_DB_NAME]
_users = _db["users"]
_content = _db["content"]
_counters = _db["counters"]
_audit_logs = _db["audit_logs"]
_favorites = _db["favorites"]
_playlists = _db["playlists"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_role_for_user(telegram_id: int) -> str:
    if telegram_id in ADMIN_IDS:
        return "admin"
    if telegram_id in MODERATOR_IDS:
        return "moderator"
    return "user"


def _seed_staff_roles() -> None:
    now = _utc_now_iso()

    for admin_id in ADMIN_IDS:
        user_id = int(admin_id)
        _users.update_one(
            {"telegram_id": user_id},
            {
                "$set": {"role": "admin"},
                "$setOnInsert": {
                    "telegram_id": user_id,
                    "join_date": now,
                },
            },
            upsert=True,
        )

    for moderator_id in MODERATOR_IDS:
        user_id = int(moderator_id)
        if user_id in ADMIN_IDS:
            continue
        _users.update_one(
            {"telegram_id": user_id},
            {
                "$set": {"role": "moderator"},
                "$setOnInsert": {
                    "telegram_id": user_id,
                    "join_date": now,
                },
            },
            upsert=True,
        )


def _sync_counter(counter_name: str, collection, field_name: str) -> None:
    latest_item = collection.find_one({}, {field_name: 1}, sort=[(field_name, DESCENDING)])
    max_id = (
        int(latest_item.get(field_name, 0))
        if latest_item and isinstance(latest_item.get(field_name), int)
        else 0
    )

    counter_doc = _counters.find_one({"_id": counter_name})
    if not counter_doc:
        _counters.insert_one({"_id": counter_name, "seq": max_id})
        return

    counter_seq = int(counter_doc.get("seq", 0))
    if counter_seq < max_id:
        _counters.update_one({"_id": counter_name}, {"$set": {"seq": max_id}})


def _next_counter(counter_name: str) -> int:
    counter = _counters.find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(counter["seq"])


def _normalize_tags(raw_tags: Any) -> list[str]:
    tags: list[str] = []

    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")

    if isinstance(raw_tags, (list, tuple, set)):
        for tag in raw_tags:
            normalized = str(tag).strip().lower()
            if normalized and normalized not in tags:
                tags.append(normalized)

    return tags


def _normalize_metadata(metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not metadata:
        return {}

    normalized: dict[str, Any] = {}

    for field in ("artist", "genre", "album", "language", "source"):
        value = metadata.get(field)
        if value is None:
            continue
        value_str = str(value).strip()
        if not value_str:
            continue
        if field == "language":
            value_str = value_str.lower()
        normalized[field] = value_str

    tags = _normalize_tags(metadata.get("tags"))
    if tags:
        normalized["tags"] = tags

    duration = metadata.get("duration")
    try:
        duration_int = int(duration)
        if duration_int > 0:
            normalized["duration"] = duration_int
    except (TypeError, ValueError):
        pass

    year = metadata.get("year")
    try:
        year_int = int(year)
        if 1900 <= year_int <= 2100:
            normalized["year"] = year_int
    except (TypeError, ValueError):
        pass

    return normalized


def init_db() -> None:
    _users.create_index([("telegram_id", ASCENDING)], unique=True)
    _users.create_index([("role", ASCENDING)])

    _content.create_index([("id", ASCENDING)], unique=True)
    _content.create_index([("category", ASCENDING)])
    _content.create_index([("title", ASCENDING)])
    _content.create_index([("upload_date", DESCENDING)])
    _content.create_index([("file_unique_id", ASCENDING)], unique=True, sparse=True)
    _content.create_index([("metadata.tags", ASCENDING)])
    _content.create_index([("metadata.language", ASCENDING)])

    _favorites.create_index([("user_id", ASCENDING), ("content_id", ASCENDING)], unique=True)
    _favorites.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])

    _playlists.create_index([("id", ASCENDING)], unique=True)
    _playlists.create_index([("user_id", ASCENDING)])
    _playlists.create_index([("user_id", ASCENDING), ("name_key", ASCENDING)], unique=True)

    _audit_logs.create_index([("timestamp", DESCENDING)])
    _audit_logs.create_index([("actor_id", ASCENDING)])
    _audit_logs.create_index([("action", ASCENDING)])

    _users.update_many({"role": {"$exists": False}}, {"$set": {"role": "user"}})
    _seed_staff_roles()

    _sync_counter("content_id", _content, "id")
    _sync_counter("playlist_id", _playlists, "id")


def add_user(telegram_id: int) -> None:
    user_id = int(telegram_id)
    desired_role = _default_role_for_user(user_id)

    _users.update_one(
        {"telegram_id": user_id},
        {
            "$setOnInsert": {
                "telegram_id": user_id,
                "join_date": _utc_now_iso(),
                "role": desired_role,
            }
        },
        upsert=True,
    )

    if desired_role != "user":
        _users.update_one({"telegram_id": user_id}, {"$set": {"role": desired_role}})


def add_content(
    title: str,
    category: str,
    file_id: str,
    *,
    file_unique_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    uploaded_by: Optional[int] = None,
) -> tuple[int, bool]:
    normalized_metadata = _normalize_metadata(metadata)

    if file_unique_id:
        existing = _content.find_one({"file_unique_id": file_unique_id}, {"id": 1, "metadata": 1})
        if existing:
            merged_metadata = dict(existing.get("metadata", {}))
            merged_metadata.update(normalized_metadata)

            _content.update_one(
                {"id": int(existing["id"])},
                {
                    "$set": {
                        "title": title,
                        "category": category,
                        "file_id": file_id,
                        "metadata": merged_metadata,
                        "updated_at": _utc_now_iso(),
                    }
                },
            )
            return int(existing["id"]), False

    content_id = _next_counter("content_id")
    payload: dict[str, Any] = {
        "id": content_id,
        "title": title,
        "category": category,
        "file_id": file_id,
        "upload_date": _utc_now_iso(),
        "metadata": normalized_metadata,
    }

    if file_unique_id:
        payload["file_unique_id"] = file_unique_id
    if uploaded_by is not None:
        payload["uploaded_by"] = int(uploaded_by)

    try:
        _content.insert_one(payload)
        return content_id, True
    except DuplicateKeyError:
        if file_unique_id:
            existing = _content.find_one({"file_unique_id": file_unique_id}, {"id": 1, "metadata": 1})
            if existing:
                merged_metadata = dict(existing.get("metadata", {}))
                merged_metadata.update(normalized_metadata)
                _content.update_one(
                    {"id": int(existing["id"])},
                    {
                        "$set": {
                            "title": title,
                            "category": category,
                            "file_id": file_id,
                            "metadata": merged_metadata,
                            "updated_at": _utc_now_iso(),
                        }
                    },
                )
                return int(existing["id"]), False

        content_id = _next_counter("content_id")
        payload["id"] = content_id
        _content.insert_one(payload)
        return content_id, True


def get_content_by_category(category: str, limit: Optional[int] = None, offset: int = 0):
    cursor = _content.find(
        {"category": category},
        {"_id": 0, "id": 1, "title": 1, "file_id": 1},
    ).sort("id", DESCENDING)

    if offset:
        cursor = cursor.skip(offset)
    if limit is not None:
        cursor = cursor.limit(limit)

    return [(int(doc["id"]), doc.get("title", ""), doc.get("file_id", "")) for doc in cursor]


def count_content_by_category(category: str) -> int:
    return _content.count_documents({"category": category})


def _build_search_query(
    *,
    query_text: str = "",
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    language: Optional[str] = None,
    artist: Optional[str] = None,
    genre: Optional[str] = None,
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []

    if category:
        clauses.append({"category": category})

    if language:
        clauses.append({"metadata.language": language.lower()})

    if tags:
        normalized_tags = _normalize_tags(tags)
        if normalized_tags:
            clauses.append({"metadata.tags": {"$all": normalized_tags}})

    if artist:
        clauses.append({"metadata.artist": {"$regex": re.escape(artist), "$options": "i"}})

    if genre:
        clauses.append({"metadata.genre": {"$regex": re.escape(genre), "$options": "i"}})

    if query_text:
        query_regex = {"$regex": re.escape(query_text.strip()), "$options": "i"}
        clauses.append(
            {
                "$or": [
                    {"title": query_regex},
                    {"metadata.artist": query_regex},
                    {"metadata.genre": query_regex},
                    {"metadata.tags": {"$elemMatch": query_regex}},
                ]
            }
        )

    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def search_content(query: str, limit: int = 20):
    return search_content_advanced(query_text=query, limit=limit)


def search_content_advanced(
    *,
    query_text: str = "",
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    language: Optional[str] = None,
    artist: Optional[str] = None,
    genre: Optional[str] = None,
    sort: str = "newest",
    limit: int = 20,
):
    mongo_query = _build_search_query(
        query_text=query_text,
        category=category,
        tags=tags,
        language=language,
        artist=artist,
        genre=genre,
    )

    sort_direction = DESCENDING if sort != "oldest" else ASCENDING
    cursor = (
        _content.find(
            mongo_query,
            {"_id": 0, "id": 1, "title": 1, "category": 1, "file_id": 1},
        )
        .sort("id", sort_direction)
        .limit(max(1, int(limit)))
    )

    return [
        (int(doc["id"]), doc.get("title", ""), doc.get("category", ""), doc.get("file_id", ""))
        for doc in cursor
    ]


def get_content_by_id(content_id: int):
    doc = _content.find_one(
        {"id": int(content_id)},
        {
            "_id": 0,
            "id": 1,
            "title": 1,
            "category": 1,
            "file_id": 1,
            "upload_date": 1,
            "metadata": 1,
        },
    )
    if not doc:
        return None

    return (
        int(doc["id"]),
        doc.get("title", ""),
        doc.get("category", ""),
        doc.get("file_id", ""),
        doc.get("upload_date", ""),
    )


def get_content_metadata(content_id: int) -> dict[str, Any]:
    doc = _content.find_one({"id": int(content_id)}, {"_id": 0, "metadata": 1})
    if not doc:
        return {}
    metadata = doc.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def get_recent_content(limit: int = 20, offset: int = 0, category: Optional[str] = None):
    query = {"category": category} if category else {}
    cursor = (
        _content.find(
            query,
            {"_id": 0, "id": 1, "title": 1, "category": 1, "upload_date": 1},
        )
        .sort("id", DESCENDING)
        .skip(max(0, int(offset)))
        .limit(max(1, int(limit)))
    )

    return [
        (int(doc["id"]), doc.get("title", ""), doc.get("category", ""), doc.get("upload_date", ""))
        for doc in cursor
    ]


def delete_content_by_id(content_id: int) -> bool:
    result = _content.delete_one({"id": int(content_id)})
    _favorites.delete_many({"content_id": int(content_id)})
    _playlists.update_many({}, {"$pull": {"item_ids": int(content_id)}})
    return result.deleted_count > 0


def add_favorite(user_id: int, content_id: int) -> bool:
    user_id = int(user_id)
    content_id = int(content_id)

    if not _content.find_one({"id": content_id}, {"_id": 1}):
        raise ValueError("Content not found")

    result = _favorites.update_one(
        {"user_id": user_id, "content_id": content_id},
        {"$setOnInsert": {"user_id": user_id, "content_id": content_id, "created_at": _utc_now_iso()}},
        upsert=True,
    )
    return result.upserted_id is not None


def remove_favorite(user_id: int, content_id: int) -> bool:
    result = _favorites.delete_one({"user_id": int(user_id), "content_id": int(content_id)})
    return result.deleted_count > 0


def list_favorites(user_id: int, limit: int = 30, offset: int = 0):
    pipeline = [
        {"$match": {"user_id": int(user_id)}},
        {"$sort": {"created_at": -1}},
        {"$skip": max(0, int(offset))},
        {"$limit": max(1, int(limit))},
        {
            "$lookup": {
                "from": "content",
                "localField": "content_id",
                "foreignField": "id",
                "as": "content",
            }
        },
        {"$unwind": "$content"},
        {
            "$project": {
                "_id": 0,
                "id": "$content.id",
                "title": "$content.title",
                "category": "$content.category",
                "file_id": "$content.file_id",
            }
        },
    ]

    items = list(_favorites.aggregate(pipeline))
    return [
        (int(item["id"]), item.get("title", ""), item.get("category", ""), item.get("file_id", ""))
        for item in items
    ]


def create_playlist(user_id: int, name: str) -> int:
    cleaned_name = str(name).strip()
    if not cleaned_name:
        raise ValueError("Playlist name cannot be empty")

    if len(cleaned_name) > 64:
        raise ValueError("Playlist name is too long (max 64 chars)")

    user_id = int(user_id)
    name_key = cleaned_name.lower()
    if _playlists.find_one({"user_id": user_id, "name_key": name_key}, {"_id": 1}):
        raise ValueError("Playlist with this name already exists")

    playlist_id = _next_counter("playlist_id")
    now = _utc_now_iso()
    _playlists.insert_one(
        {
            "id": playlist_id,
            "user_id": user_id,
            "name": cleaned_name,
            "name_key": name_key,
            "item_ids": [],
            "created_at": now,
            "updated_at": now,
        }
    )
    return playlist_id


def list_playlists(user_id: int, limit: int = 50, offset: int = 0):
    cursor = (
        _playlists.find(
            {"user_id": int(user_id)},
            {"_id": 0, "id": 1, "name": 1, "item_ids": 1},
        )
        .sort("updated_at", DESCENDING)
        .skip(max(0, int(offset)))
        .limit(max(1, int(limit)))
    )

    return [
        (int(doc["id"]), doc.get("name", "Unnamed"), len(doc.get("item_ids", [])))
        for doc in cursor
    ]


def get_playlist(user_id: int, playlist_id: int) -> Optional[dict[str, Any]]:
    return _playlists.find_one(
        {"user_id": int(user_id), "id": int(playlist_id)},
        {"_id": 0},
    )


def add_to_playlist(user_id: int, playlist_id: int, content_id: int) -> bool:
    user_id = int(user_id)
    playlist_id = int(playlist_id)
    content_id = int(content_id)

    if not _content.find_one({"id": content_id}, {"_id": 1}):
        raise ValueError("Content not found")

    result = _playlists.update_one(
        {"user_id": user_id, "id": playlist_id},
        {
            "$addToSet": {"item_ids": content_id},
            "$set": {"updated_at": _utc_now_iso()},
        },
    )

    if result.matched_count == 0:
        raise ValueError("Playlist not found")

    return result.modified_count > 0


def remove_from_playlist(user_id: int, playlist_id: int, content_id: int) -> bool:
    result = _playlists.update_one(
        {"user_id": int(user_id), "id": int(playlist_id)},
        {
            "$pull": {"item_ids": int(content_id)},
            "$set": {"updated_at": _utc_now_iso()},
        },
    )

    if result.matched_count == 0:
        raise ValueError("Playlist not found")

    return result.modified_count > 0


def list_playlist_items(user_id: int, playlist_id: int, limit: int = 100):
    playlist = get_playlist(user_id, playlist_id)
    if not playlist:
        raise ValueError("Playlist not found")

    item_ids = [int(item_id) for item_id in playlist.get("item_ids", [])]
    if not item_ids:
        return []

    content_docs = list(
        _content.find(
            {"id": {"$in": item_ids}},
            {"_id": 0, "id": 1, "title": 1, "category": 1, "file_id": 1},
        )
    )
    doc_map = {int(doc["id"]): doc for doc in content_docs}

    ordered_items = []
    for content_id in item_ids[: max(1, int(limit))]:
        doc = doc_map.get(content_id)
        if not doc:
            continue
        ordered_items.append(
            (int(doc["id"]), doc.get("title", ""), doc.get("category", ""), doc.get("file_id", ""))
        )

    return ordered_items


def delete_playlist(user_id: int, playlist_id: int) -> bool:
    result = _playlists.delete_one({"user_id": int(user_id), "id": int(playlist_id)})
    return result.deleted_count > 0


def log_audit_event(
    *,
    actor_id: int,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
    severity: str = "info",
) -> None:
    payload = {
        "timestamp": _utc_now_iso(),
        "actor_id": int(actor_id),
        "action": action,
        "severity": severity,
        "target_type": target_type,
        "target_id": int(target_id) if target_id is not None else None,
        "details": details or {},
    }
    _audit_logs.insert_one(payload)


def get_recent_audit_logs(limit: int = 20):
    cursor = (
        _audit_logs.find(
            {},
            {
                "_id": 0,
                "timestamp": 1,
                "actor_id": 1,
                "action": 1,
                "severity": 1,
                "target_type": 1,
                "target_id": 1,
                "details": 1,
            },
        )
        .sort("timestamp", DESCENDING)
        .limit(max(1, int(limit)))
    )
    return list(cursor)


def get_user_role(telegram_id: int) -> str:
    user_id = int(telegram_id)
    if user_id in ADMIN_IDS:
        return "admin"

    doc = _users.find_one({"telegram_id": user_id}, {"_id": 0, "role": 1})
    role = str(doc.get("role", "user")) if doc else "user"
    if role not in VALID_ROLES:
        return "user"

    if role == "admin":
        return "user"
    return role


def is_admin_user(telegram_id: int) -> bool:
    return get_user_role(telegram_id) == "admin"


def is_moderator_user(telegram_id: int) -> bool:
    return get_user_role(telegram_id) in {"admin", "moderator"}


def set_user_role(telegram_id: int, role: str) -> bool:
    user_id = int(telegram_id)
    normalized_role = role.strip().lower()

    if normalized_role not in VALID_ROLES:
        raise ValueError(f"Unsupported role: {role}")

    if normalized_role == "admin" and user_id not in ADMIN_IDS:
        raise ValueError("Admin role is controlled by ADMIN_IDS in environment config.")

    if user_id in ADMIN_IDS and normalized_role != "admin":
        raise ValueError("Cannot change role for configured admin users.")

    _users.update_one(
        {"telegram_id": user_id},
        {
            "$set": {"role": normalized_role},
            "$setOnInsert": {
                "telegram_id": user_id,
                "join_date": _utc_now_iso(),
            },
        },
        upsert=True,
    )
    return True


def get_total_users() -> int:
    return _users.count_documents({})


def get_total_content() -> int:
    return _content.count_documents({})


def get_content_totals_by_category() -> dict[str, int]:
    pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}]
    results = _content.aggregate(pipeline)
    return {str(item["_id"]): int(item["count"]) for item in results if item.get("_id")}


def get_user_counts_by_role() -> dict[str, int]:
    counts = {"user": 0, "moderator": 0, "admin": 0}
    pipeline = [{"$group": {"_id": "$role", "count": {"$sum": 1}}}]
    for item in _users.aggregate(pipeline):
        role = str(item.get("_id", "user"))
        if role in counts:
            counts[role] = int(item.get("count", 0))

    counts["admin"] = max(counts["admin"], len(ADMIN_IDS))
    return counts


def get_collection_counts() -> dict[str, int]:
    return {
        "users": _users.count_documents({}),
        "content": _content.count_documents({}),
        "counters": _counters.count_documents({}),
        "favorites": _favorites.count_documents({}),
        "playlists": _playlists.count_documents({}),
        "audit_logs": _audit_logs.count_documents({}),
    }


def get_health_snapshot() -> dict[str, object]:
    start_time = perf_counter()
    try:
        _client.admin.command("ping")
        latency_ms = round((perf_counter() - start_time) * 1000, 2)
        return {
            "ok": True,
            "db_name": MONGODB_DB_NAME,
            "latency_ms": latency_ms,
            "collections": get_collection_counts(),
            "roles": get_user_counts_by_role(),
        }
    except Exception as exc:
        return {
            "ok": False,
            "db_name": MONGODB_DB_NAME,
            "error": str(exc),
        }


def get_backup_payload() -> dict[str, object]:
    users = list(_users.find({}, {"_id": 0}).sort("telegram_id", ASCENDING))
    content = list(_content.find({}, {"_id": 0}).sort("id", ASCENDING))
    counters = list(_counters.find({}, {"_id": 0}))
    favorites = list(_favorites.find({}, {"_id": 0}).sort("created_at", DESCENDING))
    playlists = list(_playlists.find({}, {"_id": 0}).sort("id", ASCENDING))

    return {
        "generated_at": _utc_now_iso(),
        "db_name": MONGODB_DB_NAME,
        "users": users,
        "content": content,
        "counters": counters,
        "favorites": favorites,
        "playlists": playlists,
    }


def get_all_users() -> list[int]:
    cursor = _users.find({}, {"_id": 0, "telegram_id": 1})
    return [int(doc["telegram_id"]) for doc in cursor if "telegram_id" in doc]

import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Optional

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


def _sync_content_counter() -> None:
    latest_content = _content.find_one({}, {"id": 1}, sort=[("id", DESCENDING)])
    max_content_id = (
        int(latest_content.get("id", 0))
        if latest_content and isinstance(latest_content.get("id"), int)
        else 0
    )

    counter_doc = _counters.find_one({"_id": "content_id"})
    if not counter_doc:
        _counters.insert_one({"_id": "content_id", "seq": max_content_id})
        return

    counter_seq = int(counter_doc.get("seq", 0))
    if counter_seq < max_content_id:
        _counters.update_one({"_id": "content_id"}, {"$set": {"seq": max_content_id}})


def _next_content_id() -> int:
    counter = _counters.find_one_and_update(
        {"_id": "content_id"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(counter["seq"])


def init_db() -> None:
    _users.create_index([("telegram_id", ASCENDING)], unique=True)
    _users.create_index([("role", ASCENDING)])
    _content.create_index([("id", ASCENDING)], unique=True)
    _content.create_index([("category", ASCENDING)])
    _content.create_index([("title", ASCENDING)])
    _content.create_index([("upload_date", DESCENDING)])

    _users.update_many({"role": {"$exists": False}}, {"$set": {"role": "user"}})
    _seed_staff_roles()
    _sync_content_counter()


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


def add_content(title: str, category: str, file_id: str) -> int:
    content_id = _next_content_id()
    payload = {
        "id": content_id,
        "title": title,
        "category": category,
        "file_id": file_id,
        "upload_date": _utc_now_iso(),
    }

    try:
        _content.insert_one(payload)
        return content_id
    except DuplicateKeyError:
        content_id = _next_content_id()
        payload["id"] = content_id
        _content.insert_one(payload)
        return content_id


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


def search_content(query: str, limit: int = 20):
    query = query.strip()
    if not query:
        return []

    cursor = (
        _content.find(
            {"title": {"$regex": re.escape(query), "$options": "i"}},
            {"_id": 0, "id": 1, "title": 1, "category": 1, "file_id": 1},
        )
        .sort("id", DESCENDING)
        .limit(max(1, int(limit)))
    )

    return [
        (int(doc["id"]), doc.get("title", ""), doc.get("category", ""), doc.get("file_id", ""))
        for doc in cursor
    ]


def get_content_by_id(content_id: int):
    doc = _content.find_one(
        {"id": int(content_id)},
        {"_id": 0, "id": 1, "title": 1, "category": 1, "file_id": 1, "upload_date": 1},
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
    return result.deleted_count > 0


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

    return {
        "generated_at": _utc_now_iso(),
        "db_name": MONGODB_DB_NAME,
        "users": users,
        "content": content,
        "counters": counters,
    }


def get_all_users() -> list[int]:
    cursor = _users.find({}, {"_id": 0, "telegram_id": 1})
    return [int(doc["telegram_id"]) for doc in cursor if "telegram_id" in doc]

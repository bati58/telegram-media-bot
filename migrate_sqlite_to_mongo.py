import os
import sqlite3
from pathlib import Path

from pymongo import ASCENDING, MongoClient


def load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def main() -> None:
    load_dotenv_if_present()

    sqlite_path = os.getenv("SQLITE_PATH", "bot.db")
    mongo_uri = os.getenv("MONGODB_URI")
    mongo_db_name = os.getenv("MONGODB_DB_NAME", "telegram_media_bot")

    if not mongo_uri:
        raise RuntimeError("MONGODB_URI is required to run migration.")

    if not Path(sqlite_path).exists():
        raise RuntimeError(f"SQLite file not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()

    sqlite_cursor.execute("SELECT telegram_id, join_date FROM users")
    users = sqlite_cursor.fetchall()

    sqlite_cursor.execute("SELECT id, title, category, file_id, upload_date FROM content")
    content = sqlite_cursor.fetchall()

    sqlite_conn.close()

    client = MongoClient(mongo_uri)
    db = client[mongo_db_name]
    users_col = db["users"]
    content_col = db["content"]
    counters_col = db["counters"]

    users_col.create_index([("telegram_id", ASCENDING)], unique=True)
    users_col.create_index([("role", ASCENDING)])
    content_col.create_index([("id", ASCENDING)], unique=True)
    content_col.create_index([("category", ASCENDING)])
    content_col.create_index([("title", ASCENDING)])

    for telegram_id, join_date in users:
        users_col.update_one(
            {"telegram_id": int(telegram_id)},
            {
                "$setOnInsert": {
                    "telegram_id": int(telegram_id),
                    "join_date": join_date,
                    "role": "user",
                }
            },
            upsert=True,
        )

    max_content_id = 0
    for content_id, title, category, file_id, upload_date in content:
        content_id = int(content_id)
        max_content_id = max(max_content_id, content_id)
        content_col.update_one(
            {"id": content_id},
            {
                "$set": {
                    "id": content_id,
                    "title": title,
                    "category": category,
                    "file_id": file_id,
                    "upload_date": upload_date,
                }
            },
            upsert=True,
        )

    counter_doc = counters_col.find_one({"_id": "content_id"})
    if not counter_doc:
        counters_col.insert_one({"_id": "content_id", "seq": max_content_id})
    else:
        current_seq = int(counter_doc.get("seq", 0))
        if current_seq < max_content_id:
            counters_col.update_one({"_id": "content_id"}, {"$set": {"seq": max_content_id}})

    print(f"Migrated users: {len(users)}")
    print(f"Migrated content: {len(content)}")
    print(f"MongoDB database: {mongo_db_name}")


if __name__ == "__main__":
    main()

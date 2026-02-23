# Telegram Media Bot

Professional Telegram bot for sharing videos and music with role-based management, MongoDB Atlas storage, and operational tools.

## Features

- User media library browsing by category (`Videos`, `Music`)
- Advanced search with filters (`cat:`, `tag:`, `lang:`, `artist:`, `genre:`, `sort:`, `limit:`)
- Media delivery by Telegram `file_id` (fast and storage-efficient)
- Channel membership gate before content access
- Favorites and playlists (create/list/add/remove/delete)
- Upload deduplication by Telegram `file_unique_id`
- Rich media metadata (artist, genre, tags, language, year, duration)
- Role system:
  - `user`
  - `moderator`
  - `admin`
- Admin tools:
  - Add media (`/addvideo`, `/addmusic`)
  - Broadcast messages (`/broadcast`)
  - Health report (`/health`)
  - Export backup (`/export_content`)
  - Manage moderators (`/setmoderator`, `/removemoderator`)
  - Audit trail view (`/audit`)
- Staff tools (`moderator` + `admin`):
  - Stats (`/stats`)
  - Content listing (`/listcontent`)
  - Content deletion (`/delete`)
- Global anti-spam rate limiting middleware
- Audit logging for admin/staff/user actions
- Structured error logging middleware
- Periodic JSON backups
- Optional SQLite -> MongoDB migration script

## Tech Stack

- Python 3.11+
- [aiogram 3](https://docs.aiogram.dev/)
- MongoDB Atlas + PyMongo

## Project Structure

```text
bot.py
config.py
database.py
utils.py
runtime_state.py
keyboards.py
migrate_sqlite_to_mongo.py
handlers/
middlewares/
```

## Setup

1. Create virtual environment

```bash
python -m venv venv
```

2. Activate

Windows (PowerShell):

```powershell
venv\Scripts\Activate.ps1
```

3. Install dependencies

```bash
pip install aiogram pymongo
```

4. Create `.env` from `.env.example` and fill values.

## Environment Variables

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=7048929478
MODERATOR_IDS=
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/?retryWrites=true&w=majority&appName=<app-name>
MONGODB_DB_NAME=telegram_media_bot
REQUIRED_CHANNELS=@your_public_channel
ENABLE_PERIODIC_BACKUP=true
BACKUP_INTERVAL_MINUTES=60
BACKUP_DIRECTORY=backups
RATE_LIMIT_WINDOW_SECONDS=15
RATE_LIMIT_MAX_EVENTS=12
RATE_LIMIT_EXEMPT_STAFF=true
```

Notes:

- `ADMIN_IDS` and `MODERATOR_IDS` accept comma-separated Telegram numeric IDs.
- `REQUIRED_CHANNELS` accepts comma-separated channel/group usernames (example: `@ChannelA,@GroupB`).
- Bot should be in required chats (preferably admin) for reliable membership checks.

## Run

```bash
python bot.py
```

## Migration (Optional)

If you still have legacy SQLite data in `bot.db`, migrate to MongoDB:

```bash
python migrate_sqlite_to_mongo.py
```

## Useful Commands

### User

- `/start`
- `/help`
- `/myid`
- `/search [query]`
- `/cancel`
- `/favorites`
- `/favorite <content_id>`
- `/unfavorite <content_id>`
- `/playlists`
- `/createplaylist <name>`
- `/playlist <playlist_id>`
- `/addtoplaylist <playlist_id> <content_id>`
- `/removefromplaylist <playlist_id> <content_id>`
- `/deleteplaylist <playlist_id>`

### Moderator + Admin

- `/stats`
- `/listcontent [video|music] [page]`
- `/delete <id>`

### Admin

- `/admin`
- `/addvideo`
- `/addmusic`
- `/broadcast`
- `/health`
- `/setmoderator <id>`
- `/removemoderator <id>`
- `/export_content`
- `/audit [n]`

## MongoDB Compass

Use your `MONGODB_URI` in Compass to inspect collections:

- `users`
- `content`
- `counters`
- `favorites`
- `playlists`
- `audit_logs`

## Search Syntax

Examples:

- `/search hello`
- `/search cat:music artist:adele`
- `/search #gospel lang:en sort:newest limit:20`

## Security

- Never commit `.env`
- Rotate token immediately if leaked
- Keep `ADMIN_IDS` minimal

## License

Use or adapt for your own projects.

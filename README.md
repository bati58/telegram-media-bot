# Telegram Media Bot

Professional Telegram bot for sharing videos and music with role-based management, MongoDB Atlas storage, and operational tools.

## Features

- User media library browsing by category (`Videos`, `Music`)
- Search by title with clickable results
- Media delivery by Telegram `file_id` (fast and storage-efficient)
- Channel membership gate before content access
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
- Staff tools (`moderator` + `admin`):
  - Stats (`/stats`)
  - Content listing (`/listcontent`)
  - Content deletion (`/delete`)
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
- `/search`
- `/cancel`

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

## MongoDB Compass

Use your `MONGODB_URI` in Compass to inspect collections:

- `users`
- `content`
- `counters`

## Security

- Never commit `.env`
- Rotate token immediately if leaked
- Keep `ADMIN_IDS` minimal

## License

Use or adapt for your own projects.

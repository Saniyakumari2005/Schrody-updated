# Schrödy Discord Bot

## Overview

Schrödy is an AI-powered tutoring Discord bot built for the BeyondQuantum educational programme by ThinkingBeyond. It uses Google's Gemini API (via the `google-generativeai` library) to provide Socratic tutoring sessions, primarily focused on physics and quantum mechanics. The bot creates dedicated Discord threads for tutoring sessions, tracks conversations, collects feedback, and includes a task reminder system integrated with Google Sheets.

The bot is designed to be deployed on Railway (or similar cloud platforms) and uses MongoDB for persistent data storage with a privacy-focused architecture that separates user identity from conversation data.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Bot Framework
- **Framework:** discord.py 2.0+ with slash commands (`app_commands`)
- **Pattern:** Cog-based architecture — each feature area is a separate cog in the `cogs/` directory
- **Entry point:** `bot.py` defines the `Schrody` class extending `commands.Bot`, loads cogs in `setup_hook()`
- **Cogs:**
  - `cogs/tutor.py` — Core tutoring functionality (start/end/resume sessions, message handling, consent flow)
  - `cogs/feedback.py` — Feedback collection with hourly reminder loop
  - `cogs/database.py` — Admin-only database health/status commands
  - `cogs/general.py` — Simple utility commands (ping)
  - `cogs/reminder.py` — Task reminder system using APScheduler, integrated with Google Sheets

### AI Tutoring Engine
- **File:** `learnlm.py` — Wraps Google's Gemini API (`google-generativeai` library)
- **Model:** Configurable via `GEMINI_MODEL` env var, defaults to `gemini-2.5-flash`
- **Pedagogy:** Socratic method with strict constraints (5-sentence max responses, no LaTeX, always ends with a question)
- **Session context:** Conversation history maintained per-user in `sessions.py` and persisted as JSON files in `sessions/` directory

### Session Management
- **File:** `sessions.py` — `UserSession` class tracks per-user state (conversation history, activity timestamps)
- **Session manager:** Global `session_manager` handles multi-user sessions within Discord threads
- **Persistence:** Conversations saved both to MongoDB and local JSON files in `sessions/` directory
- **Features:** Message deduplication, inactive session detection, guest participation handling

### Database Layer
- **Technology:** MongoDB via `pymongo`
- **File:** `db.py` — Central database module
- **Privacy architecture:** Two separate databases:
  - **Main operational database** (`MONGO_DB`): Stores conversations, messages, sessions, feedback using anonymous IDs
  - **Identity database** (`MONGO_IDENTITY_DB`): Maps Discord IDs to anonymous IDs, kept separate for privacy
- **Collections:** `users`, `messages`, `sessions`, `feedback`, `conversations`, `audit_logs` (main DB); `identity_mapping`, `access_logs`, `system_config` (identity DB)
- **Privacy:** Uses salted hashing (`PRIVACY_SALT`) for anonymization

### Task Reminder System
- **Files:** `sheets.py`, `button.py`, `cogs/reminder.py`
- **Integration:** Reads tasks from a Google Sheets spreadsheet ("discord bot reminder")
- **Scheduling:** APScheduler (`AsyncIOScheduler`) for timed reminders
- **UI:** Discord button components (`ReminderView`) for marking tasks done or rescheduling
- **Auth:** Google OAuth2 with credentials stored in environment variables (`GOOGLE_TOKEN`)

### Configuration
- **File:** `config.py` — Centralizes environment variable loading
- **Environment variables required:**
  - `DISCORD_TOKEN` — Bot token
  - `MONGO_URL` — MongoDB connection string
  - `MONGO_DB` — Main database name
  - `MONGO_IDENTITY_DB` — Identity database name
  - `GEMINI_API_KEY` — Google Gemini API key
  - `GEMINI_MODEL` — Model name (optional, defaults to `gemini-2.5-flash`)
  - `PRIVACY_SALT` — Salt for anonymization (auto-generated if not set)
  - `GOOGLE_TOKEN` — Google OAuth token JSON for Sheets integration
  - `DATABASE_URL` — Additional database URL (in config.py)

### Note on config.py
There is a syntax error in `config.py` — variable names contain spaces (`GEMINI API KEY` and `GEMINI MODEL`) which is invalid Python. These should be `GEMINI_API_KEY` and `GEMINI_MODEL`.

## External Dependencies

### Core Services
- **Discord API** — Bot platform via `discord.py>=2.0.0`
- **MongoDB** — Primary data store via `pymongo`, requires `MONGO_URL` connection string
- **Google Gemini API** — AI tutoring engine via `google-generativeai`, requires `GEMINI_API_KEY`

### Integrations
- **Google Sheets API** — Task/reminder data source via `gspread` and `oauth2client`
- **Google Drive API** — Used alongside Sheets for spreadsheet access

### Python Packages
- `discord.py>=2.0.0` — Discord bot framework
- `pymongo` — MongoDB driver
- `google-generativeai` — Gemini API client
- `python-dotenv` — Environment variable management
- `aiohttp>=3.8.0` — Async HTTP client
- `PyNaCl` — Voice support / encryption for Discord
- `gspread==6.1.4` — Google Sheets API wrapper
- `APScheduler==3.11.0` — Task scheduling for reminders
- `oauth2client==4.1.3` — Google OAuth2 authentication
- `pandas==2.2.3` — Data manipulation for spreadsheet data
- `pytz` — Timezone handling

### Deployment
- Designed for **Railway** deployment (logging configured for console output)
- All secrets managed via environment variables / `.env` file
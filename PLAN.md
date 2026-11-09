# Recipe Bot — Build Plan

2026-11-09 · Oliver

A Discord bot that turns TikTok and Instagram recipe videos into clean, structured recipes. Someone shares a video link into a Discord channel. The bot downloads it, reads the caption, transcribes the audio, and looks at frames for on-screen text. Then Claude writes a real recipe with amounts and steps. Recipes are saved per server so everyone can search them later.

> **For Claude Code:** Build this one milestone at a time (see Milestones). After each milestone, stop, summarize what was built and how to test it, and wait for review before starting the next one. Ask before adding dependencies not listed here.

## 1. Goals

- **Two-tap capture:** Share button in TikTok/Instagram → Discord → `#recipes` channel → recipe appears in under ~2 minutes.
- **Honest recipes:** Real quantities wherever the video gives them. Clearly marked estimates where it doesn't.
- **Multi-user:** Works for anyone in any server the bot is in. Each server has its own recipe library, and each recipe remembers who saved it.
- **Runs on a Raspberry Pi 5 (4GB)**, and also runs locally on macOS for development.

**Non-goals (for now)**

- No public website. Recipes stay inside Discord and the bot's database.
- No storing the original videos. Media is deleted after processing.
- No YouTube support in v1 (easy to add later, since `yt-dlp` already handles it).

## 2. Multi-user model

Anyone in a server can add recipes. Each server keeps its own library, and usage limits stop one busy server from burning through the Claude budget.

| Concept | Behavior |
|---|---|
| Servers (guilds) | Each server has its own recipe library. Recipes from one server are never visible in another. |
| Recipe channel | A server admin runs `/setup channel #recipes`. The bot auto-processes links posted there. Anywhere else, people use `/recipe add <url>`. |
| Submitter | Every recipe stores the Discord user ID of who added it. `/recipes mine` lists your own. |
| Deleting | The submitter or anyone with Manage Server permission can delete a recipe. |
| Duplicates | If the same normalized video URL was already processed in that server, reply with the existing recipe instead of re-processing. |
| Fair use | Per-user daily limit (default 15 videos/day, configurable). One job queue so the Pi processes 1 video at a time (configurable). The bot tells people their place in the queue. |
| Cost | Every video costs one Claude call. With `claude_cli` it comes out of the owner's monthly subscription credit for headless use. With `api` it's a few cents of API usage. Log usage per job (see section 6a). |

## 3. Pipeline

Every link goes through the same eight steps. Two checks run before a job is queued.

**Before queuing**

1. Detect and normalize the URL (TikTok / Instagram).
2. Dedupe check (server + normalized URL). Already exists → reply with the saved recipe.
3. Rate-limit check (user's daily cap). Over the limit → polite reply.
4. Enqueue the job and react ⏳ on the message.

**The worker** (blocking work runs in threads)

1. **Download:** `yt-dlp` → video file + metadata (caption/description, creator, title, duration).
2. **Audio:** `ffmpeg` → 16kHz mono wav.
3. **Transcribe:** `faster-whisper` → transcript. Skip gracefully if there's no speech.
4. **Frames:** `ffmpeg` → 1 frame every 2s, max 20, resized to ~768px wide, near-duplicates dropped.
5. **Extract:** Claude through the configured backend (`claude_cli` or `api`): caption + transcript + frames → Recipe JSON.
6. **Save:** SQLite.
7. **Reply:** Discord embed, plus a `.md` attachment if it's too long for an embed.
8. **Clean up:** delete the temp dir, then react ✅ (or ❌ with a short reason).

**Platform notes**

- **TikTok:** `yt-dlp` usually works without login. Captions are short, so the transcript does most of the work.
- **Instagram:** Reels often require login. Support an optional cookies file (`IG_COOKIES_PATH`, Netscape format) exported from a **dedicated throwaway account**, never someone's personal account. Instagram captions often hold the full recipe, so weigh the caption heavily.
- **"Comment RECIPE for the link" posts:** The recipe isn't in the video or caption. Claude does its best from the visuals, sets `confidence: "low"`, and explains why in a note.
- **Breakage:** `yt-dlp` breaks when platforms change. On download failure, reply with a friendly message and log the full error. The README explains how to update it (`pip install -U yt-dlp`). Check for updates on startup and log a warning if outdated.
- Reject videos longer than `MAX_VIDEO_SECONDS` (default 600).

## 4. Tech stack

Python 3.11+, because every piece the bot needs is a Python library.

| Piece | Used for |
|---|---|
| `discord.py` | Bot, slash commands (`app_commands`), cogs |
| `yt-dlp` | Downloading videos. Use the Python API, not a subprocess |
| `ffmpeg` | Audio + frames. System binary, called via `asyncio.create_subprocess_exec` |
| `faster-whisper` | Transcription. CPU, `int8`. Default model `base`, try `small` if accuracy is poor |
| Claude Code CLI (`claude`) | Default `claude_cli` backend, signed in with the owner's subscription |
| `anthropic` SDK | Optional `api` backend (model via `CLAUDE_MODEL`, e.g. `claude-sonnet-5-5`) |
| `pydantic` v2 | Recipe schema + validation |
| `aiosqlite` | Storage |
| `python-dotenv` | Config |
| `pytest` + `pytest-asyncio` | Tests |

**Important:** discord.py is async, but yt-dlp and faster-whisper block. Run them with `asyncio.to_thread` (or a dedicated worker) so the bot never blocks its event loop and drops its Discord connection.

## 5. Project structure

All Claude-specific code lives in `pipeline/extract/`, so the rest of the bot doesn't care which backend is running.

```
recipe-bot/
├── PLAN.md
├── README.md                 # setup, Discord app creation, running, deploying to Pi
├── requirements.txt
├── .env.example
├── recipe_bot/
│   ├── __main__.py           # entry point: python -m recipe_bot
│   ├── config.py             # loads + validates env vars
│   ├── bot.py                # Bot subclass, intents, cog loading, command sync
│   ├── cogs/
│   │   ├── capture.py        # link detection in the recipe channel, /recipe add
│   │   ├── library.py        # /recipes search|mine|recent|random, /recipe show|delete
│   │   └── admin.py          # /setup channel, /setup limits, /status
│   ├── pipeline/
│   │   ├── urls.py           # detect + normalize TikTok/IG URLs
│   │   ├── download.py       # yt-dlp wrapper → (video_path, metadata)
│   │   ├── media.py          # ffmpeg audio + frame extraction, frame dedupe
│   │   ├── transcribe.py     # faster-whisper, model loaded once and reused
│   │   ├── extract/
│   │   │   ├── __init__.py   # get_backend(config) → picks backend from CLAUDE_BACKEND
│   │   │   ├── base.py       # ExtractionBackend interface + shared validate/retry logic
│   │   │   ├── prompt.py     # system prompt + input assembly, shared by both backends
│   │   │   ├── cli_backend.py   # claude -p subprocess (subscription)
│   │   │   └── api_backend.py   # anthropic SDK (API key)
│   │   └── queue.py          # job queue, worker(s), position tracking
│   ├── models.py             # pydantic Recipe, Ingredient, Step
│   ├── render.py             # Recipe → Discord embed(s) and → Markdown
│   └── db.py                 # schema, migrations, queries
├── tests/
│   ├── test_urls.py
│   ├── test_render.py
│   ├── test_extract_cli.py   # fake subprocess with recorded output
│   ├── test_extract_api.py   # mocked Anthropic client
│   └── fixtures/             # sample transcripts, captions, a tiny test video
└── deploy/
    └── recipe-bot.service    # systemd unit for the Pi
```

## 6. Recipe schema

Both backends return the same validated `Recipe` object.

```
class Ingredient(BaseModel):
    item: str                    # "soy sauce"
    quantity: str | None         # "2", "1/2", "a pinch"
    unit: str | None             # "tbsp", "g", None
    estimated: bool              # True if the video didn't state the amount
    note: str | None             # "low sodium", "divided"
    group: str | None            # "Sauce", "Marinade" — for recipes with components

class Step(BaseModel):
    number: int
    text: str
    duration_minutes: int | None # if a time is given or clearly implied

class Recipe(BaseModel):
    title: str
    description: str             # 1–2 sentences
    servings: str | None
    prep_minutes: int | None
    cook_minutes: int | None
    ingredients: list[Ingredient]
    steps: list[Step]
    equipment: list[str]
    tips: list[str]              # creator tips worth keeping
    tags: list[str]              # "chicken", "air fryer", "vegetarian", "dessert"...
    confidence: Literal["high", "medium", "low"]
    confidence_note: str | None  # why it's not high, e.g. "recipe was gated behind a DM"
    is_recipe: bool              # False if the video isn't actually a recipe
```

**Extraction approach (shared by both backends)**

- Inputs, in order: the caption/description, the transcript (or "no speech detected"), then the frames, labeled with timestamps.
- The output is always validated with pydantic. On failure, retry once with the validation error included. If it fails again, the job fails with a friendly message.
- System prompt guidance:
  - Combine all three sources. On-screen text and the caption usually have the most precise amounts; the transcript usually has the order and technique.
  - When an amount isn't given, estimate a sensible one for the stated servings and set `estimated: true`. Never invent ingredients that aren't shown or mentioned.
  - Use US units by default, keeping metric if that's what the creator used.
  - Write steps as clear, standalone instructions (not "like I said earlier").
  - If the video isn't a recipe, set `is_recipe: false` and keep the rest minimal.
- Log usage per job: token counts from the API backend, and whatever usage/cost fields the CLI's JSON output includes.

## 6a. Claude backends

One setting switches between the owner's subscription (`CLAUDE_BACKEND=claude_cli`, the default) and an API key (`CLAUDE_BACKEND=api`). Everything outside `pipeline/extract/` is identical either way.

```
class ExtractionBackend(Protocol):
    async def extract(self, caption: str, transcript: str | None,
                      frames: list[Path], metadata: VideoMeta) -> ExtractionResult: ...
# ExtractionResult = Recipe + usage info (tokens/cost if available) + raw output for logging
```

|  | `claude_cli` (default) | `api` |
|---|---|---|
| How it calls Claude | `claude -p` subprocess on the Pi | `anthropic.AsyncAnthropic` |
| Signs in with | `CLAUDE_CODE_OAUTH_TOKEN` (owner's Pro/Max subscription) | `ANTHROPIC_API_KEY` |
| Billed to | Monthly Agent SDK credit for headless use | Pay-per-use API billing |
| Frames sent as | Image files in the job folder, read by Claude | Base64 image content blocks |
| Structured output | JSON in the reply, parsed + validated | Forced tool call with the Recipe schema |
| Best for | The owner's personal use and testing | Sharing widely or heavy use |

### `claude_cli`: Claude Code headless mode

- Run `claude -p` with `asyncio.create_subprocess_exec`. Never use `shell=True`. Pass the prompt via stdin or an argument list.
- Working directory = the job's temp dir. It holds the frame images and a `context.md` with caption, transcript and metadata.
- Flags (confirm exact names with `claude --help` for the installed version):
  - `--output-format json`: parse the wrapper object and take the model's final text from it.
  - Read-only tools only (`--allowedTools Read`), so Claude can view the frames and `context.md` and nothing else: no Bash, no Edit, no web.
  - A low max-turns limit.
  - `--model` only if `CLAUDE_MODEL` is set.
- Prompt: the shared system prompt + "Read context.md and the frame images frame_*.jpg in this folder. Respond with ONLY a JSON object matching this schema: …" (include `Recipe.model_json_schema()`).
- Parse: strip any code fences, `json.loads`, validate with pydantic, retry once on failure (shared logic in `base.py`).
- Timeout: `CLAUDE_CLI_TIMEOUT_SECONDS` (default 180). Kill the process on timeout.
- **Auth:** the bot's environment must have `CLAUDE_CODE_OAUTH_TOKEN` (made on the Mac with `claude setup-token`) and must **not** have `ANTHROPIC_API_KEY`. Otherwise the CLI uses the API key and bills API usage. On startup, if `CLAUDE_BACKEND=claude_cli` and `ANTHROPIC_API_KEY` is set, log a loud warning.
- **Startup check:** run `claude --version`. If it's missing or not signed in, fail fast with a clear message.
- **Usage note (put this in the README):** headless `claude -p` use on Pro/Max plans draws from a separate monthly Agent SDK credit, not the interactive limits. Subscription limits assume ordinary individual use. Switch to `api` if the bot gets shared widely or used heavily. Check current Anthropic docs and your usage settings, since this policy has changed before.

### `api`: Anthropic SDK

- Uses `anthropic.AsyncAnthropic` with `ANTHROPIC_API_KEY`.
- **Forced tool use:** `tool_choice` set to a single `save_recipe` tool whose `input_schema` is the Recipe JSON schema, so the output is schema-valid.
- Records input/output tokens from the response.

### Tests

- Both backends get unit tests with the external call mocked: a fake subprocess returning recorded JSON for the CLI, a mocked client for the API.
- One optional live test per backend, behind `RUN_LIVE_TESTS=1`.

## 7. Database (SQLite)

Three tables. Daily limits are counted from `jobs`, and search runs on an FTS5 index.

```
guilds(
  guild_id INTEGER PRIMARY KEY,
  recipe_channel_id INTEGER,
  daily_limit INTEGER DEFAULT 15,
  created_at TEXT
)

recipes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER NOT NULL,
  submitter_id INTEGER NOT NULL,
  source_url TEXT NOT NULL,        -- normalized
  platform TEXT NOT NULL,          -- 'tiktok' | 'instagram'
  creator TEXT,                    -- @handle, for credit
  title TEXT NOT NULL,
  tags TEXT,                       -- comma-separated, for search
  recipe_json TEXT NOT NULL,
  confidence TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(guild_id, source_url)
)

jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id INTEGER, user_id INTEGER, source_url TEXT,
  status TEXT,                     -- queued|running|done|failed
  backend TEXT,                    -- claude_cli | api
  error TEXT,
  input_tokens INTEGER, output_tokens INTEGER,
  created_at TEXT, finished_at TEXT
)
```

- Daily limits: count rows in `jobs` per user, per server, over the last 24h.
- Search: an SQLite FTS5 table over title, tags and ingredient items, populated on insert.

## 8. Discord UX

People mostly just drop links in `#recipes`. Slash commands cover setup and browsing.

**Setup**

- The bot needs the **Message Content** privileged intent (turn it on in the Developer Portal) to read links in the recipe channel.
- Permissions: View Channel, Send Messages, Embed Links, Attach Files, Add Reactions, Read Message History, Use Application Commands.

**Commands**

| Command | Who | What |
|---|---|---|
| `/setup channel <#channel>` | Manage Server | Set the auto-capture channel |
| `/setup limits <daily>` | Manage Server | Per-user daily cap |
| `/recipe add <url>` | Anyone | Process a link from any channel |
| `/recipe show <id>` | Anyone | Show a saved recipe |
| `/recipe delete <id>` | Submitter or admin | Delete a recipe |
| `/recipes search <query>` | Anyone | Search title, tags, ingredients |
| `/recipes mine` | Anyone | Your saved recipes |
| `/recipes recent` | Anyone | Latest 10 in this server |
| `/recipes random [tag]` | Anyone | "What should I make tonight?" |
| `/status` | Anyone | Queue length, your usage today, active backend |

Lists use paginated embeds with buttons (discord.py `View`).

**Recipe reply**

- Reply in a **thread** on the original message, to keep the channel clean.
- Embed: title, description, servings/time line, ingredients (grouped, with `~` and *(est.)* on estimated amounts), numbered steps, tips, tags, and a credit line: "From @creator on TikTok · saved by @user · Recipe #42".
- Show a ⚠️ line when confidence isn't high, with the `confidence_note`.
- Respect Discord limits (embed description 4096 chars, field value 1024, 25 fields, 6000 total). If the recipe doesn't fit, send a short embed plus the full recipe as a `.md` attachment.
- Reactions on the original message: ⏳ queued/running → ✅ done / ❌ failed.

## 9. Configuration (`.env.example`)

Set either the OAuth token or the API key, never both, depending on `CLAUDE_BACKEND`.

```
DISCORD_TOKEN=

# Claude backend: claude_cli (subscription, default) or api (API key)
CLAUDE_BACKEND=claude_cli
CLAUDE_MODEL=               # optional; blank = CLI default, e.g. claude-sonnet-5-5 for api

# claude_cli backend
CLAUDE_CODE_OAUTH_TOKEN=    # from `claude setup-token`; do NOT also set ANTHROPIC_API_KEY
CLAUDE_CLI_PATH=claude
CLAUDE_CLI_TIMEOUT_SECONDS=180

# api backend
ANTHROPIC_API_KEY=          # only when CLAUDE_BACKEND=api

WHISPER_MODEL=base
IG_COOKIES_PATH=            # optional
DB_PATH=./data/recipes.db
TEMP_DIR=./data/tmp
MAX_VIDEO_SECONDS=600
MAX_FRAMES=20
FRAME_INTERVAL_SECONDS=2
DEFAULT_DAILY_LIMIT=15
WORKER_CONCURRENCY=1
DEV_GUILD_ID=               # optional: sync slash commands instantly to one test server
LOG_LEVEL=INFO
```

## 10. Milestones

Eight milestones, each ending with something runnable. Tick them off as they pass review.

- **M1: Skeleton bot**
  - Project structure, config loading, bot connects, `/status` responds, command sync to `DEV_GUILD_ID`.
  - Done when: the bot is online in a test server and `/status` replies.
- **M2: Download + transcript**
  - URL detection/normalization (with unit tests), yt-dlp download, ffmpeg audio, faster-whisper transcript.
  - `/recipe add <url>` replies in a thread with the caption + transcript as a text file. Temp files cleaned up.
  - Done when: one TikTok and one Instagram link both return a transcript.
- **M3: Claude extraction (both backends)**
  - Pydantic models, shared prompt, `ExtractionBackend` interface. Build `claude_cli` first, then `api` (text only for now: caption + transcript).
  - Embed rendering, `.md` fallback, startup checks, and the API-key warning from 6a.
  - Done when: a narrated TikTok produces a sensible recipe with estimates marked using `claude_cli`, and the same video works after flipping `CLAUDE_BACKEND=api`.
- **M4: Frames (vision)**
  - Frame sampling, near-duplicate removal, frames sent to Claude (image files in the job dir for `claude_cli`, image blocks for `api`).
  - Done when: a music-only video with on-screen ingredients produces a usable recipe.
- **M5: Storage + multi-user**
  - SQLite schema, saving, dedupe, `/setup channel`, auto-capture in the recipe channel, reactions, `/recipe show|delete`, permission checks.
  - Done when: two users can save recipes, see each other's, and delete only their own.
- **M6: Queue + limits**
  - Job queue with position messages, per-user daily limits, job logging with backend and token counts.
  - Done when: 3 links posted quickly are processed in order with queue positions shown.
- **M7: Library commands**
  - FTS5 search, `/recipes search|mine|recent|random`, paginated results.
  - Done when: searching an ingredient finds the right recipes.
- **M8: Deploy to the Pi**
  - systemd service and a README section for Raspberry Pi OS (arm64): ffmpeg, venv, first run, logs via `journalctl`, updating yt-dlp.
  - Install Claude Code on the Pi and sign it in without a screen: run `claude setup-token` on the Mac, put the token in the Pi's `.env` (loaded by systemd via `EnvironmentFile=`, permissions `600`).
  - Check transcription speed with `base` on the Pi and note it in the README.
  - Done when: the bot survives a reboot and processes a video on the Pi.

## 11. Testing

- Unit tests: URL parsing, rendering (embed size limits, `.md` fallback), schema validation, DB queries.
- Extraction tests use saved fixture inputs with the external call mocked for each backend. Live tests run only with `RUN_LIVE_TESTS=1`.
- Keep a `tests/fixtures/` set of realistic captions and transcripts: fully narrated, caption-only, music-only with on-screen text, "comment RECIPE" gated, and a non-recipe video.

## 12. Later ideas (not in v1)

- `/recipe scale <id> <servings>`
- Shopping list from several recipes (`/shop 12 15 18`)
- Export a server's library as Markdown or a PDF cookbook
- YouTube Shorts support
- A small private web page on the Pi to browse recipes
- Reaction-based favorites (⭐) and "made it" tracking


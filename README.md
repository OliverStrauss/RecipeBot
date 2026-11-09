# Recipe Bot

A Discord bot that turns TikTok and Instagram recipe videos into written recipes.
Share a video link into your `#recipes` channel. The bot downloads it, reads the caption,
transcribes the audio, looks at frames for on-screen text, and has Claude write a real
recipe with amounts and steps. Each server keeps its own searchable library.

The full design is in [PLAN.md](PLAN.md).

| Milestone | Status |
|---|---|
| M1: Skeleton bot (config, connect, `/status`, dev-server sync) | ✅ built |
| M2: Download + transcript | ✅ built, tested live on one TikTok and one Instagram reel |
| M3: Claude extraction (both backends) | ✅ built; `claude_cli` tested live, `api` tested with a mocked client only (no key available) |
| M4: Frames (vision) | ✅ built; a music-only TikTok with on-screen text gave a usable recipe |
| M5: Storage + multi-user | ✅ built, tested against an in-memory DB with Discord faked |
| M6: Queue + limits | ✅ built, tested with Discord faked |
| M7: Library commands | ✅ built, tested with Discord faked |
| M8: Deploy to the Pi | 📝 service file and instructions written; not yet run on a Pi |

Not yet verified in a real Discord server: the slash commands, threads and reactions. Unit tests
fake the Discord API. Before relying on the bot, do a run-through with your own bot token
(see [Try it](#4-try-it)).

## Requirements

- Python 3.11 or newer (`python3 --version`)
- `ffmpeg` (`brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on the Pi)
- One of:
  - Claude Code CLI, signed in (default backend, uses your Pro/Max subscription), or
  - an Anthropic API key (`CLAUDE_BACKEND=api`)

**macOS with the python.org installer:** run `/Applications/Python 3.11/Install Certificates.command`
once. Without it, every download fails with `CERTIFICATE_VERIFY_FAILED`. Homebrew Python and the
Pi's Python don't need this.

## 1. Create the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it (e.g. "Recipe Bot").
2. Go to **Bot**:
   - Click **Reset Token**, copy it. This is your `DISCORD_TOKEN`. Treat it like a password.
   - Under **Privileged Gateway Intents**, turn on **Message Content Intent** and save. The bot needs it to read links posted in the recipe channel.
3. Go to **OAuth2 > URL Generator**:
   - Scopes: `bot` and `applications.commands`
   - Bot permissions: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Embed Links, Attach Files, Add Reactions, Read Message History, Use Application Commands
   - Open the generated URL and add the bot to your server.
4. Get your test server's ID: Discord **Settings > Advanced > Developer Mode** on, then right-click the server icon > **Copy Server ID**. This is `DEV_GUILD_ID`. With it set, slash commands appear instantly in that server. Without it they sync globally, which can take up to an hour.

## 2. Install and configure

```bash
git clone https://github.com/OliverStrauss/RecipeBot.git
cd RecipeBot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `DISCORD_TOKEN` (and `DEV_GUILD_ID` while testing). Everything else has a working default. `.env` is git-ignored; never commit it.

### Claude backend

`CLAUDE_BACKEND` picks how the bot talks to Claude. Everything outside `recipe_bot/pipeline/extract/` is the same either way.

**`claude_cli` (default): your subscription.** The bot runs `claude -p` (Claude Code in headless mode) with only the Read tool, so Claude can look at the frames and nothing else.

- On your own computer, it works once you have signed in to `claude`.
- On a headless machine (the Pi), run `claude setup-token` on your computer and put the token in `.env` as `CLAUDE_CODE_OAUTH_TOKEN`.
- Do **not** also set `ANTHROPIC_API_KEY`. The CLI would use the key and bill API usage instead of your subscription. The bot logs a loud warning if both are set.
- Leave `CLAUDE_MODEL` blank for the CLI's default model, or set `sonnet` to spend less. With Sonnet, a 70-second reel cost about $0.19 of credit and took about 40 seconds. The default model (Opus) cost about $0.41.

> **Usage note:** headless `claude -p` use on Pro/Max plans draws from a separate monthly Agent SDK credit, not your interactive limits. Subscription limits assume ordinary individual use. Switch to `api` if the bot gets shared widely or used heavily. Check current Anthropic docs and your usage settings, since this policy has changed before.

**`api`: pay-per-use API key.** Set `CLAUDE_BACKEND=api` and `ANTHROPIC_API_KEY`. The default model is `claude-opus-5-5`; set `CLAUDE_MODEL=claude-sonnet-5-5` for a cheaper one. Frames go to Claude as image blocks.

PLAN.md asked for a forced `save_recipe` tool call. Current models (Opus 5.5, Sonnet 5.5) reject forced `tool_choice`, so the bot uses structured outputs instead (`messages.parse` with the Recipe schema). That gives the same guarantee: the reply always matches the schema.

### Instagram cookies (optional)

Many reels need a login. Make a **throwaway** Instagram account, never your personal one. Log in to it in a browser and export its cookies in Netscape format with a "cookies.txt" browser extension. Set `IG_COOKIES_PATH` to the file. Cookies expire; re-export them when Instagram links start failing with "Instagram wants a login".

## 3. Run

```bash
python -m recipe_bot
```

On startup the bot checks that ffmpeg is installed and (for `claude_cli`) that `claude` is installed and signed in. If either check fails, it exits with a message that says how to fix it. It also warns when yt-dlp is out of date.

You should then see `Online as Recipe Bot#1234 ... Backend: claude_cli`. Stop the bot with Ctrl+C.

The first video downloads the whisper model (about 150 MB for `base`).

### Common startup errors

| Message | Fix |
|---|---|
| `DISCORD_TOKEN is missing` | Fill it in `.env` |
| `Discord rejected DISCORD_TOKEN` | Reset the token in the portal and paste the new one |
| `Message Content intent is off` | Portal > Bot > turn on Message Content Intent |
| `ffmpeg not found` | Install ffmpeg (see Requirements) |
| `Claude Code CLI not found` / `not signed in` | Install Claude Code, then sign in or set `CLAUDE_CODE_OAUTH_TOKEN` |
| `CLAUDE_BACKEND=api needs ANTHROPIC_API_KEY` | Set the key, or switch back to `claude_cli` |
| Slash commands don't show up | Check `DEV_GUILD_ID`, restart the bot, then restart Discord (Cmd+R) |

## 4. Try it

1. In your server, a server admin runs `/setup channel #recipes`.
2. Post a TikTok or Instagram link in `#recipes`. The bot reacts ⏳, then replies in a thread with the recipe and switches to ✅ (or ❌ with a reason).
3. Post the same link again. The bot replies with the saved recipe instead of processing it twice.
4. Post three links quickly. The second and third get "N videos ahead of you".
5. Try `/recipes search <an ingredient>`, `/recipes recent` and `/recipe delete <id>` from a second account.

### Commands

| Command | Who | What |
|---|---|---|
| `/setup channel <#channel>` | Manage Server | Set the auto-capture channel |
| `/setup limits <daily>` | Manage Server | Per-user cap (videos per rolling 24 hours, default 15) |
| `/recipe add <url>` | Anyone | Process a link from any channel |
| `/recipe show <id>` | Anyone | Show a saved recipe |
| `/recipe delete <id>` | Submitter or Manage Server | Delete a recipe |
| `/recipes search <query>` | Anyone | Search titles, tags and ingredients |
| `/recipes mine` | Anyone | Recipes you saved |
| `/recipes recent` | Anyone | Latest 10 in this server |
| `/recipes random [tag]` | Anyone | "What should I make tonight?" |
| `/status` | Anyone | Queue length, your usage today, active backend |

Server admins can change who sees the `/setup` commands under Server Settings > Integrations.

Recipes that don't fit in one Discord message come as a short embed plus the full recipe as a `.md` file. Amounts the video didn't state show as `~1 tsp salt (est.)`. A ⚠ line appears when Claude wasn't confident, for example when the recipe was gated behind "comment RECIPE".

## When downloads break

yt-dlp breaks when TikTok or Instagram change their sites. The bot replies with a friendly message and logs the full error. To fix it, update yt-dlp and restart:

```bash
source .venv/bin/activate
pip install -U yt-dlp
```

The bot checks for a newer yt-dlp on startup and logs a warning when one exists.

## Tests

```bash
pytest
```

Claude, Discord and yt-dlp are faked. The ffmpeg tests generate a tiny video on the fly and are skipped when ffmpeg isn't installed.

Live tests make one real Claude call per backend:

```bash
RUN_LIVE_TESTS=1 pytest tests/test_live.py                            # claude_cli
RUN_LIVE_TESTS=1 ANTHROPIC_API_KEY=sk-... pytest tests/test_live.py   # both
```

`tests/fixtures/samples.json` has realistic captions and transcripts for the five kinds of video: fully narrated, caption-only, music-only with on-screen text, "comment RECIPE" gated, and not a recipe.

## 5. Deploy to a Raspberry Pi

Target: Raspberry Pi 5 (4 GB), Raspberry Pi OS Bookworm 64-bit. These steps haven't been run on a real Pi yet.

**1. System packages and code**

```bash
sudo apt update && sudo apt install -y ffmpeg python3-venv git
cd ~
git clone https://github.com/OliverStrauss/RecipeBot.git
cd RecipeBot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**2. Claude Code, signed in without a screen**

```bash
curl -fsSL https://claude.ai/install.sh | bash     # installs to ~/.local/bin/claude
```

On your Mac, run `claude setup-token` and copy the token it prints. On the Pi:

```bash
cp .env.example .env
nano .env                  # DISCORD_TOKEN=..., CLAUDE_CODE_OAUTH_TOKEN=..., no ANTHROPIC_API_KEY
chmod 600 .env             # the tokens are secrets
```

**3. First run by hand**, to see any errors directly (the bot reads `.env` from the current folder):

```bash
.venv/bin/python -m recipe_bot
```

Post one video and wait for the recipe. This also downloads the whisper model. Press Ctrl+C.

**4. Run it as a service** (starts on boot, restarts on crashes). The unit file has `YOUR_USER` placeholders; `sed` fills in your username:

```bash
sed "s/YOUR_USER/$USER/g" deploy/recipe-bot.service | sudo tee /etc/systemd/system/recipe-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now recipe-bot
```

**Logs:**

```bash
journalctl -u recipe-bot -f             # follow
journalctl -u recipe-bot --since today
```

Each job logs a line like `Prepared ...: 69s video, transcript 1270 chars in 6.5s, 20 frames in 0.7s`, plus its token usage.

**Updating**

```bash
cd ~/RecipeBot && git pull
.venv/bin/pip install -U -r requirements.txt   # also updates yt-dlp
sudo systemctl restart recipe-bot
```

**Check after deploying:** reboot the Pi (`sudo reboot`), then confirm `systemctl status recipe-bot` is active and a posted video still gets processed.

**Transcription speed:** a 69-second reel took 6.5 s with `base` on an M-series Mac. The Pi number is not measured yet. Read it from the `Prepared ...` log line after the first job and record it here. If transcripts are poor, try `WHISPER_MODEL=small` (slower, more accurate).

## Project layout

```
RecipeBot/
├── PLAN.md                   # the full build plan
├── README.md
├── requirements.txt
├── .env.example
├── pytest.ini
├── recipe_bot/
│   ├── __main__.py           # entry point + startup checks: python -m recipe_bot
│   ├── config.py             # loads + validates env vars
│   ├── bot.py                # Bot subclass, intents, DB, cog loading, command sync
│   ├── models.py             # pydantic Recipe, Ingredient, Step; SavedRecipe row
│   ├── render.py             # Recipe -> Discord embed (+ .md fallback) and Markdown
│   ├── db.py                 # SQLite schema and queries, FTS5 search
│   ├── cogs/
│   │   ├── capture.py        # recipe-channel links, /recipe add|show|delete, the job worker
│   │   ├── library.py        # /recipes search|mine|recent|random, paginated
│   │   └── admin.py          # /setup channel, /setup limits, /status
│   └── pipeline/
│       ├── __init__.py       # fetch() and prepare(): download, audio, transcript, frames
│       ├── urls.py           # detect + normalize TikTok/IG URLs
│       ├── download.py       # yt-dlp wrapper -> (video_path, metadata)
│       ├── media.py          # ffmpeg audio + frame extraction, frame dedupe
│       ├── transcribe.py     # faster-whisper, model loaded once and reused
│       ├── queue.py          # job queue and workers
│       └── extract/
│           ├── __init__.py   # get_backend(config)
│           ├── base.py       # ExtractionBackend interface + shared validate/retry
│           ├── prompt.py     # system prompt + input assembly
│           ├── cli_backend.py   # claude -p subprocess (subscription)
│           └── api_backend.py   # Anthropic SDK (API key)
├── tests/
│   └── fixtures/             # sample captions/transcripts, recorded CLI output
└── deploy/
    └── recipe-bot.service    # systemd unit for the Pi
```

`/recipe show` and `/recipe delete` live in `capture.py` instead of `library.py` (the plan's split). discord.py wants one command group per cog, and `/recipe add` already lives there.

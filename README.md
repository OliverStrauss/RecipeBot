# Recipe Bot

A Discord bot that turns TikTok and Instagram recipe videos into written recipes.
The full design is in [PLAN.md](PLAN.md). It's being built one milestone at a time.

| Milestone | Status |
|---|---|
| M1: Skeleton bot (config, connect, `/status`, dev-server sync) | ✅ built, awaiting review |
| M2: Download + transcript | not started |
| M3: Claude extraction (both backends) | not started |
| M4: Frames (vision) | not started |
| M5: Storage + multi-user | not started |
| M6: Queue + limits | not started |
| M7: Library commands | not started |
| M8: Deploy to the Pi | not started |

## Requirements

- Python 3.11 or newer (`python3 --version`)
- From M2 on: `ffmpeg` (`brew install ffmpeg` on macOS, `sudo apt install ffmpeg` on the Pi)
- From M3 on: Claude Code CLI signed in, or an Anthropic API key

## 1. Create the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it (e.g. "Recipe Bot").
2. Go to **Bot**:
   - Click **Reset Token**, copy it. This is your `DISCORD_TOKEN`. Treat it like a password.
   - Under **Privileged Gateway Intents**, turn on **Message Content Intent** and save.
3. Go to **OAuth2 > URL Generator**:
   - Scopes: `bot` and `applications.commands`
   - Bot permissions: View Channels, Send Messages, Embed Links, Attach Files, Add Reactions, Read Message History, Use Application Commands
   - Open the generated URL and add the bot to your test server.
4. Get your test server's ID: Discord **Settings > Advanced > Developer Mode** on, then right-click the server icon > **Copy Server ID**. This is `DEV_GUILD_ID`. With it set, slash commands appear instantly in that server; without it they sync globally, which can take up to an hour.

## 2. Install and configure

```bash
cd recipe-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at least `DISCORD_TOKEN` and `DEV_GUILD_ID`. Everything else has a working default. `.env` is git-ignored; never commit it.

## 3. Run

```bash
python -m recipe_bot
```

You should see a line like `Online as Recipe Bot#1234 ... Backend: claude_cli`. In your test server, type `/status`. Only you see the reply. Queue and usage show as not built yet until M6.

Stop the bot with Ctrl+C.

A warning about `CLAUDE_CODE_OAUTH_TOKEN` being empty is expected until M3.

### Common startup errors

| Message | Fix |
|---|---|
| `DISCORD_TOKEN is missing` | Fill it in `.env` |
| `Discord rejected DISCORD_TOKEN` | Reset the token in the portal and paste the new one |
| `Message Content intent is off` | Portal > Bot > turn on Message Content Intent |
| `/status` doesn't show up | Check `DEV_GUILD_ID` is your test server's ID, then restart the bot. Also try restarting Discord (Cmd+R) |

## Tests

```bash
pytest
```

## Project layout (so far)

```
recipe-bot/
├── PLAN.md               # the full build plan
├── README.md
├── requirements.txt
├── .env.example
├── pytest.ini
├── recipe_bot/
│   ├── __main__.py       # entry point: python -m recipe_bot
│   ├── config.py         # loads + validates env vars
│   ├── bot.py            # Bot subclass, intents, cog loading, command sync
│   └── cogs/
│       └── admin.py      # /status (later /setup channel, /setup limits)
└── tests/
    ├── test_config.py
    └── test_bot.py
```

The remaining modules from PLAN.md section 5 (`pipeline/`, `models.py`, `render.py`, `db.py`, the other cogs and `deploy/`) are added in the milestones that need them.

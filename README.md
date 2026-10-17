# discord-chaton-bot

Helper bot for Discord server.

## Maintenance

See [AUDIT.md](AUDIT.md) for the technical review, applied optimizations,
validation results and remaining priorities.

Run regression tests without connecting to Discord:
`python -m unittest discover -s tests -v`.

### Twitter network limits and cache

Twitter retrieval (including translation) runs at most 4 jobs concurrently,
with at most 16 distinct tweets running or queued. Waiting for a slot is limited
to 5 seconds; overload uses the existing fallback link. HTTP requests use a
5-second connection timeout, 10-second read/write inactivity timeout and a
20-second overall deadline per request. These limits apply to Twitter HTTP
requests, not the synchronous DeepL SDK's internal retries or other commands.

Successful tweet data and translations are cached for 5 minutes, up to 256
entries, evicting the least recently used. Concurrent requests for the same
tweet ID share a fetch, including `/i/status/` links. Errors are not cached.
Views and spoilers are rebuilt per message. The in-memory cache is cleared on
restart or hot reload. Defaults are defined in `TwitterComponentHandler`.

## Architecture

The bot is now organized into modules:

- `bot.py`: entry point and bot lifecycle.
- `settings.py`: configuration (environment variables, intents, constants).
- `cogs/slash_commands.py`: slash commands.
- `cogs/message_handlers.py`: `on_message` listeners and link/mentions fix logic.

# Commands 

🕹️ Get a random game to play from user Steam ID
- Owned option
- Wishlisted options

🧑‍🍳 Get a random recipe from HelloFresh's catalog
- Veggie option
- Easy option

🧑‍🍳 Get a random recipe from Jow's catalog
- Easy option

🌤️ Get weather forecast for a specific day
- City option


<sub>📙 Scrape information from an online library</sub>

## Hot Reload (dev)

### Preferred: reload cogs without restarting the bot process

1. Install dependencies: `pip install -r requirements.txt`
2. Enable cog hot reload:
	- PowerShell: `$env:HOT_RELOAD_COGS = "1"`
3. Start the bot as usual: `python bot.py`

When a file in `cogs/` changes, the corresponding extension is reloaded automatically.

# discord-chaton-bot

Helper bot for a friends Discord server.

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


<sub>📙 Scrape information from an online library</sub>

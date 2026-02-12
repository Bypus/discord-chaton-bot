import os

import discord

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.members = True
    intents.reactions = True
    return intents


BOT_TOKEN = os.getenv("TOKEN_BOT_DISCORD", "")
STEAM_ID_DEFAULT = os.getenv("STEAM_ID_FB", "")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
GUILD_ID = os.getenv("GUILD_ID", "")
CUCKS_ROLE_ID = os.getenv("CUCKS_ROLE_ID", "")
DEADCUCKS_ROLE_ID = os.getenv("DEADCUCKS_ROLE_ID", "")

NITTER_INSTANCE = "https://nitter.net"

DEFAULT_ACTIVITY = discord.CustomActivity(
    name="peace",
    type=discord.ActivityType.custom,
)

LANG_TO_FLAG = {
    "fr": "fr",
    "en": "gb",
    "ja": "jp",
    "ko": "kr",
    "zh": "cn",
    "de": "de",
    "es": "es",
}
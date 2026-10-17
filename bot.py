import asyncio
import os

import discord
from discord.ext import commands

from settings import DEFAULT_ACTIVITY, BOT_TOKEN, build_intents

class ChatonBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("cogs.slash_commands")
        await self.load_extension("cogs.message_handlers")
        await self.load_extension("cogs.scheduler")
        if os.getenv("HOT_RELOAD_COGS", "0") == "1":
            await self.load_extension("cogs.hot_reload")
        synced = await self.tree.sync()
        print(f"Slash commands synced: {len(synced)}")


bot = ChatonBot(command_prefix="!", intents=build_intents())

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    message_cog = bot.get_cog("MessageHandlersCog")
    if message_cog and hasattr(message_cog, "initialize_roles"):
        await message_cog.initialize_roles()

    await bot.change_presence(activity=DEFAULT_ACTIVITY)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("TOKEN_BOT_DISCORD doit être configuré.")
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

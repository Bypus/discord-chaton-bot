import asyncio
import os

import discord
from discord.ext import commands

from cogs.message_handlers import MessageHandlersCog
from settings import DEFAULT_ACTIVITY, BOT_TOKEN, build_intents


bot = commands.Bot(command_prefix="!", intents=build_intents())


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)}")
    except Exception as error:
        print(f"Error syncing slash commands: {error}")

    message_cog = bot.get_cog("MessageHandlersCog")
    if isinstance(message_cog, MessageHandlersCog):
        await message_cog.initialize_roles()

    await bot.change_presence(activity=DEFAULT_ACTIVITY)


async def main():
    await bot.load_extension("cogs.slash_commands")
    await bot.load_extension("cogs.message_handlers")
    await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

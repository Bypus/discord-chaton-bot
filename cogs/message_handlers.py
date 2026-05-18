import io
import re
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

from settings import (
    CUCKS_ROLE_ID,
    DEADCUCKS_ROLE_ID,
    GUILD_ID,
)
from cogs.twitter_handler import TwitterComponentHandler


class MessageHandlersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.twitter_handler = TwitterComponentHandler()
        self.chaton_cucks_role: Optional[discord.Role] = None
        self.chaton_deadcucks_role: Optional[discord.Role] = None

    async def initialize_roles(self):
        try:
            if GUILD_ID and CUCKS_ROLE_ID and DEADCUCKS_ROLE_ID:
                chaton_guild = self.bot.get_guild(int(GUILD_ID))
                if chaton_guild:
                    self.chaton_cucks_role = chaton_guild.get_role(int(CUCKS_ROLE_ID))
                    self.chaton_deadcucks_role = chaton_guild.get_role(int(DEADCUCKS_ROLE_ID))
                else:
                    self.chaton_cucks_role = None
                    self.chaton_deadcucks_role = None
                    print(f"Le serveur avec l'ID {GUILD_ID} n'a pas été trouvé.")
            else:
                print("GUILD_ID, CUCKS_ROLE_ID ou DEADCUCKS_ROLE_ID non défini dans les variables d'environnement.")
        except Exception as error:
            self.chaton_cucks_role = None
            self.chaton_deadcucks_role = None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if message.mention_everyone:
            emoji = discord.utils.get(self.bot.emojis, name="angerypingcircle")
            await message.add_reaction(emoji)

        # Role mentions (before URL handlers which may delete the message)
        role_response_map = {}
        if isinstance(self.chaton_cucks_role, discord.Role):
            role_response_map[self.chaton_cucks_role] = (
                "https://cdn.discordapp.com/emojis/827938389256568832.png?v=1",
                "tkench.png",
            )
        if isinstance(self.chaton_deadcucks_role, discord.Role):
            role_response_map[self.chaton_deadcucks_role] = (
                "https://cdn.discordapp.com/emojis/1469295236835446846.webp",
                "trem.png",
            )

        for role, (url, filename) in role_response_map.items():
            if role in message.role_mentions:
                async with aiohttp.ClientSession() as client_session:
                    async with client_session.get(url) as response:
                        if response.status != 200:
                            continue
                        data = io.BytesIO(await response.read())
                        await message.channel.send(file=discord.File(data, filename), silent=True)
                break

        # Twitter/X embed handler
        if await self.twitter_handler.handle_message(message):
            return

        # Reddit/Instagram/TikTok handler
        if any(domain in message.content for domain in ["reddit.com", "instagram.com", "tiktok.com"]):
            await message.edit(suppress=True)
            replacements = {
                "reddit.com": "rxddit.com",
                "instagram.com": "vxinstagram.com",
                "tiktok.com": "tnktok.com",
            }

            fixed_urls = []
            for domain, replacement in replacements.items():
                urls = re.findall(
                    rf"(\|\|)?(https?://(?:[a-z0-9-]*\.)*{re.escape(domain)}\S+)(\|\|)?",
                    message.content,
                )
                for prefix, url, suffix in urls:
                    fixed_url = url.replace(domain, replacement)
                    spoilered_url = f"{prefix or ''}{fixed_url}{suffix or ''}"
                    fixed_urls.append(f"🔗 [Fixed]({spoilered_url})")

            if fixed_urls:
                await message.channel.send("\n".join(fixed_urls), silent=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageHandlersCog(bot))
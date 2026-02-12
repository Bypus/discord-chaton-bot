import io
import re
from typing import Optional

import aiohttp
import deepl
import discord
import httpx
from bs4 import BeautifulSoup
from discord.ext import commands
from fast_langdetect import detect

from settings import (
    CUCKS_ROLE_ID,
    DEADCUCKS_ROLE_ID,
    DEEPL_API_KEY,
    GUILD_ID,
    LANG_TO_FLAG,
    NITTER_INSTANCE,
)


class MessageHandlersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.translator = deepl.DeepLClient(DEEPL_API_KEY)
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
            print(f"Cucks role not found: {error}")

    def detect_language(self, text: str) -> Optional[str]:
        try:
            cleaned_text = text.replace("\n", " ")
            result = detect(cleaned_text)
            if result and isinstance(result, list):
                return result[0]["lang"]
            return None
        except Exception:
            return None

    @staticmethod
    def format_as_quote(text: str) -> str:
        return "\n".join(f"> {line}" for line in text.split("\n"))

    async def get_tweet_text(self, username: str, tweet_id: str):
        url = f"{NITTER_INSTANCE}/{username}/status/{tweet_id}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": NITTER_INSTANCE,
        }

        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
                response = await client.get(url)

            if response.status_code != 200 or not response.text.strip():
                return None, None, None

            soup = BeautifulSoup(response.text, "html.parser")
            tweet_content = soup.find("div", class_="tweet-content")
            tweet_text = tweet_content.get_text("\n", strip=True) if tweet_content else ""

            attachments = soup.find("div", class_="attachments")
            image_elements = attachments.find_all("img") if attachments else []
            video_count = 1 if "video" in str(attachments) else 0
            image_count = len(image_elements)
            has_single_image = image_count == 1 and video_count == 0

            detected_lang = None
            if tweet_text.strip():
                detected_lang = str(self.detect_language(tweet_text))

                if detected_lang and detected_lang not in ["fr", "en"]:
                    translated = self.translator.translate_text(tweet_text, target_lang="FR").text
                    lang_flag = LANG_TO_FLAG.get(detected_lang)
                    translated = "\n".join(f"-# {line}" if line.strip() else "" for line in translated.split("\n"))
                    tweet_text = f":flag_{lang_flag}: -> :flag_fr:\n{translated}"

            return tweet_text, has_single_image, detected_lang
        except httpx.RequestError:
            print("HTTP Request Error while fetching tweet.")
            return None, None, None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if message.mention_everyone:
            emoji = discord.utils.get(self.bot.emojis, name="angerypingcircle")
            await message.add_reaction(emoji)

        if "https://x.com/" in message.content or "https://twitter.com/" in message.content:
            clean_content = re.sub(r"\n+\|\|$", "||", message.content.strip())
            twitter_match = re.search(
                r"(\|\|\s*)?(https?://(?:x|twitter)\.com/[^/\s]+/status/\d+)(\s*\|\|)?",
                clean_content,
                re.MULTILINE,
            )
            if not twitter_match:
                return

            is_spoiler = twitter_match.group(1) is not None and twitter_match.group(3) is not None
            twitter_url = twitter_match.group(2)

            username = twitter_url.split("/")[-3]
            tweet_id = twitter_url.split("/")[-1]
            tweet_text, has_single_image, detected_lang = await self.get_tweet_text(username, tweet_id)

            fixed_link = re.sub(
                r"https?://(?:x\.com|twitter\.com)",
                lambda matched: "https://fixupx.com" if "x.com" in matched.group(0) else "https://fxtwitter.com",
                twitter_match.group(2),
            )

            formatted_message = f"🔗 [Fixed]({fixed_link})\n"
            await message.edit(suppress=True)

            if has_single_image and detected_lang in ["fr", "en"]:
                await message.channel.send(formatted_message, silent=True)
                return

            if detected_lang not in ["fr", "en", None]:
                formatted_message += self.format_as_quote(tweet_text) if tweet_text else ""

            if is_spoiler:
                formatted_message = f"||{formatted_message}||"

            await message.channel.send(formatted_message, silent=True)

        if any(domain in message.content for domain in ["reddit.com", "instagram.com", "tiktok.com"]):
            await message.edit(suppress=True)
            replacements = {
                "reddit.com": "rxddit.com",
                "instagram.com": "vxinstagram.com",
                "tiktok.com": "tnktok.com",
            }
            print(f"Original message: {message.content}")

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


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageHandlersCog(bot))
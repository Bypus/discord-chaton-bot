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
    NITTER_INSTANCES,
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

    def detect_language(self, text: str) -> Optional[str]:
        try:
            cleaned_text = text.replace("\n", " ")
            result = detect(cleaned_text)
            if isinstance(result, dict):
                lang = result.get("lang")
                return lang if isinstance(lang, str) and lang else None

            # Backward compatibility if the library returns a list of candidates
            if isinstance(result, list) and result:
                first = result[0]
                if isinstance(first, dict):
                    lang = first.get("lang")
                    return lang if isinstance(lang, str) and lang else None

            if isinstance(result, str) and result:
                return result

            return None
        except Exception:
            return None

    @staticmethod
    def format_as_quote(text: str) -> str:
        return "\n".join(f"> {line}" for line in text.split("\n"))

    def translate_tweet_text(self, tweet_text: str, detected_lang: Optional[str]) -> tuple[str, Optional[str]]:
        detected_lang_base = detected_lang.split("-")[0].lower() if isinstance(detected_lang, str) and detected_lang else None

        if detected_lang_base and detected_lang_base not in ["fr", "en"]:
            translated = self.translator.translate_text(tweet_text, target_lang="FR").text
            lang_flag = LANG_TO_FLAG.get(detected_lang_base)
            translated = "\n".join(f"-# {line}" if line.strip() else "" for line in translated.split("\n"))
            source_prefix = f":flag_{lang_flag}:" if lang_flag else ":speech_balloon:"
            tweet_text = f"{source_prefix} -> :flag_fr:\n{translated}"

        return tweet_text, detected_lang_base

    async def fetch_nitter_page(self, path: str) -> Optional[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": NITTER_INSTANCE,
        }

        for instance in NITTER_INSTANCES:
            try:
                async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
                    response = await client.get(f"{instance}{path}")

                if response.status_code == 200 and response.text.strip():
                    return response.text

                print(f"Nitter instance failed: {instance} returned {response.status_code}")
            except httpx.RequestError as error:
                print(f"Nitter request failed on {instance}: {error}")

        return None

    async def resolve_username_from_i_status(self, tweet_id: str) -> Optional[str]:
        """Resolve the tweet author when URL uses /i/status/<tweet_id>."""
        page_text = await self.fetch_nitter_page(f"/i/status/{tweet_id}")
        if not page_text:
            return None

        soup = BeautifulSoup(page_text, "html.parser")
        username_link = soup.find("a", class_="username")
        if not username_link:
            return None

        username = username_link.get_text(strip=True).lstrip("@")
        return username or None

    async def get_tweet_text(self, username: str, tweet_id: str):
        try:
            # API-first for deterministic behavior across environments (Fly and local).
            api_result = await self.get_tweet_text_from_api(username, tweet_id)
            if api_result[0]:
                return api_result

            print(f"API fetch failed for @{username}/{tweet_id}. Trying Nitter fallback.")
            page_text = await self.fetch_nitter_page(f"/{username}/status/{tweet_id}")
            if not page_text:
                print(f"Unable to fetch tweet text for @{username}/{tweet_id} from API and Nitter.")
                return None, None, None

            soup = BeautifulSoup(page_text, "html.parser")
            tweet_content = soup.find("div", class_="tweet-content")
            tweet_text = tweet_content.get_text("\n", strip=True) if tweet_content else ""

            attachments = soup.find("div", class_="attachments")
            image_elements = attachments.find_all("img") if attachments else []
            video_count = 1 if "video" in str(attachments) else 0
            image_count = len(image_elements)
            has_single_image = image_count == 1 and video_count == 0

            detected_lang = None
            if tweet_text.strip():
                tweet_text, detected_lang = self.translate_tweet_text(tweet_text, self.detect_language(tweet_text))

            return tweet_text, has_single_image, detected_lang
        except Exception as error:
            print(f"Error while fetching or translating tweet: {error}")
            return None, None, None

    @staticmethod
    def render_fxtwitter_raw_text(raw_text: dict) -> Optional[str]:
        if not isinstance(raw_text, dict):
            return None

        text = raw_text.get("text")
        facets = raw_text.get("facets", [])
        if not isinstance(text, str) or not text.strip():
            return None
        if not isinstance(facets, list) or not facets:
            return text

        rendered = text
        # Replace facets from right to left to keep indices stable.
        ordered_facets = sorted(
            [f for f in facets if isinstance(f, dict) and isinstance(f.get("indices"), list) and len(f.get("indices")) == 2],
            key=lambda facet: facet["indices"][0],
            reverse=True,
        )

        for facet in ordered_facets:
            start, end = facet["indices"]
            replacement = facet.get("replacement") or facet.get("original")
            if not isinstance(start, int) or not isinstance(end, int) or not isinstance(replacement, str):
                continue
            if start < 0 or end > len(rendered) or start > end:
                continue
            rendered = rendered[:start] + replacement + rendered[end:]

        return rendered

    async def get_tweet_text_from_api(self, username: str, tweet_id: str):
        endpoints = [
            f"https://api.vxtwitter.com/{username}/status/{tweet_id}",
            f"https://api.fxtwitter.com/{username}/status/{tweet_id}",
        ]

        for endpoint in endpoints:
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                    response = await client.get(endpoint)

                if response.status_code != 200:
                    print(f"Fallback API returned {response.status_code}: {endpoint}")
                    continue

                payload = response.json()

                # vxtwitter: flat payload with text/lang/media_extended
                tweet_text = payload.get("text") if isinstance(payload, dict) else None
                detected_lang = payload.get("lang") if isinstance(payload, dict) else None
                media_extended = payload.get("media_extended", []) if isinstance(payload, dict) else []

                # fxtwitter: nested payload under tweet
                if not tweet_text and isinstance(payload, dict):
                    tweet_data = payload.get("tweet", {})
                    if isinstance(tweet_data, dict):
                        raw_text = tweet_data.get("raw_text")
                        tweet_text = self.render_fxtwitter_raw_text(raw_text) or tweet_data.get("text")
                        detected_lang = tweet_data.get("lang")
                        media_extended = tweet_data.get("media", {}).get("all", []) if isinstance(tweet_data.get("media"), dict) else []

                if not tweet_text or not str(tweet_text).strip():
                    continue

                image_count = 0
                video_count = 0
                for media in media_extended if isinstance(media_extended, list) else []:
                    if not isinstance(media, dict):
                        continue
                    media_type = str(media.get("type", "")).lower()
                    if media_type in ["photo", "image"]:
                        image_count += 1
                    elif media_type:
                        video_count += 1

                has_single_image = image_count == 1 and video_count == 0

                tweet_text, detected_lang_base = self.translate_tweet_text(str(tweet_text), detected_lang)

                return str(tweet_text), has_single_image, detected_lang_base
            except Exception as error:
                print(f"Fallback API error on {endpoint}: {error}")

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
                r"(\|\|\s*)?(https?://(?:x|twitter)\.com/(?:i|[^/\s]+)/status/\d+(?:\?[^\s|]+)?)(\s*\|\|)?",
                clean_content,
                re.MULTILINE,
            )
            if not twitter_match:
                return

            is_spoiler = twitter_match.group(1) is not None and twitter_match.group(3) is not None
            twitter_url = twitter_match.group(2)

            parts = [part for part in twitter_url.split("/") if part]
            username_or_i = parts[-3]
            tweet_id = parts[-1].split("?")[0]

            username = username_or_i
            if username_or_i == "i":
                resolved_username = await self.resolve_username_from_i_status(tweet_id)
                if resolved_username:
                    username = resolved_username

            tweet_text, has_single_image, detected_lang = await self.get_tweet_text(username, tweet_id)

            fixed_link = re.sub(
                r"https?://(?:x\.com|twitter\.com)",
                lambda matched: "https://fixupx.com" if "x.com" in matched.group(0) else "https://fxtwitter.com",
                twitter_match.group(2),
            )

            formatted_message = f"🔗 [Fixed]({fixed_link})\n"
            await message.edit(suppress=True)

            if has_single_image and detected_lang in ["fr", "en"]:
                if is_spoiler:
                    formatted_message = f"||{formatted_message}||"
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
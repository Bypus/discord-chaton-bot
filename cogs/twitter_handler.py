import re
from typing import Optional

import deepl
import discord
import httpx
from fast_langdetect import detect

from settings import DEEPL_API_KEY


class TwitterComponentHandler:
    def __init__(self):
        self.translator = deepl.DeepLClient(DEEPL_API_KEY)

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
    def has_meaningful_text(text: str) -> bool:
        """Return False for texts that are only URLs/placeholders/whitespace."""
        if not isinstance(text, str) or not text.strip():
            return False

        # Remove URLs and whitespace, then check if something meaningful remains.
        without_urls = re.sub(r"https?://\S+", "", text)
        normalized = re.sub(r"\s+", "", without_urls)
        return bool(normalized)

    @staticmethod
    def reverse_nitter_urls(text: str) -> str:
        """Reverse Nitter privacy URL substitutions back to originals."""
        replacements = {
            "piped.video/": "youtu.be/",
            "piped.kavin.rocks/": "youtu.be/",
            "inv.nadeko.net/": "youtube.com/",
            "invidious.snopyta.org/": "youtube.com/",
        }
        for nitter_domain, original_domain in replacements.items():
            text = text.replace(nitter_domain, original_domain)
        return text

    @staticmethod
    def linkify_hashtags(text: str) -> str:
        """Turn #hashtag into a clickable markdown link to X search."""
        return re.sub(r"#(\w+)", lambda m: f"[#{m.group(1)}](https://x.com/hashtag/{m.group(1)})", text)

    @staticmethod
    def linkify_bare_urls(text: str) -> str:
        """Wrap bare domain URLs (without https://) into clickable markdown links."""
        return re.sub(
            r"(?<!\S)(?<!\()(?<!//)((?:[\w-]+\.)+(?:be|com|org|net|io|co|me|tv|gg|ly|cc|to)(/\S*)?)",
            lambda m: f"[{m.group(1)}](https://{m.group(1)})",
            text,
        )

    @staticmethod
    def linkify_mentions(text: str) -> str:
        """Turn @username into a clickable markdown link to X profile."""
        return re.sub(r"(?<!\[)@(\w+)", lambda m: f"[@{m.group(1)}](https://x.com/{m.group(1)})", text)

    def translate_tweet_text(self, tweet_text: str, detected_lang: Optional[str]) -> tuple[str, Optional[str]]:
        # Strip t.co shortened links (video/media URLs appended by Twitter)
        tweet_text = re.sub(r"https?://t\.co/\S+", "", tweet_text).strip()

        if not self.has_meaningful_text(tweet_text):
            return tweet_text, None

        detected_lang_base = detected_lang.split("-")[0].lower() if isinstance(detected_lang, str) and detected_lang else None

        # zxx/und/art/qme are not useful language codes for translation decisions.
        if detected_lang_base and detected_lang_base not in ["fr", "en", "zxx", "und", "art", "qme"]:
            # Protect URLs, hashtags and mentions from being translated using DeepL XML tag handling
            protected = tweet_text
            matches = []
            for pattern in [
                r"https?://\S+",
                r"(?<!\S)[\w.-]+\.(?:be|com|org|net|io|co|me|tv|gg|ly|cc|to)/\S+",
                r"#\S+",
                r"@\w+",
            ]:
                for match in re.finditer(pattern, protected):
                    matches.append((match.start(), match.end(), match.group(0)))

            # Wrap matches in <keep> tags from right to left to preserve indices
            matches.sort(key=lambda m: m[0], reverse=True)
            for start, end, original in matches:
                protected = protected[:start] + f"<keep>{original}</keep>" + protected[end:]

            translated = self.translator.translate_text(
                protected,
                target_lang="FR",
                tag_handling="xml",
                ignore_tags=["keep"],
            ).text

            # Strip <keep> tags, preserving their content
            translated = re.sub(r"<keep>(.*?)</keep>", r"\1", translated)
            # Collapse excessive blank lines (e.g. between hashtags)
            translated = re.sub(r"\n{2,}", "\n", translated)
            tweet_text = translated

        tweet_text = self.linkify_hashtags(tweet_text)
        tweet_text = self.linkify_mentions(tweet_text)
        tweet_text = self.linkify_bare_urls(tweet_text)

        return tweet_text, detected_lang_base

    async def resolve_username_from_i_status(self, tweet_id: str) -> Optional[str]:
        """Resolve the tweet author when URL uses /i/status/<tweet_id> via vxtwitter/fxtwitter."""
        endpoints = [
            f"https://api.vxtwitter.com/i/status/{tweet_id}",
            f"https://api.fxtwitter.com/i/status/{tweet_id}",
        ]
        for endpoint in endpoints:
            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                    response = await client.get(endpoint)
                if response.status_code != 200:
                    continue
                payload = response.json()
                if not isinstance(payload, dict):
                    continue
                # vxtwitter flat
                username = payload.get("user_screen_name")
                # fxtwitter nested
                if not username:
                    tweet_data = payload.get("tweet", {})
                    if isinstance(tweet_data, dict):
                        author = tweet_data.get("author", {})
                        username = author.get("screen_name") if isinstance(author, dict) else None
                if username:
                    return str(username)
            except Exception as error:
                print(f"resolve_username error on {endpoint}: {error}")
        return None

    async def get_tweet_data(self, username: str, tweet_id: str) -> dict:
        """Fetch tweet data via vxtwitter/fxtwitter APIs."""
        return await self._get_tweet_data_from_api(username, tweet_id)

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

    @staticmethod
    def _parse_media(media_extended) -> tuple[list[str], Optional[str]]:
        """Extract image URLs and video URL from media_extended list."""
        images = []
        video_url = None
        for media in media_extended if isinstance(media_extended, list) else []:
            if not isinstance(media, dict):
                continue
            media_type = str(media.get("type", "")).lower()

            if media_type in ["photo", "image"]:
                url = media.get("media_url_https") or media.get("url") or media.get("thumbnail_url")
                if url:
                    images.append(url)
            elif media_type in ["video", "gif"]:
                url = media.get("url") or media.get("video_url")
                if url and not video_url:
                    video_url = url
        return images, video_url

    @staticmethod
    def _parse_qrt(qrt: dict) -> Optional[dict]:
        """Parse a vxtwitter qrt (quote retweet) into a simple dict."""
        if not isinstance(qrt, dict):
            return None
        text = qrt.get("text")
        if not text or not str(text).strip():
            return None
        author_name = qrt.get("user_name") or qrt.get("user_screen_name") or ""
        username = qrt.get("user_screen_name") or ""
        media_extended = qrt.get("media_extended", [])
        images, video_url = TwitterComponentHandler._parse_media(media_extended)
        return {
            "text": str(text),
            "author_name": author_name,
            "username": username,
            "images": images,
            "video_url": video_url,
        }

    async def _get_tweet_data_from_api(self, username: str, tweet_id: str) -> dict:
        empty = {
            "text": None,
            "images": [],
            "video_url": None,
            "has_video": False,
            "detected_lang": None,
            "author_name": username,
            # "author_avatar": None,
            "quote": None,
        }
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

                if not isinstance(payload, dict):
                    continue

                # vxtwitter: flat payload with text/lang/media_extended
                tweet_text = payload.get("text")
                detected_lang = payload.get("lang")
                media_extended = payload.get("media_extended", [])
                author_name = payload.get("user_name") or payload.get("user_screen_name")
                author_screen_name = payload.get("user_screen_name")
                # author_avatar = payload.get("user_profile_image_url")
                # if author_avatar:
                #     author_avatar = re.sub(r"_(normal|bigger|mini)", "_200x200", author_avatar)

                # fxtwitter: nested payload under tweet
                if not tweet_text:
                    tweet_data = payload.get("tweet", {})
                    if isinstance(tweet_data, dict):
                        raw_text = tweet_data.get("raw_text")
                        tweet_text = self.render_fxtwitter_raw_text(raw_text) or tweet_data.get("text")
                        detected_lang = tweet_data.get("lang")
                        media_extended = tweet_data.get("media", {}).get("all", []) if isinstance(tweet_data.get("media"), dict) else []
                        author_data = tweet_data.get("author", {})
                        if isinstance(author_data, dict):
                            author_name = author_name or author_data.get("name")
                            author_screen_name = author_screen_name or author_data.get("screen_name")
                            # author_avatar = author_avatar or author_data.get("avatar_url")

                if not tweet_text or not str(tweet_text).strip():
                    continue

                tweet_text = self.reverse_nitter_urls(tweet_text)
                images, video_url = self._parse_media(media_extended)

                # Quote tweet (vxtwitter: qrt, fxtwitter: quote)
                quote = self._parse_qrt(payload.get("qrt"))
                if not quote and isinstance(payload.get("tweet"), dict):
                    quote = self._parse_qrt(payload["tweet"].get("quote"))

                tweet_text, detected_lang_base = self.translate_tweet_text(str(tweet_text), detected_lang)

                return {
                    "text": str(tweet_text),
                    "images": images,
                    "video_url": video_url,
                    "has_video": video_url is not None,
                    "detected_lang": detected_lang_base,
                    "author_name": author_name or username,
                    "user_screen_name": author_screen_name or username,
                    # "author_avatar": author_avatar,
                    "date_epoch": payload.get("date_epoch"),
                    "quote": quote,
                }
            except Exception as error:
                print(f"Fallback API error on {endpoint}: {error}")

        return empty

    def build_tweet_view(self, username: str, twitter_url: str, fixed_link: str, tweet_data: dict, is_spoiler: bool) -> discord.ui.LayoutView:
        """Build a Components V2 LayoutView for a tweet."""
        view = discord.ui.LayoutView()

        # Build description lines
        lines = []
        resolved_username = tweet_data.get("user_screen_name") or username
        display_name = tweet_data.get("author_name") or resolved_username
        lines.append(f"**{display_name}** · [@{resolved_username}](https://x.com/{resolved_username})")

        if tweet_data.get("text"):
            lines.append("")
            lines.append(tweet_data["text"])

        text_content = "\n".join(lines)

        # Section with text + thumbnail (author avatar)
        children = []
        # if tweet_data.get("author_avatar"):
        #     children.append(
        #         discord.ui.Section(
        #             discord.ui.TextDisplay(text_content),
        #             accessory=discord.ui.Thumbnail(media=tweet_data["author_avatar"]),
        #         )
        #     )
        # else:
        children.append(discord.ui.TextDisplay(text_content))

        # Media gallery (images and/or video)
        media_urls = list(tweet_data.get("images", []))[:4]
        if tweet_data.get("video_url"):
            media_urls.insert(0, tweet_data["video_url"])
        if media_urls:
            gallery = discord.ui.MediaGallery()
            for url in media_urls:
                gallery.add_item(media=url)
            children.append(gallery)

        # Quote tweet
        quote = tweet_data.get("quote")
        if quote and isinstance(quote, dict):
            children.append(discord.ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.small))
            q_author = quote.get("author_name") or quote.get("username") or ""
            q_username = quote.get("username") or ""
            q_text = quote.get("text") or ""

            # Translate quote text if needed
            if q_text:
                q_lang = self.detect_language(q_text)
                q_translated, _ = self.translate_tweet_text(q_text, q_lang)
                q_text = q_translated

            if q_username:
                q_header = f"> [Repost](https://x.com/{username}/status/{twitter_url.rstrip('/').split('/')[-1]}) de **{q_author}** · [@{q_username}](https://x.com/{q_username})"
            else:
                q_header = ""

            q_all_lines = []
            if q_header:
                q_all_lines.append(q_header)

            if q_text:
                quoted_text = "\n".join(f"> {line}" if line.strip() else "> " for line in q_text.split("\n"))
                q_all_lines.append(quoted_text)
            children.append(discord.ui.TextDisplay("\n".join(q_all_lines)))

            # Quote media
            q_media_urls = list(quote.get("images", []))[:4]
            if quote.get("video_url"):
                q_media_urls.insert(0, quote["video_url"])
            if q_media_urls:
                q_gallery = discord.ui.MediaGallery()
                for url in q_media_urls:
                    q_gallery.add_item(media=url)
                children.append(q_gallery)

        # Footer
        children.append(discord.ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.small))
        footer_parts = ["𝕏", f"[Ouvrir le tweet]({twitter_url})"]
        has_any_video = tweet_data.get("has_video") or (quote and quote.get("video_url"))
        if tweet_data.get("date_epoch"):
            ts = tweet_data["date_epoch"]
            footer_parts.append(f"<t:{ts}:f>")
        lang = tweet_data.get("detected_lang")
        if lang and lang not in ["fr", "en", "zxx", "und", "art", "qme"]:
            lang_names = {
                "ja": "japonais",
                "ko": "coréen",
                "zh": "chinois",
                "de": "allemand",
                "es": "espagnol",
                "pt": "portugais",
                "it": "italien",
                "ru": "russe",
                "ar": "arabe",
                "tr": "turc",
                "nl": "néerlandais",
                "pl": "polonais",
                "sv": "suédois",
                "uk": "ukrainien",
                "th": "thaï",
                "vi": "vietnamien",
            }
            lang_label = lang_names.get(lang, lang)
            footer_parts.append(f"Traduit du {lang_label}")
        children.append(discord.ui.TextDisplay("-# " + " · ".join(footer_parts)))

        container = discord.ui.Container(
            *children,
            spoiler=is_spoiler,
            accent_colour=0x1DA1F2,
        )
        view.add_item(container)
        return view

    @staticmethod
    def _extract_twitter_match(message_content: str) -> Optional[re.Match]:
        """Extract the first Twitter/X status URL match, handling spoiler wrappers."""
        clean_content = re.sub(r"\n+\|\|$", "||", message_content.strip())
        return re.search(
            r"(\|\|\s*)?(https?://(?:x|twitter)\.com/(?:i|[^/\s]+)/status/\d+(?:\?[^\s|]+)?)(\s*\|\|)?",
            clean_content,
            re.MULTILINE,
        )

    async def handle_message(self, message: discord.Message) -> bool:
        """Handle Twitter/X message suppression and Components V2 rendering.

        Returns True when the message was handled as a Twitter/X URL, else False.
        """
        if "https://x.com/" not in message.content and "https://twitter.com/" not in message.content:
            return False

        twitter_match = self._extract_twitter_match(message.content)
        if not twitter_match:
            return False

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

        tweet_data = await self.get_tweet_data(username, tweet_id)

        fixed_link = re.sub(
            r"https?://(?:x\.com|twitter\.com)",
            lambda matched: "https://fixupx.com" if "x.com" in matched.group(0) else "https://fxtwitter.com",
            twitter_url,
        )

        # No data at all: just send the fixed link
        if not tweet_data["text"] and not tweet_data["images"] and not tweet_data.get("video_url"):
            await message.edit(suppress=True)
            await message.channel.send(f"🔗 [Fixed]({fixed_link})", silent=True)
            return True

        await message.edit(suppress=True)
        tweet_view = self.build_tweet_view(username, twitter_url, fixed_link, tweet_data, is_spoiler)

        try:
            await message.channel.send(view=tweet_view, silent=True)
        except Exception as error:
            print(f"[Tweet Embed Error] {type(error).__name__}: {error}")
            await message.channel.send(f"🔗 [Fixed]({fixed_link})", silent=True)

        return True

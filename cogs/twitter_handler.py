import asyncio
import logging
import re
from time import monotonic
from collections import OrderedDict
from copy import deepcopy
from typing import Optional

import deepl
import discord
import httpx
from fast_langdetect import detect

from settings import DEEPL_API_KEY


class TwitterComponentHandler:
    def __init__(self, *, cache_ttl=300, cache_size=256, concurrency=4,
                 max_pending=16, queue_timeout=5):
        if min(cache_ttl, cache_size, concurrency, max_pending, queue_timeout) <= 0:
            raise ValueError("Twitter limits must be positive")
        self.translator = deepl.Translator(DEEPL_API_KEY) if DEEPL_API_KEY else None
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(10, connect=5, pool=5),
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
        )
        self._cache_ttl = cache_ttl
        self._cache_size = cache_size
        self._cache = OrderedDict()
        self._inflight = {}
        self._slots = asyncio.Semaphore(concurrency)
        self._max_pending = max_pending
        self._queue_timeout = queue_timeout
        self._request_timeout = 20
        self._closed = False

    async def close(self):
        self._closed = True
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._cache.clear()
        await self.client.aclose()

    async def _request(self, endpoint):
        # HTTPX timeouts cover inactivity; this also caps the whole HTTP request.
        async with asyncio.timeout(self._request_timeout):
            return await self.client.get(endpoint)

    def prepare_text(self, text, language):
        try:
            return self.translate_tweet_text(text, language)
        except Exception:
            logging.exception("Tweet translation failed; keeping original text")
            return self.translate_tweet_text(text, None)

    def prepare_quote(self, quote):
        text = quote.get("text") or ""
        quote["text"], _ = self.prepare_text(text, self.detect_language(text))

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
        if self.translator and detected_lang_base and detected_lang_base not in ["fr", "en", "zxx", "und", "art", "qme"]:
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

        return tweet_text, detected_lang_base if self.translator else None

    async def resolve_username_from_i_status(self, tweet_id: str) -> Optional[str]:
        """Resolve the tweet author when URL uses /i/status/<tweet_id> via vxtwitter/fxtwitter."""
        endpoints = [
            f"https://api.vxtwitter.com/i/status/{tweet_id}",
            f"https://api.fxtwitter.com/i/status/{tweet_id}",
        ]
        for endpoint in endpoints:
            try:
                response = await self._request(endpoint)
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
        """Cache normalized data, sharing work by tweet ID across URL variants."""
        if self._closed:
            return {}
        now = monotonic()
        for key, (expires, _) in list(self._cache.items()):
            if expires <= now:
                del self._cache[key]
        if tweet_id in self._cache:
            self._cache.move_to_end(tweet_id)
            return deepcopy(self._cache[tweet_id][1])
        task = self._inflight.get(tweet_id)
        if task is None:
            if len(self._inflight) >= self._max_pending:
                logging.warning("Twitter queue full; using fallback link")
                return {}
            task = asyncio.create_task(self._fetch_cached(username, tweet_id))
            self._inflight[tweet_id] = task
        # Cancelling one message must not cancel a fetch shared by other messages.
        return deepcopy(await asyncio.shield(task))

    async def _fetch_cached(self, username, tweet_id):
        acquired = False
        try:
            try:
                await asyncio.wait_for(self._slots.acquire(), self._queue_timeout)
                acquired = True
            except TimeoutError:
                logging.warning("Twitter queue wait expired; using fallback link")
                return {}
            if username == "i":
                username = await self.resolve_username_from_i_status(tweet_id) or username
            data = await self._get_tweet_data_from_api(username, tweet_id)
            if any(data.get(key) for key in ("text", "images", "video_url", "quote")):
                self._cache[tweet_id] = (monotonic() + self._cache_ttl, deepcopy(data))
                self._cache.move_to_end(tweet_id)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            return data
        except Exception:
            logging.exception("Twitter fetch failed; using fallback link")
            return {}
        finally:
            if acquired:
                self._slots.release()
            self._inflight.pop(tweet_id, None)

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
            [f for f in facets if isinstance(f, dict) and isinstance(f.get("indices"), list)
             and len(f["indices"]) == 2 and all(isinstance(i, int) for i in f["indices"])],
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
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    images.append(url)
            elif media_type in ["video", "gif", "animated_gif"]:
                url = media.get("url") or media.get("video_url")
                if isinstance(url, str) and url.startswith(("https://", "http://")) and not video_url:
                    video_url = url
        return images, video_url

    @staticmethod
    def _parse_qrt(qrt: dict) -> Optional[dict]:
        """Normalize both vxtwitter quotes and fxtwitter nested statuses."""
        if not isinstance(qrt, dict):
            return None
        text = TwitterComponentHandler.render_fxtwitter_raw_text(qrt.get("raw_text")) or qrt.get("text") or ""
        author = qrt.get("author") if isinstance(qrt.get("author"), dict) else {}
        author_name = qrt.get("user_name") or author.get("name") or qrt.get("user_screen_name") or ""
        username = qrt.get("user_screen_name") or author.get("screen_name") or ""
        qrt_id = qrt.get("tweetID") or qrt.get("id")
        media = qrt.get("media") if isinstance(qrt.get("media"), dict) else {}
        media_extended = qrt.get("media_extended") or media.get("all", [])
        images, video_url = TwitterComponentHandler._parse_media(media_extended)
        if not str(text).strip() and not images and not video_url:
            return None
        return {
            "text": str(text),
            "author_name": author_name,
            "username": username,
            "id": qrt_id,
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
                response = await self._request(endpoint)

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
                if isinstance(payload.get("tweet"), dict):
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

                tweet_text = self.reverse_nitter_urls(str(tweet_text or ""))
                images, video_url = self._parse_media(media_extended)

                # Quote tweet (vxtwitter: qrt, fxtwitter: quote)
                quote = self._parse_qrt(payload.get("qrt"))
                if not quote and isinstance(payload.get("tweet"), dict):
                    quote = self._parse_qrt(payload["tweet"].get("quote"))

                if not tweet_text.strip() and not images and not video_url and not quote:
                    continue

                tweet_text, detected_lang_base = await asyncio.to_thread(self.prepare_text, str(tweet_text), detected_lang)
                if quote:
                    await asyncio.to_thread(self.prepare_quote, quote)

                return {
                    "text": str(tweet_text),
                    "images": images,
                    "video_url": video_url,
                    "has_video": video_url is not None,
                    "detected_lang": detected_lang_base,
                    "author_name": author_name or username,
                    "user_screen_name": author_screen_name or username,
                    # "author_avatar": author_avatar,
                    "date_epoch": payload.get("date_epoch") or (
                        payload["tweet"].get("created_timestamp") if isinstance(payload.get("tweet"), dict) else None
                    ),
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
        children.append(discord.ui.TextDisplay(self._shorten(text_content, 2400)))

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

            if q_username:
                q_id = quote.get("id")
                q_url = f"https://x.com/{q_username}/status/{q_id}" if q_id else f"https://x.com/{q_username}"
                q_header = f"> [Repost]({q_url}) de **{q_author}** · [@{q_username}](https://x.com/{q_username})"
            else:
                q_header = ""

            q_all_lines = []
            if q_header:
                q_all_lines.append(q_header)

            if q_text:
                quoted_text = "\n".join(f"> {line}" if line.strip() else "> " for line in q_text.split("\n"))
                q_all_lines.append(quoted_text)
            # A single quoted image fits beside the text as a thumbnail.
            # Keep galleries for videos and multiple images so every media stays visible.
            q_images = list(quote.get("images") or [])[:4]
            q_video = quote.get("video_url")
            q_content = self._shorten("\n".join(q_all_lines) or "> Repost", 1200)
            if len(q_images) == 1 and not q_video:
                children.append(discord.ui.Section(
                    discord.ui.TextDisplay(q_content),
                    accessory=discord.ui.Thumbnail(media=q_images[0]),
                ))
            else:
                children.append(discord.ui.TextDisplay(q_content))
                q_media_urls = ([q_video] if q_video else []) + q_images
                if q_media_urls:
                    q_gallery = discord.ui.MediaGallery()
                    for url in q_media_urls:
                        q_gallery.add_item(media=url)
                    children.append(q_gallery)

        # Footer
        children.append(discord.ui.Separator(visible=True, spacing=discord.enums.SeparatorSpacing.small))
        footer_parts = ["𝕏", f"[Ouvrir le tweet]({twitter_url})"]
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
        children.append(discord.ui.TextDisplay(self._shorten("-# " + " · ".join(footer_parts), 400)))

        container = discord.ui.Container(
            *children,
            spoiler=is_spoiler,
            accent_colour=0x1DA1F2,
        )
        view.add_item(container)
        return view

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        # Count UTF-16 units conservatively, including emoji and Markdown URLs.
        encoded = text.encode("utf-16-le")
        if len(encoded) <= limit * 2:
            return text
        suffix = "\n… (suite dans le tweet original)"
        prefix = encoded[:(limit - len(suffix)) * 2].decode("utf-16-le", errors="ignore")
        # Avoid leaving an unfinished Markdown link in the excerpt.
        if prefix.rfind("[") > prefix.rfind(")"):
            prefix = prefix[:prefix.rfind("[")]
        return prefix.rstrip() + suffix

    @staticmethod
    def _extract_twitter_match(message_content: str) -> Optional[re.Match]:
        """Extract the first Twitter/X status URL match, handling spoiler wrappers."""
        return re.search(
            r"(\|\|\s*)?(https?://(?:x|twitter)\.com/(?:i|[^/\s]+)/status/\d+(?:\?[^\s|]+)?)(\s*\|\|)?",
            message_content,
            re.MULTILINE,
        )

    async def handle_message(self, message: discord.Message) -> bool:
        """Handle Twitter/X message suppression and Components V2 rendering.

        Returns True when the message was handled as a Twitter/X URL, else False.
        """
        twitter_match = self._extract_twitter_match(message.content)
        if not twitter_match:
            return False

        # Also recognize a link inside a larger spoiler containing other text.
        is_spoiler = (
            message.content[:twitter_match.start(2)].count("||") % 2 == 1
            and "||" in message.content[twitter_match.end(2):]
        )
        twitter_url = twitter_match.group(2)

        parts = [part for part in twitter_url.split("/") if part]
        username_or_i = parts[-3]
        tweet_id = parts[-1].split("?")[0]

        username = username_or_i
        tweet_data = await self.get_tweet_data(username, tweet_id)

        fixed_link = re.sub(
            r"https?://(?:x\.com|twitter\.com)",
            lambda matched: "https://fixupx.com" if "x.com" in matched.group(0) else "https://fxtwitter.com",
            twitter_url,
        )

        has_content = any(tweet_data.get(key) for key in ("text", "images", "video_url", "quote"))
        sent = False
        if has_content:
            try:
                tweet_view = self.build_tweet_view(username, twitter_url, fixed_link, tweet_data, is_spoiler)
                await message.channel.send(
                    view=tweet_view, silent=True, allowed_mentions=discord.AllowedMentions.none()
                )
                sent = True
            except Exception:
                logging.exception("Tweet rendering or sending failed; trying fallback")
        if not sent:
            fallback = f"🔗 [Ouvrir le tweet]({fixed_link})"
            if is_spoiler:
                fallback = f"||{fallback}||"
            try:
                await message.channel.send(
                    fallback, silent=True, suppress_embeds=is_spoiler,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logging.exception("Tweet fallback failed; original preview retained")
                return True
        # Only hide the original once a replacement has been published.
        try:
            await message.edit(suppress=True)
        except discord.HTTPException:
            logging.warning("Cannot suppress original tweet preview", exc_info=True)
        return True

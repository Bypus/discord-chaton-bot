from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord
import httpx

from cogs.twitter_handler import TwitterComponentHandler


URL = 'https://x.com/test/status/123'
IMAGE = 'https://example.com/image.jpg'
VIDEO = 'https://example.com/video.mp4'


def forbidden():
    return discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing permissions')


class TwitterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch('cogs.twitter_handler.DEEPL_API_KEY', ''):
            self.handler = TwitterComponentHandler()
        self.message = SimpleNamespace(
            content=URL, channel=SimpleNamespace(send=AsyncMock()), edit=AsyncMock())

    async def asyncTearDown(self):
        await self.handler.close()

    async def test_send_before_suppress(self):
        async def send(**kwargs):
            self.message.edit.assert_not_awaited()
        self.message.channel.send.side_effect = send
        with patch.object(self.handler, 'get_tweet_data', AsyncMock(return_value={'text': 'hello'})):
            await self.handler.handle_message(self.message)
        self.message.edit.assert_awaited_once_with(suppress=True)

    async def test_both_sends_fail_original_retained(self):
        self.message.channel.send.side_effect = forbidden()
        with patch.object(self.handler, 'get_tweet_data', AsyncMock(return_value={'text': 'hello'})):
            with self.assertLogs(level='ERROR'):
                await self.handler.handle_message(self.message)
        self.message.edit.assert_not_awaited()
        self.assertEqual(self.message.channel.send.await_count, 2)

    async def test_missing_suppress_permission_no_duplicate(self):
        self.message.edit.side_effect = forbidden()
        with patch.object(self.handler, 'get_tweet_data', AsyncMock(return_value={'text': 'hello'})):
            with self.assertLogs(level='WARNING'):
                await self.handler.handle_message(self.message)
        self.message.channel.send.assert_awaited_once()

    async def test_fallback_spoilers_including_surrounding_text(self):
        for content in (f'||{URL}||', f'  || spoiler : {URL}\n||  '):
            with self.subTest(content=content):
                self.message.content = content
                self.message.channel.send.reset_mock()
                with patch.object(self.handler, 'get_tweet_data', AsyncMock(return_value={})):
                    await self.handler.handle_message(self.message)
                call = self.message.channel.send.call_args
                self.assertTrue(call.args[0].startswith('||'))
                self.assertTrue(call.args[0].endswith('||'))
                self.assertTrue(call.kwargs['suppress_embeds'])

    async def test_render_failure_fallback_preserves_spoiler(self):
        self.message.content = f'||{URL}||'
        with patch.object(self.handler, 'get_tweet_data', AsyncMock(return_value={'text': 'hello'})), \
             patch.object(self.handler, 'build_tweet_view', side_effect=ValueError('invalid render')):
            with self.assertLogs(level='ERROR'):
                await self.handler.handle_message(self.message)
        self.assertTrue(self.message.channel.send.call_args.args[0].startswith('||'))
        self.message.edit.assert_awaited_once()

    async def test_media_only_payloads_and_fx_quote(self):
        payloads = [
            {'text': '', 'media_extended': [{'type': 'image', 'url': IMAGE}]},
            {'tweet': {'text': '', 'media': {'all': [{'type': 'video', 'url': VIDEO}]}}},
            {'tweet': {'text': '', 'quote': {
                'id': '456', 'author': {'name': 'Author', 'screen_name': 'author'},
                'text': '', 'media': {'all': [{'type': 'photo', 'url': IMAGE}]},
            }}},
        ]
        for index, payload in enumerate(payloads):
            with self.subTest(index=index):
                with patch.object(self.handler.client, 'get', AsyncMock(return_value=httpx.Response(200, json=payload))):
                    with patch.object(self.handler, 'prepare_quote'):
                        result = await self.handler.get_tweet_data('test', str(index))
                if index == 0:
                    self.assertEqual(result['images'], [IMAGE])
                elif index == 1:
                    self.assertEqual(result['video_url'], VIDEO)
                else:
                    self.assertEqual(result['quote']['username'], 'author')
                    self.assertEqual(result['quote']['images'], [IMAGE])

    async def test_api_failure_uses_second_provider(self):
        responses = [httpx.Response(503), httpx.Response(200, json={
            'tweet': {'text': 'ok', 'created_timestamp': 123, 'author': {'screen_name': 'test'}}})]
        with patch.object(self.handler.client, 'get', AsyncMock(side_effect=responses)):
            result = await self.handler.get_tweet_data('test', '123')
        self.assertEqual(result['text'], 'ok')
        self.assertEqual(result['date_epoch'], 123)

    async def test_long_text_budget_and_visible_quoted_image(self):
        view = self.handler.build_tweet_view('test', URL, URL, {
            'text': '😀' * 5000, 'images': [IMAGE],
            'quote': {'text': 'long\n' * 2000, 'images': [IMAGE], 'username': 'author'},
        }, True)
        components = list(view.walk_children())
        text_units = sum(len(c.content.encode('utf-16-le')) // 2
                         for c in components if isinstance(c, discord.ui.TextDisplay))
        self.assertLessEqual(text_units, 4000)
        self.assertTrue(view.children[0].spoiler)
        self.assertTrue(any(isinstance(c, discord.ui.Thumbnail) for c in components))
        self.assertTrue(any(isinstance(c, discord.ui.MediaGallery) for c in components))
        self.assertIn('suite dans le tweet original', str(view.to_components()))

    async def test_quote_video_stays_visible(self):
        view = self.handler.build_tweet_view('test', URL, URL, {
            'quote': {'video_url': VIDEO, 'text': '', 'images': []},
        }, False)
        self.assertIn(VIDEO, str(view.to_components()))
        self.assertTrue(any(isinstance(c, discord.ui.MediaGallery) for c in view.walk_children()))

    async def test_malformed_facets_ignored(self):
        result = self.handler.render_fxtwitter_raw_text({
            'text': 'hello', 'facets': [{'indices': ['bad', 2]}, {'indices': [0, 5], 'replacement': 'ok'}],
        })
        self.assertEqual(result, 'ok')

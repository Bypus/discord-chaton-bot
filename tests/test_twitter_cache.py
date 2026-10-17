import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cogs.twitter_handler import TwitterComponentHandler


class TwitterCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch('cogs.twitter_handler.DEEPL_API_KEY', ''), \
             patch('cogs.twitter_handler.httpx.AsyncClient') as client:
            client.return_value.aclose = AsyncMock()
            self.handler = TwitterComponentHandler(cache_size=2, concurrency=1, max_pending=2)

    async def asyncTearDown(self):
        await self.handler.close()

    async def test_cache_copy_expiry_and_lru(self):
        fetch = AsyncMock(return_value={'text': 'hello', 'images': ['image']})
        with patch.object(self.handler, '_get_tweet_data_from_api', fetch), \
             patch('cogs.twitter_handler.monotonic', return_value=100) as clock:
            result = await self.handler.get_tweet_data('user', '1')
            result['images'].clear()
            self.assertEqual((await self.handler.get_tweet_data('other', '1'))['images'], ['image'])
            await self.handler.get_tweet_data('user', '2')
            await self.handler.get_tweet_data('user', '1')
            await self.handler.get_tweet_data('user', '3')
            self.assertEqual(list(self.handler._cache), ['1', '3'])
            self.assertEqual(fetch.await_count, 3)
            clock.return_value = 401
            await self.handler.get_tweet_data('user', '1')
            self.assertEqual(fetch.await_count, 4)

    async def test_same_tweet_shared_and_waiter_cancellation_isolated(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def fetch(*args):
            started.set()
            await release.wait()
            return {'text': 'ok'}
        with patch.object(self.handler, '_get_tweet_data_from_api', AsyncMock(side_effect=fetch)) as mocked:
            first = asyncio.create_task(self.handler.get_tweet_data('user', '1'))
            await started.wait()
            second = asyncio.create_task(self.handler.get_tweet_data('other', '1'))
            await asyncio.sleep(0)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            release.set()
            self.assertEqual(await second, {'text': 'ok'})
            mocked.assert_awaited_once()

    async def test_concurrency_and_pending_cap(self):
        started, release = asyncio.Event(), asyncio.Event()
        active = peak = 0
        async def fetch(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.set()
            await release.wait()
            active -= 1
            return {'text': 'ok'}
        with patch.object(self.handler, '_get_tweet_data_from_api', side_effect=fetch):
            first = asyncio.create_task(self.handler.get_tweet_data('user', '1'))
            await started.wait()
            second = asyncio.create_task(self.handler.get_tweet_data('user', '2'))
            await asyncio.sleep(0)
            with self.assertLogs(level='WARNING'):
                self.assertEqual(await self.handler.get_tweet_data('user', '3'), {})
            release.set()
            await asyncio.gather(first, second)
            self.assertEqual(peak, 1)

    async def test_queue_wait_expires(self):
        self.handler._queue_timeout = 0.01
        await self.handler._slots.acquire()
        try:
            with self.assertLogs(level='WARNING'):
                self.assertEqual(await self.handler.get_tweet_data('user', '1'), {})
            self.assertFalse(self.handler._inflight)
        finally:
            self.handler._slots.release()

    async def test_failure_not_cached(self):
        with patch.object(self.handler, '_get_tweet_data_from_api', AsyncMock(side_effect=[{}, {'text': 'ok'}])) as fetch:
            self.assertEqual(await self.handler.get_tweet_data('user', '1'), {})
            self.assertEqual(await self.handler.get_tweet_data('user', '1'), {'text': 'ok'})
            self.assertEqual(fetch.await_count, 2)

    async def test_http_request_deadline(self):
        self.handler._request_timeout = 0.01
        async def stalled(*args):
            await asyncio.Event().wait()
        self.handler.client.get = AsyncMock(side_effect=stalled)
        with self.assertRaises(TimeoutError):
            await self.handler._request('https://example.com')

    async def test_i_status_resolution_cached_with_tweet(self):
        with patch.object(self.handler, 'resolve_username_from_i_status', AsyncMock(return_value='user')) as resolve, \
             patch.object(self.handler, '_get_tweet_data_from_api', AsyncMock(return_value={'text': 'ok'})) as fetch:
            await self.handler.get_tweet_data('i', '1')
            await self.handler.get_tweet_data('user', '1')
            await self.handler.get_tweet_data('i', '1')
            resolve.assert_awaited_once()
            fetch.assert_awaited_once_with('user', '1')

    async def test_close_cancels_fetches_and_clears_cache(self):
        started = asyncio.Event()
        async def fetch(*args):
            started.set()
            await asyncio.Event().wait()
        with patch.object(self.handler, '_get_tweet_data_from_api', side_effect=fetch):
            waiter = asyncio.create_task(self.handler.get_tweet_data('user', '1'))
            await started.wait()
            await self.handler.close()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertFalse(self.handler._inflight)
            self.assertFalse(self.handler._cache)
            self.assertEqual(await self.handler.get_tweet_data('user', '2'), {})

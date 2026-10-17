import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from cogs.scheduler import PARIS, next_28_at_16h
from cogs.slash_commands import SlashCommandsCog
from resources import hellofreshLib, jowLib, steamLib


class RegressionTests(unittest.TestCase):
    def test_paris_transition_dates(self):
        for month, offset in [(3, 1), (10, 1), (7, 2)]:
            with self.subTest(month=month):
                target = next_28_at_16h(datetime(2026, month, 1, tzinfo=PARIS))
                self.assertEqual(target.day, 28)
                self.assertEqual(target.hour, 16)
                self.assertEqual(target.utcoffset(), timedelta(hours=offset))

    def test_year_rollover(self):
        target = next_28_at_16h(datetime(2026, 12, 28, 16, tzinfo=PARIS))
        self.assertEqual(target, datetime(2027, 1, 28, 16, tzinfo=PARIS))

    def test_empty_owned_games(self):
        with patch.object(steamLib.steam.users, 'get_owned_games', return_value={'games': []}):
            self.assertIsNone(steamLib.get_random_game('test'))

    def test_empty_wishlist(self):
        with patch.object(steamLib.steam.users, 'get_profile_wishlist', return_value={}):
            self.assertIsNone(steamLib.get_wishlist_game('test'))

    def test_no_hellofresh_matches_returns_embed_list(self):
        result = hellofreshLib.get_recipe_embed('zzzzzzzz-no-recipe')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, 'No matching recipes found')

    def test_jow_fewer_results_than_requested(self):
        recipe = SimpleNamespace(name='Test', url='https://example.com', description='Test',
                                 imageUrl='https://example.com/image.png', preparationTime=1,
                                 preparationExtraTimePerCover=0, cookingTime=1, ingredients=[])
        with patch.object(jowLib.Jow, 'search', return_value=[recipe]):
            self.assertEqual(len(jowLib.get_recipe_embed('test', 5)), 1)

    def test_jow_no_results(self):
        with patch.object(jowLib.Jow, 'search', return_value=[]):
            self.assertEqual(jowLib.get_recipe_embed('test', 5), [])


class AsyncRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_command_acknowledges_and_runs_off_event_loop(self):
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()),
                                      edit_original_response=AsyncMock())
        loop = asyncio.get_running_loop()

        def search(*args):
            interaction.response.defer.assert_awaited_once()
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            return []

        with patch.object(jowLib, 'get_recipe_embed', side_effect=search):
            await SlashCommandsCog.jaifaim.callback(SlashCommandsCog(None), interaction, 'test')
        self.assertIs(asyncio.get_running_loop(), loop)
        interaction.edit_original_response.assert_awaited_once_with(
            content='Aucune recette trouvée pour ces ingrédients.', embeds=[])


if __name__ == '__main__':
    unittest.main()

import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from resources import hellofreshLib, jowLib, steamLib, weatherLib
from settings import STEAM_ID_DEFAULT


class WeatherDateSelect(discord.ui.Select):
    def __init__(self, city: str, requester_id: int):
        self.city = city
        self.requester_id = requester_id

        options = [
            discord.SelectOption(label=label, value=value)
            for label, value in weatherLib.get_next_days_options(14)
        ]

        super().__init__(
            placeholder="Sélectionne une date",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Ce sélecteur ne t'est pas destiné.",
                ephemeral=True,
            )
            return

        selected_date = self.values[0]
        await interaction.response.defer()
        try:
            embed = await asyncio.to_thread(weatherLib.get_weather_embed, self.city, selected_date)
            await interaction.edit_original_response(content=None, embed=embed, view=None)
        except ValueError as error:
            await interaction.edit_original_response(content=str(error), embed=None, view=None)
        except Exception:
            logging.exception("Weather request failed")
            await interaction.edit_original_response(
                content="Impossible de récupérer la météo pour le moment.",
                embed=None,
                view=None,
            )


class WeatherDateView(discord.ui.View):
    def __init__(self, city: str, requester_id: int):
        super().__init__(timeout=120)
        self.add_item(WeatherDateSelect(city, requester_id))


class SlashCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(self, interaction, error):
        logging.error("Slash command failed", exc_info=(type(error), error, error.__traceback__))
        text = "Impossible de récupérer les données pour le moment. Réessaie plus tard."
        if interaction.response.is_done():
            await interaction.edit_original_response(content=text, embeds=[], view=None)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="mennuie", description="Propose 1 jeu Steam à partir des listes de FlugButt.")
    @app_commands.describe(
        steam_id="Propose 1 jeu Steam à partir de ton ID Steam.",
        wish="Propose également 1 jeu de la wishlist.",
    )
    @app_commands.choices(
        wish=[
            app_commands.Choice(name="Oui", value=1),
            app_commands.Choice(name="Non", value=0),
        ]
    )
    async def mennuie(
        self,
        interaction: discord.Interaction,
        steam_id: str = STEAM_ID_DEFAULT,
        wish: Optional[app_commands.Choice[int]] = None,
    ):
        await interaction.response.defer(thinking=True)
        game_rand = await asyncio.to_thread(steamLib.get_random_game, steam_id)
        wish_value = wish.value if isinstance(wish, app_commands.Choice) else 1

        if game_rand is None:
            await interaction.edit_original_response(
                content="Je ne trouve pas de jeu avec cet ID. Les jeux du profil sont privés ?",
            )
            return

        embeds = [await asyncio.to_thread(steamLib.get_embed, game_rand)]
        if wish_value == 1:
            game_wish = await asyncio.to_thread(steamLib.get_wishlist_game, steam_id)
            if game_wish is not None:
                embeds.append(await asyncio.to_thread(steamLib.get_embed, game_wish))
        await interaction.edit_original_response(embeds=embeds)

    @app_commands.command(name="jaifaim", description="Propose des recettes de Jow.")
    @app_commands.describe(
        ingredients="Précise un ou plusieurs ingrédients que tu aimerais cuisiner.",
        nombredeplats="Combien d'idées de recette veux tu ? (1 par défaut)",
        couverts="Combien de parts ? (2 par défaut)",
    )
    async def jaifaim(
        self,
        interaction: discord.Interaction,
        ingredients: str,
        nombredeplats: app_commands.Range[int, 1, 5] = 1,
        couverts: app_commands.Range[int, 1, 100] = 2,
    ):
        await interaction.response.defer(thinking=True)
        embeds = await asyncio.to_thread(jowLib.get_recipe_embed, ingredients, nombredeplats, couverts)
        await interaction.edit_original_response(
            content=None if embeds else "Aucune recette trouvée pour ces ingrédients.",
            embeds=embeds,
        )

    @app_commands.command(name="jaitresfaim", description="Propose des recettes de HelloFresh.")
    @app_commands.describe(
        ingredients="Précise un ou plusieurs ingrédients que tu aimerais cuisiner.",
        facile="Précise si tu veux une recette élaborée ou non.",
    )
    @app_commands.choices(
        facile=[
            app_commands.Choice(name="Oui", value=1),
            app_commands.Choice(name="Non", value=0),
        ]
    )
    async def jaitresfaim(
        self,
        interaction: discord.Interaction,
        ingredients: str,
        facile: Optional[app_commands.Choice[int]] = None,
    ):
        facile_value = facile.value if isinstance(facile, app_commands.Choice) else 1
        await interaction.response.defer(thinking=True)
        embeds = await asyncio.to_thread(hellofreshLib.get_recipe_embed, ingredients, facile_value)
        await interaction.edit_original_response(embeds=embeds)

    @app_commands.command(name="meteo", description="Affiche la météo prévue pour un jour donné.")
    @app_commands.describe(
        ville="Ville à rechercher (ex: Paris)",
    )
    async def meteo(
        self,
        interaction: discord.Interaction,
        ville: str,
    ):
        view = WeatherDateView(ville, interaction.user.id)
        await interaction.response.send_message(
            "Choisis une date (14 prochains jours) pour afficher la météo.",
            view=view,
            ephemeral=True,
        )
        return

    @app_commands.command(name="status", description="Change le statut du bot.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(text="Le texte du statut.", activity_type="Le type d'activité.")
    @app_commands.choices(
        activity_type=[
            app_commands.Choice(name="Joue", value=0),
            app_commands.Choice(name="Stream", value=1),
            app_commands.Choice(name="Écoute", value=2),
            app_commands.Choice(name="Regarde", value=3),
            app_commands.Choice(name="Custom", value=4),
            app_commands.Choice(name="Classée", value=5),
        ]
    )
    async def status(
        self,
        interaction: discord.Interaction,
        text: str,
        activity_type: app_commands.Choice[int],
    ):
        try:
            if activity_type.value == 0:
                activity = discord.Game(name=text)
            elif activity_type.value == 1:
                activity = discord.Streaming(name=text, url="https://www.twitch.tv/bypus")
            elif activity_type.value == 4:
                activity = discord.CustomActivity(name=text)
            else:
                mapped_type = discord.ActivityType(activity_type.value)
                activity = discord.Activity(type=mapped_type, name=text)

            await self.bot.change_presence(activity=activity)
            await interaction.response.send_message(
                f"Statut changé pour : **{activity_type.name} {text}**",
                ephemeral=True,
            )
        except Exception as error:
            await interaction.response.send_message(
                f"Erreur lors du changement de statut : {error}",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommandsCog(bot))

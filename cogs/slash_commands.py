from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from resources import hellofreshLib, jowLib, steamLib
from settings import STEAM_ID_DEFAULT


class SlashCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
        game_rand = steamLib.get_random_game(steam_id)
        wish_value = wish.value if isinstance(wish, app_commands.Choice) else 1

        if game_rand is None:
            await interaction.response.send_message(
                "Je ne trouve pas de jeu avec cet ID. Les jeux du profil sont privés ?",
                ephemeral=True,
            )
            return

        embeds = [steamLib.get_embed(game_rand)]
        if wish_value == 1:
            game_wish = steamLib.get_wishlist_game(steam_id)
            embeds.append(steamLib.get_embed(game_wish))
        await interaction.response.send_message(embeds=embeds)

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
        nombredeplats: int = 1,
        couverts: int = 2,
    ):
        if nombredeplats > 5:
            nombredeplats = 5
            await interaction.response.send_message(
                "Ça fait beaucoup. Voici 5 recettes au hasard",
                ephemeral=True,
            )
            embeds = jowLib.get_recipe_embed(ingredients, nombredeplats, couverts)
            await interaction.followup.send(embeds=embeds, wait=True)
            return

        embeds = jowLib.get_recipe_embed(ingredients, nombredeplats, couverts)
        await interaction.response.send_message(embeds=embeds)

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
        facile: Optional[app_commands.Choice[int]],
    ):
        facile_value = facile.value if isinstance(facile, app_commands.Choice) else 1
        embeds = hellofreshLib.get_recipe_embed(ingredients, facile_value)
        await interaction.response.send_message(embeds=embeds)

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
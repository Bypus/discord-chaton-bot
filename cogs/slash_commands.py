from typing import Optional
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from resources import hellofreshLib, itadLib, jowLib, steamLib, weatherLib
from settings import FREE_GAMES_CHANNEL_ID, ITAD_API_KEY, ITAD_COUNTRY, STEAM_ID_DEFAULT


STORE_ICONS = {
    "steam": "https://cdn.brandfetch.io/idMpZmhn_O/theme/dark/symbol.svg?c=1bxid64Mup7aczewSAYMX&t=1767337337884",
    "epic game store": "https://upload.wikimedia.org/wikipedia/commons/d/d0/Epic_games_store_logo.png",
    "epic games store": "https://upload.wikimedia.org/wikipedia/commons/d/d0/Epic_games_store_logo.png",
}


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
        try:
            embed = weatherLib.get_weather_embed(self.city, selected_date)
            await interaction.response.edit_message(content=None, embed=embed, view=None)
        except ValueError as error:
            await interaction.response.edit_message(content=str(error), embed=None, view=None)
        except Exception:
            await interaction.response.edit_message(
                content="Impossible de récupérer la météo pour le moment.",
                embed=None,
                view=None,
            )


class WeatherDateView(discord.ui.View):
    def __init__(self, city: str, requester_id: int):
        super().__init__(timeout=120)
        self.add_item(WeatherDateSelect(city, requester_id))


class FreeGamesChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog: "SlashCommandsCog"):
        self.cog = cog
        super().__init__(
            placeholder="Sélectionne un salon pour les deals gratuits",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        if hasattr(channel, "id"):
            self.cog._free_games_channel_id = str(channel.id)
            channel_mention = f"<#{channel.id}>"
            await interaction.response.send_message(
                f"✅ Canal pour les deals gratuits défini à : {channel_mention}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Le canal sélectionné n'est pas valide (type: {type(channel).__name__}).",
                ephemeral=True,
            )


class FreeGamesChannelView(discord.ui.View):
    def __init__(self, cog: "SlashCommandsCog"):
        super().__init__(timeout=300)
        self.add_item(FreeGamesChannelSelect(cog))


class SlashCommandsCog(commands.Cog):
    SCHEDULED_HOURS = [22, 10, 16]  # 22h, 10h, 16h UTC

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._seen_free_game_ids: set[str] = set()
        self._free_games_baseline_ready = False
        self._free_games_channel_id = FREE_GAMES_CHANNEL_ID or ""
        self._free_games_task = None

    async def cog_load(self):
        self._free_games_task = asyncio.create_task(self._free_games_check_loop())

    def cog_unload(self):
        if hasattr(self, "_free_games_task"):
            self._free_games_task.cancel()

    def _build_free_game_embed(self, game: dict[str, object], appid: int | None = None) -> discord.Embed:
        title = str(game.get("title") or "Jeu sans titre")
        shop = str(game.get("shop") or "Store inconnu")
        summary = str(game.get("summary") or "Free for a limited time")
        rating = str(game.get("rating") or "")
        tags = game.get("tags")
        url = str(game.get("url") or "")
        banner_url = str(game.get("banner_url") or "")
        shop_lower = shop.lower()

        description = summary
        if rating:
            description = f"{summary}  {rating}"

        embed = discord.Embed(
            title=title,
            url=url or None,
            description=description,
            color=discord.Color.green(),
        )

        # embed.add_field(name="Store", value=shop, inline=True)

        if url:
            embed.add_field(name="Voir l'offre", value=f"[Ouvrir dans le navigateur ⮺]({url})", inline=True)
        if shop_lower == "steam" and appid:
            open_app_url = f"https://www.jorisstocker.ovh/open-app/steam/{appid}"
            embed.add_field(name="Steam", value=f"[Ouvrir dans Steam ⮺]({open_app_url})", inline=True)
        elif "epic" in shop_lower and appid:
            open_app_url = f"https://www.jorisstocker.ovh/open-app/epic/{appid}"
            embed.add_field(name="Epic", value=f"[Ouvrir dans Epic ⮺]({open_app_url})", inline=True)

        if isinstance(tags, list) and tags:
            tags_text = " | ".join(f"**{tag}**" for tag in tags[:5])
            embed.add_field(name="Tags", value=tags_text, inline=False)

        icon_url = STORE_ICONS.get(shop_lower)
        if icon_url:
            embed.set_thumbnail(url=icon_url)

        if banner_url:
            embed.set_image(url=banner_url)

        embed.timestamp = discord.utils.utcnow()

        embed.set_footer(text="IsThereAnyDeal")
        return embed

    async def _send_free_games_alerts(
        self,
        channel: discord.abc.Messageable,
        games: list[dict[str, object]],
    ) -> None:
        for game in games[:5]:
            url = str(game.get("url") or "")
            shop = str(game.get("shop") or "")
            raw_appid = game.get("appid")
            appid: int | None
            if isinstance(raw_appid, int):
                appid = raw_appid
            elif isinstance(raw_appid, str) and raw_appid.isdigit():
                appid = int(raw_appid)
            else:
                appid = None
            embed = self._build_free_game_embed(game, appid)
            await channel.send(embed=embed)

        extra_count = len(games) - 5
        if extra_count > 0:
            await channel.send(f"... et {extra_count} autre(s) jeu(x) gratuit(s).")

    async def _free_games_check_loop(self):
        await self.bot.wait_until_ready()
        while True:
            now = discord.utils.utcnow()
            if now.hour in self.SCHEDULED_HOURS:
                await self._execute_free_games_check()

            hours_list = sorted(self.SCHEDULED_HOURS)
            next_target_hour = None
            for h in hours_list:
                if h > now.hour:
                    next_target_hour = h
                    break

            if next_target_hour is None:
                next_target_hour = hours_list[0]
                hours_diff = 24 - now.hour + next_target_hour
            else:
                hours_diff = next_target_hour - now.hour

            delay_seconds = hours_diff * 3600 - now.minute * 60 - now.second
            await asyncio.sleep(delay_seconds)

    async def _execute_free_games_check(self):
        if not ITAD_API_KEY:
            return

        try:
            free_games = await itadLib.fetch_free_deals_with_info(ITAD_API_KEY, country=ITAD_COUNTRY)
        except Exception as error:
            print(f"ITAD free games check failed: {error}")
            return

        current_ids = {game["id"] for game in free_games if "id" in game}
        if not self._free_games_baseline_ready:
            self._seen_free_game_ids = current_ids
            self._free_games_baseline_ready = True
            return

        new_ids = current_ids - self._seen_free_game_ids
        self._seen_free_game_ids = current_ids
        if not new_ids:
            return

        if not self._free_games_channel_id:
            print("[ITAD] Free games channel is not configured, skipping free games alert.")
            return

        try:
            channel = self.bot.get_channel(int(self._free_games_channel_id))
        except ValueError as e:
            print(f"[ITAD] Free games channel ID '{self._free_games_channel_id}' is invalid: {e}")
            return

        if not isinstance(channel, discord.abc.Messageable):
            print(f"[ITAD] Configured free games channel (ID {self._free_games_channel_id}) was not found or is not messageable (type: {type(channel).__name__ if channel else 'None'}).")
            return

        new_games = [game for game in free_games if game.get("id") in new_ids]
        new_games.sort(key=lambda game: game.get("title", ""))

        await self._send_free_games_alerts(channel, new_games)

    @app_commands.command(name="check_free_games", description="Force une vérification immédiate des jeux gratuits.")
    @app_commands.default_permissions(administrator=True)
    async def check_free_games(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not ITAD_API_KEY:
            await interaction.followup.send(
                "❌ ITAD_API_KEY n'est pas configurée.",
                ephemeral=True,
            )
            return

        try:
            free_games = await itadLib.fetch_free_deals_with_info(ITAD_API_KEY, country=ITAD_COUNTRY)
        except Exception as error:
            await interaction.followup.send(
                f"❌ Erreur lors de la vérification ITAD : {error}",
                ephemeral=True,
            )
            return

        current_ids = {game["id"] for game in free_games if "id" in game}
        new_ids = current_ids - self._seen_free_game_ids
        self._seen_free_game_ids = current_ids

        if not new_ids:
            await interaction.followup.send(
                f"ℹ️ Aucun nouveau jeu gratuit trouvé. ({len(current_ids)} jeux gratuits actuels)",
                ephemeral=True,
            )
            return

        if not self._free_games_channel_id:
            await interaction.followup.send(
                f"⚠️ {len(new_ids)} nouveau(x) jeu(x) gratuit(s) détecté(s), mais aucun canal n'est configuré.",
                ephemeral=True,
            )
            return

        try:
            channel = self.bot.get_channel(int(self._free_games_channel_id))
        except ValueError as e:
            await interaction.followup.send(
                f"❌ Le canal ID '{self._free_games_channel_id}' n'est pas valide (erreur: {e}). Utilise `/setup_free_games_channel` pour configurer.",
                ephemeral=True,
            )
            return

        if not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send(
                f"❌ Le canal avec l'ID {self._free_games_channel_id} n'est pas un salon textuel (type: {type(channel).__name__ if channel else 'None'}).",
                ephemeral=True,
            )
            return

        new_games = [game for game in free_games if game.get("id") in new_ids]
        new_games.sort(key=lambda game: game.get("title", ""))

        await self._send_free_games_alerts(channel, new_games)
        await interaction.followup.send(
            f"✅ Alerte envoyée! {len(new_games)} nouveau(x) jeu(x) gratuit(s).",
            ephemeral=True,
        )

    @app_commands.command(name="setup_free_games_channel", description="Configure le canal pour les alertes de jeux gratuits.")
    @app_commands.default_permissions(administrator=True)
    async def setup_free_games_channel(self, interaction: discord.Interaction):
        view = FreeGamesChannelView(self)
        await interaction.response.send_message(
            "Clique sur le menu ci-dessous pour sélectionner le canal des deals gratuits:",
            view=view,
            ephemeral=True,
        )

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
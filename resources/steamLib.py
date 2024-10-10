from calendar import c
import os
import time
import datetime
import locale
import random
import discord
from steam_web_api import Steam

locale.setlocale(locale.LC_ALL, '')

KEY = os.environ.get("STEAM_API_KEY")
steam = Steam(KEY)
current_datetime = int(datetime.datetime.now().timestamp())

def get_random_game(steam_id):
    games = steam.users.get_owned_games(steam_id)
    return random.choice(list(games['games']))

def get_wishlist_game(steam_id):
    wishlist = steam.users.get_profile_wishlist(steam_id)
    array_of_key_value_pairs = [{"appid": key, **value} for key, value in wishlist.items() if int(value.get('release_date', 0)) < current_datetime]

    return random.choice(array_of_key_value_pairs)

def get_steam_game(game):
    return steam.apps.get_app_details(int(game), "FR")

def find_in_dict(d, search_key):
    if isinstance(d, dict):
        for key, value in d.items():
            if key == search_key:
                return value
            elif isinstance(value, dict):
                result = find_in_dict(value, search_key)
                if result:
                    return result
    return None

def get_embed(game):
    ownwish = {}
    appid = game['appid']
    gameEmbed = get_steam_game(appid)
    
    embed = discord.Embed(title=find_in_dict(game, "name"),
                      url="https://store.steampowered.com/app/" + str(appid),
                      description=find_in_dict(gameEmbed, "short_description"),
                      colour=0x00b0f4)

    if 'img_icon_url' in game:
        ownwish["icon"] = "http://media.steampowered.com/steamcommunity/public/images/apps/" + str(appid) + "/" + game['img_icon_url'] + ".jpg"
        ownwish["name"] = "JOUE"
        embed.colour = 0xA2E362
    else:
        ownwish["icon"] = ""
        ownwish["name"] = "ACHETE"
        print(game)
        if 'reviews_percent' in game:
            if game['reviews_percent'] > 80:
                embed.colour = 0x00CE7A
            elif game['reviews_percent'] > 50:
                embed.colour = 0xFFBD3F
            else:
                embed.colour = 0xFF6874
        else:
            embed.colour = 0x9C5B4B
    embed.set_author(name=ownwish["name"],
                    icon_url=ownwish["icon"])

    if ('playtime_forever' in game):
        playtime = game['playtime_forever']
        if  playtime == 0:
            playtime_str = "Jamais joué"
        elif playtime < 60:
            playtime_str = f"{playtime} minutes"
        else:
            hours = playtime / 60
            playtime_str = f"{hours:.1f} heure" if hours < 2 else f"{hours:.1f} heures"
        embed.add_field(name="Temps joué",
                        value=playtime_str,
                        inline=True)
        if 'rtime_last_played' in game:
            human_readable_time = datetime.datetime.fromtimestamp(game['rtime_last_played']).strftime('%A %d %B %Y %H:%M:%S') if game['rtime_last_played'] > 0 else "Jamais"
            embed.add_field(name="Dernière session",
                            value=str(human_readable_time),
                            inline=True)
    else:
        embed.add_field(name="Prix",
                        value=str(float(game['subs'][0]['price']) / 100.00) + "€",
                        inline=True)
        
        embed.add_field(name="Avis",
                        value=game['review_desc'],
                        inline=True)

    embed.set_image(url=find_in_dict(gameEmbed, "header_image"))

    return embed
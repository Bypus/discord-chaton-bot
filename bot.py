import asyncio
from shlex import quote
import discord
from discord import app_commands
from discord.ext import tasks, commands
import requests
import httpx

from bs4 import BeautifulSoup
import deepl

from fast_langdetect import detect

import os
import re
import io
import aiohttp
from resources import jowLib, hellofreshLib, nhentai, steamLib
import random
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# Intents setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True

DEEPL = os.environ.get("DEEPL_API_KEY")
translator = deepl.DeepLClient(DEEPL)

# Utilisation de commands.Bot pour une meilleure gestion des commandes
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration du bot
colors = ['Violet', 'Indigo', 'Blue', 'Green', 'Yellow', 'Orange', 'Red']

colorshex = {
    'Violet': 9699539,
    'Indigo': 4915330,
    'Blue': 255,
    'Green': 65280,
    'Yellow': 16776960,
    'Orange': 16744192,
    'Red': 16711680
}

my_activity = discord.Activity(name="comme il fait beau, dehors", type=discord.ActivityType.watching)

def get_book(sauce, emoji):
    book = nhentai.Doujinshi(sauce)
    
    embed = discord.Embed(title=book.name, url="https://nhentai.net/g/" + str(sauce), color=0x80BA25)
    embed.set_author(name=str(sauce))
    embed.set_thumbnail(url=str(book.cover))

    if book.parodies:
        embed.add_field(name="Parodies", value=book.parodies[:-2], inline=False)
    if book.characters:
        embed.add_field(name="Characters", value=book.characters[:-2], inline=False)
    if book.wewo == 1:
        embed.add_field(name="Tags " + str(emoji), value=book.tags[:-2], inline=False)
    else:
        embed.add_field(name="Tags", value=book.tags[:-2], inline=False)
    if book.artists:
        embed.add_field(name="Artists", value=book.artists[:-2], inline=False)
    if book.groups:
        embed.add_field(name="Groups", value=book.groups[:-2], inline=False)
    if book.languages:
        embed.add_field(name="Languages", value=book.languages[:-2], inline=False)

    embed.set_footer(text="Les liens peuvent nécessiter un VPN")

    return embed

# @tasks.loop(hours=24.0)
# async def change_role():
#     colorday = random.choice(colors)
#     colorint = discord.Color(colorshex[colorday])
#     try:
#         chaton_cute_role = bot.get_guild(240567272605876224).get_role(307297743376875520)
#         await chaton_cute_role.edit(name='Rainbow ' + colorday, colour=colorint)
#     except Exception as e:
#         print(f"Error changing role color: {e}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")
    try:
        global chaton_cucks_role
        chaton_cucks_role = bot.get_guild(240567272605876224).get_role(826563068615065719)
        print(f"Cucks role found")
    except Exception as e:
        chaton_cucks_role = ""
        print(f"Cucks role not found")
    await bot.change_presence(activity=my_activity)
    # change_role.start()

async def test(ctx, arg):
    await ctx.send(arg)

@bot.tree.command(name="mennuie", description="Propose 1 jeu Steam à partir des listes de FlugButt.")
@app_commands.describe(steam_id="Propose 1 jeu Steam à partir de ton ID Steam.", wish="Propose également 1 jeu de la wishlist.")
@app_commands.choices(wish=[
    app_commands.Choice(name="Oui", value=1),
    app_commands.Choice(name="Non", value=0),
    ])
async def mennuie(interaction: discord.Interaction, steam_id: str = "76561198037697617", wish: app_commands.Choice[int] = 1):
    gameRand = steamLib.get_random_game(steam_id)
    if (gameRand is None):
        await interaction.response.send_message("Je ne trouve pas de jeu avec cet ID. Les jeux du profil sont privés ?", ephemeral=True)
    else:
        embeds = [steamLib.get_embed(gameRand)]
        if wish == 1:
            gameWish = steamLib.get_wishlist_game(steam_id)
            embeds.append(steamLib.get_embed(gameWish))
        await interaction.response.send_message(embeds=embeds)

@bot.tree.command(name="jaifaim", description="Propose des recettes de Jow.")
@app_commands.describe(ingredients="Précise un ou plusieurs ingrédients que tu aimerais cuisiner.", 
                       nombredeplats="Combien d'idées de recette veux tu ? (1 par défaut)", 
                       couverts="Combien de parts ? (2 par défaut)")
async def jaifaim(interaction: discord.Interaction, ingredients: str, nombredeplats: int = 1, couverts: int = 2):
    if nombredeplats > 5:
        nombredeplats = 5
        await interaction.response.send_message("Ça fait beaucoup. Voici 5 recettes au hasard", ephemeral=True)
        embeds = jowLib.get_recipe_embed(ingredients, nombredeplats, couverts)
        await interaction.followup.send(embeds=embeds, wait=True)
    else:
        embeds = jowLib.get_recipe_embed(ingredients, nombredeplats, couverts)
        await interaction.response.send_message(embeds=embeds)

@bot.tree.command(name="jaitresfaim", description="Propose des recettes de HelloFresh.")
@app_commands.describe(ingredients="Précise un ou plusieurs ingrédients que tu aimerais cuisiner.",
                       facile="Précise si tu veux une recette élaborée ou non.")
@app_commands.choices(facile=[
    app_commands.Choice(name="Oui", value=1),
    app_commands.Choice(name="Non", value=0),
    ])
async def jaitresfaim(interaction: discord.Interaction, ingredients: str, facile: app_commands.Choice[int] = 1):

        embeds = hellofreshLib.get_recipe_embed(ingredients, facile)
        await interaction.response.send_message(embeds=embeds)

@bot.tree.command(name="hbook", description="*NSFW* Montre les informations de la référence passée en argument.")
@app_commands.describe(reference="Numéro de référence du livre.")
@app_commands.choices(nsfw=[
    app_commands.Choice(name="Oui", value=1),
    app_commands.Choice(name="Non", value=0),
    ])
async def hbook(interaction: discord.Interaction, reference: int, nsfw: app_commands.Choice[int]):
    if nsfw.value == 0:
        await interaction.response.send_message("Il est sage de reconsidérer ses choix.\n-# Tu as mis le paramètre NSFW sur '**Non**'.", ephemeral=True)
        return
    
    is_dm = interaction.guild is None  # Vérifier si c'est un DM
    nsfw_shitpost = interaction.channel if is_dm else (
        interaction.guild.get_channel(603314634442932307) if interaction.guild.id == 588460743083687998
        else interaction.guild.get_channel(568885536404668436)
    )
    
    try:
        emoji = discord.utils.get(bot.emojis, name="wewo")
        
        if is_dm:
            await interaction.response.send_message(embed=get_book(reference, emoji))
        else:
            await nsfw_shitpost.send(embed=get_book(reference, emoji))
            await interaction.response.send_message(f"Le livre a été envoyé dans {nsfw_shitpost.mention}.", ephemeral=True)

    except Exception as e:
        with open("resources/error.png", 'rb') as fp:
            await interaction.response.send_message("Une erreur est survenue lors de la recherche de ce livre.", file=discord.File(fp, filename="error400.png"), ephemeral=True)
        
        if interaction.guild:
            cd = bot.get_guild(588460743083687998).get_channel(603314634442932307)
            await cd.send(f"```{str(e)}```")
        else:
            app_info = await bot.application_info()
            owner = app_info.owner
            await owner.send(f"```{str(e)}```")

NITTER_INSTANCE = "https://nitter.net"

def detect_language(text):
    """Uses fast_langdetect to detect the language of a given text."""
    try:
        cleaned_text = text.replace("\n", " ")
        return detect(cleaned_text)['lang']  # Retourne directement le code langue
    except Exception as e:
        return str(e)

def format_as_quote(text):
    """Ajoute '>' devant chaque ligne pour le formatage en citation Discord."""
    return "\n".join(f"> {line}" for line in text.split("\n"))

async def get_tweet_text(username, tweet_id):
    """Récupère et formate le texte d'un tweet depuis Nitter."""
    url = f"{NITTER_INSTANCE}/{username}/status/{tweet_id}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer": NITTER_INSTANCE,
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            response = await client.get(url)

        if response.status_code != 200 or not response.text.strip():
            return None, None, None, None, False, None

        soup = BeautifulSoup(response.text, "html.parser")

        # 📝 Récupération du tweet principal
        tweet_content = soup.find("div", class_="tweet-content")
        # for link in tweet_content.find_all("a"):
        #     href = link.get("href", "")
        #     text = link.get_text(strip=True)

        #     # Vérifie si le texte du lien est tronqué
        #     if ("." in text or "…" in text) and href:
        #         link.replace_with(f"[{text}]({href})")

        tweet_text = tweet_content.get_text("\n", strip=True) if tweet_content else ""

        # 🔗 Correction des liens raccourcis

        # 📸 Détection des images attachées
        attachments = soup.find("div", class_="attachments")
        image_elements = attachments.find_all("img") if attachments else []
        # video_elements = attachments.find_all("video") if attachments else []

        video_count = 0
        if "video" in str(attachments):
            video_count = 1
        image_count = len(image_elements)
        # video_count = len(video_elements)

        # 🔎 Vérifie si le tweet contient exactement UNE image # et AUCUN texte
        has_single_image = image_count == 1 and video_count == 0 # and not tweet_text.strip()

        # 🏷️ Détection de la langue
        detected_lang = None
        if tweet_text.strip():
            detected_lang = detect_language(tweet_text)
            
            # ✍️ Traduction si nécessaire
            if detected_lang not in ["fr", "en"]:
                translated = translator.translate_text(tweet_text, target_lang="FR").text
                lang_flag = "jp" if detected_lang == "ja" else detected_lang
                translated = "\n".join(f"-# {line}" if line.strip() else "" for line in translated.split("\n"))

                tweet_text = f":flag_{lang_flag}: -> :flag_fr:\n{translated}"

        # 🔁 Gestion du quote retweet
        # quote_tweet = soup.find("div", class_="quote")
        # print(f"Quote tweet: {quote_tweet}")
        # quote_text = None
        # quote_author_text = None
        # quote_date_text = None
        # if quote_tweet:
        #     quote_author = quote_tweet.find("a", class_="username")
        #     quote_date = quote_tweet.find("span", class_="tweet-date")
        #     quote_content = quote_tweet.find("div", class_="quote-text")

        #     if quote_author and quote_content:
        #         quote_author_text = quote_author.get_text(strip=True)
        #         quote_date_text = quote_date.get_text(strip=True) if quote_date else ""
        #         quote_text_raw = quote_content.get_text("\n", strip=True).rstrip("\n")
        #         quote_text = format_as_quote(quote_text_raw)

        return tweet_text, has_single_image, detected_lang # quote_text, quote_author_text, quote_date_text, 

    except httpx.RequestError:
        return None, None, None, None, False, None

@bot.listen()
async def on_message(message):
    if message.author == bot.user:
        return

    if message.mention_everyone:
        emojie = discord.utils.get(bot.emojis, name="angerypingcircle")
        await message.add_reaction(emojie)

    if "https://x.com/" in message.content or "https://twitter.com/" in message.content:
        clean_content = re.sub(r"\n+\|\|$", "||", message.content.strip())
        twitter_match = re.search(r"(\|\|)?(https?://(?:x|twitter)\.com/[^/]+/status/\d+)(\|\|)?", clean_content)
        is_spoiler = twitter_match and twitter_match.group(1) == "||" and twitter_match.group(3) == "||"
        twitter_url = twitter_match.group(2)
        
        username, tweet_id = twitter_url.split("/")[-3], twitter_url.split("/")[-1]
        tweet_text, has_single_image, detected_lang = await get_tweet_text(username, tweet_id) # quote_text, quote_author, quote_date, 
        

        # g.fixupx.com
        # g.fxtwitter.com
        fixed_link = re.sub(r"https?://(?:x\.com|twitter\.com)", 
                            lambda m: "https://fixupx.com" if "x.com" in m.group(0) else "https://fxtwitter.com", 
                            twitter_match.group(2))
        

        formatted_message = f"🔗 [Fixuped]({fixed_link})\n"

        await message.edit(suppress=True)

        if has_single_image and detected_lang in ["fr", "en"]:
            await message.channel.send(formatted_message, reference=message, mention_author=False)
            return

        # embed_one = discord.Embed(title=f"🔁 Quote Retweet de **{quote_author}** ({quote_date}) :", description=f"{quote_text}", color=discord.Colour.blue())
        # embed_two = discord.Embed(title=f"📢 **Tweet de @{username}**", description=f"{tweet_text}", color=discord.Colour.blue())

        # if quote_text:
        #     formatted_message += f"🔁 Quote Retweet de **{quote_author}** ({quote_date}) :\n*{quote_text}*"

        if detected_lang not in ["fr", "en"]:
            formatted_message += f"{format_as_quote(tweet_text)}" if tweet_text else ""

        if is_spoiler:
            formatted_message = f"||{formatted_message}||"

        # await message.channel.send(content=formatted_message, embeds=[embed_one, embed_two], reference=message, mention_author=False)
        await message.channel.send(formatted_message, reference=message, mention_author=False)

    if "www.reddit.com" in message.content:
        await message.edit(suppress=True)
        modified_content = message.content.replace("reddit.com", "rxddit.com")
        await message.channel.send(f"🔄 [rxddit]({modified_content})", reference=message, mention_author=False)

    if "instagram.com" in message.content:
        await message.edit(suppress=True)
        modified_content = message.content.replace("instagram.com", "instagramez.com")
        await message.channel.send(f"🔄 [EmbedEZ]({modified_content})", reference=message, mention_author=False)

    if "tiktok.com" in message.content:
        await message.edit(suppress=True)
        modified_content = message.content.replace("tiktok.com", "vxtiktok.com")
        await message.channel.send(f"🔄 [EmbedEZ]({modified_content})", reference=message, mention_author=False)

    # if "bilibili.com" in message.content: 
    #     await message.edit(suppress=True)
    #     modified_content = message.content.replace("bilibili.com", "vxbilibili.com")
    #     await message.channel.send(f"🔄 [BiliFix]({modified_content})", reference=message, mention_author=False)

    # if "www.youtube.com" in message.content:
    #     await message.edit(suppress=True)
    #     modified_content = message.content.replace("www.youtube.com", "yt.cdn.13373333.one")
    #     await message.channel.send(f"🔄 [Fixed]({modified_content})", reference=message, mention_author=False)

    if message.content.startswith('n. '):
        # if '<' in message.content:
        result = re.search(r':(.*):', message.content)
        img_url = str(discord.utils.get(bot.emojis, name=result.group(1)).url)
        async with aiohttp.ClientSession() as cs:
            async with cs.get(img_url) as r:
                if r.status != 200:
                    return await message.channel.send('No.')
                data = io.BytesIO(await r.read())
                await message.channel.send(file=discord.File(data, 'blbl.png'))
        await message.delete()

    if (chaton_cucks_role != "") & (chaton_cucks_role in message.role_mentions):
        img_url = str("https://cdn.discordapp.com/emojis/827938389256568832.png?v=1")
        async with aiohttp.ClientSession() as cs:
            async with cs.get(img_url) as r:
                if r.status != 200:
                    return await message.channel.send('No.')
                data = io.BytesIO(await r.read())
                await message.channel.send(file=discord.File(data, 'slurp.png'))

        # global cringe_joke
        # if cringe_joke == 0:
        # await message.channel.send(file=discord.File("./resources/fin_frerot.mp4", filename="Fin frérot...mp4"))
            # cringe_joke = 1

# Lancer le bot
token = os.getenv("TOKEN_BOT_DISCORD")
bot.run(token)

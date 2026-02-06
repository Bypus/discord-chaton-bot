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
from resources import jowLib, hellofreshLib, steamLib
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

DEEPL = os.environ.get("DEEPL_API_KEY", "")
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

# Mapping ISO-639-1 -> Emoji flag ISO-3166
LANG_TO_FLAG = {
    "fr": "fr",  # français
    "en": "gb",  # anglais → drapeau UK (Discord n'a pas :flag_en:)
    "ja": "jp",  # japonais
    "ko": "kr",  # coréen
    "zh": "cn",  # chinois simplifié
    "de": "de",  # allemand
    "es": "es",  # espagnol
}

my_activity = discord.Activity(name="comme il fait beau, dehors", type=discord.ActivityType.watching)

steam_id_fb = os.environ.get("STEAM_ID_FB", "")
guild_test_id = int(os.environ.get("GUILD_TEST_ID", ""))



# @tasks.loop(hours=24.0)
# async def change_role():
#     colorday = random.choice(colors)
#     colorint = discord.Color(colorshex[colorday])
#     try:
#         guild_id = int(os.environ.get("GUILD_ID"))
#         chaton_cute_role = bot.get_guild(guild_id).get_role(307297743376875520)
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
        global chaton_deadcucks_role
        
        # Récupération de l'ID depuis les variables d'environnement
        target_guild_id = os.environ.get("GUILD_ID", "")
        target_cucks_id = os.environ.get("CUCKS_ROLE_ID", "")
        target_deadcucks_id = os.environ.get("DEADCUCKS_ROLE_ID", "")
        
        if target_guild_id and target_cucks_id and target_deadcucks_id:
            chaton_guild = bot.get_guild(int(target_guild_id))
        
            if chaton_guild:
                chaton_cucks_role = chaton_guild.get_role(int(target_cucks_id))
                chaton_deadcucks_role = chaton_guild.get_role(int(target_deadcucks_id))
            else:
                print(f"Le serveur avec l'ID {target_guild_id} n'a pas été trouvé.")
        else:
            print("GUILD_ID, CUCKS_ROLE_ID ou DEADCUCKS_ROLE_ID non défini dans les variables d'environnement.")
    except Exception as e:
        chaton_cucks_role = ""
        chaton_deadcucks_role = ""
        print(f"Cucks role not found: {e}")
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
async def mennuie(interaction: discord.Interaction, steam_id: str = steam_id_fb, wish: app_commands.Choice[int] = 1):
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



NITTER_INSTANCE = "https://nitter.net"

def detect_language(text):
    """Uses fast_langdetect to detect the language of a given text."""
    try:
        cleaned_text = text.replace("\n", " ")
        result = detect(cleaned_text)
        if result and isinstance(result, list):
            return result[0]['lang']  # Prend la première détection
        return None
    except Exception as e:
        # Language detection failed
        return None

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
            return None, None, None
        
        soup = BeautifulSoup(response.text, "html.parser")

        # 📝 Récupération du tweet principal
        tweet_content = soup.find("div", class_="tweet-content")

        tweet_text = tweet_content.get_text("\n", strip=True) if tweet_content else ""

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
            if detected_lang and detected_lang not in ["fr", "en"]:
                translated = translator.translate_text(tweet_text, target_lang="FR").text
                lang_flag = LANG_TO_FLAG.get(detected_lang)  # fallback si non trouvé

                translated = "\n".join(f"-# {line}" if line.strip() else "" for line in translated.split("\n"))

                tweet_text = f":flag_{lang_flag}: -> :flag_fr:\n{translated}"

        return tweet_text, has_single_image, detected_lang # quote_text, quote_author_text, quote_date_text, 

    except httpx.RequestError:
        print("HTTP Request Error while fetching tweet.")
        return None, None, None

@bot.listen()
async def on_message(message):
    if message.author == bot.user:
        return

    if message.mention_everyone:
        emojie = discord.utils.get(bot.emojis, name="angerypingcircle")
        await message.add_reaction(emojie)

    if "https://x.com/" in message.content or "https://twitter.com/" in message.content:
        clean_content = re.sub(r"\n+\|\|$", "||", message.content.strip())

        twitter_match = re.search(
            r"(\|\|\s*)?(https?://(?:x|twitter)\.com/[^/\s]+/status/\d+)(\s*\|\|)?",
            clean_content,
            re.MULTILINE
        )

        is_spoiler = (
            twitter_match
            and twitter_match.group(1) is not None
            and twitter_match.group(3) is not None
        )
        twitter_url = twitter_match.group(2) if twitter_match else None
        
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
            await message.channel.send(formatted_message, reference=message, mention_author=False, silent=True)
            return

        if detected_lang not in ["fr", "en", None]:
            formatted_message += f"{format_as_quote(tweet_text)}" if tweet_text else ""

        if is_spoiler:
            formatted_message = f"||{formatted_message}||"

        # await message.channel.send(content=formatted_message, embeds=[embed_one, embed_two], reference=message, mention_author=False)
        await message.channel.send(formatted_message, reference=message, mention_author=False, silent=True)

    if any(domain in message.content for domain in ["reddit.com", "instagram.com", "tiktok.com"]):
        await message.edit(suppress=True)

        replacements = {
            "reddit.com": "rxddit.com",
            "instagram.com": "vxinstagram.com",
            "tiktok.com": "tnktok.com",
        }

        fixed_urls = []

        for domain, replacement in replacements.items():
            # Regex qui capture avec ou sans || (spoiler)
            urls = re.findall(rf"(\|\|)?(https?://(?:www\.)?{re.escape(domain)}\S+)(\|\|)?", message.content)

            for prefix, url, suffix in urls:
                fixed_url = url.replace(domain, replacement)
                spoilered_url = f"{prefix or ''}{fixed_url}{suffix or ''}"
                fixed_urls.append(spoilered_url)

        if fixed_urls:
            await message.channel.send("\n".join(fixed_urls), reference=message, mention_author=False, silent=True)

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
                await message.channel.send(file=discord.File(data, 'slurp.png'), silent=True)

        # global cringe_joke
        # if cringe_joke == 0:
        # await message.channel.send(file=discord.File("./resources/fin_frerot.mp4", filename="Fin frérot...mp4"))
            # cringe_joke = 1

# Lancer le bot
token = os.getenv("TOKEN_BOT_DISCORD")
bot.run(token)

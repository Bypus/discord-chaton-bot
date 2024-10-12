import json
import os
import unicodedata
import discord
import random
from deep_translator import GoogleTranslator
import requests
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

def search_image(query):
    api_key = os.environ.get("CUSTOM_SEARCH_API")  # Remplacez par votre clé API Google
    search_engine_id =  os.environ.get("SEARCH_ENGINE_ID")  # Remplacez par votre ID de moteur de recherche personnalisé
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&cx={search_engine_id}&searchType=image&key={api_key}"
    
    response = requests.get(url).json()

    # Extraire l'URL de la première image trouvée
    if "items" in response:
        image_url = response["items"][0]["link"]
        return image_url
    else:
        return None

# Load the JSON file
with open('resources/translated_recipes.json', 'r', encoding='utf-8') as file:
    data = json.load(file)

# Fonction pour retirer les accents d'une chaîne
def remove_accents(input_str):
    input_str = input_str.replace('œ', 'oe').replace('æ', 'ae')
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def get_recipe_embed(ingredients: str):
    # Split the input ingredients string into individual ingredients
    ingredient_list = ingredients.split()
    normalized_ingredient_list = [remove_accents(ingredient.lower()) for ingredient in ingredient_list]

    # Find matching recipes where all ingredients are in the recipe name
    matching_recipes = []
    for recipe in data:  # Loop over dictionary items
        # Check if all ingredients are found in the recipe name
        # print(recipe['name'])
        normalized_recipe_name = remove_accents(recipe['name'].lower())

        if all(ingredient in normalized_recipe_name for ingredient in normalized_ingredient_list):
            matching_recipes.append(recipe)
            words = normalized_recipe_name.split()
            first_three_words = ' '.join(words[:3])

    # If no matching recipes are found
    if not matching_recipes:
        return discord.Embed(
            title="No matching recipes found",
            description=f"No recipes found with ingredients: {', '.join(ingredient_list)}",
            color=discord.Color.red()
        )
    
    # Select a random matching recipe
    selected_recipe = random.choice(matching_recipes)

    image_url = search_image(first_three_words)

    # Create the embed message
    embed_name = discord.Embed(
        title=selected_recipe['name'],
        description=selected_recipe['description'],
        color=discord.Color.green()
    )
    embed_name.set_image(url=image_url)
    embed_name.set_footer(text="Immage non contractuelle")

    recipe_ingredients = ""
    for ingredient in selected_recipe['ingredients']:
        recipe_ingredients += f"- {ingredient}\n"
    
    # Add instructions to the embed
    embed_cook = discord.Embed(
        title="Ingrédients et instructions",
        color=discord.Color.green()
    )
    embed_cook.add_field(name="Ingredients", value=recipe_ingredients, inline=False)
    step_number = 0
    for step in selected_recipe['instructions']:
        step_number += 1
        embed_cook.add_field(name=f"Etape {step_number}", value=step['text'], inline=True)

    return embed_name, embed_cook

# get_recipe_embed("boeuf")
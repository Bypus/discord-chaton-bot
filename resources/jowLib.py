import discord
from jow_api import Jow
import random

def get_recipe_embed(ingredients: str, limit: int = 1, couverts: int = 2):

    recipes = Jow.search(ingredients)
    recipes = random.sample(recipes, limit)
    embeds = []
    for recipe in recipes:
        embed = discord.Embed(title=recipe.name,
                              url=recipe.url,
                              description=recipe.description,
                              colour=0x00b0f4)
        embed.set_thumbnail(url=recipe.imageUrl)
        embed.add_field(name="Temps de préparation", value=f"{recipe.preparationTime + ((couverts*recipe.preparationExtraTimePerCover) if (couverts > 1) else 0)} minutes")
        embed.add_field(name="Temps de cuisson", value=f"{recipe.cookingTime} minutes")
        ingredients = ""
        for ingredient in recipe.ingredients:
            ingredients += f"- {ingredient.name}: {ingredient.quantity * couverts} {ingredient.unit}\n"
            if ingredient.isOptional:
                ingredients += "(facultatif)\n"
        embed.add_field(name="Nombre de couverts", value=couverts)
        embed.add_field(name="Ingrédients", value=ingredients, inline=False)
        embeds.append(embed)
    return embeds

# recipes = Jow.search("poulet")

# Loop through each recipe in the results and print its attributes
# for recipe in recipes:
#     print(f"ID: {recipe.id}")
#     print(f"Name: {recipe.name}")
#     print(f"URL: {recipe.url}")
#     print(f"Description: {recipe.description}")
#     print(f"Preparation time: {recipe.preparationTime}")
#     print(f"Cooking time: {recipe.cookingTime}")
#     print(f"Preparation extra time per cover: {recipe.preparationExtraTimePerCover}")
#     print(f"Covers count: {recipe.coversCount}")
#     print("Ingredients:")
#     for ingredient in recipe.ingredients:
#         print(f"\t{ingredient.name}: {ingredient.quantity} {ingredient.unit}")
#         if ingredient.isOptional:
#             print("\t(optional)")
#     print()

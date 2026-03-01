from datetime import date, datetime, timedelta
from typing import Optional

import discord
import requests


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODE_TO_LABEL = {
    0: "Ciel dégagé",
    1: "Plutôt ensoleillé",
    2: "Partiellement nuageux",
    3: "Couvert",
    45: "Brouillard",
    48: "Brouillard givrant",
    51: "Bruine légère",
    53: "Bruine modérée",
    55: "Bruine forte",
    56: "Bruine verglaçante légère",
    57: "Bruine verglaçante forte",
    61: "Pluie faible",
    63: "Pluie modérée",
    65: "Pluie forte",
    66: "Pluie verglaçante faible",
    67: "Pluie verglaçante forte",
    71: "Neige faible",
    73: "Neige modérée",
    75: "Neige forte",
    77: "Grains de neige",
    80: "Averses faibles",
    81: "Averses modérées",
    82: "Averses violentes",
    85: "Averses de neige faibles",
    86: "Averses de neige fortes",
    95: "Orage",
    96: "Orage avec grêle faible",
    99: "Orage avec grêle forte",
}

WEEKDAYS_FR = {
    0: "Lundi",
    1: "Mardi",
    2: "Mercredi",
    3: "Jeudi",
    4: "Vendredi",
    5: "Samedi",
    6: "Dimanche",
}

MONTHS_FR = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}

WEATHER_IMAGES = {
    "clear": "https://images.unsplash.com/photo-1601297183305-6df142704ea2?auto=format&fit=crop&w=1600&h=500&q=80",
    "cloudy": "https://images.unsplash.com/photo-1534088568595-a066f410bcda?auto=format&fit=crop&w=1600&h=500&q=80",
    "fog": "https://images.unsplash.com/photo-1487621167305-5d248087c724?auto=format&fit=crop&w=1600&h=500&q=80",
    "rain": "https://images.unsplash.com/photo-1519692933481-e162a57d6721?auto=format&fit=crop&w=1600&h=500&q=80",
    "snow": "https://images.unsplash.com/photo-1457269449834-928af64c684d?auto=format&fit=crop&w=1600&h=500&q=80",
    "storm": "https://images.unsplash.com/photo-1605727216801-e27ce1d0cc28?auto=format&fit=crop&w=1600&h=500&q=80",
}


def _parse_date(value: Optional[str]) -> date:
    if value is None or value.strip() == "":
        return date.today()

    normalized = value.strip().lower()
    if normalized in {"today", "aujourdhui", "aujourd'hui"}:
        return date.today()
    if normalized in {"demain", "tomorrow"}:
        return date.today().fromordinal(date.today().toordinal() + 1)

    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), date_format).date()
        except ValueError:
            continue

    raise ValueError("Format de date invalide. Utilise YYYY-MM-DD ou DD/MM/YYYY.")


def _format_date_fr(target_date: date) -> str:
    weekday = WEEKDAYS_FR[target_date.weekday()]
    month = MONTHS_FR[target_date.month]
    return f"{weekday} {target_date.day} {month} {target_date.year}"


def _wind_direction(degrees: Optional[float]) -> str:
    if degrees is None:
        return "-"

    directions = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
    index = round((degrees % 360) / 45) % 8
    return directions[index]


def _weather_image_url(weather_code: Optional[int]) -> str:
    if weather_code is None:
        fallback = WEATHER_IMAGES["cloudy"]
    elif weather_code == 0:
        fallback = WEATHER_IMAGES["clear"]
    elif weather_code in {1, 2, 3}:
        fallback = WEATHER_IMAGES["cloudy"]
    elif weather_code in {45, 48}:
        fallback = WEATHER_IMAGES["fog"]
    elif weather_code in {71, 73, 75, 77, 85, 86}:
        fallback = WEATHER_IMAGES["snow"]
    elif weather_code in {95, 96, 99}:
        fallback = WEATHER_IMAGES["storm"]
    else:
        fallback = WEATHER_IMAGES["rain"]

    return fallback



def _weather_emoji(weather_code: Optional[int]) -> str:
    if weather_code is None:
        return "🌤️"
    if weather_code == 0:
        return "☀️"
    if weather_code in {1, 2}:
        return "🌤️"
    if weather_code == 3:
        return "☁️"
    if weather_code in {45, 48}:
        return "🌫️"
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return "❄️"
    if weather_code in {95, 96, 99}:
        return "⛈️"
    return "🌧️"


def _get_location(city: str) -> dict:
    response = requests.get(
        GEOCODING_URL,
        params={"name": city, "count": 1, "language": "fr", "format": "json"},
        timeout=10,
    )
    response.raise_for_status()

    payload = response.json()
    results = payload.get("results")
    if not results:
        raise ValueError(f"Aucune ville trouvée pour '{city}'.")

    return results[0]


def get_weather_embed(city: str, target_date_raw: Optional[str] = None) -> discord.Embed:
    target_date = _parse_date(target_date_raw)
    target_date_iso = target_date.isoformat()

    location = _get_location(city)

    forecast_response = requests.get(
        FORECAST_URL,
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "timezone": "auto",
            "start_date": target_date_iso,
            "end_date": target_date_iso,
            "daily": [
                "weather_code",
                "temperature_2m_min",
                "temperature_2m_max",
                "precipitation_probability_max",
                "windspeed_10m_max",
                "winddirection_10m_dominant",
            ],
        },
        timeout=10,
    )
    forecast_response.raise_for_status()

    daily = forecast_response.json().get("daily", {})
    if not daily or not daily.get("time"):
        raise ValueError("Prévision indisponible pour cette date.")

    weather_code = daily.get("weather_code", [None])[0]
    min_temp = daily.get("temperature_2m_min", [None])[0]
    max_temp = daily.get("temperature_2m_max", [None])[0]
    rain_probability = daily.get("precipitation_probability_max", [None])[0]
    max_wind = daily.get("windspeed_10m_max", [None])[0]
    wind_direction = daily.get("winddirection_10m_dominant", [None])[0]

    city_name = location.get("name", city)
    country_name = location.get("country", "")
    location_display = f"{city_name}, {country_name}" if country_name else city_name

    weather_label = WMO_CODE_TO_LABEL.get(weather_code, "Conditions inconnues")
    date_label = _format_date_fr(target_date)

    embed = discord.Embed(
        title=f"{date_label} • {location_display}",
        description="Prévisions météo",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Conditions", value=weather_label, inline=True)
    embed.add_field(name="Températures", value=f"{min_temp}°C → {max_temp}°C", inline=True)
    embed.add_field(name="Pluie", value=f"{rain_probability}%", inline=True)
    embed.add_field(
        name="Vent",
        value=f"{max_wind} km/h ({_wind_direction(wind_direction)})",
        inline=True,
    )
    embed.set_image(url=_weather_image_url(weather_code))
    embed.set_footer(text="Source: Open-Meteo")

    return embed


def get_next_days_options(days: int = 14) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    today = date.today()

    for offset in range(days):
        target_date = today + timedelta(days=offset)
        if offset == 0:
            prefix = "Aujourd'hui"
        elif offset == 1:
            prefix = "Demain"
        else:
            prefix = f"J+{offset}"

        label = f"{prefix} • {_format_date_fr(target_date)}"
        options.append((label, target_date.isoformat()))

    return options

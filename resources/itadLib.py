from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from settings import ITAD_BASE_URL


ITAD_FREE_GAMES_FILTER = "N4IgDgTglgxgpiAXKAtlAdk9BXANrgGhBQEMAPJABgF8iZsAXJVDJARksqNIsQ5qIMAnmDgA5APZNEAbQBMAXWpA"
TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
_GAME_INFO_CACHE: dict[str, dict[str, Any]] = {}


async def _get_text_with_retries(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None = None,
    retries: int = 2,
    follow_redirects: bool = False,
    headers: dict[str, str] | None = None,
) -> str | None:
    for attempt in range(retries + 1):
        try:
            response = await client.get(
                url,
                params=params,
                follow_redirects=follow_redirects,
                headers=headers,
            )
            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                return None

            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code if error.response else None
            if status_code in TRANSIENT_STATUS_CODES and attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            return None
        except (httpx.RequestError, httpx.TimeoutException):
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            return None

    return None


def _clean_description(text: str, max_len: int = 500) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[: max_len - 1]}..."


def _normalize_lookup_key(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _extract_epic_slug_from_url(url: str) -> str | None:
    if not url:
        return None

    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None

    for idx, part in enumerate(parts):
        if part in {"p", "product"} and idx + 1 < len(parts):
            return parts[idx + 1]

    return parts[-1]


def _find_first_text_by_keys(data: Any, wanted_keys: set[str]) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in wanted_keys and isinstance(value, str) and value.strip():
                return value

        for value in data.values():
            found = _find_first_text_by_keys(value, wanted_keys)
            if found:
                return found

    if isinstance(data, list):
        for item in data:
            found = _find_first_text_by_keys(item, wanted_keys)
            if found:
                return found

    return None


def _extract_html_meta_description(html: str) -> str:
    lowered = html.lower()
    patterns = [
        ('property="og:description" content="', '"'),
        ("property='og:description' content='", "'"),
        ('name="description" content="', '"'),
        ("name='description' content='", "'"),
        ('content="', '" property="og:description"'),
        ("content='", "' property='og:description'"),
    ]

    for start_pattern, end_pattern in patterns:
        start = lowered.find(start_pattern)
        if start == -1:
            continue
        value_start = start + len(start_pattern)
        end = lowered.find(end_pattern, value_start)
        if end == -1:
            continue
        raw_value = html[value_start:end]
        cleaned = _clean_description(raw_value.replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&"))
        if cleaned:
            return cleaned

    return ""


async def _fetch_steam_description(client: httpx.AsyncClient, appid: int) -> str:
    payload = await _get_json_with_retries(
        client,
        "https://store.steampowered.com/api/appdetails",
        {"appids": str(appid), "l": "french"},
    )
    if not payload:
        return ""

    app_data = payload.get(str(appid)) if isinstance(payload, dict) else None
    if not isinstance(app_data, dict) or not app_data.get("success"):
        return ""

    data = app_data.get("data")
    if not isinstance(data, dict):
        return ""

    short_description = data.get("short_description")
    if isinstance(short_description, str) and short_description.strip():
        return _clean_description(short_description)

    return ""


async def _resolve_final_url(client: httpx.AsyncClient, url: str) -> str:
    if not url:
        return ""

    try:
        response = await client.get(
            url,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            },
        )
        return str(response.url)
    except Exception:
        return url


def _extract_epic_slugs(element: dict[str, Any]) -> set[str]:
    slugs: set[str] = set()

    for key in ("productSlug", "urlSlug"):
        value = element.get(key)
        if isinstance(value, str) and value:
            slugs.add(value)

    offer_mappings = element.get("offerMappings")
    if isinstance(offer_mappings, list):
        for mapping in offer_mappings:
            if not isinstance(mapping, dict):
                continue
            page_slug = mapping.get("pageSlug")
            if isinstance(page_slug, str) and page_slug:
                slugs.add(page_slug)

    return slugs


def _extract_epic_description_from_element(element: dict[str, Any]) -> str:
    for key in ("description", "shortDescription", "short_description"):
        value = element.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_description(value)
    return ""


async def _fetch_epic_description(client: httpx.AsyncClient, deal_url: str, deal_title: str) -> str:
    resolved_url = await _resolve_final_url(client, deal_url)
    target_slug = _extract_epic_slug_from_url(resolved_url) or _extract_epic_slug_from_url(deal_url)
    title_key = _normalize_lookup_key(deal_title)

    for locale in ("fr-FR", "en-US"):
        payload = await _get_json_with_retries(
            client,
            "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions",
            {"locale": locale, "country": "FR", "allowCountries": "FR"},
        )
        if not payload:
            continue

        elements = _get_nested_value(payload, "data", "Catalog", "searchStore", "elements")
        if not isinstance(elements, list):
            continue

        if target_slug:
            for element in elements:
                if not isinstance(element, dict):
                    continue
                if target_slug in _extract_epic_slugs(element):
                    description = _extract_epic_description_from_element(element)
                    if description:
                        return description

        if title_key:
            for element in elements:
                if not isinstance(element, dict):
                    continue
                title = element.get("title")
                if isinstance(title, str) and _normalize_lookup_key(title) == title_key:
                    description = _extract_epic_description_from_element(element)
                    if description:
                        return description

    return ""


async def _fetch_gog_description(client: httpx.AsyncClient, deal_url: str) -> str:
    resolved_url = await _resolve_final_url(client, deal_url)
    if not resolved_url:
        return ""

    html = await _get_text_with_retries(
        client,
        resolved_url,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        },
    )
    if not html:
        return ""

    return _extract_html_meta_description(html)


async def _fetch_store_description(
    client: httpx.AsyncClient,
    shop: str,
    appid: int | None,
    deal_url: str,
    deal_title: str,
) -> str:
    shop_lower = shop.lower()

    if shop_lower == "steam" and appid:
        return await _fetch_steam_description(client, appid)

    if "epic" in shop_lower:
        return await _fetch_epic_description(client, deal_url, deal_title)

    if shop_lower == "gog":
        return await _fetch_gog_description(client, deal_url)

    return ""


async def _get_json_with_retries(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    retries: int = 3,
) -> dict[str, Any] | None:
    for attempt in range(retries + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                return None

            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return None
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code if error.response else None
            if status_code in TRANSIENT_STATUS_CODES and attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            return None
        except (httpx.RequestError, httpx.TimeoutException):
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            return None

    return None


def _get_nested_value(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_game_id(deal_item: dict[str, Any]) -> str | None:
    for key in ("id", "gameId", "gid"):
        value = deal_item.get(key)
        if isinstance(value, str) and value:
            return value
    value = _get_nested_value(deal_item, "game", "id")
    if isinstance(value, str) and value:
        return value
    return None


def _extract_game_title(deal_item: dict[str, Any]) -> str:
    for key in ("title", "name"):
        value = deal_item.get(key)
        if isinstance(value, str) and value:
            return value
    value = _get_nested_value(deal_item, "game", "title")
    if isinstance(value, str) and value:
        return value
    return "Jeu sans titre"


def _extract_deal_url(deal_item: dict[str, Any]) -> str | None:
    for path in (("deal", "url"), ("url",), ("deal", "urls", "buy")):
        current = _get_nested_value(deal_item, *path)
        if isinstance(current, str) and current:
            return current
    return None


def _extract_banner_url(deal_item: dict[str, Any]) -> str | None:
    for key in ("banner600", "banner400", "banner300", "banner145"):
        value = _get_nested_value(deal_item, "assets", key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_shop_title(deal_item: dict[str, Any]) -> str:
    title = _get_nested_value(deal_item, "deal", "shop", "name") or _get_nested_value(deal_item, "deal", "shop", "title")
    if isinstance(title, str) and title:
        return title
    return "Store inconnu"


def _extract_money(data: Any) -> tuple[float | None, str | None]:
    if not isinstance(data, dict):
        return None, None

    amount = data.get("amount")
    currency = data.get("currency")
    if not isinstance(amount, (int, float)):
        amount = None
    if not isinstance(currency, str) or not currency:
        currency = None
    return amount, currency


def _extract_expiry(deal_item: dict[str, Any]) -> str | None:
    value = _get_nested_value(deal_item, "deal", "expiry")
    if isinstance(value, str) and value:
        return value
    return None


def _extract_timestamp(deal_item: dict[str, Any]) -> str | None:
    value = _get_nested_value(deal_item, "deal", "timestamp")
    if isinstance(value, str) and value:
        return value
    return None


def _iso_to_unix(iso_str: str) -> int | None:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def _iso_to_fr_date(iso_str: str) -> str | None:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%y")
    except (ValueError, TypeError):
        return None


def _extract_deal_summary(deal_item: dict[str, Any]) -> str:
    regular_amount, regular_currency = _extract_money(_get_nested_value(deal_item, "deal", "regular"))
    expiry = _extract_expiry(deal_item)

    parts: list[str] = []
    if regular_amount is not None:
        currency_text = f" {regular_currency}" if regular_currency else ""
        parts.append(f"~~{regular_amount:g}{currency_text}~~ **Gratuit**")

    if expiry:
        unix_ts = _iso_to_unix(expiry)
        fr_date = _iso_to_fr_date(expiry)
        if unix_ts and fr_date:
            parts.append(f"jusqu'à <t:{unix_ts}:R> ({fr_date})")
        elif unix_ts:
            parts.append(f"jusqu'à <t:{unix_ts}:R>")

    return " ".join(parts) if parts else "Free for a limited time"


async def fetch_free_deals(
    api_key: str,
    country: str = "FR",
) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "country": country,
        "mature": "false",
        "filter": ITAD_FREE_GAMES_FILTER,
    }

    free_games: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=20) as client:
        payload = await _get_json_with_retries(
            client,
            f"{ITAD_BASE_URL}/deals/v2",
            params,
        )
        if not payload:
            return []

        deals = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(deals, list) or not deals:
            return []

        for deal_item in deals:
            if not isinstance(deal_item, dict):
                continue

            game_id = _extract_game_id(deal_item)
            if not game_id:
                continue

            expiry_raw = _extract_expiry(deal_item) or ""
            expiry_unix = _iso_to_unix(expiry_raw) if expiry_raw else None

            free_games[game_id] = {
                "id": game_id,
                "title": _extract_game_title(deal_item),
                "url": _extract_deal_url(deal_item) or "",
                "shop": _extract_shop_title(deal_item),
                "banner_url": _extract_banner_url(deal_item) or "",
                "expiry_unix": expiry_unix,
                "summary": _extract_deal_summary(deal_item),
            }

    return list(free_games.values())


async def _fetch_games_info(
    client: httpx.AsyncClient,
    api_key: str,
    game_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch extra info (tags, reviews) for a batch of game IDs."""
    result: dict[str, dict[str, Any]] = {}
    for game_id in game_ids:
        payload = await _get_json_with_retries(
            client,
            f"{ITAD_BASE_URL}/games/info/v2",
            {"key": api_key, "id": game_id},
        )
        if payload:
            result[game_id] = payload
        await asyncio.sleep(0.3)
    return result


async def fetch_free_deals_with_info(
    api_key: str,
    country: str = "FR",
) -> list[dict[str, Any]]:
    """Fetch free deals then enrich with game info (tags, reviews)."""
    deals = await fetch_free_deals(api_key, country)
    if not deals:
        return deals

    game_ids = [d["id"] for d in deals if d.get("id")]
    missing_ids = [gid for gid in game_ids if gid not in _GAME_INFO_CACHE]

    if missing_ids:
        async with httpx.AsyncClient(timeout=20) as client:
            fetched_infos = await _fetch_games_info(client, api_key, missing_ids)
        _GAME_INFO_CACHE.update(fetched_infos)

    # Keep only currently active games in cache to avoid unbounded growth.
    active_ids = set(game_ids)
    for stale_id in list(_GAME_INFO_CACHE.keys()):
        if stale_id not in active_ids:
            del _GAME_INFO_CACHE[stale_id]

    for deal in deals:
        info = _GAME_INFO_CACHE.get(deal["id"], {})
        deal["tags"] = info.get("tags", [])
        deal["appid"] = info.get("appid")

        reviews = info.get("reviews", [])
        if reviews:
            best = max(reviews, key=lambda r: r.get("count", 0))
            score = best.get("score")
            if score is not None:
                deal["rating"] = f"{score / 10:g}/10"
            else:
                deal["rating"] = ""
        else:
            deal["rating"] = ""

    to_fetch_description: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for deal in deals:
        info = _GAME_INFO_CACHE.get(deal["id"], {})
        if "description" not in info:
            to_fetch_description.append((deal, info))

    if to_fetch_description:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for deal, info in to_fetch_description:
                raw_appid = info.get("appid")
                appid: int | None
                if isinstance(raw_appid, int):
                    appid = raw_appid
                elif isinstance(raw_appid, str) and raw_appid.isdigit():
                    appid = int(raw_appid)
                else:
                    appid = None

                try:
                    description = await _fetch_store_description(
                        client,
                        str(deal.get("shop") or ""),
                        appid,
                        str(deal.get("url") or ""),
                        str(deal.get("title") or ""),
                    )
                except Exception:
                    description = ""
                info["description"] = description

                # Keep requests gentle to avoid temporary upstream blocks.
                await asyncio.sleep(0.2)

    for deal in deals:
        info = _GAME_INFO_CACHE.get(deal["id"], {})
        description = info.get("description")
        deal["description"] = description if isinstance(description, str) else ""

    return deals

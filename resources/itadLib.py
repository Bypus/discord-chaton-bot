from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from settings import ITAD_BASE_URL


ITAD_FREE_GAMES_FILTER = "N4IgDgTglgxgpiAXKAtlAdk9BXANrgGhBQEMAPJABgF8iZsAXJVDJARksqNIsQ5qIMAnmDgA5APZNEAbQBMAXWpA"
TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
_GAME_INFO_CACHE: dict[str, dict[str, Any]] = {}


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


def _extract_deal_summary(deal_item: dict[str, Any]) -> str:
    regular_amount, regular_currency = _extract_money(_get_nested_value(deal_item, "deal", "regular"))
    expiry = _extract_expiry(deal_item)

    parts: list[str] = []
    if regular_amount is not None:
        currency_text = f" {regular_currency}" if regular_currency else ""
        parts.append(f"~~{regular_amount:g}{currency_text}~~ **Free**")

    if expiry:
        unix_ts = _iso_to_unix(expiry)
        if unix_ts:
            parts.append(f"until <t:{unix_ts}:d>")

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

    return deals

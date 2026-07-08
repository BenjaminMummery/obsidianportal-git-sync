from __future__ import annotations

from typing import Any

import requests

DDB_CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/{character_id}"


class DdbFetchError(Exception):
    pass


def fetch_character(character_id: str | int, *, timeout: float = 30) -> dict[str, Any]:
    url = DDB_CHARACTER_URL.format(character_id=character_id)
    response = requests.get(url, timeout=timeout)
    if response.status_code == 404:
        raise DdbFetchError(f"D&D Beyond character {character_id} not found (is the sheet public?)")
    if response.status_code >= 400:
        raise DdbFetchError(f"D&D Beyond request failed: {response.status_code} {response.text[:500]}")
    payload = response.json()
    if not payload.get("success"):
        message = payload.get("message") or "unknown error"
        raise DdbFetchError(f"D&D Beyond returned error for {character_id}: {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise DdbFetchError(f"D&D Beyond response for {character_id} had no character data")
    return data

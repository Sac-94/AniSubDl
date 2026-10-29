"""AniList GraphQL metadata resolver and directory name cleaner."""

from __future__ import annotations

import re
from typing import Dict, Optional
import requests

from .models import AnimeMetadata

ANILIST_API_URL = "https://graphql.anilist.co"

_ANILIST_CACHE: Dict[str, Optional[AnimeMetadata]] = {}


def clean_anime_query(raw_name: str) -> str:
    """
    Clean a local anime folder or release name into a clean search query.
    Strips [Group], [1080p], (2024), (BD), hashes, and trailing noise while keeping season numbers.
    """
    name = raw_name.strip()
    # Strip file extension if accidentally passed
    name = re.sub(r"\.(mkv|mp4|avi|mov|webm)$", "", name, flags=re.IGNORECASE)
    # Remove [bracketed] metadata tags (groups, hashes, codecs, resolutions)
    name = re.sub(r"\[[^\]]*\]", " ", name)
    # Remove parenthesized years or technical tags like (2023), (1080p), (BD), (Dual Audio)
    name = re.sub(
        r"\((?:\d{4}|[^)]*(?:1080p|720p|2160p|480p|bd|bluray|web|dual|dub|sub|hevc|x264|x265|av1|batch)[^)]*)\)",
        " ",
        name,
        flags=re.IGNORECASE,
    )
    # Replace dots/underscores used as word separators (when no spaces exist)
    if " " not in name and ("." in name or "_" in name):
        name = name.replace(".", " ").replace("_", " ")
    else:
        name = name.replace("_", " ")

    # Remove standalone technical tokens
    name = re.sub(
        r"\b(?:2160p|1080p|720p|480p|bluray|bdrip|web-dl|webrip|hevc|x265|x264|av1|10bit|dual[\s-]?audio|multi[\s-]?subs?)\b",
        " ",
        name,
        flags=re.IGNORECASE,
    )
    # Collapse whitespace and stray trailing dashes
    name = re.sub(r"\s+", " ", name).strip(" -–—")
    return name or raw_name.strip()


def extract_season_hint(raw_name: str) -> Optional[int]:
    """Extract an explicit season number hint from a folder/query name if present."""
    patterns = [
        r"\b[Ss](?:eason\s*)?0*(\d{1,2})\b",
        r"\b(\d{1,2})(?:nd|rd|th)\s+[Ss]eason\b",
        r"\bPart\s+(\d{1,2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, raw_name, flags=re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 20:
                return val
    return None


def resolve_anilist(
    search_term: str,
    session: Optional[requests.Session] = None,
    timeout: int = 10,
) -> Optional[AnimeMetadata]:
    """
    Query AniList GraphQL API for canonical Romaji/English titles and AniList/MAL IDs.
    Results are cached in-memory per cleaned query.
    """
    cleaned = clean_anime_query(search_term)
    cache_key = cleaned.lower()
    if cache_key in _ANILIST_CACHE:
        return _ANILIST_CACHE[cache_key]

    query = """
    query ($search: String) {
      Media (search: $search, type: ANIME) {
        id
        idMal
        episodes
        seasonYear
        title {
          romaji
          english
          native
        }
        synonyms
      }
    }
    """
    http = session or requests.Session()
    try:
        resp = http.post(
            ANILIST_API_URL,
            json={"query": query, "variables": {"search": cleaned}},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        media = (payload.get("data") or {}).get("Media")
        if not media:
            _ANILIST_CACHE[cache_key] = None
            return None

        titles = media.get("title") or {}
        meta = AnimeMetadata(
            query_used=cleaned,
            anilist_id=media.get("id"),
            mal_id=media.get("idMal"),
            romaji_title=titles.get("romaji"),
            english_title=titles.get("english"),
            native_title=titles.get("native"),
            synonyms=[s for s in (media.get("synonyms") or []) if isinstance(s, str)],
            episodes=media.get("episodes"),
            season_year=media.get("seasonYear"),
        )
        _ANILIST_CACHE[cache_key] = meta
        return meta
    except requests.RequestException:
        _ANILIST_CACHE[cache_key] = None
        return None

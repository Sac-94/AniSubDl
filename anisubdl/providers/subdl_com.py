"""SubDL (subdl.com) API v1 subtitle provider (optional API-key fallback/source)."""

from __future__ import annotations

import getpass
import os
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse
import requests

from ..anilist import extract_season_hint
from ..matcher import extract_release_group
from ..models import (
    AnimeMetadata,
    FontAttachment,
    ReleaseEntry,
    SubtitleTrack,
    normalize_lang,
)
from .base import SubtitleProvider

SUBDL_API_URL = "https://api.subdl.com/api/v1/subtitles"
SUBDL_DOWNLOAD_BASE = "https://dl.subdl.com"
SUBDL_API_KEY_ENV = "SUBDL_API_KEY"


def _to_subdl_lang(lang_code: str) -> str:
    """Convert canonical language code (e.g. 'en', 'pt-BR', 'zh-Hans') to SubDL uppercase code."""
    norm = normalize_lang(lang_code)
    mapping = {
        "en": "EN",
        "ja": "JA",
        "es": "ES",
        "es-419": "ES",
        "pt": "PT",
        "pt-BR": "BR_PT",
        "fr": "FR",
        "de": "DE",
        "it": "IT",
        "ru": "RU",
        "ar": "AR",
        "zh": "ZH",
        "zh-Hans": "ZH",
        "zh-Hant": "ZH_BG",
        "pl": "PL",
        "id": "ID",
        "th": "TH",
        "vi": "VI",
        "ko": "KO",
        "tr": "TR",
        "nl": "NL",
    }
    return mapping.get(norm, norm.split("-", 1)[0].upper())


def is_safe_subdl_download_url(url: str) -> bool:
    """Verify SubDL download URL points over HTTPS to subdl.com or *.subdl.com."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "subdl.com" or host.endswith(".subdl.com"))


def redact_api_key(text: str, api_key: str) -> str:
    """Ensure API key never appears in error messages or logs."""
    if not api_key:
        return text
    for secret in (api_key, quote(api_key, safe="")):
        if secret:
            text = text.replace(secret, "***")
    return text


class SubDLProvider(SubtitleProvider):
    """
    Subtitle provider for SubDL (https://subdl.com).
    Requires a free API key via SUBDL_API_KEY env var (or interactive hidden prompt when -p subdl is chosen).
    Supports:
    - Both TV series and anime movies
    - Both single-episode entries and full_season zip packs
    - Multi-language requests (-l en,ja,es,...)
    """

    slug = "subdl"
    name = "SubDL (subdl.com)"
    base_url = "https://subdl.com"

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        api_key: Optional[str] = None,
        langs: Optional[List[str]] = None,
        allow_prompt: bool = False,
    ):
        super().__init__(session=session)
        self.api_key = (api_key or os.environ.get(SUBDL_API_KEY_ENV, "")).strip() or None
        self.langs = langs or ["en"]
        self.allow_prompt = allow_prompt

    def _ensure_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        env_key = os.environ.get(SUBDL_API_KEY_ENV, "").strip()
        if env_key:
            self.api_key = env_key
            return self.api_key
        if self.allow_prompt and sys.stdin.isatty():
            print(f"\nSubDL requires a free API key (set {SUBDL_API_KEY_ENV} to skip this prompt).")
            entered = getpass.getpass("SubDL API key (hidden, Enter to skip): ").strip()
            if entered:
                self.api_key = entered
                return self.api_key
        return None

    def _api_get(self, **params) -> Optional[Dict]:
        key = self._ensure_api_key()
        if not key:
            return None
        req_params = dict(params)
        req_params["api_key"] = key
        try:
            resp = self.session.get(SUBDL_API_URL, params=req_params, timeout=20)
        except requests.RequestException as exc:
            msg = redact_api_key(str(exc), key)
            raise RuntimeError(f"Could not reach SubDL: {msg}") from None

        if resp.status_code in (401, 403):
            raise RuntimeError("SubDL rejected SUBDL_API_KEY (HTTP 401/403).")
        if resp.status_code == 429:
            raise RuntimeError("SubDL rate limit reached (HTTP 429).")

        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, dict) or not data.get("status"):
            return None
        return data

    def _subdl_languages_param(self) -> str:
        if not self.langs or "all" in self.langs:
            return "EN"
        codes = sorted({_to_subdl_lang(c) for c in self.langs if c})
        return ",".join(codes) if codes else "EN"

    def find_releases(
        self,
        title: str,
        metadata: Optional[AnimeMetadata] = None,
        resolution: str = "1080p",
        max_pages: int = 2,
    ) -> List[ReleaseEntry]:
        if not self._ensure_api_key():
            return []

        candidates = metadata.candidate_titles() if metadata else [title]
        if title not in candidates:
            candidates.insert(0, title)

        # Prefer English title first on SubDL (TMDB-indexed), then Romaji, then folder query
        if metadata and metadata.english_title and metadata.english_title in candidates:
            candidates.remove(metadata.english_title)
            candidates.insert(0, metadata.english_title)

        season_num = extract_season_hint(title) or 1
        langs_param = self._subdl_languages_param()
        is_likely_movie = bool(metadata and metadata.episodes == 1)
        media_types = ("movie", "tv") if is_likely_movie else ("tv", "movie")

        matched_series: Optional[Dict] = None
        matched_type = "tv"

        for m_type in media_types:
            for cand in candidates:
                data = self._api_get(film_name=cand, type=m_type, languages=langs_param, subs_per_page=5)
                results = [r for r in ((data or {}).get("results") or []) if isinstance(r, dict) and r.get("sd_id")]
                if results:
                    matched_series = results[0]
                    matched_type = m_type
                    break
            if matched_series:
                break

        if not matched_series:
            return []

        sd_id = matched_series["sd_id"]
        query_kwargs: Dict = {
            "sd_id": sd_id,
            "languages": langs_param,
            "subs_per_page": 30,
            "hi": 1,
        }
        if matched_type == "tv":
            query_kwargs["season_number"] = season_num

        sub_data = self._api_get(**query_kwargs)
        sub_items = (sub_data or {}).get("subtitles") or []

        releases: List[ReleaseEntry] = []
        for idx, sub in enumerate(sub_items):
            if not isinstance(sub, dict) or not sub.get("url"):
                continue
            dl_url = urljoin(SUBDL_DOWNLOAD_BASE, str(sub["url"]))
            if not is_safe_subdl_download_url(dl_url):
                continue

            rel_name = sub.get("release_name") or sub.get("name") or f"{matched_series.get('name', title)} #{idx + 1}"
            grp = extract_release_group(rel_name) or "SubDL"
            ep_val = sub.get("episode")
            ep_int = int(ep_val) if isinstance(ep_val, int) or (isinstance(ep_val, str) and ep_val.isdigit()) else None
            lang_norm = normalize_lang(sub.get("lang") or sub.get("language") or "en")
            hi_flag = "1" if sub.get("hi") else "0"
            # Encode metadata directly into release_id so fetch_tracks_for_releases needs zero extra API calls
            packed_id = f"{lang_norm}|{hi_flag}|{ep_int or ''}|{dl_url}"

            releases.append(
                ReleaseEntry(
                    provider=self.slug,
                    release_id=packed_id,
                    title=rel_name,
                    group=grp,
                    is_batch=bool(sub.get("full_season")),
                    sub_langs=[lang_norm],
                    episode_no=ep_int,
                    view_url=self.base_url,
                )
            )
        return releases

    def fetch_tracks_for_releases(
        self,
        releases: List[ReleaseEntry],
    ) -> Tuple[List[SubtitleTrack], List[FontAttachment]]:
        tracks: List[SubtitleTrack] = []
        for rel in releases:
            parts = rel.release_id.split("|", 3)
            if len(parts) != 4:
                continue
            lang_norm, hi_flag, ep_str, dl_url = parts
            if not is_safe_subdl_download_url(dl_url):
                continue

            v_name = rel.title
            if ep_str and f"{int(ep_str):02d}" not in v_name:
                v_name = f"{v_name} - {int(ep_str):02d}.zip"
            elif not v_name.lower().endswith(".zip"):
                v_name = f"{v_name}.zip"

            tracks.append(
                SubtitleTrack(
                    provider=self.slug,
                    release_id=rel.release_id,
                    release_title=rel.title,
                    video_filename=v_name,
                    download_url=dl_url,
                    lang=lang_norm,
                    format="zip",
                    compressed="zip",
                    track_name="SDH" if hi_flag == "1" else "",
                    is_default=(hi_flag == "0"),
                    is_forced=False,
                    release_group=rel.group,
                )
            )
        return tracks, []

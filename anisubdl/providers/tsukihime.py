"""TsukiHime (tsukihime.org) REST API v1 subtitle & font provider."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
import requests

from ..matcher import extract_release_group
from ..models import (
    AnimeMetadata,
    FontAttachment,
    ReleaseEntry,
    SubtitleTrack,
    normalize_format,
    normalize_lang,
)
from .base import SubtitleProvider, request_with_backoff

TSUKIHIME_API_BASE = "https://api.tsukihime.org/v1"
TSUKIHIME_WEB_BASE = "https://tsukihime.org"
TSUKIHIME_STORAGE_BASE = "https://storage.tsukihime.org"


class TsukiHimeProvider(SubtitleProvider):
    """
    Subtitle & font provider powered by TsukiHime (tsukihime.org) REST API v1.
    Supports direct AniList ID resolution (/v1/animes/anilist/{id}) as well as
    keyword search (/v1/search/torrents), individual .xz subtitle tracks,
    individual .xz font attachments (.ttf/.otf), and .7z attachment packs.
    """

    slug = "tsukihime"
    name = "TsukiHime (tsukihime.org)"
    base_url = TSUKIHIME_WEB_BASE

    def _search_by_anilist_id(self, anilist_id: int, max_pages: int = 2) -> List[Dict]:
        """Lookup TsukiHime internal anime_id from AniList ID and fetch its torrents."""
        try:
            resp = request_with_backoff(
                self.session,
                "GET",
                f"{TSUKIHIME_API_BASE}/animes/anilist/{anilist_id}",
                timeout=10,
            )
            anime_obj = resp.json()
            tsuki_anime_id = anime_obj.get("id")
            if not tsuki_anime_id:
                return []
        except (requests.RequestException, ValueError):
            return []

        items: List[Dict] = []
        limit = 50
        for page in range(max(1, max_pages)):
            try:
                r_tor = request_with_backoff(
                    self.session,
                    "GET",
                    f"{TSUKIHIME_API_BASE}/animes/{tsuki_anime_id}",
                    params={"limit": limit, "offset": page * limit},
                    timeout=10,
                )
                payload = r_tor.json()
                batch = payload.get("results") or []
                items.extend(batch)
                if len(batch) < limit:
                    break
            except (requests.RequestException, ValueError):
                break
        return items

    def _search_by_keyword(self, query_str: str, max_pages: int = 2) -> List[Dict]:
        items: List[Dict] = []
        limit = 50
        for page in range(max(1, max_pages)):
            try:
                resp = request_with_backoff(
                    self.session,
                    "GET",
                    f"{TSUKIHIME_API_BASE}/search/torrents",
                    params={"q": query_str, "limit": limit, "offset": page * limit},
                    timeout=10,
                )
                payload = resp.json()
                batch = payload.get("results") or []
                items.extend(batch)
                if len(batch) < limit:
                    break
            except (requests.RequestException, ValueError):
                break
        return items

    def find_releases(
        self,
        title: str,
        metadata: Optional[AnimeMetadata] = None,
        resolution: str = "1080p",
        max_pages: int = 2,
    ) -> List[ReleaseEntry]:
        raw_items: List[Dict] = []
        seen_ids = set()

        # 1. Exact AniList ID lookup first when available
        if metadata and metadata.anilist_id:
            for item in self._search_by_anilist_id(metadata.anilist_id, max_pages=max_pages):
                if resolution and resolution != "any" and resolution.lower() not in (item.get("name") or "").lower():
                    continue
                tid = item.get("id")
                if tid is not None and tid not in seen_ids:
                    seen_ids.add(tid)
                    raw_items.append(item)

        # 2. Keyword search fallback / supplement
        if not raw_items:
            candidates = metadata.candidate_titles() if metadata else [title]
            if title not in candidates:
                candidates.insert(0, title)

            for cand in candidates:
                q = f"{cand} {resolution}".strip() if resolution and resolution != "any" else cand
                batch = self._search_by_keyword(q, max_pages=max_pages)
                if not batch and resolution and resolution != "any":
                    batch = self._search_by_keyword(cand, max_pages=max_pages)
                for item in batch:
                    tid = item.get("id")
                    if tid is not None and tid not in seen_ids:
                        seen_ids.add(tid)
                        raw_items.append(item)
                if raw_items:
                    break

        releases: List[ReleaseEntry] = []
        for item in raw_items:
            if (item.get("state") or "").lower() not in ("completed", "complete", ""):
                continue
            sublangs = item.get("sublangs") or []
            r_name = item.get("name") or ""
            grp_obj = item.get("group") or {}
            group = grp_obj.get("name") or extract_release_group(r_name)
            tid = str(item["id"])
            filecount = item.get("filecount") or 1
            releases.append(
                ReleaseEntry(
                    provider=self.slug,
                    release_id=tid,
                    title=r_name,
                    group=group,
                    is_batch=bool(filecount > 1 or "batch" in r_name.lower()),
                    size_bytes=item.get("totalsize"),
                    sub_langs=[normalize_lang(code) for code in sublangs],
                    episode_no=item.get("episode_no"),
                    view_url=f"{TSUKIHIME_WEB_BASE}/view/{tid}",
                )
            )
        return releases

    def fetch_tracks_for_releases(
        self,
        releases: List[ReleaseEntry],
    ) -> Tuple[List[SubtitleTrack], List[FontAttachment]]:
        tracks: List[SubtitleTrack] = []
        fonts: List[FontAttachment] = []
        seen_font_ids = set()

        for rel in releases:
            try:
                resp = request_with_backoff(
                    self.session,
                    "GET",
                    f"{TSUKIHIME_API_BASE}/torrents/{rel.release_id}",
                    timeout=12,
                )
                td = resp.json()
            except (requests.RequestException, ValueError):
                continue

            for f_obj in td.get("files") or []:
                if (f_obj.get("state") or "completed").lower() not in ("completed", "complete"):
                    continue
                raw_filename = f_obj.get("filename") or rel.title
                v_basename = os.path.basename(raw_filename)
                v_stem = os.path.splitext(v_basename)[0]
                fid = f_obj.get("id")
                pack_url = (
                    f"{TSUKIHIME_STORAGE_BASE}/attachpack/{rel.release_id}_{fid}/{quote(v_stem)}_attachments.7z"
                    if fid is not None
                    else None
                )

                for att in f_obj.get("attachments") or []:
                    att_id = att.get("id")
                    att_type = att.get("type")
                    info = att.get("info") or {}
                    if att_id is None:
                        continue
                    hex_id = f"{int(att_id):08X}"

                    if att_type == 1:  # Subtitle track
                        raw_lang = info.get("lang") or ""
                        lang_norm = normalize_lang(raw_lang, info.get("name") or "")
                        fmt = normalize_format(info.get("codec") or "ass")
                        tracknum = info.get("tracknum")
                        lang_segment = f".{raw_lang}" if raw_lang else ""
                        dl_url = (
                            f"{TSUKIHIME_STORAGE_BASE}/attach/{hex_id}/"
                            f"{quote(v_stem)}_track{tracknum}{lang_segment}.{fmt}.xz"
                        )
                        tracks.append(
                            SubtitleTrack(
                                provider=self.slug,
                                release_id=rel.release_id,
                                release_title=rel.title,
                                video_filename=v_basename,
                                download_url=dl_url,
                                lang=lang_norm,
                                format=fmt,
                                compressed="xz",
                                track_name=info.get("name") or "",
                                track_num=tracknum,
                                is_default=bool(info.get("default")),
                                is_forced=bool(info.get("forced")),
                                release_group=rel.group,
                                pack_url=pack_url,
                            )
                        )
                    elif att_type == 0 and info.get("name"):  # Font attachment (.ttf / .otf)
                        if att_id not in seen_font_ids:
                            seen_font_ids.add(att_id)
                            font_name = info["name"]
                            font_url = f"{TSUKIHIME_STORAGE_BASE}/attach/{hex_id}/{quote(font_name)}.xz"
                            fonts.append(
                                FontAttachment(
                                    provider=self.slug,
                                    name=font_name,
                                    download_url=font_url,
                                    compressed="xz",
                                )
                            )

        return tracks, fonts

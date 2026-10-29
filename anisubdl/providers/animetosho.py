"""Anime Tosho NEW (animetosho.net / custom AT mirror) JSON API provider."""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
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

DEFAULT_AT_WEB_URL = "https://animetosho.net"
DEFAULT_AT_FEED_URL = "https://feed.animetosho.net/json"


class AnimeToshoProvider(SubtitleProvider):
    """
    Subtitle provider powered by Anime Tosho NEW (animetosho.net, successor to animetosho.org/.xyz).
    Uses the structured JSON Feed API (/json?t=search & /json?show=torrent&id=...) which supports
    both single-episode releases and multi-episode batches, multi-language ASS/SRT tracks, and .7z packs.
    """

    slug = "animetosho"
    name = "Anime Tosho NEW (animetosho.net)"

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        web_url: Optional[str] = None,
    ):
        super().__init__(session=session)
        if web_url:
            parsed = urlparse(web_url if "://" in web_url else f"https://{web_url}")
            host = parsed.netloc
            # Normalize legacy animetosho.xyz redirect domain to canonical animetosho.net
            if host.endswith("animetosho.xyz"):
                host = host.replace("animetosho.xyz", "animetosho.net")
            self.base_url = f"{parsed.scheme}://{host}".rstrip("/")
            self.feed_url = (
                f"{parsed.scheme}://feed.{host}/json"
                if not host.startswith("feed.")
                else f"{parsed.scheme}://{host}/json"
            )
        else:
            self.base_url = DEFAULT_AT_WEB_URL
            self.feed_url = DEFAULT_AT_FEED_URL

    def _search_query(self, query_str: str, max_pages: int = 2) -> List[Dict]:
        results: List[Dict] = []
        seen_ids = set()
        for page in range(1, max(1, max_pages) + 1):
            params = {"t": "search", "q": query_str, "page": page}
            try:
                resp = request_with_backoff(self.session, "GET", self.feed_url, params=params, timeout=12)
                items = resp.json()
            except (requests.RequestException, ValueError):
                break

            if not isinstance(items, list) or not items:
                break

            new_count = 0
            for item in items:
                tid = item.get("id")
                if tid is None or tid in seen_ids:
                    continue
                seen_ids.add(tid)
                new_count += 1
                results.append(item)

            if len(items) < 75 or new_count == 0:
                break
        return results

    def find_releases(
        self,
        title: str,
        metadata: Optional[AnimeMetadata] = None,
        resolution: str = "1080p",
        max_pages: int = 2,
    ) -> List[ReleaseEntry]:
        candidate_queries = metadata.candidate_titles() if metadata else [title]
        if title not in candidate_queries:
            candidate_queries.insert(0, title)

        raw_entries: List[Dict] = []
        seen_ids = set()

        for cand in candidate_queries:
            q = f"{cand} {resolution}".strip() if resolution and resolution != "any" else cand
            batch = self._search_query(q, max_pages=max_pages)
            if not batch and resolution and resolution != "any":
                # Fallback without resolution filter
                batch = self._search_query(cand, max_pages=max_pages)
            for item in batch:
                tid = item.get("id")
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    raw_entries.append(item)
            if raw_entries:
                break

        releases: List[ReleaseEntry] = []
        for item in raw_entries:
            # Skip entries explicitly marked skipped by AT mirror (>25GB / raw / unmirrored)
            status = (item.get("status") or "").lower()
            if status == "skipped":
                continue
            r_title = item.get("title") or item.get("torrent_name") or ""
            tid = str(item["id"])
            group = extract_release_group(r_title)
            num_files = item.get("num_files") or 1
            releases.append(
                ReleaseEntry(
                    provider=self.slug,
                    release_id=tid,
                    title=r_title,
                    group=group,
                    is_batch=bool(num_files > 1 or "batch" in r_title.lower()),
                    size_bytes=item.get("total_size"),
                    seeders=item.get("seeders"),
                    view_url=f"{self.base_url}/view/{tid}",
                    pack_url=f"{self.base_url}/download/{tid}/subs/all",
                )
            )
        return releases

    def fetch_tracks_for_releases(
        self,
        releases: List[ReleaseEntry],
    ) -> Tuple[List[SubtitleTrack], List[FontAttachment]]:
        tracks: List[SubtitleTrack] = []
        fonts: List[FontAttachment] = []

        for rel in releases:
            try:
                resp = request_with_backoff(
                    self.session,
                    "GET",
                    self.feed_url,
                    params={"show": "torrent", "id": rel.release_id},
                    timeout=12,
                )
                td = resp.json()
            except (requests.RequestException, ValueError):
                continue

            if not isinstance(td, dict) or (td.get("status") or "").lower() == "skipped":
                continue

            files = td.get("files") or []
            top_attachments = td.get("attachments") or []
            pack_url = f"{self.base_url}/download/{rel.release_id}/subs/all"

            # Single-file releases on animetosho.net may place attachments at top-level td['attachments']
            if not files and top_attachments:
                files = [{"filename": rel.title, "attachments": top_attachments}]

            for f_idx, f_obj in enumerate(files):
                v_name = os.path.basename(f_obj.get("filename") or f_obj.get("name") or rel.title)
                att_list = f_obj.get("attachments")
                if not att_list and len(files) == 1 and f_idx == 0:
                    att_list = top_attachments
                if not att_list:
                    continue

                for att in att_list:
                    att_type = (att.get("type") or "").lower()
                    info = att.get("info") or {}
                    dl_url = att.get("url")
                    if not dl_url:
                        continue

                    if att_type == "subtitle":
                        lang_code = normalize_lang(info.get("language_code"), info.get("language") or "")
                        fmt = normalize_format(info.get("format") or "ass")
                        tracks.append(
                            SubtitleTrack(
                                provider=self.slug,
                                release_id=rel.release_id,
                                release_title=rel.title,
                                video_filename=v_name,
                                download_url=dl_url,
                                lang=lang_code,
                                format=fmt,
                                compressed="xz" if ".xz" in dl_url else "none",
                                track_name=info.get("name") or info.get("language") or "",
                                track_num=info.get("tracknum"),
                                is_default=bool(info.get("default")),
                                is_forced=bool(info.get("forced")),
                                release_group=rel.group,
                                pack_url=pack_url,
                            )
                        )
                    elif att_type == "font" and info.get("name"):
                        fonts.append(
                            FontAttachment(
                                provider=self.slug,
                                name=info["name"],
                                download_url=dl_url,
                                compressed="xz" if ".xz" in dl_url else "none",
                            )
                        )

        return tracks, fonts

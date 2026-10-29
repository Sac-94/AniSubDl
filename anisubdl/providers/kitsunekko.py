"""Kitsunekko (kitsunekko.net) English & Japanese anime subtitle directory provider."""

from __future__ import annotations

from difflib import SequenceMatcher
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
import requests

from ..matcher import extract_release_group
from ..models import (
    AnimeMetadata,
    FontAttachment,
    ReleaseEntry,
    SubtitleTrack,
    normalize_format,
)
from .base import SubtitleProvider, request_with_backoff

KITSUNEKKO_BASE = "https://kitsunekko.net"
KITSUNEKKO_DIRS = {
    "en": "/dirlist.php?dir=subtitles%2F",
    "ja": "/dirlist.php?dir=subtitles%2Fjapanese%2F",
}


def _norm_title_for_match(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class KitsunekkoProvider(SubtitleProvider):
    """
    Direct-download subtitle archive provider for Kitsunekko (kitsunekko.net).
    Supports both English ('subtitles/') and Japanese ('subtitles/japanese/') anime directories.
    """

    slug = "kitsunekko"
    name = "Kitsunekko (kitsunekko.net)"
    base_url = KITSUNEKKO_BASE

    def __init__(self, session: Optional[requests.Session] = None, langs: Optional[List[str]] = None):
        super().__init__(session=session)
        self.langs = langs or ["en"]
        self._dir_cache: Dict[str, List[Tuple[str, str]]] = {}

    def _load_directory_index(self, lang_code: str) -> List[Tuple[str, str]]:
        if lang_code in self._dir_cache:
            return self._dir_cache[lang_code]
        rel_url = KITSUNEKKO_DIRS.get(lang_code)
        if not rel_url:
            return []
        try:
            resp = request_with_backoff(self.session, "GET", urljoin(KITSUNEKKO_BASE, rel_url), timeout=12)
            soup = BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException:
            return []

        entries: List[Tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            label = a.get_text(strip=True)
            if "dirlist.php?dir=subtitles" not in href or "&sort=" in href:
                continue
            if label in ("English subtitles", "Japanese subtitles", "..", "."):
                continue
            entries.append((label, href))
        self._dir_cache[lang_code] = entries
        return entries

    def _match_series_dirs(self, candidates: List[str], lang_code: str) -> List[Tuple[str, str, float]]:
        index = self._load_directory_index(lang_code)
        if not index:
            return []

        norm_cands = [_norm_title_for_match(c) for c in candidates if _norm_title_for_match(c)]
        scored: List[Tuple[str, str, float]] = []

        for folder_name, href in index:
            nf = _norm_title_for_match(folder_name)
            if not nf:
                continue
            best = 0.0
            for nc in norm_cands:
                if nf == nc:
                    best = max(best, 1.0)
                else:
                    shorter, longer = (nc, nf) if len(nc) <= len(nf) else (nf, nc)
                    ratio = SequenceMatcher(None, nc, nf).ratio()
                    if len(shorter) >= 5 and f" {shorter} " in f" {longer} ":
                        best = max(best, max(0.80, ratio))
                    else:
                        best = max(best, ratio)
            if best >= 0.76:
                scored.append((folder_name, href, best))

        scored.sort(key=lambda x: x[2], reverse=True)
        # If there is an exact/near-exact match (>= 0.95), return only top matches
        if scored and scored[0][2] >= 0.95:
            return [s for s in scored if s[2] >= 0.90][:3]
        return scored[:5]

    def find_releases(
        self,
        title: str,
        metadata: Optional[AnimeMetadata] = None,
        resolution: str = "1080p",
        max_pages: int = 2,
    ) -> List[ReleaseEntry]:
        candidates = metadata.candidate_titles() if metadata else [title]
        if title not in candidates:
            candidates.insert(0, title)

        target_langs: List[str] = []
        if not self.langs or "all" in self.langs:
            target_langs = ["en", "ja"]
        else:
            for l_code in self.langs:
                if l_code.startswith("ja") or l_code == "jp":
                    if "ja" not in target_langs:
                        target_langs.append("ja")
                elif l_code.startswith("en"):
                    if "en" not in target_langs:
                        target_langs.append("en")
            if not target_langs:
                return []

        releases: List[ReleaseEntry] = []
        for l_code in target_langs:
            matches = self._match_series_dirs(candidates, l_code)
            for folder_name, href, _score in matches:
                group_label = f"Kitsunekko-{l_code.upper()}"
                releases.append(
                    ReleaseEntry(
                        provider=self.slug,
                        release_id=f"{l_code}::{href}",
                        title=f"[{group_label}] {folder_name}",
                        group=group_label,
                        is_batch=True,
                        sub_langs=[l_code],
                        view_url=urljoin(KITSUNEKKO_BASE, href.lstrip("/")),
                    )
                )
        return releases

    def fetch_tracks_for_releases(
        self,
        releases: List[ReleaseEntry],
    ) -> Tuple[List[SubtitleTrack], List[FontAttachment]]:
        tracks: List[SubtitleTrack] = []
        for rel in releases:
            if "::" in rel.release_id:
                l_code, href = rel.release_id.split("::", 1)
            else:
                l_code, href = "en", rel.release_id

            page_url = urljoin(KITSUNEKKO_BASE + "/", href.lstrip("/"))
            try:
                resp = request_with_backoff(self.session, "GET", page_url, timeout=12)
                soup = BeautifulSoup(resp.text, "html.parser")
            except requests.RequestException:
                continue

            for a in soup.find_all("a", href=True):
                f_href = a["href"]
                if not f_href.startswith("subtitles/"):
                    continue
                fname = os.path.basename(f_href)
                ext = os.path.splitext(fname)[1].lower().lstrip(".")
                if ext not in ("ass", "ssa", "srt", "zip", "7z", "rar"):
                    continue

                encoded_path = "/".join(quote(seg) for seg in f_href.split("/"))
                dl_url = f"{KITSUNEKKO_BASE}/{encoded_path}"
                comp = ext if ext in ("zip", "7z", "rar") else "none"
                grp = extract_release_group(fname) or rel.group
                tracks.append(
                    SubtitleTrack(
                        provider=self.slug,
                        release_id=rel.release_id,
                        release_title=rel.title,
                        video_filename=fname,
                        download_url=dl_url,
                        lang=l_code,
                        format=normalize_format(ext),
                        compressed=comp,
                        track_name=fname,
                        is_default=True,
                        is_forced=False,
                        release_group=grp,
                    )
                )

        return tracks, []

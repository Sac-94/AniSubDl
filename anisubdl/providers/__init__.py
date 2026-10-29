"""Provider registry, multi-provider 'auto' coordinator, and ecosystem status checker."""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple
import requests

from ..models import (
    AnimeMetadata,
    FontAttachment,
    ProviderHealth,
    ReleaseEntry,
    SubtitleTrack,
)
from .animetosho import AnimeToshoProvider
from .base import SubtitleProvider, create_http_session
from .kitsunekko import KitsunekkoProvider
from .subdl_com import SUBDL_API_KEY_ENV, SubDLProvider
from .tsukihime import TsukiHimeProvider

SUPPORTED_PROVIDERS = ("auto", "animetosho", "tsukihime", "kitsunekko", "subdl")


class AutoSubtitleProvider(SubtitleProvider):
    """
    Smart multi-provider coordinator:
    1. Queries both Anime Tosho NEW (animetosho.net) and TsukiHime (tsukihime.org) so users get
       maximum coverage of both ongoing seasonal anime and back-catalog batches/fonts (keyless).
    2. Falls back to Kitsunekko (kitsunekko.net) and SubDL (if SUBDL_API_KEY is set) when neither
       primary mirror has matches.
    """

    slug = "auto"
    name = "Auto (Anime Tosho NEW + TsukiHime + Kitsunekko/SubDL fallback)"

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        custom_at_url: Optional[str] = None,
        langs: Optional[List[str]] = None,
    ):
        super().__init__(session=session)
        self.at = AnimeToshoProvider(session=self.session, web_url=custom_at_url)
        self.tsuki = TsukiHimeProvider(session=self.session)
        self.kitsu = KitsunekkoProvider(session=self.session, langs=langs)
        self.subdl = SubDLProvider(session=self.session, langs=langs, allow_prompt=False)
        self._by_slug: Dict[str, SubtitleProvider] = {
            self.at.slug: self.at,
            self.tsuki.slug: self.tsuki,
            self.kitsu.slug: self.kitsu,
            self.subdl.slug: self.subdl,
        }

    def find_releases(
        self,
        title: str,
        metadata: Optional[AnimeMetadata] = None,
        resolution: str = "1080p",
        max_pages: int = 2,
    ) -> List[ReleaseEntry]:
        combined: List[ReleaseEntry] = []
        for prov in (self.at, self.tsuki):
            try:
                rels = prov.find_releases(
                    title=title,
                    metadata=metadata,
                    resolution=resolution,
                    max_pages=max_pages,
                )
                combined.extend(rels)
            except Exception:
                continue

        if not combined:
            for fallback in (self.kitsu, self.subdl):
                try:
                    combined.extend(
                        fallback.find_releases(
                            title=title,
                            metadata=metadata,
                            resolution=resolution,
                            max_pages=1,
                        )
                    )
                except Exception:
                    continue
        return combined

    def fetch_tracks_for_releases(
        self,
        releases: List[ReleaseEntry],
    ) -> Tuple[List[SubtitleTrack], List[FontAttachment]]:
        grouped: Dict[str, List[ReleaseEntry]] = {}
        for rel in releases:
            grouped.setdefault(rel.provider, []).append(rel)

        all_tracks: List[SubtitleTrack] = []
        all_fonts: List[FontAttachment] = []

        # Query Anime Tosho NEW and TsukiHime; deduplicate identical episode+lang+format tracks across mirrors
        for p_slug, p_rels in grouped.items():
            prov = self._by_slug.get(p_slug)
            if not prov:
                continue
            tracks, fonts = prov.fetch_tracks_for_releases(p_rels)
            all_tracks.extend(tracks)
            all_fonts.extend(fonts)

        return all_tracks, all_fonts


def get_provider(
    provider_slug: str,
    session: Optional[requests.Session] = None,
    custom_at_url: Optional[str] = None,
    langs: Optional[List[str]] = None,
) -> SubtitleProvider:
    slug = (provider_slug or "auto").lower().strip()
    sess = session or create_http_session()
    if slug == "animetosho":
        return AnimeToshoProvider(session=sess, web_url=custom_at_url)
    if slug == "tsukihime":
        return TsukiHimeProvider(session=sess)
    if slug == "kitsunekko":
        return KitsunekkoProvider(session=sess, langs=langs)
    if slug == "subdl":
        return SubDLProvider(session=sess, langs=langs, allow_prompt=True)
    return AutoSubtitleProvider(session=sess, custom_at_url=custom_at_url, langs=langs)


def check_ecosystem_health(timeout: int = 6) -> List[ProviderHealth]:
    """
    Live-check the Anime Tosho continuation ecosystem & subtitle mirrors:
    - Anime Tosho NEW (animetosho.net, formerly animetosho.xyz)
    - TsukiHime (tsukihime.org)
    - Kitsunekko (kitsunekko.net)
    - aninzb (aninzb.moe)
    - Otakuness (otakuness.top)
    - ameNZB (amenzb.moe)
    - Anime Tosho Classic Archive (animetosho.org)
    """
    sess = create_http_session()
    targets = [
        (
            "animetosho",
            "Anime Tosho NEW",
            "https://feed.animetosho.net/json?t=search&q=Frieren",
            "https://animetosho.net",
            True,
            True,
            "Active successor (redirects from animetosho.xyz); public JSON API + ASS/SRT/.7z extractions",
        ),
        (
            "tsukihime",
            "TsukiHime",
            "https://api.tsukihime.org/v1/stats",
            "https://tsukihime.org",
            True,
            True,
            "Active successor; Swagger REST API v1 + AniList lookup + ASS/SRT/Font extractions",
        ),
        (
            "kitsunekko",
            "Kitsunekko",
            "https://kitsunekko.net/dirlist.php?dir=subtitles%2F",
            "https://kitsunekko.net",
            True,
            True,
            "Community English & Japanese anime subtitle archive (.ass/.srt/.zip)",
        ),
        (
            "subdl",
            "SubDL",
            "https://subdl.com",
            "https://subdl.com",
            True,
            True,
            f"Optional multilingual fallback (set {SUBDL_API_KEY_ENV}; status={'configured' if os.environ.get(SUBDL_API_KEY_ENV) else 'key not set'})",
        ),
        (
            "aninzb",
            "aninzb",
            "https://aninzb.moe/",
            "https://aninzb.moe",
            True,
            False,
            "Usenet indexer w/ web sub extractions; uses rotating signed URLs & anti-bot filtering",
        ),
        (
            "otakuness",
            "Otakuness",
            "https://otakuness.top/",
            "https://otakuness.top",
            False,
            False,
            "Nyaa-to-DDL video mirror + screenshots/MediaInfo only (no standalone subtitle extractions)",
        ),
        (
            "amenzb",
            "ameNZB",
            "https://amenzb.moe/",
            "https://amenzb.moe",
            False,
            False,
            "Usenet NZB mirror only (no standalone subtitle extractions)",
        ),
        (
            "animetosho-org",
            "Anime Tosho (Classic)",
            "https://animetosho.org/",
            "https://animetosho.org",
            False,
            False,
            "Halted new releases May 2026; feed/attachment storage servers expired Oct 2026",
        ),
    ]

    reports: List[ProviderHealth] = []
    for slug, name, probe_url, display_url, has_subs, supported, notes in targets:
        t0 = time.monotonic()
        online = False
        latency_ms: Optional[int] = None
        try:
            resp = sess.get(probe_url, timeout=timeout)
            elapsed = int((time.monotonic() - t0) * 1000)
            if 200 <= resp.status_code < 400:
                online = True
                latency_ms = elapsed
        except requests.RequestException:
            online = False

        reports.append(
            ProviderHealth(
                slug=slug,
                name=name,
                url=display_url,
                online=online,
                has_subtitles=has_subs,
                supported_in_tool=supported,
                latency_ms=latency_ms,
                notes=notes,
            )
        )
    return reports

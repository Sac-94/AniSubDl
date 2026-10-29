"""Data models and language/format normalization utilities for AniSubDl."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Canonical ISO-639-1 / special language mapping across Anime Tosho, TsukiHime, and Kitsunekko
LANG_ALIASES: Dict[str, str] = {
    # English
    "en": "en",
    "eng": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    # Japanese
    "ja": "ja",
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    # Spanish
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "es-es": "es",
    "es-419": "es-419",
    "latin american": "es-419",
    "spanish (latin america)": "es-419",
    "european spanish": "es",
    # Portuguese
    "pt": "pt",
    "por": "pt",
    "portuguese": "pt",
    "pt-br": "pt-BR",
    "brazilian": "pt-BR",
    "portuguese[br]": "pt-BR",
    "portuguese (brazil)": "pt-BR",
    # French
    "fr": "fr",
    "fre": "fr",
    "fra": "fr",
    "french": "fr",
    # German
    "de": "de",
    "ger": "de",
    "deu": "de",
    "german": "de",
    # Italian
    "it": "it",
    "ita": "it",
    "italian": "it",
    # Russian
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    # Arabic
    "ar": "ar",
    "ara": "ar",
    "arabic": "ar",
    "saudi arabia": "ar",
    # Chinese
    "zh": "zh",
    "chi": "zh",
    "zho": "zh",
    "chinese": "zh",
    "zh-hans": "zh-Hans",
    "simplified": "zh-Hans",
    "zh-hant": "zh-Hant",
    "traditional": "zh-Hant",
    # Polish
    "pl": "pl",
    "pol": "pl",
    "polish": "pl",
    # Indonesian / Malay / Thai / Vietnamese / Korean
    "id": "id",
    "ind": "id",
    "indonesian": "id",
    "ms": "ms",
    "may": "ms",
    "msa": "ms",
    "malay": "ms",
    "th": "th",
    "tha": "th",
    "thai": "th",
    "vi": "vi",
    "vie": "vi",
    "vietnamese": "vi",
    "ko": "ko",
    "kor": "ko",
    "korean": "ko",
    # Turkish / Dutch / Ukrainian / Hebrew / Hindi
    "tr": "tr",
    "tur": "tr",
    "turkish": "tr",
    "nl": "nl",
    "dut": "nl",
    "nld": "nl",
    "dutch": "nl",
    "uk": "uk",
    "ukr": "uk",
    "ukrainian": "uk",
    "he": "he",
    "heb": "he",
    "hebrew": "he",
    "hi": "hi",
    "hin": "hi",
    "hindi": "hi",
    # Non-linguistic / Undetermined
    "zxx": "zxx",
    "und": "und",
}


def normalize_lang(raw: Optional[str], fallback_label: str = "") -> str:
    """
    Normalize a provider language tag or human label into a canonical code.
    If fallback_label provides a regional variant (e.g. 'Latin American' -> 'es-419',
    'Portuguese[BR]' -> 'pt-BR', 'Simplified' -> 'zh-Hans') of a generic ISO-639-2 code
    ('spa', 'por', 'chi'), prefer the specific regional code.
    """
    def _lookup(val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        cleaned = val.strip().lower()
        if cleaned in LANG_ALIASES:
            return LANG_ALIASES[cleaned]
        base_cleaned = cleaned.split("(")[0].strip()
        if base_cleaned in LANG_ALIASES:
            return LANG_ALIASES[base_cleaned]
        if "-" in cleaned:
            prefix = cleaned.split("-", 1)[0]
            if prefix in LANG_ALIASES:
                return LANG_ALIASES[prefix]
        return None

    primary = _lookup(raw)
    secondary = _lookup(fallback_label)

    # Prefer regional subtag from human label when primary is only the generic base code
    if primary and secondary and "-" in secondary and secondary.split("-", 1)[0].lower() == primary.lower():
        return secondary
    if primary:
        return primary
    if secondary:
        return secondary
    if raw and raw.strip():
        return raw.strip().lower()
    return "und"


def lang_matches(track_lang: str, requested_langs: List[str]) -> bool:
    """
    Check if a normalized track language matches the user's requested languages.
    Requesting a base language like 'es', 'pt', or 'zh' matches regional variants
    ('es-419', 'pt-BR', 'zh-Hans', 'zh-Hant'), whereas requesting a specific
    regional variant ('pt-BR') matches only that variant.
    """
    if not requested_langs or "all" in requested_langs or "any" in requested_langs:
        return True

    norm_track = normalize_lang(track_lang)
    track_base = norm_track.split("-", 1)[0].lower()

    for req in requested_langs:
        req_clean = req.strip()
        if req_clean.lower() in ("all", "any", "*"):
            return True
        norm_req = normalize_lang(req_clean)
        if norm_track.lower() == norm_req.lower():
            return True
        # Base language match (e.g. 'es' matches 'es-419', 'pt' matches 'pt-BR')
        if "-" not in norm_req and track_base == norm_req.lower():
            return True
    return False


def normalize_format(raw_fmt: Optional[str]) -> str:
    """Normalize subtitle codec/extension names to lowercase file extension."""
    if not raw_fmt:
        return "ass"
    cleaned = raw_fmt.strip().lower().lstrip(".")
    mapping = {
        "ass": "ass",
        "ssa": "ssa",
        "srt": "srt",
        "subrip": "srt",
        "utf-8": "srt",
        "vtt": "vtt",
        "webvtt": "vtt",
        "sup": "sup",
        "pgs": "sup",
        "zip": "zip",
        "7z": "7z",
        "rar": "rar",
    }
    return mapping.get(cleaned, cleaned)


@dataclass
class AnimeMetadata:
    """Resolved anime metadata from AniList."""

    query_used: str
    anilist_id: Optional[int] = None
    mal_id: Optional[int] = None
    romaji_title: Optional[str] = None
    english_title: Optional[str] = None
    native_title: Optional[str] = None
    synonyms: List[str] = field(default_factory=list)
    episodes: Optional[int] = None
    season_year: Optional[int] = None

    def candidate_titles(self) -> List[str]:
        """Ordered deduplicated list of search titles."""
        seen = set()
        result: List[str] = []
        for t in [self.romaji_title, self.english_title, self.query_used] + self.synonyms[:3]:
            if t:
                key = t.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    result.append(t.strip())
        return result


@dataclass
class SubtitleTrack:
    """Represents a downloadable subtitle track or archive."""

    provider: str
    release_id: str
    release_title: str
    video_filename: str
    download_url: str
    lang: str  # Canonical code (e.g. 'en', 'ja', 'es-419', 'pt-BR')
    format: str  # 'ass', 'srt', 'zip', '7z', etc.
    compressed: str = "xz"  # 'xz', 'none', 'zip', '7z', 'rar'
    track_name: str = ""
    track_num: Optional[int] = None
    is_default: bool = False
    is_forced: bool = False
    release_group: Optional[str] = None
    pack_url: Optional[str] = None  # Optional .7z all-attachments pack URL

    @property
    def is_signs_only(self) -> bool:
        """Heuristic check for Signs & Songs / Forced non-dialogue tracks."""
        if self.is_forced or self.lang == "zxx":
            return True
        name_l = (self.track_name or "").lower()
        if "full" in name_l or "dialogue" in name_l:
            return False
        return any(tok in name_l for tok in ("signs", "songs", "s&s", "forced"))

    @property
    def is_sdh(self) -> bool:
        name_l = (self.track_name or "").lower()
        return any(tok in name_l for tok in ("sdh", "cc", "hearing impaired", "deaf"))

    def priority_key(self, preferred_format: str = "any") -> Tuple[int, int, int, int]:
        """
        Lower tuple sorts higher priority when selecting the primary track for an episode:
        1. Full dialogue over signs/forced
        2. Matches preferred format (default prefers ASS over SRT for anime styling)
        3. Non-SDH over SDH
        4. Marked default track
        """
        signs_penalty = 1 if self.is_signs_only else 0
        if preferred_format in ("ass", "any"):
            fmt_rank = 0 if self.format == "ass" else (1 if self.format == "srt" else 2)
        elif preferred_format == "srt":
            fmt_rank = 0 if self.format == "srt" else (1 if self.format == "ass" else 2)
        else:
            fmt_rank = 0 if self.format == preferred_format else 1
        sdh_penalty = 1 if self.is_sdh else 0
        default_rank = 0 if self.is_default else 1
        return (signs_penalty, fmt_rank, sdh_penalty, default_rank)


@dataclass
class FontAttachment:
    """Represents a downloadable font attachment (.ttf / .otf)."""

    provider: str
    name: str
    download_url: str
    compressed: str = "xz"


@dataclass
class ReleaseEntry:
    """Represents a torrent/release entry discovered on a provider."""

    provider: str
    release_id: str
    title: str
    group: Optional[str] = None
    is_batch: bool = False
    size_bytes: Optional[int] = None
    seeders: Optional[int] = None
    sub_langs: List[str] = field(default_factory=list)
    episode_no: Optional[int] = None
    view_url: Optional[str] = None
    pack_url: Optional[str] = None


@dataclass
class ProviderHealth:
    """Health & capability report for an Anime Tosho ecosystem service."""

    slug: str
    name: str
    url: str
    online: bool
    has_subtitles: bool
    supported_in_tool: bool
    latency_ms: Optional[int] = None
    notes: str = ""

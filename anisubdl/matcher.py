"""Episode/season matching, release group detection, and subtitle renaming."""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v"}
SUBTITLE_EXTENSIONS = {".ass", ".ssa", ".srt", ".vtt", ".sup"}

_NON_GROUP_TOKENS = {
    "1080p",
    "720p",
    "2160p",
    "480p",
    "4k",
    "bd",
    "bluray",
    "web",
    "dl",
    "webrip",
    "hevc",
    "avc",
    "av1",
    "x264",
    "x265",
    "h264",
    "h265",
    "10bit",
    "8bit",
    "hi10p",
    "aac",
    "flac",
    "opus",
    "eac3",
    "ac3",
    "sub",
    "subs",
    "msub",
    "msubs",
    "multisub",
    "multisubs",
    "dual",
    "audio",
    "dub",
    "batch",
    "uncensored",
    "weekly",
}


def extract_release_group(name: str) -> Optional[str]:
    """
    Extract release group from either '[Group] Title...' or 'Title.1080p.WEB-DL-Group'.
    """
    if not name:
        return None
    s = os.path.basename(name).strip()
    # Strip known media/subtitle extensions
    s = re.sub(r"\.(?:ass|ssa|srt|vtt|xz|7z|zip|mkv|mp4|avi|mov|webm)$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\.(?:ass|ssa|srt|vtt|mkv|mp4)$", "", s, flags=re.IGNORECASE)

    # 1. Leading [Group]
    m_lead = re.match(r"^\[([^\]]{1,35})\]", s)
    if m_lead:
        cand = m_lead.group(1).strip()
        if cand.lower() not in _NON_GROUP_TOKENS and not re.fullmatch(r"[0-9A-Fa-f]{8}", cand):
            return cand

    # 2. Trailing scene/WEB-DL '-Group' (after stripping trailing parenthetical aliases or [CRC32])
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    cleaned = re.sub(r"\s*\[[0-9A-Fa-f]{8}\]\s*$", "", cleaned).strip()
    cleaned = re.sub(r"_track\d+(?:\.[A-Za-z0-9-]+)?$", "", cleaned).strip()
    m_trail = re.search(r"-([A-Za-z][A-Za-z0-9_]{1,24})$", cleaned)
    if m_trail:
        cand = m_trail.group(1)
        if cand.lower() not in _NON_GROUP_TOKENS and not re.fullmatch(r"[Ss]\d+[Ee]\d+|v\d+|\d+p", cand):
            return cand

    return None


def detect_local_release_groups(directory: str) -> List[str]:
    """Inspect existing video files in a directory and return detected release groups sorted by frequency."""
    if not os.path.isdir(directory):
        return []
    counts: Counter[str] = Counter()
    for fname in find_video_files(directory):
        grp = extract_release_group(fname)
        if grp:
            counts[grp] += 1
    return [grp for grp, _ in counts.most_common()]


def extract_episode_info(filename: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract (season, episode) integers from an anime video or subtitle filename.
    Returns (season_or_None, episode_or_None).
    """
    base = os.path.basename(filename)
    # Strip double/single extensions and track suffixes
    base = re.sub(r"\.(?:xz|gz|7z|zip)$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\.(?:ass|ssa|srt|vtt|sup|mkv|mp4|avi|mov|webm|m4v)$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"_track\d+(?:\.[A-Za-z0-9-]+)*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\.(?:forced|signs|sdh)(?:\.[A-Za-z0-9-]+)?$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\.[a-z]{2,3}(?:-[A-Za-z0-9]+)?$", "", base)

    # Remove CRC32 [8 hex chars]
    s = re.sub(r"\[[0-9A-Fa-f]{8}\]", " ", base)
    # Normalize underscores and dot-separated tokens to spaces so word boundaries (\b) always match
    s = s.replace("_", " ")
    s = re.sub(r"(?<=[A-Za-z0-9])\.(?=[A-Za-z0-9])", " ", s)
    # Remove resolutions, video/audio codecs, and years that could confuse number matching
    s = re.sub(r"\b(?:1920x1080|1280x720|3840x2160|2160p|1080p|720p|576p|480p)\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\b(?:x264|x265|h\s*264|h\s*265|hevc|av1|hi10p|10-?bit|8-?bit|aac(?:\s*2\s*0)?|opus(?:\s*2\s*0)?|ddp(?:\s*[25]\s*[01])?|e-?ac-?3|flacx?\d*)\b",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\((?:19|20)\d{2}\)", " ", s)

    # 1. Explicit S01E05 / S2E10
    m = re.search(r"\b[Ss](\d{1,2})[Ee](\d{1,4})(?:v\d+)?\b", s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 2. 1x05
    m = re.search(r"\b(\d{1,2})x(\d{2,4})(?:v\d+)?\b", s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 3. 'S2 - 10' or 'Season 2 - 10'
    m = re.search(r"\b[Ss](?:eason\s*)?0*(\d{1,2})\s*[-–]\s*0*(\d{1,4})(?:v\d+)?\b", s, flags=re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Capture optional season hint elsewhere in the title (e.g. '2nd Season - 05')
    season_hint: Optional[int] = None
    ms = re.search(r"\b(?:[Ss](?:eason\s*)?0*(\d{1,2})|(\d{1,2})(?:nd|rd|th)\s+Season)\b", s, flags=re.IGNORECASE)
    if ms:
        season_hint = int(ms.group(1) or ms.group(2))

    # 4. 'Episode 05' / 'Ep 05' / 'Ep.05'
    m = re.search(r"\b[Ee]p(?:isode)?\.?\s*0*(\d{1,4})(?:v\d+)?\b", s)
    if m:
        return season_hint, int(m.group(1))

    # 5. ' - 05 ' or ' -05 ' (standard fansub / SubsPlease / Erai-raws)
    # Avoid matching ranges like '01-12' (batches)
    m = re.search(r"(?:\s[-–]\s*|\s-)0*(\d{1,4})(?:v\d+)?(?!\s*[-–]\s*\d)(?=\s|\[|\(|$|\.)", s)
    if m:
        return season_hint, int(m.group(1))

    # 6. Bracketed episode number '[05]' or '[05v2]'
    m = re.search(r"\[\s*0*(\d{2,3})(?:v\d+)?\s*\]", s)
    if m:
        return season_hint, int(m.group(1))

    # 7. 'Show Title 05 - Episode Name' (number immediately before ' - Episode Title')
    m = re.search(r"\s0*(\d{2,3})(?:v\d+)?(?=\s+[-–]\s+[A-Za-z])", s)
    if m:
        ep = int(m.group(1))
        if not (1980 <= ep <= 2035):
            return season_hint, ep

    # 8. Trailing standalone number before brackets/end (e.g. 'Majestic Prince 25 [Dual-Audio]')
    m = re.search(r"\s0*(\d{2,3})(?:v\d+)?(?=\s*(?:\[|\(|$))", s)
    if m:
        ep = int(m.group(1))
        if not (1980 <= ep <= 2035):
            return season_hint, ep

    return season_hint, None


def extract_episode_number(filename: str) -> Optional[str]:
    """Backward-compatible helper returning zero-padded episode string (e.g. '05') or None."""
    _, ep = extract_episode_info(filename)
    if ep is None:
        return None
    return str(ep).zfill(2)


def parse_episode_filter(expr: Optional[str]) -> Optional[Set[int]]:
    """
    Parse an episode range expression like '1-12', '5', or '1,3,5-8' into a set of episode ints.
    Returns None if expr is empty/None.
    """
    if not expr or not expr.strip():
        return None
    episodes: Set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            if bounds[0].strip().isdigit() and bounds[1].strip().isdigit():
                start, end = int(bounds[0]), int(bounds[1])
                if start <= end and (end - start) <= 2000:
                    episodes.update(range(start, end + 1))
        elif part.isdigit():
            episodes.add(int(part))
    return episodes or None


def find_video_files(directory: str) -> List[str]:
    """Return sorted list of video filenames inside directory."""
    if not os.path.isdir(directory):
        return []
    return sorted(
        f
        for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
    )


def video_has_subtitle(directory: str, video_filename: str, lang: Optional[str] = None) -> bool:
    """Check whether a video file already has a matching external subtitle file on disk."""
    stem = os.path.splitext(video_filename)[0]
    existing = set(os.listdir(directory)) if os.path.isdir(directory) else set()
    for ext in SUBTITLE_EXTENSIONS:
        if f"{stem}{ext}" in existing:
            return True
        if lang and f"{stem}.{lang}{ext}" in existing:
            return True
    return False


@dataclass
class DownloadedSubtitle:
    """Metadata about a downloaded subtitle file on disk for smart renaming."""

    filepath: str
    lang: str = "en"
    format: str = "ass"
    is_signs_only: bool = False
    is_sdh: bool = False
    source_video_name: str = ""


def build_subtitle_rename_plan(
    directory: str,
    downloaded: List[DownloadedSubtitle],
    naming_style: str = "exact",
    multi_lang: bool = False,
    overwrite: bool = False,
) -> Dict[str, str]:
    """
    Match downloaded subtitle files to local video files by (season, episode) and construct
    safe target paths ({old_path: new_path}).
    - naming_style='exact': VideoName.ass (automatically switches to VideoName.lang.ass if multi_lang=True)
    - naming_style='lang' or 'plex': VideoName.en.ass / VideoName.en.forced.ass
    """
    video_files = find_video_files(directory)
    if not video_files or not downloaded:
        return {}

    video_index: List[Tuple[str, Optional[int], Optional[int]]] = []
    for vf in video_files:
        s_num, e_num = extract_episode_info(vf)
        if e_num is not None:
            video_index.append((vf, s_num, e_num))

    if not video_index:
        return {}

    use_lang_tag = naming_style in ("lang", "plex") or multi_lang
    plan: Dict[str, str] = {}
    reserved_targets: Set[str] = set()

    # Sort downloaded subtitles so primary full dialogue tracks claim primary filenames first
    ordered_subs = sorted(
        downloaded,
        key=lambda d: (1 if d.is_signs_only else 0, 1 if d.is_sdh else 0, 0 if d.format == "ass" else 1),
    )

    for item in ordered_subs:
        sub_season, sub_ep = extract_episode_info(item.source_video_name or item.filepath)
        if sub_ep is None:
            sub_season, sub_ep = extract_episode_info(item.filepath)
        if sub_ep is None:
            continue

        matched_video: Optional[str] = None
        # Pass 1: exact season + episode match when both have season numbers
        for vf, v_season, v_ep in video_index:
            if v_ep == sub_ep and sub_season is not None and v_season is not None and sub_season == v_season:
                matched_video = vf
                break
        # Pass 2: episode match when at least one side lacks explicit season
        if matched_video is None:
            for vf, v_season, v_ep in video_index:
                if v_ep == sub_ep and (sub_season is None or v_season is None):
                    matched_video = vf
                    break

        if not matched_video:
            continue

        video_stem = os.path.splitext(matched_video)[0]
        ext = os.path.splitext(item.filepath)[1] or f".{item.format}"

        suffix_parts: List[str] = []
        if use_lang_tag and item.lang and item.lang != "und":
            suffix_parts.append(item.lang)
        if item.is_signs_only:
            suffix_parts.append("forced")
        elif item.is_sdh and use_lang_tag:
            suffix_parts.append("sdh")

        suffix = ("." + ".".join(suffix_parts)) if suffix_parts else ""
        target_name = f"{video_stem}{suffix}{ext}"
        target_path = os.path.join(directory, target_name)

        if os.path.abspath(item.filepath) == os.path.abspath(target_path):
            continue
        if target_path in reserved_targets:
            continue
        if os.path.exists(target_path) and not overwrite:
            continue

        reserved_targets.add(target_path)
        plan[item.filepath] = target_path

    return plan

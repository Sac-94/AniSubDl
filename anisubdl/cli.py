"""Main CLI orchestration, track filtering, concurrent downloader, and batch mode."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import sys
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import __version__
from .anilist import clean_anime_query, extract_season_hint, resolve_anilist
from .config import AppConfig, load_config, save_config
from .matcher import (
    DownloadedSubtitle,
    build_subtitle_rename_plan,
    detect_local_release_groups,
    extract_episode_info,
    find_video_files,
    parse_episode_filter,
    video_has_subtitle,
)
from .models import (
    AnimeMetadata,
    FontAttachment,
    ReleaseEntry,
    SubtitleTrack,
    lang_matches,
    normalize_lang,
)
from .providers import SUPPORTED_PROVIDERS, check_ecosystem_health, get_provider
from .providers.base import (
    SubtitleProvider,
    create_http_session,
    extract_archive_bytes,
    request_with_backoff,
    sanitize_filename,
)
from . import ui

IGNORED_SUBDIRS = {"fonts", "subs", "subtitles", "extras", "featurettes", "ncop", "nced", "specials"}


def build_parser(cfg: AppConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subdl.py",
        description=(
            "AniSubDl v2 — Interactive & automated anime subtitle downloader supporting "
            "Anime Tosho NEW (animetosho.net), TsukiHime (tsukihime.org), and Kitsunekko."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python subdl.py \"/path/to/Anime\"                     # Interactive library mode\n"
            "  python subdl.py -q \"Sousou no Frieren\" -g SubsPlease  # Direct title query\n"
            "  python subdl.py \"/path/to/Anime\" -l en,ja --naming-style plex\n"
            "  python subdl.py \"/path/to/Anime\" -p tsukihime --fonts --rename auto\n"
            "  python subdl.py \"/path/to/Anime\" --batch              # Automated library scan\n"
            "  python subdl.py --check-providers                     # Test live mirror status\n"
        ),
    )
    parser.add_argument(
        "anime_dir",
        nargs="?",
        default=None,
        help="Path to your anime library root OR a single anime series folder.",
    )
    parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Search directly by anime title instead of browsing local folders.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Destination folder for downloaded subtitles (defaults to selected anime folder or ./downloads/<title>).",
    )
    parser.add_argument(
        "-p",
        "--provider",
        choices=SUPPORTED_PROVIDERS,
        default=cfg.provider,
        help=f"Subtitle source provider (default: {cfg.provider}). 'auto' queries animetosho.net + tsukihime.org + kitsunekko fallback.",
    )
    parser.add_argument(
        "--custom-url",
        default=cfg.custom_animetosho_url,
        help="Custom Anime Tosho-compatible domain/URL if using a self-hosted or alternate mirror.",
    )
    parser.add_argument(
        "-g",
        "--group",
        default=None,
        help="Release group to select automatically (e.g. SubsPlease, Erai-raws, VARYG, or ALL).",
    )
    parser.add_argument(
        "-l",
        "--lang",
        default=cfg.lang,
        help=f"Comma-separated subtitle languages, e.g. 'en', 'ja', 'en,es', 'pt-BR', or 'all' (default: {cfg.lang}).",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("any", "ass", "srt"),
        default=cfg.format,
        help=f"Subtitle format filter (default: {cfg.format}).",
    )
    parser.add_argument(
        "-r",
        "--resolution",
        choices=("2160p", "1080p", "720p", "480p", "any"),
        default=cfg.resolution,
        help=f"Preferred video release resolution filter (default: {cfg.resolution}).",
    )
    parser.add_argument(
        "-e",
        "--episodes",
        default=None,
        help="Episode filter range, e.g. '1-12', '5', or '1,3,5-8'.",
    )
    parser.add_argument(
        "--include-forced",
        action="store_true",
        help="Include Forced / Signs & Songs tracks (saved with .forced suffix so full subs are never overwritten).",
    )
    parser.add_argument(
        "--all-tracks",
        action="store_true",
        help="Download every matching track instead of deduplicating to the best track per episode & language.",
    )
    parser.add_argument(
        "--fonts",
        action="store_true",
        help="Also download attached .ttf/.otf font files into a Fonts/ subdirectory.",
    )
    parser.add_argument(
        "--all-attachments",
        action="store_true",
        help="Download full .7z attachment bundles (subtitles + fonts) when offered by the provider.",
    )
    parser.add_argument(
        "--rename",
        choices=("ask", "auto", "never"),
        default=None,
        help="Rename downloaded subtitles to match local video filenames ('ask' default, 'auto' in --batch).",
    )
    parser.add_argument(
        "--naming-style",
        choices=("exact", "lang", "plex"),
        default=cfg.naming_style,
        help=f"Renamed subtitle style: 'exact' (Video.ass) or 'lang'/'plex' (Video.en.ass) (default: {cfg.naming_style}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing subtitle files if already present.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Non-interactive batch mode: scan series folders, auto-match release groups, download & rename missing subs.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=cfg.workers,
        help=f"Concurrent download threads (default: {cfg.workers}).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Maximum search result pages to inspect per provider (default: 2).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate search, track selection, and file renaming without writing any files.",
    )
    parser.add_argument(
        "--save-defaults",
        action="store_true",
        help="Save the current CLI options (provider, lang, format, resolution, naming-style, workers) to subdl.cfg.",
    )
    parser.add_argument(
        "--check-providers",
        action="store_true",
        help="Test live status & subtitle availability across Anime Tosho continuation sites and exit.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"AniSubDl {__version__}",
    )
    return parser


def filter_and_deduplicate_tracks(
    tracks: List[SubtitleTrack],
    requested_langs: List[str],
    fmt_filter: str = "any",
    include_forced: bool = False,
    all_tracks: bool = False,
    episode_set: Optional[Set[int]] = None,
    season_hint: Optional[int] = None,
) -> List[SubtitleTrack]:
    """Filter subtitle tracks by language, format, signs/forced status, and episode; deduplicate cleanly."""
    filtered: List[SubtitleTrack] = []

    for tr in tracks:
        is_archive = tr.format in ("zip", "7z", "rar")
        if not is_archive:
            # Signs / Forced check
            if tr.is_signs_only and not include_forced:
                continue
            # Language check (allow zxx signs track only when include_forced is True)
            if not (include_forced and tr.lang == "zxx"):
                if not lang_matches(tr.lang, requested_langs):
                    continue
            # Format check
            if fmt_filter != "any" and tr.format != fmt_filter:
                continue

        # Season & Episode check
        tr_season, tr_ep = extract_episode_info(tr.video_filename)
        if season_hint is not None and tr_season is not None and tr_season != season_hint:
            continue
        if episode_set is not None and tr_ep is not None and tr_ep not in episode_set:
            continue

        filtered.append(tr)

    if all_tracks:
        return filtered

    # Deduplicate to the highest-priority track per (episode_key, lang, is_signs_only)
    best_map: Dict[Tuple[str, str, bool], SubtitleTrack] = {}
    for tr in filtered:
        tr_season, tr_ep = extract_episode_info(tr.video_filename)
        if tr_ep is not None:
            ep_key = f"s{tr_season or 0:02d}e{tr_ep:04d}"
        else:
            ep_key = os.path.splitext(tr.video_filename)[0].lower()

        dedup_key = (ep_key, tr.lang, tr.is_signs_only)
        existing = best_map.get(dedup_key)
        if existing is None or tr.priority_key(fmt_filter) < existing.priority_key(fmt_filter):
            best_map[dedup_key] = tr

    # Sort cleanly by episode key then language
    return [best_map[k] for k in sorted(best_map.keys())]


def build_track_output_filename(
    track: SubtitleTrack,
    multi_lang: bool,
    naming_style: str,
    all_tracks: bool,
) -> str:
    """Build safe initial filename in output_dir before video-matching rename."""
    if track.compressed in ("zip", "7z", "rar"):
        return sanitize_filename(track.video_filename)

    stem = os.path.splitext(os.path.basename(track.video_filename))[0]
    parts: List[str] = []
    if (multi_lang or naming_style in ("lang", "plex") or all_tracks) and track.lang and track.lang != "und":
        parts.append(track.lang)
    if track.is_signs_only:
        parts.append("forced")
    if all_tracks and track.track_num is not None:
        parts.append(f"track{track.track_num}")
    suffix = ("." + ".".join(parts)) if parts else ""
    return sanitize_filename(f"{stem}{suffix}.{track.format}")


def download_tracks_concurrently(
    tracks: List[SubtitleTrack],
    fonts: List[FontAttachment],
    output_dir: str,
    workers: int = 4,
    multi_lang: bool = False,
    naming_style: str = "exact",
    all_tracks: bool = False,
    download_fonts: bool = False,
    download_packs: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
) -> List[DownloadedSubtitle]:
    """Download and extract subtitle tracks (and optional fonts / .7z packs) in parallel."""
    downloaded: List[DownloadedSubtitle] = []
    if not tracks and not (download_fonts and fonts):
        return downloaded

    if dry_run:
        ui.info(f"[Dry-Run] Would download {len(tracks)} subtitle track(s) into '{output_dir}':")
        for tr in tracks:
            fname = build_track_output_filename(tr, multi_lang, naming_style, all_tracks)
            ui.info(f"  • [{tr.provider}] {fname} ({tr.lang}, {tr.format.upper()})")
            downloaded.append(
                DownloadedSubtitle(
                    filepath=os.path.join(output_dir, fname),
                    lang=tr.lang,
                    format=tr.format,
                    is_signs_only=tr.is_signs_only,
                    is_sdh=tr.is_sdh,
                    source_video_name=tr.video_filename,
                )
            )
        if download_fonts and fonts:
            ui.info(f"[Dry-Run] Would also download {len(fonts)} font attachment(s) into '{os.path.join(output_dir, 'Fonts')}'.")
        return downloaded

    os.makedirs(output_dir, exist_ok=True)
    max_workers = max(1, min(workers, 16))

    def _fetch_one_sub(tr: SubtitleTrack) -> List[DownloadedSubtitle]:
        out_name = build_track_output_filename(tr, multi_lang, naming_style, all_tracks)
        expected_path = os.path.join(output_dir, out_name)
        if os.path.exists(expected_path) and not overwrite and tr.compressed in ("xz", "none"):
            return [
                DownloadedSubtitle(
                    filepath=expected_path,
                    lang=tr.lang,
                    format=tr.format,
                    is_signs_only=tr.is_signs_only,
                    is_sdh=tr.is_sdh,
                    source_video_name=tr.video_filename,
                )
            ]

        sess = create_http_session()
        resp = request_with_backoff(sess, "GET", tr.download_url, timeout=25)
        written_paths = extract_archive_bytes(resp.content, tr.compressed, output_dir, out_name)
        items: List[DownloadedSubtitle] = []
        for wp in written_paths:
            ext = os.path.splitext(wp)[1].lower().lstrip(".")
            if ext in ("ass", "ssa", "srt", "vtt", "sup"):
                items.append(
                    DownloadedSubtitle(
                        filepath=wp,
                        lang=tr.lang,
                        format=ext,
                        is_signs_only=tr.is_signs_only,
                        is_sdh=tr.is_sdh,
                        source_video_name=tr.video_filename if len(written_paths) == 1 else os.path.basename(wp),
                    )
                )
        return items

    def _fetch_one_font(fa: FontAttachment) -> Optional[str]:
        fonts_dir = os.path.join(output_dir, "Fonts")
        os.makedirs(fonts_dir, exist_ok=True)
        target = os.path.join(fonts_dir, sanitize_filename(fa.name))
        if os.path.exists(target) and not overwrite:
            return target
        sess = create_http_session()
        resp = request_with_backoff(sess, "GET", fa.download_url, timeout=25)
        paths = extract_archive_bytes(resp.content, fa.compressed, fonts_dir, fa.name)
        return paths[0] if paths else None

    progress = ui.make_progress()
    errors: List[str] = []

    if progress:
        with progress:
            sub_task = progress.add_task("[cyan]Downloading subtitles...", total=len(tracks))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                fut_map = {pool.submit(_fetch_one_sub, tr): tr for tr in tracks}
                for fut in as_completed(fut_map):
                    tr = fut_map[fut]
                    try:
                        downloaded.extend(fut.result())
                    except Exception as exc:
                        errors.append(f"{tr.video_filename}: {exc}")
                    progress.advance(sub_task)

            if download_fonts and fonts:
                font_task = progress.add_task("[magenta]Downloading fonts...", total=len(fonts))
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    font_futs = [pool.submit(_fetch_one_font, fa) for fa in fonts]
                    for fut in as_completed(font_futs):
                        try:
                            fut.result()
                        except Exception as exc:
                            errors.append(f"Font error: {exc}")
                        progress.advance(font_task)
    else:
        ui.info(f"Downloading {len(tracks)} subtitle file(s)...")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_map = {pool.submit(_fetch_one_sub, tr): tr for tr in tracks}
            for fut in as_completed(fut_map):
                tr = fut_map[fut]
                try:
                    downloaded.extend(fut.result())
                except Exception as exc:
                    errors.append(f"{tr.video_filename}: {exc}")

        if download_fonts and fonts:
            ui.info(f"Downloading {len(fonts)} font file(s)...")
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for fut in as_completed([pool.submit(_fetch_one_font, fa) for fa in fonts]):
                    try:
                        fut.result()
                    except Exception as exc:
                        errors.append(f"Font error: {exc}")

    # Optional .7z all-attachments packs
    if download_packs:
        pack_urls = sorted({tr.pack_url for tr in tracks if tr.pack_url})
        if pack_urls:
            ui.info(f"Downloading {len(pack_urls)} attachment pack(s) (.7z)...")
            sess = create_http_session()
            for idx, p_url in enumerate(pack_urls, 1):
                try:
                    resp = request_with_backoff(sess, "GET", p_url, timeout=45)
                    extract_archive_bytes(resp.content, "7z", output_dir, f"attachments_pack_{idx}.7z")
                except Exception as exc:
                    errors.append(f"Pack {p_url}: {exc}")

    for err in errors[:5]:
        ui.warn(f"Download issue — {err}")

    return downloaded


def handle_renaming(
    directory: str,
    downloaded: List[DownloadedSubtitle],
    rename_mode: str,
    naming_style: str,
    multi_lang: bool,
    overwrite: bool,
    dry_run: bool,
) -> int:
    """Match downloaded subtitles to local video files and apply or prompt for renaming."""
    if rename_mode == "never" or not downloaded:
        return 0

    plan = build_subtitle_rename_plan(
        directory=directory,
        downloaded=downloaded,
        naming_style=naming_style,
        multi_lang=multi_lang,
        overwrite=overwrite,
    )
    if not plan:
        video_files = find_video_files(directory)
        if video_files:
            ui.info("No additional subtitle renames needed (already named or no matching episode numbers).")
        return 0

    ui.info(f"Proposed subtitle renames ({len(plan)} file(s)):")
    for old_p, new_p in plan.items():
        print(f"  '{os.path.basename(old_p)}'  ->  '{os.path.basename(new_p)}'")

    if dry_run:
        ui.info("[Dry-Run] Skipping actual file renames.")
        return len(plan)

    apply_changes = True if rename_mode == "auto" else ui.confirm_prompt("Apply these renames?", default=True)
    if not apply_changes:
        ui.info("Renaming skipped.")
        return 0

    renamed_count = 0
    for old_p, new_p in plan.items():
        try:
            os.replace(old_p, new_p)
            renamed_count += 1
        except OSError as exc:
            ui.error(f"Could not rename '{os.path.basename(old_p)}': {exc}")

    ui.success(f"Renamed {renamed_count} subtitle file(s) to match local video files.")
    return renamed_count


def group_releases_by_tag(releases: List[ReleaseEntry]) -> Tuple[List[str], Dict[str, List[ReleaseEntry]]]:
    """Bucket ReleaseEntry objects by release group name (with 'Ungrouped' fallback)."""
    grouped: Dict[str, List[ReleaseEntry]] = {}
    for rel in releases:
        grp = rel.group or "Ungrouped"
        grouped.setdefault(grp, []).append(rel)

    sorted_groups = sorted(grouped.keys(), key=lambda g: (g == "Ungrouped", g.lower()))
    return sorted_groups, grouped


def process_single_series(
    series_name: str,
    target_dir: str,
    provider: SubtitleProvider,
    requested_langs: List[str],
    args: argparse.Namespace,
    interactive: bool = True,
) -> bool:
    """Search, select group, download subtitles (+ optional fonts), and rename for one anime series."""
    cleaned_name = clean_anime_query(series_name)
    season_hint = extract_season_hint(series_name)
    ui.info(f"Resolving metadata on AniList for [bold]{cleaned_name}[/bold]..." if ui.HAS_RICH else f"Resolving AniList metadata for '{cleaned_name}'...")

    metadata: Optional[AnimeMetadata] = resolve_anilist(series_name, session=provider.session)
    if metadata and metadata.romaji_title:
        eng_note = f" / {metadata.english_title}" if metadata.english_title and metadata.english_title != metadata.romaji_title else ""
        ui.success(f"Matched AniList #{metadata.anilist_id}: {metadata.romaji_title}{eng_note}")
    else:
        ui.warn(f"No AniList match for '{cleaned_name}'; searching providers directly with folder/query title.")

    ui.info(f"Searching {provider.name} (resolution={args.resolution})...")
    releases = provider.find_releases(
        title=cleaned_name,
        metadata=metadata,
        resolution=args.resolution,
        max_pages=args.max_pages,
    )

    if not releases:
        ui.warn(f"No releases with subtitles found for '{series_name}'.")
        return False

    group_names, grouped_map = group_releases_by_tag(releases)
    local_groups = detect_local_release_groups(target_dir)

    selected_releases: List[ReleaseEntry] = []
    if args.group:
        if args.group.upper() == "ALL":
            selected_releases = releases
            ui.info(f"Selected ALL release groups ({len(releases)} release entries).")
        else:
            matched_g = next((g for g in group_names if g.lower() == args.group.lower()), None)
            if not matched_g:
                matched_g = next((g for g in group_names if args.group.lower() in g.lower()), None)
            if not matched_g:
                ui.error(f"Release group '{args.group}' not found. Available: {', '.join(group_names)}")
                return False
            selected_releases = grouped_map[matched_g]
            ui.info(f"Selected release group: {matched_g} ({len(selected_releases)} entries)")
    elif not interactive:
        # Batch mode auto-selection: prefer group matching local video files, else group with most entries
        chosen_g: Optional[str] = None
        for lg in local_groups:
            chosen_g = next((g for g in group_names if g.lower() == lg.lower()), None)
            if chosen_g:
                break
        if not chosen_g:
            chosen_g = max(group_names, key=lambda g: len(grouped_map[g]))
        selected_releases = grouped_map[chosen_g]
        ui.info(f"[Batch] Auto-selected release group '{chosen_g}' ({len(selected_releases)} entries)")
    else:
        # Interactive selection menu with provider/batch/local-match annotations
        menu_items = list(group_names) + ["[ALL GROUPS]"]
        annotations: List[str] = []
        default_idx: Optional[int] = None
        for idx, g in enumerate(group_names):
            rels = grouped_map[g]
            provs = sorted({r.provider for r in rels})
            batch_tag = ", includes Batch" if any(r.is_batch for r in rels) else ""
            local_tag = ""
            if any(g.lower() == lg.lower() for lg in local_groups):
                local_tag = " ★ Matches your local video files"
                if default_idx is None:
                    default_idx = idx
            annotations.append(f"{len(rels)} release(s) via {'+'.join(provs)}{batch_tag}{local_tag}")
        annotations.append(f"Search across all {len(releases)} releases")

        choice_idx = ui.select_from_list(
            menu_items,
            prompt=f"Select a release group for '{series_name}':",
            annotations=annotations,
            default_index=default_idx,
        )
        if choice_idx is None:
            return False
        if choice_idx == len(group_names):
            selected_releases = releases
        else:
            chosen_g = group_names[choice_idx]
            selected_releases = grouped_map[chosen_g]
            ui.info(f"Selected release group: {chosen_g}")

    # Cap excessive redundant torrent lookups when a group has dozens of reposts
    selected_releases = selected_releases[:40]
    ui.info(f"Inspecting subtitle attachments across {len(selected_releases)} release(s)...")
    tracks, fonts = provider.fetch_tracks_for_releases(selected_releases)

    episode_set = parse_episode_filter(args.episodes)

    # In --batch mode without --overwrite, skip episodes that already have local subtitles
    if args.batch and not args.overwrite and os.path.isdir(target_dir):
        primary_lang = normalize_lang(requested_langs[0]) if len(requested_langs) == 1 and requested_langs[0] != "all" else None
        missing_eps: Set[int] = set()
        local_videos = find_video_files(target_dir)
        for vf in local_videos:
            if not video_has_subtitle(target_dir, vf, lang=primary_lang):
                _, ep = extract_episode_info(vf)
                if ep is not None:
                    missing_eps.add(ep)
        if local_videos and not missing_eps:
            ui.success(f"[Batch] All {len(local_videos)} video file(s) in '{series_name}' already have subtitles.")
            return True
        if missing_eps:
            episode_set = (episode_set & missing_eps) if episode_set else missing_eps

    matched_tracks = filter_and_deduplicate_tracks(
        tracks=tracks,
        requested_langs=requested_langs,
        fmt_filter=args.format,
        include_forced=args.include_forced,
        all_tracks=args.all_tracks,
        episode_set=episode_set,
        season_hint=season_hint,
    )

    if not matched_tracks:
        avail_langs = sorted({t.lang for t in tracks})
        avail_fmts = sorted({t.format for t in tracks})
        ui.warn(
            f"No tracks matched filters (lang={','.join(requested_langs)}, format={args.format}). "
            f"Available in selected group: langs={avail_langs or 'none'}, formats={avail_fmts or 'none'}."
        )
        return False

    multi_lang = len({t.lang for t in matched_tracks}) > 1 or ("all" in requested_langs)
    ui.success(f"Matched {len(matched_tracks)} subtitle track(s) ready for download.")

    downloaded = download_tracks_concurrently(
        tracks=matched_tracks,
        fonts=fonts,
        output_dir=target_dir,
        workers=args.workers,
        multi_lang=multi_lang,
        naming_style=args.naming_style,
        all_tracks=args.all_tracks,
        download_fonts=args.fonts,
        download_packs=args.all_attachments,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    if downloaded:
        if not args.dry_run:
            ui.success(f"Downloaded and extracted {len(downloaded)} subtitle file(s) to '{target_dir}'.")
        rename_mode = args.rename or ("auto" if args.batch else "ask")
        handle_renaming(
            directory=target_dir,
            downloaded=downloaded,
            rename_mode=rename_mode,
            naming_style=args.naming_style,
            multi_lang=multi_lang,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        return True

    return False


def discover_series_targets(root_path: str) -> List[Tuple[str, str]]:
    """
    Given a user-supplied path, return list of (series_display_name, directory_path).
    Supports BOTH an anime library root containing series folders AND pointing directly
    to a single series directory containing .mkv/.mp4 files.
    """
    subdirs = sorted(
        d
        for d in os.listdir(root_path)
        if os.path.isdir(os.path.join(root_path, d))
        and not d.startswith(".")
        and d.lower() not in IGNORED_SUBDIRS
    )
    direct_videos = find_video_files(root_path)

    if direct_videos and not subdirs:
        # User pointed directly at a single anime series folder!
        series_title = os.path.basename(os.path.abspath(root_path))
        return [(series_title, root_path)]

    targets = [(d, os.path.join(root_path, d)) for d in subdirs]
    if direct_videos and subdirs:
        series_title = os.path.basename(os.path.abspath(root_path))
        targets.insert(0, (f"{series_title} (current folder)", root_path))
    return targets


def main(argv: Optional[Sequence[str]] = None) -> int:
    cfg = load_config()
    parser = build_parser(cfg)
    args = parser.parse_args(argv)

    ui.print_banner(__version__)

    if args.check_providers:
        ui.info("Checking live connectivity across Anime Tosho successors & subtitle archives...")
        reports = check_ecosystem_health()
        ui.render_provider_health(reports)
        return 0

    requested_langs = [x.strip() for x in (args.lang or "en").split(",") if x.strip()] or ["en"]
    provider = get_provider(
        provider_slug=args.provider,
        custom_at_url=args.custom_url,
        langs=requested_langs,
    )

    # Persist preferences if requested
    if args.save_defaults:
        cfg.provider = args.provider
        cfg.lang = args.lang
        cfg.format = args.format
        cfg.resolution = args.resolution
        cfg.naming_style = args.naming_style
        cfg.workers = args.workers
        if args.custom_url:
            cfg.custom_animetosho_url = args.custom_url
        if args.anime_dir and os.path.isdir(args.anime_dir):
            cfg.anime_dir = os.path.abspath(args.anime_dir)
        if save_config(cfg):
            ui.success("Saved CLI defaults to subdl.cfg.")

    # Mode A: Direct --query mode (no local anime library folder required)
    if args.query:
        out_dir = args.output or os.path.join(os.getcwd(), "downloads", sanitize_filename(clean_anime_query(args.query)))
        interactive = not args.batch and sys.stdin.isatty()
        ok = process_single_series(
            series_name=args.query,
            target_dir=out_dir,
            provider=provider,
            requested_langs=requested_langs,
            args=args,
            interactive=interactive,
        )
        return 0 if ok else 1

    # Mode B: Directory-based library or single-series mode
    anime_root = args.anime_dir or cfg.anime_dir
    if anime_root and not args.anime_dir:
        ui.info(f"Loaded anime directory from config: {anime_root}")

    if not anime_root:
        try:
            anime_root = input("Please enter the path to your anime directory: ").strip().strip('"').strip("'")
        except EOFError:
            ui.error("No anime directory provided.")
            return 1

    if not anime_root or not os.path.isdir(anime_root):
        ui.error(f"The path '{anime_root}' is not a valid directory.")
        return 1

    anime_root = os.path.abspath(anime_root)
    cfg.anime_dir = anime_root
    save_config(cfg)

    targets = discover_series_targets(anime_root)
    if not targets:
        ui.warn(f"No anime series folders or video files found in '{anime_root}'.")
        return 1

    # Batch mode across all discovered folders
    if args.batch:
        ui.info(f"Running non-interactive batch scan across {len(targets)} folder(s)...")
        succeeded = 0
        for s_name, s_path in targets:
            clean_label = s_name.replace(" (current folder)", "")
            print()
            ui.info(f"=== [Batch] {clean_label} ===")
            out_dir = args.output or s_path
            if process_single_series(
                series_name=clean_label,
                target_dir=out_dir,
                provider=provider,
                requested_langs=requested_langs,
                args=args,
                interactive=False,
            ):
                succeeded += 1
        ui.success(f"Batch run complete: {succeeded}/{len(targets)} series processed successfully.")
        return 0 if succeeded > 0 else 1

    # Single folder auto-run if user pointed directly to a single anime folder
    if len(targets) == 1 and targets[0][1] == anime_root:
        s_name, s_path = targets[0]
        clean_label = s_name.replace(" (current folder)", "")
        ui.info(f"Detected single anime folder: {clean_label}")
        ok = process_single_series(
            series_name=clean_label,
            target_dir=args.output or s_path,
            provider=provider,
            requested_langs=requested_langs,
            args=args,
            interactive=sys.stdin.isatty(),
        )
        return 0 if ok else 1

    # Interactive folder selection
    labels = [t[0] for t in targets]
    notes = []
    for _, p in targets:
        vids = find_video_files(p)
        notes.append(f"{len(vids)} video file(s)" if vids else "folder")

    idx = ui.select_from_list(labels, prompt="Select an anime directory:", annotations=notes)
    if idx is None:
        return 0

    chosen_name, chosen_path = targets[idx]
    clean_label = chosen_name.replace(" (current folder)", "")
    ok = process_single_series(
        series_name=clean_label,
        target_dir=args.output or chosen_path,
        provider=provider,
        requested_langs=requested_langs,
        args=args,
        interactive=True,
    )
    return 0 if ok else 1

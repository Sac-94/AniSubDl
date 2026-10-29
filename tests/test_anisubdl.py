"""Unit and live-provider integration tests for AniSubDl v2."""

from __future__ import annotations

import lzma
import os
import tempfile

from anisubdl.anilist import clean_anime_query, extract_season_hint, resolve_anilist
from anisubdl.cli import filter_and_deduplicate_tracks, main
from anisubdl.config import AppConfig, load_config, save_config
from anisubdl.matcher import (
    DownloadedSubtitle,
    build_subtitle_rename_plan,
    detect_local_release_groups,
    extract_episode_info,
    extract_release_group,
    parse_episode_filter,
)
from anisubdl.models import SubtitleTrack, lang_matches, normalize_lang
from anisubdl.providers.animetosho import AnimeToshoProvider
from anisubdl.providers.base import extract_archive_bytes
from anisubdl.providers.subdl_com import is_safe_subdl_download_url, redact_api_key
from anisubdl.providers.tsukihime import TsukiHimeProvider


def test_clean_anime_query_and_season_hint():
    assert clean_anime_query("[SubsPlease] Sousou no Frieren (2023) [1080p] [Batch]") == "Sousou no Frieren"
    assert clean_anime_query("Frieren.Beyond.Journeys.End.S01.1080p.BluRay.x265") == "Frieren Beyond Journeys End S01"
    assert extract_season_hint("Kusuriya no Hitorigoto 2nd Season") == 2
    assert extract_season_hint("Sousou no Frieren S02") == 2
    assert extract_season_hint("Odd Taxi (2021)") is None


def test_extract_release_group_variants():
    assert extract_release_group("[SubsPlease] Sousou no Frieren - 01 (1080p) [7D35515E].mkv") == "SubsPlease"
    assert extract_release_group("[Erai-raws] Dandadan - 05 [1080p][MultiSub][ABCD1234].mkv") == "Erai-raws"
    assert (
        extract_release_group(
            "Overgeared S01E01 1080p CR WEB-DL DUAL AAC2.0 H.264-VARYG (Temppal, Multi-Subs)"
        )
        == "VARYG"
    )
    assert (
        extract_release_group(
            "Nia.Liston.The.Merciless.Maiden.S01E01.1080p.AMZN.WEB-DL.JPN.AAC2.0.H.264.MSubs-ToonsHub.mkv"
        )
        == "ToonsHub"
    )


def test_extract_episode_info_patterns():
    assert extract_episode_info("[SubsPlease] Sousou no Frieren S2 - 10 (1080p) [7D35515E].mkv") == (2, 10)
    assert extract_episode_info("Overgeared.S01E05.1080p.CR.WEB-DL.H.264-VARYG.mkv") == (1, 5)
    assert extract_episode_info("[Erai-raws] Shin Tennis no Ouji-sama -05 [1080p CR WEBRip][CF0353B5].mkv") == (None, 5)
    assert extract_episode_info("[Kulot] Ginga Kikoutai Majestic Prince 25 [Dual-Audio][BDRip 1920x1080] [9ADA3F8A].mkv") == (
        None,
        25,
    )
    assert extract_episode_info("Anime Name - Episode 03v2 [1080p].ass") == (None, 3)
    assert extract_episode_info("[a-s].hack Liminality 01 - In the Case of Mai Minase.ass") == (None, 1)


def test_language_normalization_and_matching():
    assert normalize_lang("eng") == "en"
    assert normalize_lang("pt-BR") == "pt-BR"
    assert normalize_lang("spa", "Latin American") == "es-419"
    assert lang_matches("es-419", ["es"]) is True
    assert lang_matches("es", ["es-419"]) is False
    assert lang_matches("pt-BR", ["pt"]) is True
    assert lang_matches("ja", ["en,ja".split(",")][0]) is True


def test_signs_and_forced_never_overwrite_full_subs():
    tracks = [
        SubtitleTrack(
            provider="tsukihime",
            release_id="1",
            release_title="Test",
            video_filename="Show - S01E01 [1080p].mkv",
            download_url="https://example.com/signs.xz",
            lang="en",
            format="ass",
            track_name="Signs & Songs",
            is_default=False,
            is_forced=True,
        ),
        SubtitleTrack(
            provider="tsukihime",
            release_id="1",
            release_title="Test",
            video_filename="Show - S01E01 [1080p].mkv",
            download_url="https://example.com/full.xz",
            lang="en",
            format="ass",
            track_name="Full Subtitles",
            is_default=True,
            is_forced=False,
        ),
    ]
    selected_default = filter_and_deduplicate_tracks(tracks, requested_langs=["en"], include_forced=False)
    assert len(selected_default) == 1
    assert selected_default[0].download_url == "https://example.com/full.xz"

    selected_with_forced = filter_and_deduplicate_tracks(tracks, requested_langs=["en"], include_forced=True)
    assert len(selected_with_forced) == 2


def test_rename_plan_exact_and_plex():
    with tempfile.TemporaryDirectory() as tmp:
        v1 = os.path.join(tmp, "[SubsPlease] Show - 01 (1080p).mkv")
        v2 = os.path.join(tmp, "[SubsPlease] Show - 02 (1080p).mkv")
        s1_en = os.path.join(tmp, "Downloaded_Show_S01E01.en.ass")
        s1_ja = os.path.join(tmp, "Downloaded_Show_S01E01.ja.ass")
        for p in (v1, v2, s1_en, s1_ja):
            with open(p, "w", encoding="utf-8") as f:
                f.write("dummy")

        assert detect_local_release_groups(tmp) == ["SubsPlease"]

        dl_single = [DownloadedSubtitle(filepath=s1_en, lang="en", format="ass")]
        plan_exact = build_subtitle_rename_plan(tmp, dl_single, naming_style="exact", multi_lang=False)
        assert plan_exact[s1_en] == os.path.join(tmp, "[SubsPlease] Show - 01 (1080p).ass")

        dl_multi = [
            DownloadedSubtitle(filepath=s1_en, lang="en", format="ass"),
            DownloadedSubtitle(filepath=s1_ja, lang="ja", format="ass"),
        ]
        plan_multi = build_subtitle_rename_plan(tmp, dl_multi, naming_style="exact", multi_lang=True)
        assert plan_multi[s1_en] == os.path.join(tmp, "[SubsPlease] Show - 01 (1080p).en.ass")
        assert plan_multi[s1_ja] == os.path.join(tmp, "[SubsPlease] Show - 01 (1080p).ja.ass")


def test_legacy_and_v2_config_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        anime_folder = os.path.join(tmp, "AnimeLib")
        os.makedirs(anime_folder)
        cfg_file = os.path.join(tmp, "subdl.cfg")

        # Legacy plain-text v1 format
        with open(cfg_file, "w", encoding="utf-8") as f:
            f.write(anime_folder + "\n")
        loaded_v1 = load_config(cfg_file)
        assert loaded_v1.anime_dir == anime_folder

        # v2 JSON format
        new_cfg = AppConfig(anime_dir=anime_folder, provider="tsukihime", lang="en,ja", naming_style="plex")
        assert save_config(new_cfg, cfg_file) is True
        loaded_v2 = load_config(cfg_file)
        assert loaded_v2.provider == "tsukihime"
        assert loaded_v2.lang == "en,ja"
        assert loaded_v2.naming_style == "plex"


def test_xz_extraction_and_episode_filter():
    assert parse_episode_filter("1-3, 7") == {1, 2, 3, 7}
    with tempfile.TemporaryDirectory() as tmp:
        payload = lzma.compress(b"[Script Info]\nTitle: UnitTest\n")
        written = extract_archive_bytes(payload, "xz", tmp, "Episode 01.ass")
        assert len(written) == 1
        with open(written[0], "rb") as f:
            assert b"UnitTest" in f.read()


def test_live_anilist_animetosho_and_tsukihime():
    meta = resolve_anilist("Sousou no Frieren")
    assert meta is not None
    assert meta.anilist_id == 154587

    at = AnimeToshoProvider()
    at_rels = at.find_releases("Sousou no Frieren", metadata=meta, resolution="1080p", max_pages=1)
    assert len(at_rels) > 0

    tsuki = TsukiHimeProvider()
    ts_rels = tsuki.find_releases("Sousou no Frieren", metadata=meta, resolution="1080p", max_pages=1)
    assert len(ts_rels) > 0
    tracks, _fonts = tsuki.fetch_tracks_for_releases(ts_rels[:2])
    assert len(tracks) > 0


def test_cli_dry_run_query():
    with tempfile.TemporaryDirectory() as tmp:
        rc = main(
            [
                "-q",
                "Sousou no Frieren",
                "-p",
                "tsukihime",
                "-g",
                "BlackRabbit",
                "-e",
                "1-2",
                "-o",
                tmp,
                "--dry-run",
            ]
        )
        assert rc == 0


def test_subdl_security_and_zip_hardening():
    assert is_safe_subdl_download_url("https://dl.subdl.com/subtitle/12345.zip") is True
    assert is_safe_subdl_download_url("http://dl.subdl.com/subtitle/12345.zip") is False
    assert is_safe_subdl_download_url("https://evil-subdl.com/subtitle/12345.zip") is False
    assert redact_api_key("GET https://api.subdl.com?api_key=SECRET123 failed", "SECRET123") == (
        "GET https://api.subdl.com?api_key=*** failed"
    )

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("__MACOSX/ep01.ass", "junk")
        zf.writestr("._ep01.ass", "junk")
        zf.writestr("ep01.ass", "[Script Info]\nTitle: Clean\n")

    with tempfile.TemporaryDirectory() as tmp:
        written = extract_archive_bytes(buf.getvalue(), "zip", tmp, "pack.zip")
        assert len(written) == 1
        assert os.path.basename(written[0]) == "ep01.ass"


# AniSubDl v2.0 — Multi-Provider Anime Subtitle Downloader

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**AniSubDl** is a cross-platform command-line and interactive terminal tool for finding, downloading, extracting, and auto-renaming subtitles (and attached fonts) for your anime library.

Updated for the **post-2026 Anime Tosho ecosystem**: following the shutdown of `animetosho.org`'s ingestion in May 2026 and the expiration of its attachment storage in October 2026, **AniSubDl v2.0** natively integrates the active continuation mirrors via their official public APIs — requiring **zero accounts or API keys**.

---

## Supported Providers & 2026 Ecosystem Status

Run `python subdl.py --check-providers` anytime to check live mirror health and latency.

| Service | Domain | Standalone Subtitles? | Supported in `AniSubDl` | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Anime Tosho NEW** | `animetosho.net` *(redirects from `.xyz`)* | **Yes** (`.ass`, `.srt`, `.7z` packs) | ✅ `-p animetosho` *(in `auto`)* | Official JSON Feed API (`feed.animetosho.net/json`), single episodes & batches, multi-language |
| **TsukiHime** | `tsukihime.org` | **Yes** (`.ass`, `.srt`, `.ttf`/`.otf` fonts, `.7z`) | ✅ `-p tsukihime` *(in `auto`)* | Official Swagger REST API v1 (`api.tsukihime.org/v1`), direct AniList ID lookup & per-font downloads |
| **Kitsunekko** | `kitsunekko.net` | **Yes** (`.ass`, `.srt`, `.zip`) | ✅ `-p kitsunekko` *(fallback in `auto`)* | Community English & Japanese anime subtitle archive |
| **SubDL** | `subdl.com` | **Yes** (`.ass`, `.srt`, `.ssa`, season `.zip` packs) | ✅ `-p subdl` *(fallback in `auto` when `SUBDL_API_KEY` set)* | Optional TMDB-indexed multilingual fallback (`export SUBDL_API_KEY=...`); supports TV & anime movies |
| **aninzb** | `aninzb.moe` | Web UI only | ❌ | Usenet indexer; web pages use rotating per-request signed tokens & strict anti-bot filtering |
| **Otakuness** | `otakuness.top` | **No** | ❌ | Mirrors full video files to DDL hosts + screenshots/MediaInfo only |
| **ameNZB** | `amenzb.moe` | **No** | ❌ | Usenet NZB mirror only (no standalone subtitle extraction) |
| **Anime Tosho (Classic)** | `animetosho.org` | **Expired** | ❌ | Halted new releases May 2026; feed & attachment storage servers expired Oct 2026 |

---

## Key Features in v2.0

- **Multi-Provider `auto` Engine**: Queries both **Anime Tosho NEW (`animetosho.net`)** and **TsukiHime (`tsukihime.org`)** JSON APIs (including multi-episode **batch** torrents!) with automatic fallback to **Kitsunekko (`kitsunekko.net`)**.
- **Smart AniList Resolution**: Cleans noisy folder names (`[1080p]`, `(2024)`, `[SubsPlease]`) and resolves canonical Romaji/English titles + AniList IDs in a single cached GraphQL request.
- **Multi-Language & Format Filtering**: Download `en`, `ja`, `es`, `es-419`, `pt-BR`, `fr`, `de`, `ar`, `ru`, `it`, `zh-Hans`, `zh-Hant`, or `all` in `.ass` or `.srt`.
- **Signs & Songs Protection**: Automatically prioritizes full dialogue tracks so *Signs & Songs* / *Forced* tracks never overwrite full episode subtitles (use `--include-forced` to keep forced tracks safely suffixed as `.forced.ass`).
- **Font Extraction (`--fonts`)**: Downloads embedded `.ttf` / `.otf` subtitle fonts directly into a `Fonts/` subfolder.
- **Smart Video Matching & Plex/Jellyfin Naming**: Matches subtitles by `(season, episode)`, detects local release groups from your video files (`[SubsPlease]`, `-VARYG`, etc.), and supports both exact (`Video.ass`) and media-server (`Video.en.ass`) naming.
- **Concurrent Downloads & Batch Automation**: Multi-threaded downloads (`--workers`) with `429 Retry-After` rate-limit handling, plus `--batch` mode to scan an entire anime library unattended.

---

## Installation

```bash
git clone https://github.com/Sac-94/AniSubDl.git
cd AniSubDl
pip install -r requirements.txt
```

*(Optional)* Install as a system/virtualenv CLI command (`anisubdl`) and add `.7z` extraction support:

```bash
pip install -e ".[7z]"
```

---

## Usage Examples

### 1. Interactive Library Mode (Classic Workflow)
```bash
python subdl.py "/path/to/Anime"
# Subsequent runs load your saved path & preferences from subdl.cfg automatically:
python subdl.py
```

### 2. Direct Title Query (No Local Video Folder Needed)
```bash
python subdl.py -q "Sousou no Frieren" -g BlackRabbit -e 1-12 -o ./Frieren_Subs
```

### 3. Multi-Language + Plex / Jellyfin Naming + Fonts
```bash
python subdl.py "/path/to/Anime/Sousou no Frieren" -p tsukihime -l en,es -f ass --fonts --naming-style plex --rename auto
```

### 4. Unattended Full-Library Batch Mode
Automatically scans every series folder in your library, detects the release group from existing `.mkv`/`.mp4` files, downloads only missing episode subtitles, and renames them to match:
```bash
python subdl.py "/path/to/Anime" --batch
```

### 5. Check Live Ecosystem Mirror Health
```bash
python subdl.py --check-providers
```

---

## CLI Options Reference

| Flag | Description | Default |
| :--- | :--- | :--- |
| `anime_dir` | Path to anime library root OR single anime series folder | Loaded from `subdl.cfg` |
| `-q, --query TEXT` | Search directly by anime title without local folders | — |
| `-o, --output DIR` | Custom output directory for downloaded subtitles | Target anime folder |
| `-p, --provider` | `auto`, `animetosho`, `tsukihime`, `kitsunekko`, or `subdl` | `auto` |
| `--custom-url URL` | Custom Anime Tosho-compatible domain/mirror URL | — |
| `-g, --group GROUP` | Pre-select release group (e.g. `SubsPlease`, `VARYG`, or `ALL`) | Interactive / auto |
| `-l, --lang LANGS` | Comma-separated language codes (`en`, `ja`, `en,es`, `pt-BR`, `all`) | `en` |
| `-f, --format` | Subtitle format filter: `any`, `ass`, or `srt` | `any` |
| `-r, --resolution` | Release resolution filter: `2160p`, `1080p`, `720p`, `480p`, `any` | `1080p` |
| `-e, --episodes` | Episode range filter, e.g. `1-12`, `5`, `1,3,5-8` | All episodes |
| `--include-forced` | Also download Forced / Signs & Songs tracks (`.forced` suffix) | `False` |
| `--all-tracks` | Keep every matching track variant instead of deduplicating | `False` |
| `--fonts` | Download `.ttf`/`.otf` font attachments into `Fonts/` | `False` |
| `--all-attachments` | Download `.7z` full attachment packs (`_attachments.7z`) | `False` |
| `--rename` | Rename mode: `ask`, `auto`, or `never` | `ask` (`auto` in `--batch`) |
| `--naming-style` | `exact` (`Video.ass`) or `lang`/`plex` (`Video.en.ass`) | `exact` |
| `--overwrite` | Overwrite existing subtitle files | `False` |
| `--batch` | Non-interactive full-library scan & auto-rename | `False` |
| `-w, --workers INT` | Parallel download threads (`1–16`) | `4` |
| `--max-pages INT` | Maximum search pages per provider | `2` |
| `--dry-run` | Preview downloads & renames without writing files | `False` |
| `--save-defaults` | Save current flags as persistent defaults in `subdl.cfg` | `False` |
| `--check-providers` | Live-test status of Anime Tosho ecosystem mirrors | `False` |

---

## License

MIT License — see [LICENSE](LICENSE).

*Disclaimer: Intended for personal and educational library management. Please support official anime releases.*

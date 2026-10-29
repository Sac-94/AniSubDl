"""Base provider abstractions, resilient HTTP session, and archive extraction helpers."""

from __future__ import annotations

import abc
import io
import lzma
import os
import shutil
import subprocess
import time
import zipfile
from typing import List, Optional, Tuple
import requests

from ..models import AnimeMetadata, FontAttachment, ReleaseEntry, SubtitleTrack

DEFAULT_USER_AGENT = "AniSubDl/2.0 (+https://github.com/Sac-94/AniSubDl)"


def create_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    return session


def request_with_backoff(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 3,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """Perform HTTP request with automatic 429 Retry-After handling and transient backoff."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = session.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code == 429 and attempt < retries - 1:
                retry_after = resp.headers.get("Retry-After")
                wait_s = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else (1.5 * (attempt + 1))
                time.sleep(min(wait_s, 12.0))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
            else:
                raise
    raise RuntimeError(f"Request failed for {url}: {last_exc}")


def sanitize_filename(name: str) -> str:
    """Remove filesystem-unsafe characters while preserving readable anime filenames."""
    cleaned = name.replace("/", "_").replace("\\", "_")
    for ch in (":", "*", "?", '"', "<", ">", "|", "\0"):
        cleaned = cleaned.replace(ch, "")
    return cleaned.strip()


def extract_archive_bytes(
    raw_bytes: bytes,
    compressed_type: str,
    target_dir: str,
    preferred_filename: str,
) -> List[str]:
    """
    Decompress downloaded subtitle/font payload into target_dir.
    Supports:
    - 'xz': pure-Python lzma decompression into preferred_filename
    - 'none': writes raw bytes directly to preferred_filename
    - 'zip': extracts subtitle/font files via stdlib zipfile
    - '7z': extracts via py7zr or system '7z'/'7za' if available, else saves the .7z archive intact
    Returns list of written file paths.
    """
    os.makedirs(target_dir, exist_ok=True)
    safe_name = sanitize_filename(preferred_filename)
    out_path = os.path.join(target_dir, safe_name)

    if compressed_type == "xz":
        decompressed = lzma.decompress(raw_bytes)
        with open(out_path, "wb") as f:
            f.write(decompressed)
        return [out_path]

    if compressed_type == "none":
        with open(out_path, "wb") as f:
            f.write(raw_bytes)
        return [out_path]

    if compressed_type == "zip":
        max_member_bytes = 20 * 1024 * 1024
        written: List[str] = []
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            for member in zf.infolist():
                if member.is_dir() or member.filename.startswith("__MACOSX/"):
                    continue
                if member.file_size <= 0 or member.file_size > max_member_bytes:
                    continue
                raw_base = os.path.basename(member.filename)
                if raw_base.startswith("._"):
                    continue
                member_base = sanitize_filename(raw_base)
                if not member_base:
                    continue
                ext = os.path.splitext(member_base)[1].lower()
                if ext in (".ass", ".ssa", ".srt", ".vtt", ".sup"):
                    dest = os.path.join(target_dir, member_base)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    written.append(dest)
                elif ext in (".ttf", ".otf"):
                    fonts_sub = os.path.join(target_dir, "Fonts")
                    os.makedirs(fonts_sub, exist_ok=True)
                    dest = os.path.join(fonts_sub, member_base)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        return written

    if compressed_type == "7z":
        archive_path = out_path if out_path.endswith(".7z") else f"{out_path}.7z"
        with open(archive_path, "wb") as f:
            f.write(raw_bytes)

        # Try optional py7zr first
        try:
            import py7zr  # type: ignore

            with py7zr.SevenZipFile(archive_path, mode="r") as z:
                names = z.getnames()
                z.extractall(path=target_dir)
            os.remove(archive_path)
            return [os.path.join(target_dir, n) for n in names if os.path.isfile(os.path.join(target_dir, n))]
        except ImportError:
            pass
        except Exception:
            return [archive_path]

        # Try system 7z / 7zz / 7za CLI if installed
        for cmd in ("7z", "7zz", "7za"):
            if shutil.which(cmd):
                res = subprocess.run(
                    [cmd, "x", "-y", f"-o{target_dir}", archive_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if res.returncode == 0:
                    os.remove(archive_path)
                    return [archive_path]
        return [archive_path]

    # Fallback: save raw archive as-is
    with open(out_path, "wb") as f:
        f.write(raw_bytes)
    return [out_path]


class SubtitleProvider(abc.ABC):
    """Abstract base class for anime subtitle providers."""

    slug: str = "base"
    name: str = "Base Provider"
    base_url: str = ""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or create_http_session()

    @abc.abstractmethod
    def find_releases(
        self,
        title: str,
        metadata: Optional[AnimeMetadata] = None,
        resolution: str = "1080p",
        max_pages: int = 2,
    ) -> List[ReleaseEntry]:
        """Search releases for an anime title."""

    @abc.abstractmethod
    def fetch_tracks_for_releases(
        self,
        releases: List[ReleaseEntry],
    ) -> Tuple[List[SubtitleTrack], List[FontAttachment]]:
        """Retrieve subtitle tracks and optional font attachments for selected releases."""

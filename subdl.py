#!/usr/bin/env python3
"""
AniSubDl — Interactive & Automated Multi-Provider Anime Subtitle Downloader.
Entry point preserving backward compatibility with `python subdl.py [anime_dir]`.
"""

import sys

from anisubdl.cli import main

if __name__ == "__main__":
    sys.exit(main())

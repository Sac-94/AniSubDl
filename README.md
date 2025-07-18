# AniSubDl: The Interactive Anime Subtitle Downloader

![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

**AniSubDl** is a sophisticated, cross-platform command-line tool designed to streamline the process of finding and downloading English subtitles for your anime library from [Anime Tosho](https://animetosho.org).

It provides an interactive experience that intelligently searches for subtitles by leveraging both directory names and the [AniList API](https://anilist.co) for robust matching.

---

## Key Features

- 🎬 **Interactive Selection**: A user-friendly, menu-driven interface for selecting anime series and release groups.
- 🧠 **Intelligent Title Resolution**: Automatically queries the AniList API for Romaji titles when initial searches yield no results, ensuring a higher success rate.
- 📦 **Automatic Decompression**: Seamlessly downloads `.xz` archives, extracts the `.ass` subtitle file, and cleans up the archive, leaving only the ready-to-use subtitle.
- ✍️ **Interactive Renaming**: After downloading, automatically matches subtitles to your existing video files (`.mkv`, `.mp4`) and prompts you to approve renaming them for perfect media player integration.
- 🌐 **Cross-Platform Compatibility**: Fully tested and compatible with Windows, macOS, and Linux environments.
- ⚙️ **Zero External Dependencies**: Requires no external software installations beyond the specified Python libraries.

---

## Prerequisites

- Python 3.7 or higher.
- `pip` for managing Python packages.

## Installation

1.  **Clone the repository to your local machine:**
    ```bash
    git clone https://github.com/Sac-94/AniSubDl.git
    cd AniSubDl
    ```
2.  **Install the required dependencies using pip:**
    ```bash
    pip install -r requirements.txt
    ```

---

## Usage Guide

The tool determines which path to use based on the following priority:
1.  The path provided as a **command-line argument**.
2.  The path automatically loaded from the `subdl.cfg` configuration file.
3.  The path entered into the **interactive prompt**.

#### Mode 1: Command-Line Argument (Highest Priority)

Provide the absolute path to your anime collection directory as an argument. This method always takes precedence.

```bash
# On Windows
python subdl.py "C:\Users\YourUser\Videos\Anime"

# On macOS or Linux
python subdl.py "/home/youruser/Videos/Anime"
```

#### Mode 2: Automatic Path Loading

If you run the script without an argument, it will automatically load the path from `subdl.cfg`, if it exists.

```bash
python download_subs.py
```
> Loaded anime directory from config: C:\Users\YourUser\Videos\Anime

#### Mode 3: Interactive Prompt (Fallback)

If no argument is given and no valid configuration file is found, the script will prompt you to enter the directory path.

### Configuration File

For convenience, `AniSubDl` automatically saves the last successfully used anime directory to a configuration file named `subdl.cfg`. This allows you to run the script without arguments on subsequent uses.

---

## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/Sac-94/AniSubDl/blob/main/LICENSE) file for more details.

## Acknowledgements

- This tool relies on the services provided by [Anime Tosho](https://animetosho.org) for subtitle distribution.
- Anime metadata is graciously provided by the [AniList API](https://anilist.co).

*Disclaimer: This tool is intended for personal and educational use only. Please support official anime releases.*

import os
import re
import requests
import lzma
import argparse
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

# --- Constants ---
ANIMETOSHO_BASE_URL = 'https://animetosho.org'
ANILIST_API_URL = 'https://graphql.anilist.co'
CONFIG_FILE = 'subdl.cfg'

# --- Path Configuration ---

def save_path(path):
    """Saves the given path to the config file."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(path)
    except IOError as e:
        print(f"\nWarning: Could not save path to config file: {e}")

def load_path():
    """Loads the path from the config file if it exists and is valid."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                path = f.read().strip()
                if os.path.isdir(path):
                    return path
                else:
                    print(f"Warning: Saved path '{path}' is no longer valid.")
                    return None
        except IOError as e:
            print(f"\nWarning: Could not read config file: {e}")
    return None

# --- Core Functions ---

def get_soup(url):
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Error: Could not fetch {url}. Reason: {e}")
        return None

def get_anilist_title(search_term):
    """
    Searches AniList for an anime and returns its Romaji title.
    Returns None if not found.
    """
    query = '''
    query ($search: String) {
      Media (search: $search, type: ANIME) {
        title {
          romaji
          english
        }
      }
    }
    '''
    variables = {'search': search_term}
    
    print(f"Searching AniList for '{search_term}'...")
    try:
        response = requests.post(ANILIST_API_URL, json={'query': query, 'variables': variables})
        response.raise_for_status()
        data = response.json()
        media = data.get('data', {}).get('Media')
        if media and media.get('title'):
            romaji_title = media['title'].get('romaji')
            print(f"Found Romaji title: {romaji_title}")
            return romaji_title
    except requests.exceptions.RequestException as e:
        print(f"Error querying AniList API: {e}")
    
    print("Could not find a title on AniList.")
    return None

def find_release_groups(anime_title):
    """
    Searches Anime Tosho for an anime title and returns a list of release groups.
    """
    print(f"Searching for release groups for '{anime_title}'...")
    search_query = quote(f'{anime_title} 1080p')
    search_url = f"{ANIMETOSHO_BASE_URL}/search?q={search_query}"
    
    soup = get_soup(search_url)
    if not soup:
        return []

    groups = set()
    torrent_entries = soup.find_all('div', class_='home_list_entry')
    
    for entry in torrent_entries:
        release_name = entry.find('div', class_='link').find('a').get_text(strip=True)
        if release_name.startswith('['):
            group = release_name.split(']')[0][1:]
            groups.add(group)
            
    if not groups:
        print("No release groups found on the first search.")
        return []
        
    print(f"Found groups: {list(groups)}")
    return sorted(list(groups))

def download_and_extract_subtitles(search_term, output_dir):
    """
    Downloads and extracts all English ASS subtitles for a given search term.
    Returns a list of paths to the extracted subtitle files.
    """
    search_query = quote(f'{search_term} 1080p')
    search_url = f"{ANIMETOSHO_BASE_URL}/search?disp=attachments&q={search_query}"
    
    print(f"\nFetching subtitles from: {search_url}")
    soup = get_soup(search_url)
    if not soup:
        return []

    os.makedirs(output_dir, exist_ok=True)
    subtitle_links = soup.find_all('a', string='English subs [eng, ASS]')
    if not subtitle_links:
        print("No 'English subs [eng, ASS]' links found on the page.")
        return []

    print(f"Found {len(subtitle_links)} English subtitle files. Downloading...")
    downloaded_files = []

    for link in subtitle_links:
        entry = link.find_parent('div', class_='home_list_entry')
        if not entry: continue
            
        release_name = entry.find('div', class_='link').find('a').get_text(strip=True)
        base_filename = os.path.splitext(release_name)[0]
        
        xz_filename = f"{base_filename}.ass.xz"
        ass_filename = f"{base_filename}.ass"
        xz_filepath = os.path.join(output_dir, xz_filename)
        ass_filepath = os.path.join(output_dir, ass_filename)

        relative_url = link.get('href')
        if not relative_url: continue
        
        absolute_url = urljoin(ANIMETOSHO_BASE_URL, relative_url)
        
        print(f"  -> Downloading {xz_filename}...")
        try:
            sub_response = requests.get(absolute_url)
            sub_response.raise_for_status()
            
            with open(xz_filepath, 'wb') as f: f.write(sub_response.content)
            
            print(f"  -> Extracting to {ass_filename}...")
            with lzma.open(xz_filepath, 'rb') as xz_file:
                with open(ass_filepath, 'wb') as ass_file:
                    ass_file.write(xz_file.read())
            
            os.remove(xz_filepath)
            downloaded_files.append(ass_filepath)

        except requests.exceptions.RequestException as e: print(f"    Error downloading file: {e}")
        except lzma.LZMAError as e: print(f"    Error extracting file: {e}")
        except IOError as e: print(f"    File system error: {e}")

    print("\nSubtitle download and extraction complete.")
    return downloaded_files

# --- Renaming Functions ---

def extract_episode_number(filename):
    """Extracts an episode number from a filename using regex."""
    match = re.search(
        r'(?:[._\s-]|[Ee]pisode|[Ee]p\b|[Ss]\d+[Ee])(\d{1,3})\b',
        filename
    )
    if match:
        return match.group(1).zfill(2)
    return None

def find_video_files(directory):
    """Finds all video files in a given directory."""
    video_exts = ['.mkv', '.mp4', '.avi', '.mov', '.webm']
    return [f for f in os.listdir(directory) if os.path.splitext(f)[1].lower() in video_exts]

def interactive_rename_subtitles(directory, subtitle_paths):
    """Matches subtitles to video files and interactively renames them."""
    print("\n--- Optional: Subtitle Renaming ---")
    video_files = find_video_files(directory)
    if not video_files:
        print("No video files found in the directory. Skipping renaming.")
        return

    rename_map = {}

    for sub_path in subtitle_paths:
        sub_filename = os.path.basename(sub_path)
        sub_episode_num = extract_episode_number(sub_filename)

        if not sub_episode_num:
            print(f"Could not determine episode number for: {sub_filename}")
            continue

        for video_filename in video_files:
            video_episode_num = extract_episode_number(video_filename)
            if sub_episode_num == video_episode_num:
                video_basename = os.path.splitext(video_filename)[0]
                new_sub_filename = f"{video_basename}.ass"
                new_sub_path = os.path.join(directory, new_sub_filename)
                
                if os.path.exists(new_sub_path):
                    print(f"Warning: Proposed new name already exists, skipping: {new_sub_filename}")
                    break
                
                rename_map[sub_path] = new_sub_path
                break
    
    if not rename_map:
        print("Could not find any matching video files for the downloaded subtitles.")
        return

    print("\nProposed renames:")
    for old, new in rename_map.items():
        print(f"  '{os.path.basename(old)}'  ->  '{os.path.basename(new)}'")

    while True:
        choice = input("\nDo you want to apply these renames? (y/n): ").lower().strip()
        if choice in ['y', 'yes']:
            for old, new in rename_map.items():
                try:
                    os.rename(old, new)
                    print(f"Renamed to '{os.path.basename(new)}'")
                except OSError as e:
                    print(f"Error renaming '{os.path.basename(old)}': {e}")
            break
        elif choice in ['n', 'no']:
            print("Renaming cancelled.")
            break
        else:
            print("Invalid input. Please enter 'y' or 'n'.")

# --- UI Functions ---

def select_from_list(items, prompt):
    """Generic function to display a numbered list and get user's choice."""
    if not items:
        print(f"No items to select for: {prompt}")
        return None
        
    print(f"\n{prompt}")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item}")
    
    while True:
        try:
            choice = int(input(f"Select a number (1-{len(items)}): "))
            if 1 <= choice <= len(items):
                return items[choice - 1]
            else:
                print("Invalid number. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")

# --- Main Execution ---

def main():
    """Main function to run the interactive subtitle downloader."""
    parser = argparse.ArgumentParser(
        description="An interactive subtitle downloader for Anime Tosho.",
        epilog="If no directory is provided, the script will load the last used path or prompt for a new one."
    )
    parser.add_argument('anime_dir', nargs='?', default=None, help="The path to your main anime directory (optional).")
    args = parser.parse_args()

    anime_root_dir = args.anime_dir

    if not anime_root_dir:
        anime_root_dir = load_path()
        if anime_root_dir:
            print(f"Loaded anime directory from config: {anime_root_dir}")

    if not anime_root_dir:
        anime_root_dir = input("Please enter the path to your anime directory: ")

    print("\n--- Subdl: Anime Tosho Subtitle Downloader ---")
    
    try:
        if not os.path.isdir(anime_root_dir):
            print(f"\nError: The path '{anime_root_dir}' is not a valid directory.")
            return
        
        save_path(anime_root_dir)
        anime_dirs = sorted([d for d in os.listdir(anime_root_dir) if os.path.isdir(os.path.join(anime_root_dir, d))])
    except FileNotFoundError:
        print(f"\nError: The directory '{anime_root_dir}' was not found.")
        return

    if not anime_dirs:
        print(f"\nNo anime series found in '{anime_root_dir}'.")
        return

    selected_dir_name = select_from_list(anime_dirs, "Select an anime directory:")
    if not selected_dir_name: return
        
    selected_dir_path = os.path.join(anime_root_dir, selected_dir_name)
    print(f"\nYou selected: {selected_dir_name}")

    release_groups = find_release_groups(selected_dir_name)
    
    if not release_groups:
        print("\nNo groups found with the directory name. Trying AniList...")
        romaji_title = get_anilist_title(selected_dir_name)
        if romaji_title:
            release_groups = find_release_groups(romaji_title)

    if not release_groups:
        print(f"\nCould not find any release groups for '{selected_dir_name}'.")
        return

    selected_group = select_from_list(release_groups, "Select a release group:")
    if not selected_group: return
        
    print(f"\nYou selected group: {selected_group}")

    final_search_title = get_anilist_title(selected_dir_name) or selected_dir_name
    search_term = f"[{selected_group}] {final_search_title}"
    
    downloaded_subs = download_and_extract_subtitles(search_term, selected_dir_path)
    
    if downloaded_subs:
        interactive_rename_subtitles(selected_dir_path, downloaded_subs)

if __name__ == "__main__":
    main()
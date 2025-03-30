import os
import pathlib
import re  # Added for filename sanitization
import sys
from argparse import ArgumentParser, Namespace
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)  # Added for parallel downloads
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, cast, Tuple

import eyed3
import requests  # Added for album art download
import spotipy as sp
from dotenv import load_dotenv  # New import for .env support
from mutagen.easyid3 import EasyID3  # Added for metadata
from mutagen.id3 import ID3  # Added for metadata/album art
from mutagen.id3._frames import APIC  # Added for metadata/album art
from mutagen.id3._util import ID3NoHeaderError  # Added for metadata/album art
from spotipy.oauth2 import SpotifyOAuth
from youtubesearchpython import VideosSearch  # Added for YouTube search
from yt_dlp import YoutubeDL

# Load environment variables from .env file if it exists
load_dotenv()

SPOTIFY_API_SCOPE = "user-library-read,playlist-read-private,playlist-modify-private"
CHUNK_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
# DEFAULT_MAX_WORKERS = 5 # Can replace the old MAX_WORKERS constant

# Constants for magic numbers
TRACK_FORMAT_PARTS_4 = 4  # TrackNo - Artist - Album - Name
TRACK_FORMAT_PARTS_3 = 3  # Artist - Album - Name
TRACK_FORMAT_PARTS_2 = 2  # Album - Name


@dataclass
class SpotifyConnection:
    """
    Holds the authenticated Spotipy client and user information.

    Attributes:
        connection: The authenticated Spotipy client instance.
        userid: The Spotify user ID.
        username: The Spotify display name.
    """

    connection: sp.Spotify
    userid: Optional[str] = None
    username: Optional[str] = None


@dataclass
class TrackInfo:
    """
    Represents a music track, holding metadata from either MP3 tags or Spotify.

    Attributes:
        filename: The local filesystem path to the MP3 file (if applicable).
        artist: The primary artist of the track.
        album: The album the track belongs to.
        title: The title of the track.
        url: The Spotify URL of the track (used in 'to-spotify').
        youtube_url: The found YouTube URL for the track (used in 'from-spotify').
        spotify_id: The unique Spotify ID for the track.
        album_art_url: The URL of the album artwork from Spotify.
    """

    filename: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    youtube_url: Optional[str] = None
    spotify_id: Optional[str] = None
    album_art_url: Optional[str] = None

    @property
    def search_query_spotify(self) -> str:
        """
        Generates a search query string suitable for the Spotify API based on
        MP3 metadata. Prioritizes artist and title.

        Returns:
            A formatted search query string.
        """
        if not self.artist or not self.title:
            # Fallback to title only if artist is missing
            return self.title or ""
        # Use Spotify's specific field filters for better accuracy
        return f"artist:{self.artist} track:{self.title}"

    @property
    def search_query_youtube(self) -> str:
        """
        Generates a search query string suitable for YouTube, combining available
        metadata to find the corresponding audio.

        Returns:
            A formatted search query string.
        """
        query_parts = []
        if self.artist:
            query_parts.append(self.artist)
        if self.title:
            query_parts.append(self.title)
        if self.album:
            query_parts.append(self.album)
        # Append ' audio' to hint for music/audio results over music videos
        return " ".join(query_parts) + " audio"

    @property
    def is_valid_for_spotify_search(self) -> bool:
        """
        Checks if the track has the minimum required information (title)
        to be searchable on Spotify.

        Returns:
            True if the track has a title, False otherwise.
        """
        return bool(self.title)

    @property
    def is_valid_for_youtube_search(self) -> bool:
        """
        Checks if the track has the minimum required information (title and artist)
        to be effectively searchable on YouTube.

        Returns:
            True if the track has both title and artist, False otherwise.
        """
        return bool(self.title and self.artist)

    @property
    def has_spotify_url(self) -> bool:
        """
        Checks if the track object has a Spotify URL associated with it.

        Returns:
            True if a Spotify URL exists, False otherwise.
        """
        return bool(self.url)

    @property
    def has_youtube_url(self) -> bool:
        """
        Checks if the track object has a YouTube URL associated with it.

        Returns:
            True if a YouTube URL exists, False otherwise.
        """
        return bool(self.youtube_url)


def spotify_connect() -> SpotifyConnection:
    """
    Establishes a connection to the Spotify API using OAuth2.

    Handles the authentication flow and retrieves basic user information.

    Returns:
        A SpotifyConnection object containing the authenticated client
        and user details (ID, username). Returns connection object even
        if user info fails, but userid/username might be None.
    """
    print("Connecting to Spotify...")
    try:
        # Set up the OAuth manager using environment variables or provided credentials
        auth_manager = SpotifyOAuth(scope=SPOTIFY_API_SCOPE)
        connection = sp.Spotify(auth_manager=auth_manager)

        # Fetch current user details to confirm successful authentication
        user_info = connection.current_user()
        if not user_info:
            print("Warning: Could not retrieve Spotify user info after authentication.")
            return SpotifyConnection(connection=connection)

        user_id = user_info.get("id", "")
        username = user_info.get("display_name", "")
        print(f"Successfully connected as Spotify user: {username} ({user_id})")
        return SpotifyConnection(
            connection=connection,
            userid=user_id,
            username=username,
        )
    except Exception as e:
        # Catch potential errors during authentication (e.g., network issues, bad credentials)
        print(f"Error connecting to Spotify: {e}")
        # Still return a potentially unauthenticated connection object if possible,
        # downstream functions will handle missing user ID if required.
        # If sp.Spotify itself fails, this might need adjustment.
        try:
            # Attempt to return a connection object even on error, might be partially usable
            return SpotifyConnection(connection=sp.Spotify(auth_manager=None))
        except Exception: # If even creating a basic client fails
             print("Fatal error: Could not create Spotify client instance.")
             sys.exit(1) # Exit if connection totally fails


def spotify_check_playlist(
    connection: SpotifyConnection, playlistname: str, playlistid: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Finds a user's Spotify playlist by its name or optionally by its ID.

    Args:
        connection: The authenticated SpotifyConnection object.
        playlistname: The name of the playlist to search for.
        playlistid: An optional playlist ID to also check against.

    Returns:
        A dictionary representing the found playlist, or None if not found.
    """
    print(f"Checking for existing Spotify playlist named '{playlistname}'...")
    try:
        # Fetch user's playlists in batches (Spotify API limit is usually 50 per request)
        # Note: This might not find *all* playlists if user has > 50.
        # A more robust implementation would paginate through all playlists.
        playlists = connection.connection.current_user_playlists(limit=50)
        if not playlists or "items" not in playlists:
            print("No playlists found or unexpected API response format.")
            return None

        for playlist in playlists["items"]:
            # Check if the name matches
            if playlist["name"] == playlistname:
                print(f"  Found existing playlist by name (ID: {playlist['id']}).")
                # Ensure the return type matches the annotation
                return cast(Dict[str, Any], playlist)
            # Optionally check if the ID matches (less common scenario)
            if playlistid and playlist["id"] == playlistid:
                print(f"  Found existing playlist by ID: {playlistid}.")
                return cast(Dict[str, Any], playlist)

        print(f"  Playlist '{playlistname}' not found in the first 50 playlists.")
        return None
    except Exception as e:
        print(f"Error checking for playlist: {e}")
        return None


def spotify_create_playlist(
    connection: SpotifyConnection, playlistname: str
) -> Optional[str]:
    """
    Creates a new private Spotify playlist for the authenticated user.

    Args:
        connection: The authenticated SpotifyConnection object.
        playlistname: The desired name for the new playlist.

    Returns:
        The ID of the newly created playlist, or None if creation fails.
    """
    if not connection.userid:
        print("Error: Spotify User ID is required to create a playlist.")
        return None

    print(f"Creating new private Spotify playlist named '{playlistname}' for user {connection.username}...")
    try:
        # API call to create the playlist
        playlist_data = connection.connection.user_playlist_create(
            connection.userid, playlistname, public=False
        )
        # Cast the result type hint for the type checker
        playlist = cast(Dict[str, Any], playlist_data)

        if not playlist or "id" not in playlist:
            print("Error: Failed to create playlist or response missing ID.")
            return None

        playlistid = cast(str, playlist["id"]) # Ensure ID is treated as string
        print(f"Successfully created playlist with ID: {playlistid}")
        return playlistid
    except Exception as e:
        print(f"Error creating Spotify playlist: {e}")
        return None


def mp3_walk_directory(directory: str) -> Iterator[TrackInfo]:
    """
    Recursively scans a directory for MP3 files and yields TrackInfo objects.

    Attempts to extract metadata from ID3 tags first, then falls back to
    parsing the filename.

    Args:
        directory: The path to the directory to scan.

    Yields:
        TrackInfo objects containing metadata for each valid MP3 found.
    """
    print(f"Scanning directory for MP3 files: {directory}")
    try:
        search_path = pathlib.Path(directory)
        if not search_path.is_dir():
            print(f"Error: Directory not found: {directory}")
            return

        # Use glob to find all .mp3 files recursively
        for filepath in search_path.glob("**/*.mp3"):
            print(f"Processing file: {filepath.name}")
            track_info = TrackInfo(filename=str(filepath))

            try:
                # Attempt to load ID3 tags using eyed3
                mp3 = eyed3.load(filepath)
                # Check if loading was successful and tags exist
                if mp3 and mp3.tag:
                    track_info.artist = mp3.tag.artist
                    track_info.album = mp3.tag.album
                    track_info.title = mp3.tag.title
                    print(f"  Found ID3 tags: Artist='{track_info.artist}', Title='{track_info.title}'")
                else:
                    # If no tags, attempt to parse from filename
                    print("  No ID3 tags found, attempting to parse filename...")
                    track_info = _parse_track_from_filename(filepath)
                    print(f"  Parsed from filename: Artist='{track_info.artist}', Title='{track_info.title}'")

                # Only yield tracks that have enough info for Spotify search (at least a title)
                if track_info.is_valid_for_spotify_search:
                    yield track_info
                else:
                    print("  Skipping file - insufficient metadata (missing title).")

            except Exception as e:
                # Catch errors during individual file processing (e.g., corrupted file)
                print(f"  Error processing file {filepath.name}: {e}")
                # Continue to the next file
                pass
    except Exception as e:
        # Catch errors related to directory access or globbing
        print(f"Error scanning directory {directory}: {e}")


def _parse_track_from_filename(filepath: pathlib.Path) -> TrackInfo:
    """
    Parses artist, album, and title from a filename based on common patterns.

    Assumes separators like ' - '. Used as a fallback if ID3 tags are missing.

    Args:
        filepath: The pathlib.Path object for the MP3 file.

    Returns:
        A TrackInfo object populated with parsed data (can be incomplete).
    """
    # Get filename without extension, replace underscores with spaces
    filename = filepath.stem.replace("_", " ")
    parts = [part.strip() for part in filename.split("-")] # Split by hyphen and strip whitespace

    track = TrackInfo(filename=str(filepath))

    num_parts = len(parts)

    # Try matching known patterns based on the number of parts
    if num_parts == TRACK_FORMAT_PARTS_4:  # TrackNo - Artist - Album - Name
        # Assuming first part is track number, skip it
        track.artist = parts[1]
        track.album = parts[2]
        track.title = parts[3]
    elif num_parts == TRACK_FORMAT_PARTS_3:  # Artist - Album - Name
        track.artist = parts[0]
        track.album = parts[1]
        track.title = parts[2]
    elif num_parts == TRACK_FORMAT_PARTS_2:  # Album - Name
        # Cannot determine artist reliably
        track.album = parts[0]
        track.title = parts[1]
    else:
        # If no pattern matches, assume the whole filename is the title
        print(f"    Could not parse filename into parts: '{filename}'. Using full stem as title.")
        track.title = filename

    # Basic validation check after parsing
    if not track.title:
        print(f"    Warning: Could not extract title from filename: {filepath.name}")

    return track


def list_chunks(lst: List, n: int) -> Iterator[List]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def get_playlist_tracks(sp_conn: sp.Spotify, playlist_id: str) -> List[TrackInfo]:
    """
    Fetches all track details from a specific Spotify playlist ID.

    Handles pagination to retrieve all tracks.

    Args:
        sp_conn: Authenticated Spotipy client instance.
        playlist_id: The unique ID of the Spotify playlist.

    Returns:
        A list of TrackInfo objects representing the tracks in the playlist.
    """
    tracks: List[TrackInfo] = []
    offset = 0
    print(f"Fetching tracks from Spotify playlist ID: {playlist_id}")
    while True:
        try:
            # Request playlist items, specifying needed fields
            results = sp_conn.playlist_items(
                playlist_id,
                offset=offset,
                # Request specific fields to minimize data transfer
                fields="items(track(id, name, artists(name), album(name, images)))",
                additional_types=["track"],
            )
            if not results: # Check if results are None or empty
                print("  No results returned from Spotify API.")
                break

            items = results.get("items", [])
            if not items: # End of playlist
                print("  No more items found in playlist.")
                break

            # Process each item in the current batch
            for item in items:
                track_data = item.get("track")
                # Ensure item is a track and has data
                if track_data and isinstance(track_data, dict):
                    # Extract metadata safely using .get()
                    artist_list = track_data.get("artists")
                    album_data = track_data.get("album")
                    images = album_data.get("images") if isinstance(album_data, dict) else None

                    track_info = TrackInfo(
                        spotify_id=track_data.get("id"),
                        title=track_data.get("name"),
                        artist=artist_list[0]["name"] if artist_list else None,
                        album=album_data["name"] if isinstance(album_data, dict) else None,
                        album_art_url=images[0]["url"] if images else None,
                    )
                    # Only add tracks that have enough info for YouTube search
                    if track_info.is_valid_for_youtube_search:
                        tracks.append(track_info)
                    else:
                         print(f"  Skipping track due to missing title/artist: {track_data.get('name')}")

            # Move to the next batch
            offset += len(items)
            print(f"  Fetched {len(tracks)} tracks so far...")
            # Add a small delay to avoid hitting rate limits aggressively
            # time.sleep(0.1)

        except Exception as e:
            print(f"Error fetching playlist items (offset {offset}): {e}")
            # Stop fetching on error
            break

    print(f"Finished fetching. Total valid tracks found: {len(tracks)}")
    return tracks


def search_youtube(track: TrackInfo) -> Optional[str]:
    """
    Searches YouTube for a given track using its metadata.

    Args:
        track: The TrackInfo object containing track metadata.

    Returns:
        The URL of the best matching YouTube video, or None if not found/error.
    """
    if not track.is_valid_for_youtube_search:
        print(f"Skipping YouTube search for track '{track.title or track.filename}' - insufficient metadata.")
        return None

    query = track.search_query_youtube
    print(f"Searching YouTube for: '{query}'")
    try:
        # Perform the search, limiting to 1 result
        search = VideosSearch(query, limit=1)
        results_dict = search.result() # Get results as dictionary

        # Check the structure of the response carefully
        if results_dict and isinstance(results_dict, dict) and "result" in results_dict:
            result_list = results_dict["result"]
            if result_list and isinstance(result_list, list) and len(result_list) > 0:
                # Get the link from the first result item
                video_url = result_list[0].get("link")
                if video_url and isinstance(video_url, str):
                    print(f"  Found YouTube URL: {video_url}")
                    return video_url
                else:
                     print(f"  Found result item, but missing 'link': {result_list[0]}")

        # If any check fails or no results found
        print(f"  No valid YouTube results found for '{query}'.")
        return None
    except Exception as e:
        # Catch potential exceptions during the search process
        print(f"Error searching YouTube for '{query}': {e}")
        return None


def sanitize_filename(name: str) -> str:
    """
    Removes characters from a string that are typically invalid in filenames
    across different operating systems and cleans common YouTube title additions.

    Args:
        name: The input string (potential filename part, likely from YouTube title).

    Returns:
        A sanitized string suitable for use in filenames.
    """
    # 1. Remove common YouTube additions (case-insensitive)
    #    Patterns like (Official Music Video), [Lyrics], | Artist Name etc.
    name = re.sub(r'\s*\(.*Official Video.*?\)\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\(.*Music Video.*?\)\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\(.*Lyric Video.*?\)\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\(.*Audio.*?\)\s*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\[.*?\]\s*', '', name) # Remove content in square brackets
    name = re.sub(r'\s*\|.*$', '', name) # Remove pipe and everything after
    name = re.sub(r'\s*//.*$', '', name) # Remove double slash and everything after

    # 2. Remove characters invalid in filenames
    name = re.sub(r'[<>:"/\\|?*\n\t]', "", name)

    # 3. Clean up whitespace: replace multiple spaces/tabs with single space, strip ends
    name = re.sub(r"\s+", " ", name).strip()

    # 4. Optional: Consolidate multiple hyphens or dashes if needed
    # name = re.sub(r'-+', '-', name).strip('-')

    # Optional: Limit filename length if needed
    # max_len = 100
    # name = name[:max_len]

    return name


def add_metadata(mp3_path: str, track: TrackInfo):
    """
    Adds ID3 metadata (title, artist, album) and album art to a downloaded MP3 file.

    Uses the `mutagen` library. Note: `yt-dlp` can often handle this embedding
    natively, making this function potentially redundant but useful for fine-tuning.

    Args:
        mp3_path: The path to the MP3 file.
        track: The TrackInfo object containing the metadata to add.
    """
    target_path = pathlib.Path(mp3_path)
    if not target_path.is_file():
        print(f"  Error adding metadata: File not found at {mp3_path}")
        return

    print(f"  Attempting to add metadata to {target_path.name}...")
    try:
        # --- Add Basic Tags (Title, Artist, Album) ---
        try:
            # Load existing tags or create new ones
            audio = EasyID3(mp3_path)
        except ID3NoHeaderError:
            # If no ID3 header exists, create one by saving empty ID3 tags
            print(f"    No ID3 header found, creating one for {target_path.name}.")
            audio_id3_create = ID3()
            audio_id3_create.save(mp3_path)
            audio = EasyID3(mp3_path) # Reload as EasyID3

        # Assign metadata if available in the TrackInfo object
        if track.title:
            audio["title"] = track.title
        if track.artist:
            audio["artist"] = track.artist
        if track.album:
            audio["album"] = track.album
        audio.save() # Save the basic tags
        print(f"    Added basic metadata (Title/Artist/Album).")

        # --- Add Album Art ---
        if track.album_art_url:
            print(f"    Attempting to download and embed album art from {track.album_art_url[:50]}...")
            try:
                # Download the album art image
                response = requests.get(track.album_art_url, stream=True, timeout=15) # Increased timeout
                response.raise_for_status() # Check for HTTP errors
                image_data = response.content
                content_type = response.headers.get('content-type', 'image/jpeg').lower() # Get MIME type

                 # Determine MIME type for APIC frame
                if 'image/jpeg' in content_type or 'image/jpg' in content_type:
                    mime = 'image/jpeg'
                elif 'image/png' in content_type:
                    mime = 'image/png'
                else:
                    print(f"    Warning: Unsupported image type '{content_type}', skipping album art.")
                    return # Skip adding art if type unknown

                # Load the file with mutagen.id3.ID3 to add complex tags like APIC
                audio_id3_art = ID3(mp3_path)
                # Remove existing APIC frames before adding new one
                audio_id3_art.delall('APIC')
                audio_id3_art.add(
                    APIC(
                        encoding=3,  # 3: UTF-8
                        mime=mime,
                        type=3,  # 3: Cover (front)
                        desc='Cover',
                        data=image_data,
                    )
                )
                # Save changes using ID3.save, forcing ID3v2.3 for compatibility
                audio_id3_art.save(v2_version=3)
                print(f"    Successfully added album art.")

            except requests.exceptions.RequestException as req_e:
                print(f"    Failed to download album art: {req_e}")
            except Exception as art_e:
                # Catch other potential errors during tag manipulation
                print(f"    Failed to embed album art: {art_e}")
        else:
            print("    No album art URL available.")

    except Exception as meta_e:
        # Catch general errors during metadata processing
        print(f"  Error adding metadata to {target_path.name}: {meta_e}")


def download_track_from_youtube(track: TrackInfo, output_dir: pathlib.Path) -> bool:
    """
    Downloads audio from a YouTube URL using yt-dlp, converts it to MP3,
    and attempts to embed metadata and album art.

    Args:
        track: The TrackInfo object containing the YouTube URL and metadata.
        output_dir: The directory where the downloaded MP3 should be saved.

    Returns:
        True if the download and conversion were successful, False otherwise.
    """
    if not track.youtube_url or not track.artist or not track.title:
        print(f"Skipping download for track '{track.title or track.filename}' - missing YouTube URL, artist, or title.")
        return False

    # Create a sanitized filename based on artist and title
    filename_base = sanitize_filename(f"{track.artist} - {track.title}")
    # Define the output template for yt-dlp (includes path and desired extension)
    output_template = output_dir / f"{filename_base}.%(ext)s"
    # Define the final expected MP3 path
    mp3_path = output_dir / f"{filename_base}.mp3"

    # --- Check if file already exists ---
    if mp3_path.exists():
        print(f"  Skipping download, file already exists: {mp3_path.name}")
        # Optional: You could add logic here to check if metadata is missing
        # and call add_metadata() if needed, even if the file exists.
        return True # Consider existing file a success

    # --- Configure yt-dlp options ---
    ydl_opts = {
        "format": "bestaudio/best", # Prefer best audio quality
        "outtmpl": str(output_template), # Output path and filename template
        "noplaylist": True, # Ensure only single video is downloaded
        "quiet": True, # Suppress yt-dlp console output
        "noprogress": True, # Suppress progress bar
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio", # Use FFmpeg to extract audio
                "preferredcodec": "mp3", # Convert to MP3
                "preferredquality": "192", # Set MP3 quality (e.g., 192kbps)
            },
            # Add metadata using FFmpeg during post-processing
             {'key': 'FFmpegMetadata', 'add_metadata': True},
             # Embed thumbnail using FFmpeg (requires thumbnail download)
             {'key': 'EmbedThumbnail', 'already_have_thumbnail': False},
        ],
        "writethumbnail": True, # Tell yt-dlp to download the thumbnail
        "addmetadata": True, # Tell yt-dlp to add metadata if possible (might be redundant with FFmpegMetadata)
        # Using 'metadatafromtitle' might be unreliable, prefer specific metadata args if possible
        # 'metadatafromtitle': '%(artist)s - %(title)s',
        # 'postprocessor_args': { # This method of passing args might be less reliable than FFmpegMetadata PP
        #      'ffmpeg': ['-metadata', f'title={track.title}',
        #                 '-metadata', f'artist={track.artist}',
        #                 '-metadata', f'album={track.album or "Unknown Album"}']
        # },
        'embedthumbnail': True, # Tell FFmpeg postprocessor to embed downloaded thumbnail
        'ignoreerrors': True, # Continue if a specific download fails
        'retries': MAX_RETRIES, # Retry downloads on transient errors
        # 'fragment_retries': MAX_RETRIES, # Also retry fragments if applicable
    }

    print(f"Downloading: {track.artist} - {track.title} from {track.youtube_url}")
    try:
        # Instantiate YoutubeDL - ignore potential type checker confusion
        # The 'operator' ignore code is common for this specific issue with yt-dlp
        ydl = YoutubeDL(ydl_opts)  # type: ignore[operator]
        # Start the download process for the given URL
        error_code = ydl.download([track.youtube_url])

        # Check results
        if error_code == 0 and mp3_path.exists():
            print(f"  Successfully downloaded and converted: {mp3_path.name}")
            # Optionally call our custom add_metadata for more control,
            # though yt-dlp with FFmpegMetadata/EmbedThumbnail should handle it.
            # add_metadata(str(mp3_path), track)
            return True
        elif error_code != 0:
             print(f"  yt-dlp reported an error (code {error_code}) for '{track.title}'.")
             return False
        else: # error_code == 0 but file doesn't exist
            print(f"  Download seemed to finish, but expected MP3 file not found: {mp3_path.name}")
            # This might indicate an issue during the FFmpeg conversion stage.
            return False

    except Exception as e:
        # Catch any unexpected errors during the download process
        print(f"  Unhandled error downloading '{track.title}': {e}")
        # Optionally clean up partial files here if needed
        # e.g., list(output_dir.glob(f"{filename_base}.*")) and remove them
        return False


def _parse_youtube_title(raw_title: str) -> str:
    """
    Cleans a raw YouTube video title by removing common additions.

    Args:
        raw_title: The original title string from YouTube.

    Returns:
        A cleaned title string.
    """
    cleaned_title = raw_title # Start with the raw title

    # Apply aggressive cleaning (remove common junk)
    cleaned_title = re.sub(r'\s*\(.*Official Video.*?\)\s*', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s*\(.*Music Video.*?\)\s*', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s*\(.*Lyric Video.*?\)\s*', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s*\(.*Audio.*?\)\s*', '', cleaned_title, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'\s*\[.*?\]\s*', '', cleaned_title) # Remove content in square brackets
    cleaned_title = re.sub(r'\s*\|.*$', '', cleaned_title) # Remove pipe and everything after
    cleaned_title = re.sub(r'\s*//.*$', '', cleaned_title) # Remove double slash and everything after
    # Add more specific rules if needed, e.g., removing " | Napalm Records" specifically
    # cleaned_title = re.sub(r'\s*\|\s*Napalm Records\s*$', '', cleaned_title, flags=re.IGNORECASE)

    # Remove potential leftover invalid filename chars AFTER specific cleaning
    cleaned_title = re.sub(r'[<>:"/\\|?*\n\t]', "", cleaned_title)
    # Clean up whitespace
    cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip()
    # Clean potential leading/trailing hyphens left from splits/removals
    cleaned_title = cleaned_title.strip("- ")

    print(f"  Cleaned YT Title: '{cleaned_title}' (From: '{raw_title[:50]}...')")
    return cleaned_title


# --- Add Helper to Write Tags ---
def _write_youtube_tags(filepath: pathlib.Path, artist: Optional[str], title: Optional[str], info_dict: Dict):
    """
    Writes ID3 tags (artist, title, album art) to an MP3 file using Mutagen,
    specifically for files downloaded from YouTube.

    Args:
        filepath: Path to the MP3 file.
        artist: The guessed artist name.
        title: The cleaned title.
        info_dict: The yt-dlp info dictionary containing thumbnail path.
    """
    if not filepath.is_file():
        print(f"  Error writing tags: File not found at {filepath}")
        return

    print(f"  Writing ID3 Tags for: {filepath.name}")
    try:
        # --- Add Basic Tags (Title, Artist) ---
        try:
            audio = EasyID3(filepath)
        except ID3NoHeaderError:
            print(f"    No ID3 header found, creating one for {filepath.name}.")
            audio_id3_create = ID3()
            audio_id3_create.save(filepath)
            audio = EasyID3(filepath)

        if title:
            audio["title"] = title
            # Clear potentially incorrect album extracted by yt-dlp if we only have title/artist
            if "album" in audio: del audio["album"]
        if artist:
            audio["artist"] = artist
        audio.save()
        print(f"    Saved Title='{title}', Artist='{artist}'")

        # --- Embed Thumbnail as Album Art ---
        # yt-dlp puts the final thumbnail path in 'thumbnail' key AFTER processing
        thumbnail_path_str = info_dict.get('thumbnail')
        if thumbnail_path_str and pathlib.Path(thumbnail_path_str).is_file():
            thumbnail_path = pathlib.Path(thumbnail_path_str)
            print(f"    Attempting to embed thumbnail: {thumbnail_path.name}")
            try:
                with open(thumbnail_path, 'rb') as art_file:
                    image_data = art_file.read()

                # Determine MIME type from file extension
                ext = thumbnail_path.suffix.lower()
                if ext in ['.jpg', '.jpeg']:
                    mime = 'image/jpeg'
                elif ext == '.png':
                    mime = 'image/png'
                elif ext == '.webp':
                     mime = 'image/webp' # Mutagen supports webp in APIC
                else:
                    print(f"    Warning: Unsupported thumbnail image type '{ext}', skipping embed.")
                    return

                audio_id3_art = ID3(filepath)
                audio_id3_art.delall('APIC') # Remove existing art
                audio_id3_art.add(
                    APIC(
                        encoding=3, mime=mime, type=3, desc='Cover', data=image_data
                    )
                )
                audio_id3_art.save(v2_version=3)
                print(f"    Successfully embedded thumbnail as album art.")

            except FileNotFoundError:
                 print(f"    Error embedding thumbnail: File not found at {thumbnail_path_str}")
            except Exception as art_e:
                 print(f"    Error embedding thumbnail: {art_e}")
        else:
            print(f"    No valid thumbnail path found in info_dict ('{thumbnail_path_str}').")

    except Exception as meta_e:
        print(f"  Error writing tags to {filepath.name}: {meta_e}")


def rename_hook(d: Dict[str, Any]):
    """
    yt-dlp hook function called after download and postprocessing.
    Finds the final MP3 file, renames it using playlist index, uploader/channel as artist,
    and sanitized title, then writes cleaned ID3 tags.

    Args:
        d: Dictionary passed by yt-dlp containing download status and info.
    """
    if d['status'] == 'finished':
        info_dict = d.get('info_dict', {})
        final_filepath_str = info_dict.get('filepath') or d.get('filename')
        if not final_filepath_str: # ... (error handling) ...
             return
        final_filepath = pathlib.Path(final_filepath_str).resolve()
        if not final_filepath.is_file() or final_filepath.suffix.lower() != '.mp3': # ... (error handling) ...
             return

        # --- Get necessary info for new name and tags ---
        playlist_index_str = str(info_dict.get('playlist_index', '00'))
        playlist_index_padded = playlist_index_str.zfill(2)
        raw_title = info_dict.get('title', final_filepath.stem)

        # --- Determine Artist (Uploader/Channel) and Clean Title ---
        # Use 'uploader' or 'channel' as the best guess for Artist
        artist_guess = info_dict.get('uploader') or info_dict.get('channel') or "Unknown Artist"
        # Clean the raw title using the simplified function
        cleaned_title = _parse_youtube_title(raw_title)

        # --- Construct New Filename ---
        # Combine index, guessed artist, and cleaned title
        new_filename_stem = f"{playlist_index_padded} - {artist_guess} - {cleaned_title}"
        # Sanitize the fully constructed stem
        new_filename_stem_sanitized = sanitize_filename(new_filename_stem)
        new_filename = f"{new_filename_stem_sanitized}.mp3"
        new_filepath = final_filepath.parent / new_filename

        # --- Perform Rename ---
        final_path_for_tags = None
        # ... (rest of rename logic remains the same, determining final_path_for_tags) ...
        if final_filepath == new_filepath:
             print(f"  Filename already correct: '{final_filepath.name}'")
             final_path_for_tags = final_filepath # Use the existing path
        else:
            try:
                print(f"  Renaming: '{final_filepath.name}' -> '{new_filename}'")
                final_filepath.rename(new_filepath)
                final_path_for_tags = new_filepath # Use the new path for tags
            except OSError as e:
                print(f"  ERROR renaming file '{final_filepath.name}' to '{new_filename}': {e}")
                if final_filepath.is_file():
                     print(f"  Attempting to write tags to original file path: {final_filepath.name}")
                     final_path_for_tags = final_filepath
            except Exception as e:
                 print(f"  Unexpected error during rename: {e}")

        # --- Write Corrected ID3 Tags ---
        if final_path_for_tags:
            # Pass the determined artist and cleaned title to the tag writer
            _write_youtube_tags(final_path_for_tags, artist_guess, cleaned_title, info_dict)
        else:
             print(f"  Skipping tag writing due to rename/file access issues for original: {final_filepath.name}")


def run_sync_to_spotify(args: Namespace, connection: SpotifyConnection) -> int:
    """
    Implements the 'to-spotify' command. Scans local MP3s, finds matches
    on Spotify, and adds them to a specified playlist.

    Args:
        args: Parsed command-line arguments specific to 'to-spotify'.
        connection: The authenticated SpotifyConnection object.

    Returns:
        0 on success, 1 on failure.
    """
    print("\nStarting sync: Local MP3s -> Spotify Playlist")
    n_mp3 = 0
    tracks_found_on_spotify: List[TrackInfo] = []

    # 1. Scan local directory
    for track in mp3_walk_directory(args.directory):
        n_mp3 += 1
        if not track.is_valid_for_spotify_search:
            print(f"  Skipping {track.filename or 'Unknown File'} - insufficient info for search.")
            continue

        # 2. Search Spotify for each valid local track
        try:
            query = track.search_query_spotify
            print(f"Searching Spotify for: '{query}'")
            results = connection.connection.search(q=query, type="track", limit=1)

            # Process search results
            if (
                results
                and isinstance(results, dict)
                and "tracks" in results
                and isinstance(results["tracks"], dict)
                and "items" in results["tracks"]
                and results["tracks"]["items"] # Check if list is not empty
            ):
                spotify_track = results["tracks"]["items"][0]
                # Extract necessary info safely
                track.url = spotify_track.get("external_urls", {}).get("spotify")
                track.spotify_id = spotify_track.get("id")

                if track.url and track.spotify_id:
                    print(f"  Found Spotify match: {track.url}")
                    tracks_found_on_spotify.append(track)
                else:
                    print("  Found track, but missing URL or ID in response.")
            else:
                print("  Not found on Spotify.")
        except Exception as e:
            print(f"  Error searching Spotify for track '{track.title or track.filename}': {e}")
            continue # Continue with the next track

    # 3. Get or Create the target Spotify Playlist
    print(f"\nChecking/Creating Spotify playlist: '{args.playlist}'")
    playlist = spotify_check_playlist(connection, playlistname=args.playlist)
    if not playlist:
        playlist_id = spotify_create_playlist(connection, args.playlist)
        if not playlist_id:
            # spotify_create_playlist prints errors, just exit
             return 1
        playlist = {"id": playlist_id, "name": args.playlist} # Simulate playlist dict

    if not playlist or "id" not in playlist:
        print("Fatal: Failed to get or create playlist ID.")
        return 1

    playlistid = playlist["id"]
    print(f"Using playlist ID: {playlistid}")

    # 4. Add found tracks to the playlist
    tracks_to_add_urls = [t.url for t in tracks_found_on_spotify if t.has_spotify_url]
    if not tracks_to_add_urls:
        print("\nNo valid Spotify tracks found from local MP3s to add to the playlist.")
        print(f"Sync finished. MP3s scanned: {n_mp3}")
        return 0 # Not an error if no tracks were found/added

    print(f"\nAdding {len(tracks_to_add_urls)} tracks to playlist '{args.playlist}'...")
    added_count = 0
    # Process in chunks to avoid hitting API limits
    for chunk_urls in list_chunks(tracks_to_add_urls, CHUNK_SIZE):
        try:
            connection.connection.playlist_add_items(playlistid, chunk_urls)
            print(f"  Added chunk of {len(chunk_urls)} tracks.")
            added_count += len(chunk_urls)
        except Exception as e:
            print(f"  Error adding tracks chunk to playlist: {e}")
            # Optionally implement retries here or decide to stop/continue
            # continue

    print(
        f"\nSync finished. MP3s scanned: {n_mp3} | "
        f"Tracks added to Spotify: {added_count}"
    )
    return 0 # Success


def run_sync_from_spotify(args: Namespace, connection: SpotifyConnection) -> int:
    """
    Implements the 'from-spotify' command. Fetches tracks from a Spotify playlist,
    searches YouTube, downloads audio, converts to MP3, and adds metadata.
    Uses parallel workers for searching and downloading.

    Args:
        args: Parsed command-line arguments including 'num_cores'.
        connection: The authenticated SpotifyConnection object.

    Returns:
        0 on success, 1 on failure.
    """
    print("\nStarting sync: Spotify Playlist -> Local MP3s")

    # Determine number of workers
    # If num_cores is 0, ThreadPoolExecutor uses default (usually CPU cores)
    max_workers_to_use = args.num_cores if args.num_cores > 0 else None
    print(f"Using up to {max_workers_to_use or 'maximum available'} workers for parallel tasks.")

    if not args.playlist_id:
        print("Error: Spotify Playlist ID is required via --playlist-id.")
        return 1

    # Prepare output directory
    try:
        output_dir = pathlib.Path(args.directory).resolve() # Use resolved path
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory set to: {output_dir}")
    except Exception as e:
        print(f"Error creating output directory '{args.directory}': {e}")
        return 1

    # 1. Get tracks from Spotify playlist
    spotify_tracks = get_playlist_tracks(connection.connection, args.playlist_id)
    if not spotify_tracks:
        print("No tracks found in the specified playlist or failed to fetch.")
        return 1 # Exit if no tracks to process

    # 2. Search YouTube for each track (in parallel)
    print(f"\nSearching YouTube for {len(spotify_tracks)} tracks...")
    tracks_with_youtube_url: List[TrackInfo] = []
    search_futures = {}
    # Use the determined number of workers
    with ThreadPoolExecutor(max_workers=max_workers_to_use, thread_name_prefix="youtube_search") as executor:
        # Submit all search tasks
        for track in spotify_tracks:
            future = executor.submit(search_youtube, track)
            search_futures[future] = track # Map future back to track

        # Process results as they complete
        for future in as_completed(search_futures):
            track = search_futures[future]
            try:
                youtube_url = future.result()
                if youtube_url:
                    track.youtube_url = youtube_url
                    tracks_with_youtube_url.append(track)
                    # print(f"  Found YouTube URL for: {track.title}") # Already printed in search_youtube
            except Exception as exc:
                print(f"  YouTube search for '{track.title}' generated an exception: {exc}")

    if not tracks_with_youtube_url:
        print("\nNo YouTube URLs could be found for any tracks in the playlist.")
        return 1 # Exit if no tracks can be downloaded

    # 3. Download and convert tracks (in parallel)
    print(f"\nDownloading {len(tracks_with_youtube_url)} tracks...")
    download_futures = {}
    successful_downloads = 0
    failed_downloads = 0
    # Use the determined number of workers
    with ThreadPoolExecutor(max_workers=max_workers_to_use, thread_name_prefix="youtube_download") as executor:
        # Submit all download tasks
        for track in tracks_with_youtube_url:
            future = executor.submit(download_track_from_youtube, track, output_dir)
            download_futures[future] = track # Map future back to track

        # Process results as downloads complete
        for future in as_completed(download_futures):
            track = download_futures[future] # Get track associated with this future
            try:
                success = future.result()
                if success:
                    successful_downloads += 1
                else:
                    # Download function already prints errors
                    failed_downloads += 1
            except Exception as exc:
                print(f"  Download for '{track.title}' generated an unexpected exception: {exc}")
                failed_downloads += 1

    # Final summary report
    print(
        f"\nSync finished."
        f"\n  Tracks in Spotify playlist: {len(spotify_tracks)}"
        f"\n  Tracks found on YouTube:    {len(tracks_with_youtube_url)}"
        f"\n  Successful downloads:       {successful_downloads}"
        f"\n  Failed downloads:           {failed_downloads}"
    )
    # Return success (0) even if some downloads failed, as the process completed.
    # Could return 1 if failed_downloads > 0 if desired.
    return 0


def run_sync_from_youtube(args: Namespace) -> int:
    """
    Implements the 'from-youtube' command. Downloads audio from all videos
    in a YouTube playlist using yt-dlp, converts to MP3, adds metadata,
    and renames files using a sanitized title via a postprocessor hook.

    Args:
        args: Parsed command-line arguments including 'num_cores'.

    Returns:
        0 on success, 1 on failure.
    """
    print("\nStarting sync: YouTube Playlist -> Local MP3s")

    # Acknowledge the num_cores setting, although yt-dlp manages its own parallelism
    num_cores_info = args.num_cores if args.num_cores > 0 else 'maximum available'
    print(f"(Note: yt-dlp manages download parallelism internally; --num-cores setting '{num_cores_info}' not directly applied here.)")

    if not args.playlist_url:
        print("Error: YouTube Playlist URL is required via --playlist-url.")
        return 1

    # Prepare output directory
    try:
        output_dir = pathlib.Path(args.directory).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory set to: {output_dir}")
    except Exception as e:
        print(f"Error creating output directory '{args.directory}': {e}")
        return 1

    # --- Determine Default for Keeping Intermediate Files (YouTube Only) ---
    default_keep_intermediate = False
    try:
        env_keep = os.environ.get("MP3IFY_KEEP_INTERMEDIATE", "false").lower()
        if env_keep in ('true', '1', 'yes', 'y'):
            default_keep_intermediate = True
            print(f"Using MP3IFY_KEEP_INTERMEDIATE environment variable: {default_keep_intermediate}")
    except Exception: # Catch potential errors during env var processing
        print(f"Warning: Invalid value for MP3IFY_KEEP_INTERMEDIATE env var. Using default: {default_keep_intermediate}")
        default_keep_intermediate = False

    # --- Configure yt-dlp options for playlist download ---
    # Use a simple, reliable template like video ID initially.
    # The hook will rename the final file based on sanitized title and index.
    output_template = output_dir / "%(id)s.%(ext)s" # Use video ID for initial temp name

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_template), # Initial template using video ID
        "noplaylist": False,
        "ignoreerrors": True,
        "quiet": False,
        "noprogress": False,
        "keepvideo": args.keep_intermediate_files,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            # Metadata/Thumbnail embedding PPs should run before our rename hook
            {'key': 'FFmpegMetadata', 'add_metadata': True}, # Add whatever metadata yt-dlp can find initially
            {'key': 'EmbedThumbnail', 'already_have_thumbnail': False},
        ],
        "writethumbnail": True,
        # 'addmetadata': True, # FFmpegMetadata is likely sufficient
        'embedthumbnail': True, # Tell FFmpeg PP to embed
        'retries': MAX_RETRIES,
        'postprocessor_hooks': [rename_hook], # Our hook runs last
    }

    print(f"Attempting to download playlist: {args.playlist_url}")
    try:
        ydl = YoutubeDL(ydl_opts) # type: ignore[operator]
        error_code = ydl.download([args.playlist_url])

        if error_code == 0:
            print("\nPlaylist download process completed successfully (check logs for skipped/renamed files).")
            if args.keep_intermediate_files:
                print("(Note: Intermediate files like original downloads and thumbnails were kept.)")
            else:
                print("(Note: Intermediate files were deleted, only final MP3s remain.)")
            return 0
        else:
            print(f"\nPlaylist download process finished, but yt-dlp reported errors (exit code: {error_code}).")
            return 1

    except Exception as e:
        print(f"\nAn unexpected error occurred during YouTube playlist download: {e}")
        return 1


def setup() -> Namespace:
    """
    Parses command-line arguments using argparse, including subparsers for
    different commands ('to-spotify', 'from-spotify', 'from-youtube'). Also handles loading
    of environment variables from a .env file, validates required credentials,
    and determines the number of parallel workers.

    Returns:
        An argparse.Namespace object containing the parsed arguments.
    """
    parser = ArgumentParser(
        description="Sync music between local MP3s, Spotify playlists, and YouTube playlists."
    )

    # --- Determine Default Number of Cores ---
    # Priority: Environment Variable (NUMCORES) > Default (e.g., 5)
    default_num_cores = 5 # Fallback default
    try:
        env_cores = os.environ.get("NUMCORES")
        if env_cores is not None:
            default_num_cores = int(env_cores)
            print(f"Using NUMCORES environment variable: {default_num_cores}")
            # Clamp non-negative, 0 means max parallelism later
            if default_num_cores < 0:
                default_num_cores = 5 # Reset to fallback if negative
    except ValueError:
        print(f"Warning: Invalid value for NUMCORES environment variable ('{env_cores}'). Using default: {default_num_cores}")
        default_num_cores = 5 # Reset to fallback

    # --- Determine Default for Keeping Intermediate Files (YouTube Only) ---
    default_keep_intermediate = False
    try:
        env_keep = os.environ.get("MP3IFY_KEEP_INTERMEDIATE", "false").lower()
        if env_keep in ('true', '1', 'yes', 'y'):
            default_keep_intermediate = True
            print(f"Using MP3IFY_KEEP_INTERMEDIATE environment variable: {default_keep_intermediate}")
    except Exception: # Catch potential errors during env var processing
        print(f"Warning: Invalid value for MP3IFY_KEEP_INTERMEDIATE env var. Using default: {default_keep_intermediate}")
        default_keep_intermediate = False

    # --- Global Arguments (Apply to all commands) ---
    parser.add_argument(
        "--env-file",
        dest="env_file", action="store", required=False, type=str,
        help="Path to .env file (defaults to '.env' in current directory)",
    )
    parser.add_argument(
        "--num-cores",
        dest="num_cores",
        action="store",
        required=False,
        type=int,
        default=default_num_cores, # Default set based on env var or fallback
        help="Number of parallel workers for downloads (0 for max available cores, "
             f"default: {default_num_cores} based on NUMCORES env var or fallback)",
    )

    # Group for authentication arguments, common to all subcommands
    auth_group = parser.add_argument_group("Spotify Authentication")
    auth_group.add_argument(
        "--oauthclientid",
        dest="clientid",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_CLIENT_ID"),
        help="Spotify Client ID (or use SPOTIPY_CLIENT_ID env var)",
    )
    auth_group.add_argument(
        "--oauthclientsecret",
        dest="clientsecret",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_CLIENT_SECRET"),
        help="Spotify Client Secret (or use SPOTIPY_CLIENT_SECRET env var)",
    )
    auth_group.add_argument(
        "--oauthredirecturi",
        dest="redirecturi",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_REDIRECT_URI"),
        help="Spotify Redirect URI (or use SPOTIPY_REDIRECT_URI env var)",
    )

    # Define subparsers for the main commands
    subparsers = parser.add_subparsers(
        dest="command", help="Choose operation: 'to-spotify', 'from-spotify', or 'from-youtube'", required=True
    )

    # --- Subparser: to-spotify (Local MP3s -> Spotify Playlist) ---
    parser_to_spotify = subparsers.add_parser(
        "to-spotify", help="Sync local MP3s to a Spotify playlist"
    )
    parser_to_spotify.add_argument(
        "--directory",
        "-d",
        dest="directory",
        action="store",
        required=False,
        type=str,
        default="mp3/", # Default input directory
        help="Directory containing MP3 files to scan",
    )
    parser_to_spotify.add_argument(
        "--playlist",
        dest="playlist",
        action="store",
        required=False,
        type=str,
        default="MP3ify", # Default playlist name
        help="Name of the Spotify playlist to create/update",
    )

    # --- Subparser: from-spotify (Spotify Playlist -> Local MP3s) ---
    parser_from_spotify = subparsers.add_parser(
        "from-spotify", help="Download tracks from a Spotify playlist to local MP3s"
    )
    parser_from_spotify.add_argument(
        "--playlist-id",
        dest="playlist_id",
        action="store",
        required=True, # Playlist ID is mandatory for this command
        type=str,
        help="Spotify Playlist ID to download from",
    )
    parser_from_spotify.add_argument(
        "--directory", # Using -d consistently, but destination is 'directory'
        "-d",
        dest="directory", # Argument destination name matches 'to-spotify'
        action="store",
        required=False,
        type=str,
        default="spotify_downloads/", # Default output directory
        help="Directory to save downloaded MP3 files",
    )

    # --- Subparser: from-youtube (YouTube Playlist -> Local MP3s) ---
    parser_from_youtube = subparsers.add_parser(
        "from-youtube", help="Download audio from a YouTube playlist to local MP3s"
    )
    parser_from_youtube.add_argument(
        "--playlist-url",
        dest="playlist_url",
        action="store",
        required=True, # YouTube Playlist URL is mandatory
        type=str,
        help="URL of the YouTube playlist to download",
    )
    parser_from_youtube.add_argument(
        "--directory",
        "-d",
        dest="directory",
        action="store",
        required=False,
        type=str,
        default="youtube_downloads/", # Different default output directory
        help="Directory to save downloaded MP3 files",
    )
    parser_from_youtube.add_argument(
        "--keep-intermediate-files",
        dest="keep_intermediate_files",
        action="store_true", # Makes it a boolean flag
        default=default_keep_intermediate, # Default based on env var
        help="Keep all downloaded files (e.g., original format, thumbnails), not just the final MP3. "
             "(Default: delete intermediates)",
    )

    # Parse the arguments provided
    # The --num-cores value will be determined by: command-line > env var > fallback default
    args = parser.parse_args()

    # --- Load .env file ---
    # Determine the path to the .env file (default or specified)
    env_file_path_str = args.env_file if args.env_file else ".env"
    env_file_path = pathlib.Path(env_file_path_str)
    # Load only if the file exists
    if env_file_path.is_file():
        if load_dotenv(dotenv_path=env_file_path, override=True): # Override existing env vars
             print(f"Loaded environment variables from: {env_file_path.resolve()}")
        else:
             print(f"Attempted to load .env file, but load_dotenv returned False: {env_file_path.resolve()}")
    elif args.env_file: # Warn only if a specific file was requested but not found
         print(f"Warning: Specified --env-file not found: {args.env_file}")
    # else: No warning if default .env is missing

    # --- Apply command-line arguments over environment variables ---
    # This allows overriding .env or system env vars via command line
    if args.clientid:
        os.environ["SPOTIPY_CLIENT_ID"] = args.clientid
    if args.clientsecret:
        os.environ["SPOTIPY_CLIENT_SECRET"] = args.clientsecret
    if args.redirecturi:
        os.environ["SPOTIPY_REDIRECT_URI"] = args.redirecturi

    # --- Validate required credentials ---
    # Check that essential Spotify credentials are set after all loading methods
    if args.command in ["to-spotify", "from-spotify"]:
        if not (
            os.environ.get("SPOTIPY_CLIENT_ID")
            and os.environ.get("SPOTIPY_CLIENT_SECRET")
            and os.environ.get("SPOTIPY_REDIRECT_URI")
        ):
            parser.error(
                f"Missing Spotify credentials for command '{args.command}'. Provide SPOTIPY_CLIENT_ID, "
                "SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI via arguments, "
                "environment variables, or a .env file."
            )

    return args


def main_dispatcher(args: Namespace) -> int:
    """
    Main application dispatcher. Connects to Spotify if needed and calls the
    appropriate sync function based on the parsed command-line arguments.

    Args:
        args: The parsed Namespace object containing arguments and the subcommand.

    Returns:
        The exit code of the executed sync function (0 for success, 1 for failure).
    """
    command = args.command
    print(f"\nExecuting command: {command}")

    # Only connect to Spotify if needed
    connection: Optional[SpotifyConnection] = None
    if command in ["to-spotify", "from-spotify"]:
        connection = spotify_connect()
        if not connection or not connection.connection:
            print("Fatal Error: Could not establish Spotify connection for this command.")
            return 1

    # Dispatch based on the chosen command
    if command == "to-spotify":
        # 'to-spotify' requires a user ID
        if not connection or not connection.userid: # Ensure connection is not None here
            print(
                "Error: Could not retrieve Spotify user information required "
                "for 'to-spotify' command. Authentication might have failed."
            )
            return 1
        return run_sync_to_spotify(args, connection)

    elif command == "from-spotify":
        # 'from-spotify' also requires the connection
        if not connection: # Should not happen if check above passes, but belt-and-suspenders
             print("Error: Spotify connection object missing for 'from-spotify'.")
             return 1
        return run_sync_from_spotify(args, connection)

    elif command == "from-youtube":
        # 'from-youtube' does not require Spotify connection
        return run_sync_from_youtube(args)

    else:
        # This case should be unreachable if subparsers are required=True
        print(f"Error: Unknown command '{command}'. Use --help for options.")
        return 1


if __name__ == "__main__":
    # Parse arguments when script is run directly
    parsed_args = setup()
    # Call the main dispatcher and exit with its return code
    exit_code = main_dispatcher(parsed_args)
    sys.exit(exit_code)

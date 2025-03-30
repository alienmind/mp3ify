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
from typing import Any, Dict, Iterator, List, Optional, cast

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
MAX_WORKERS = 5  # Max parallel downloads

# Constants for magic numbers
TRACK_FORMAT_PARTS_4 = 4  # TrackNo - Artist - Album - Name
TRACK_FORMAT_PARTS_3 = 3  # Artist - Album - Name
TRACK_FORMAT_PARTS_2 = 2  # Album - Name


@dataclass
class SpotifyConnection:
    connection: sp.Spotify
    userid: Optional[str] = None
    username: Optional[str] = None


@dataclass
class TrackInfo:
    filename: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None  # Spotify URL for sync-to-spotify
    youtube_url: Optional[str] = None  # YouTube URL for sync-from-spotify
    spotify_id: Optional[str] = None  # Spotify Track ID
    album_art_url: Optional[str] = None  # URL for album art

    @property
    def search_query_spotify(self) -> str:
        """Generate a Spotify search query from MP3 track info."""
        if not self.artist or not self.title:
            return self.title or ""
        return f"artist:{self.artist} track:{self.title}"  # Adjusted for Spotify search

    @property
    def search_query_youtube(self) -> str:
        """Generate a YouTube search query from Spotify track info."""
        query_parts = []
        if self.artist:
            query_parts.append(self.artist)
        if self.title:
            query_parts.append(self.title)
        if self.album:  # Adding album can sometimes improve results
            query_parts.append(self.album)
        return (
            " ".join(query_parts) + " audio"
        )  # Add 'audio' to prioritize music results

    @property
    def is_valid_for_spotify_search(self) -> bool:
        """Check if track has minimum required information for Spotify searching."""
        return bool(self.title)

    @property
    def is_valid_for_youtube_search(self) -> bool:
        """Check if track has minimum required information for YouTube searching."""
        return bool(self.title and self.artist)  # Require artist and title

    @property
    def has_spotify_url(self) -> bool:
        """Check if the track has a Spotify URL."""
        return bool(self.url)

    @property
    def has_youtube_url(self) -> bool:
        """Check if the track has a YouTube URL."""
        return bool(self.youtube_url)


def spotify_connect() -> SpotifyConnection:
    """Connect to Spotify API and return a connection object."""
    connection = sp.Spotify(auth_manager=SpotifyOAuth(scope=SPOTIFY_API_SCOPE))

    try:
        user_info = connection.current_user()
        # Make sure we got valid user info
        if not user_info:
            print("No user info returned from Spotify API")
            return SpotifyConnection(connection=connection)

        # We know user_info is not None at this point
        return SpotifyConnection(
            connection=connection,
            userid=user_info.get("id", ""),
            username=user_info.get("display_name", ""),
        )
    except Exception as e:
        print(f"Error retrieving Spotify user info: {e}")
        return SpotifyConnection(connection=connection)


def spotify_check_playlist(
    connection: SpotifyConnection, playlistname: str, playlistid: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Find a playlist by name or ID."""
    try:
        playlists = connection.connection.current_user_playlists(limit=50)
        if not playlists or "items" not in playlists:
            print("No playlists found or unexpected API response format")
            return None

        for playlist in playlists["items"]:
            if playlist["name"] == playlistname:
                # Cast the playlist to ensure it's a Dict[str, Any]
                return cast(Dict[str, Any], playlist)
            if playlistid and playlist["id"] == playlistid:
                # Cast the playlist to ensure it's a Dict[str, Any]
                return cast(Dict[str, Any], playlist)
        return None
    except Exception as e:
        print(f"Error checking playlist: {e}")
        return None


def spotify_create_playlist(
    connection: SpotifyConnection, playlistname: str
) -> Optional[str]:
    """Create a new Spotify playlist."""
    if not connection.userid:
        print("Error: User ID is required to create a playlist")
        return None

    print(f"User: {connection.username} ({connection.userid})")

    try:
        # Cast the result to Dict to satisfy type checking
        playlist = cast(
            Dict[str, Any],
            connection.connection.user_playlist_create(
                connection.userid, playlistname, public=False
            ),
        )

        if not playlist or "id" not in playlist:
            print("Failed to create playlist or missing ID in response")
            return None

        playlistid = playlist["id"]
        print(f"Playlist id: {playlistid}")
        return playlistid
    except Exception as e:
        print(f"Error creating playlist: {e}")
        return None


def mp3_walk_directory(directory: str) -> Iterator[TrackInfo]:
    """Walk through a directory and yield TrackInfo objects for each MP3 file."""
    path = pathlib.Path(directory)
    for filepath in path.glob("**/*.mp3"):
        track_info = TrackInfo(filename=str(filepath))

        try:
            # Try to extract info from MP3 tags
            mp3 = eyed3.load(filepath)
            if mp3 and mp3.tag:
                track_info.artist = mp3.tag.artist
                track_info.album = mp3.tag.album
                track_info.title = mp3.tag.title
                print(f"===== {filepath} ======")
            else:
                # Fallback to filename parsing if no tags
                track_info = _parse_track_from_filename(filepath)

            if track_info.is_valid_for_spotify_search:
                yield track_info

        except Exception as e:
            print(f"Error processing {filepath}: {e}")
            # If both methods fail, skip this file
            pass


def _parse_track_from_filename(filepath: pathlib.Path) -> TrackInfo:
    """Parse track information from filename."""
    filename = str(filepath.stem).replace("_", " ")
    parts = filename.split("-")

    track = TrackInfo(filename=str(filepath))

    if len(parts) == TRACK_FORMAT_PARTS_4:  # TrackNo - Artist - Album - Name
        track.artist = parts[1].strip()
        track.album = parts[2].strip()
        track.title = parts[3].strip()
    elif len(parts) == TRACK_FORMAT_PARTS_3:  # Artist - Album - Name
        track.artist = parts[0].strip()
        track.album = parts[1].strip()
        track.title = parts[2].strip()
    elif len(parts) == TRACK_FORMAT_PARTS_2:  # Album - Name
        track.album = parts[0].strip()
        track.title = parts[1].strip()
    else:
        track.title = filename  # Use full filename as title

    return track


def list_chunks(lst: List, n: int) -> Iterator[List]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def get_playlist_tracks(sp_conn: sp.Spotify, playlist_id: str) -> List[TrackInfo]:
    """Fetch all tracks from a Spotify playlist."""
    tracks = []
    offset = 0
    print(f"Fetching tracks from playlist ID: {playlist_id}")
    while True:
        try:
            results = sp_conn.playlist_items(
                playlist_id,
                offset=offset,
                fields="items(track(id, name, artists(name), album(name, images)))",
                additional_types=["track"],
            )
            if not results:
                break
            items = results.get("items", [])
            if not items:
                break
            for item in items:
                track_data = item.get("track")
                if track_data:
                    track_info = TrackInfo(
                        spotify_id=track_data.get("id"),
                        title=track_data.get("name"),
                        artist=track_data["artists"][0]["name"]
                        if track_data.get("artists")
                        else None,
                        album=track_data["album"]["name"]
                        if track_data.get("album")
                        else None,
                        album_art_url=track_data["album"]["images"][0]["url"]
                        if track_data.get("album") and track_data["album"].get("images")
                        else None,
                    )
                    if track_info.is_valid_for_youtube_search:
                        tracks.append(track_info)
            offset += len(items)
            print(f"Fetched {len(tracks)} tracks...")
        except Exception as e:
            print(f"Error fetching playlist items (offset {offset}): {e}")
            break
    print(f"Finished fetching. Total valid tracks: {len(tracks)}")
    return tracks


def search_youtube(track: TrackInfo) -> Optional[str]:
    """Search YouTube for a track and return the video URL."""
    if not track.is_valid_for_youtube_search:
        return None

    query = track.search_query_youtube
    print(f"Searching YouTube for: '{query}'")
    try:
        # Limit to 1 result as we usually want the top hit
        results = VideosSearch(query, limit=1).result()
        if results and isinstance(results, dict) and "result" in results:
            result = results["result"]
            if result and isinstance(result, list) and len(result) > 0:
                video_url = result[0].get("link")
                if video_url:
                    print(f"  Found YouTube URL: {video_url}")
                    return video_url
        else:
            print(f"  No YouTube results found for '{query}'")
            return None
    except Exception as e:
        print(f"Error searching YouTube for '{query}': {e}")
        return None


def sanitize_filename(name: str) -> str:
    """Remove invalid characters for filenames."""
    # Remove characters not allowed in most filesystems
    name = re.sub(r'[<>:"/\\|?*\n\t]', "", name)
    # Replace multiple spaces with single space
    name = re.sub(r"\s+", " ", name).strip()
    return name


def add_metadata(mp3_path: str, track: TrackInfo):
    """Add ID3 metadata and album art to the MP3 file."""
    try:
        audio = EasyID3(mp3_path)
    except ID3NoHeaderError:
        # If no ID3 header exists, create one
        audio = ID3()
        audio.save(mp3_path)  # Save empty tags first
        audio = EasyID3(mp3_path)  # Reload as EasyID3

    if track.title:
        audio["title"] = track.title
    if track.artist:
        audio["artist"] = track.artist
    if track.album:
        audio["album"] = track.album
    audio.save()
    print(f"  Added basic metadata to {pathlib.Path(mp3_path).name}")

    # Add album art
    if track.album_art_url:
        try:
            response = requests.get(track.album_art_url, stream=True, timeout=10)
            response.raise_for_status()
            image_data = response.content

            audio_id3 = ID3(mp3_path)
            audio_id3.add(
                APIC(
                    encoding=3,  # UTF-8
                    mime="image/jpeg",  # Assume JPEG, common for web
                    type=3,  # 3 is for the cover image
                    desc="Cover",
                    data=image_data,
                )
            )
            audio_id3.save(v2_version=3)  # Save ID3v2.3 tags, widely compatible
            print(f"  Added album art to {pathlib.Path(mp3_path).name}")
        except requests.exceptions.RequestException as e:
            print(f"  Failed to download album art: {e}")
        except Exception as e:
            print(f"  Failed to add album art: {e}")


def download_track_from_youtube(track: TrackInfo, output_dir: pathlib.Path) -> bool:
    """Download a single track's audio from YouTube."""
    if not track.youtube_url:
        return False

    # Create a sanitized filename
    filename_base = sanitize_filename(f"{track.artist} - {track.title}")
    output_template = output_dir / f"{filename_base}.%(ext)s"
    mp3_path = output_dir / f"{filename_base}.mp3"

    # Avoid re-downloading if file exists
    if mp3_path.exists():
        print(f"  Skipping download, file exists: {mp3_path.name}")
        # Optionally, re-add metadata if needed?
        # add_metadata(str(mp3_path), track)
        return True

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_template),
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",  # Standard MP3 quality
            }
        ],
        # --- Embed metadata and thumbnail using yt-dlp ---
        "writethumbnail": True,  # Download thumbnail
        "postprocessor_args": {
            "ffmpeg": [
                "-metadata",
                f"title={track.title}",
                "-metadata",
                f"artist={track.artist}",
                "-metadata",
                f"album={track.album or 'Unknown Album'}",
            ]
        },
        "embedthumbnail": True,  # Embed thumbnail as album art
        "addmetadata": True,  # Add basic metadata
    }

    print(f"Downloading: {track.artist} - {track.title}")
    try:
        # --- Ignore type checking for this line ---
        ydl = YoutubeDL(ydl_opts)  # type: ignore[operator]
        ydl.download([track.youtube_url])

        # Check if the MP3 file was created
        if mp3_path.exists():
            print(f"  Successfully downloaded and converted: {mp3_path.name}")
            # yt-dlp handles metadata/art embedding, but we can call our function
            # for potentially more control or different fields if needed.
            # add_metadata(str(mp3_path), track) # Maybe redundant if yt-dlp worked
            return True
        else:
            print(f"  Download finished, but MP3 file not found: {mp3_path.name}")
            # Check for intermediate files (.webm, .m4a etc.) that might not
            # have converted properly.
            return False
    except Exception as e:
        print(f"  Error downloading '{track.title}': {e}")
        # Clean up potential partial downloads?
        # Example: glob for filename_base.* and remove
        return False


def run_sync_to_spotify(args: Namespace, connection: SpotifyConnection) -> int:
    """Runs the MP3s -> Spotify Playlist sync."""
    print("Starting sync: Local MP3s -> Spotify Playlist")
    # Find tracks and search for them on Spotify
    n_mp3 = 0
    tracks_found_on_spotify: List[TrackInfo] = []

    for track in mp3_walk_directory(args.directory):
        n_mp3 += 1

        if not track.is_valid_for_spotify_search:
            continue

        try:
            print(f"Searching Spotify for: {track.search_query_spotify}")
            results = connection.connection.search(
                q=track.search_query_spotify, type="track", limit=1
            )  # Limit to 1
            if (
                results
                and isinstance(results, dict)
                and "tracks" in results
                and results["tracks"]
                and "items" in results["tracks"]
                and results["tracks"]["items"]
            ):
                spotify_track = results["tracks"]["items"][0]
                track.url = spotify_track["external_urls"]["spotify"]
                track.spotify_id = spotify_track["id"]
                print(f"  Found: {track.url}")
                tracks_found_on_spotify.append(track)
            else:
                print("  Not found on Spotify.")
        except Exception as e:
            print(f"  Error searching Spotify for track {track.title}: {e}")
            continue

    # Get or create the playlist
    playlist = spotify_check_playlist(connection, playlistname=args.playlist)
    if not playlist:
        try:
            if not connection.userid:
                print("Error: User ID is required to create a playlist")
                return 1
            print(f"Creating new playlist: {args.playlist}")
            playlist = cast(
                Dict[str, Any],
                connection.connection.user_playlist_create(
                    connection.userid, args.playlist, public=False
                ),
            )
        except Exception as e:
            print(f"Error creating playlist: {e}")
            return 1

    if not playlist or "id" not in playlist:
        print("Failed to get or create playlist")
        return 1

    playlistid = playlist["id"]
    print(f"Using playlist ID: {playlistid}")

    # Add tracks to the playlist in chunks
    tracks_to_add_urls = [t.url for t in tracks_found_on_spotify if t.has_spotify_url]
    if not tracks_to_add_urls:
        print("No valid Spotify tracks found to add.")
        return 0

    print(f"Adding {len(tracks_to_add_urls)} tracks to playlist...")
    for chunk_urls in list_chunks(tracks_to_add_urls, CHUNK_SIZE):
        try:
            connection.connection.playlist_add_items(
                playlistid, chunk_urls
            )  # Use playlist_add_items
            print(f"  Added chunk of {len(chunk_urls)} tracks.")
        except Exception as e:
            print(f"  Error adding tracks chunk to playlist: {e}")
            # Decide whether to continue or stop on error
            # continue

    print(
        f"Sync finished. MP3s scanned: {n_mp3} | "
        f"Tracks added to Spotify: {len(tracks_to_add_urls)}"
    )
    return 0  # Success


def run_sync_from_spotify(args: Namespace, connection: SpotifyConnection) -> int:
    """Runs the Spotify Playlist -> Local MP3s sync."""
    print("Starting sync: Spotify Playlist -> Local MP3s")

    if not args.playlist_id:
        print("Error: Spotify Playlist ID is required (--playlist-id)")
        return 1

    output_dir = pathlib.Path(args.directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir.resolve()}")

    # 1. Get tracks from Spotify playlist
    spotify_tracks = get_playlist_tracks(connection.connection, args.playlist_id)
    if not spotify_tracks:
        print("No tracks found in the specified playlist or failed to fetch.")
        return 1

    # 2. Search YouTube for each track (can be done in parallel)
    print(f"\nSearching YouTube for {len(spotify_tracks)} tracks...")
    tracks_with_youtube_url: List[TrackInfo] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_track = {
            executor.submit(search_youtube, track): track for track in spotify_tracks
        }
        for future in as_completed(future_to_track):
            track = future_to_track[future]
            try:
                youtube_url = future.result()
                if youtube_url:
                    track.youtube_url = youtube_url
                    tracks_with_youtube_url.append(track)
            except Exception as exc:
                # Find which track caused the error if possible
                # (more complex tracking needed for exact track)
                print(f"A download generated an exception: {exc}")

    if not tracks_with_youtube_url:
        print("No YouTube URLs found for any tracks.")
        return 1

    # 3. Download and convert tracks (can be done in parallel)
    print(f"\nDownloading {len(tracks_with_youtube_url)} tracks...")
    download_futures: List[Any] = []
    successful_downloads = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit download tasks
        for track in tracks_with_youtube_url:
            download_futures.append(
                executor.submit(download_track_from_youtube, track, output_dir)
            )

        # Process completed downloads
        for future in as_completed(download_futures):
            try:
                success = future.result()
                if success:
                    successful_downloads += 1
            except Exception as exc:
                # Find which track caused the error if possible
                # (more complex tracking needed for exact track)
                print(f"A download generated an exception: {exc}")

    print(
        f"\nSync finished. Tracks processed: {len(spotify_tracks)} | "
        f"Downloads attempted: {len(tracks_with_youtube_url)} | "
        f"Successful downloads: {successful_downloads}"
    )
    return 0  # Success


def setup() -> Namespace:
    """Parse command-line arguments including subparsers."""
    parser = ArgumentParser(
        description="Sync music between local MP3 files and Spotify playlists."
    )
    parser.add_argument(
        "--env-file",
        dest="env_file",
        action="store",
        required=False,
        type=str,
        help="Path to .env file (defaults to .env in current directory)",
    )

    # Global Spotify Auth Arguments (apply to all subcommands)
    auth_group = parser.add_argument_group("Spotify Authentication")
    auth_group.add_argument(
        "--oauthclientid",
        dest="clientid",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_CLIENT_ID"),
        help="OAuth2 Client Id (or use SPOTIPY_CLIENT_ID env var)",
    )
    auth_group.add_argument(
        "--oauthclientsecret",
        dest="clientsecret",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_CLIENT_SECRET"),
        help="OAuth2 Secret (or use SPOTIPY_CLIENT_SECRET env var)",
    )
    auth_group.add_argument(
        "--oauthredirecturi",
        dest="redirecturi",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_REDIRECT_URI"),
        help="OAuth2 Redirect URI (or use SPOTIPY_REDIRECT_URI env var)",
    )

    subparsers = parser.add_subparsers(
        dest="command", help="Choose sync direction", required=True
    )

    # --- Renamed Subparser: MP3s -> Spotify ---
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
        default="mp3/",
        help="Directory containing MP3 files to scan",
    )
    parser_to_spotify.add_argument(
        "--playlist",
        dest="playlist",
        action="store",
        required=False,
        type=str,
        default="MP3ify",
        help="Name of the Spotify playlist to create/update",
    )

    # --- Renamed Subparser: Spotify -> MP3s ---
    parser_from_spotify = subparsers.add_parser(
        "from-spotify", help="Download tracks from a Spotify playlist to local MP3s"
    )
    parser_from_spotify.add_argument(
        "--playlist-id",
        dest="playlist_id",
        action="store",
        required=True,
        type=str,
        help="Spotify Playlist ID to download from",
    )
    parser_from_spotify.add_argument(
        "--directory", "-d", dest="directory", action="store", required=False, type=str,
        default="spotify_downloads/", help="Directory to save downloaded MP3 files",
    )

    args = parser.parse_args()

    # Load environment variables from specified .env file if provided
    # Do this *before* setting variables from args
    env_file_path_str = args.env_file if args.env_file else ".env"
    env_file_path = pathlib.Path(env_file_path_str) # Use pathlib
    if env_file_path.is_file(): # Use pathlib's is_file()
        if load_dotenv(dotenv_path=env_file_path): # Specify path explicitly
            print(f"Loaded environment variables from {env_file_path}")
    elif args.env_file: # Only warn if a specific file was requested but not found
        print(f"Warning: Env file {args.env_file} not found")

    # Set environment variables if provided in arguments
    # (overrides .env and existing env vars)
    if args.clientid:
        os.environ["SPOTIPY_CLIENT_ID"] = args.clientid
    if args.clientsecret:
        os.environ["SPOTIPY_CLIENT_SECRET"] = args.clientsecret
    if args.redirecturi:
        os.environ["SPOTIPY_REDIRECT_URI"] = args.redirecturi

    # Basic validation of required env vars AFTER loading/args
    if not (
        os.environ.get("SPOTIPY_CLIENT_ID")
        and os.environ.get("SPOTIPY_CLIENT_SECRET")
        and os.environ.get("SPOTIPY_REDIRECT_URI")
    ):
        parser.error(
            "Missing Spotify credentials. Provide via arguments, environment "
            "variables (SPOTIPY_CLIENT_ID, etc.), or a .env file."
        )

    return args


def main_dispatcher(args: Namespace) -> int:
    """Main application dispatcher based on command."""
    # Connect to Spotify (needed for both commands)
    connection = spotify_connect()

    # Verify we have user_id if needed (playlist creation/adding needs it)
    if not connection.userid and args.command == "to-spotify":
        print(
            "Error: Could not retrieve Spotify user information required "
            "for to-spotify."
        )
        return 1
    # sync-from-spotify might only need the connection object itself for some ops
    # but checking playlists/getting track details likely still needs user auth.

    if args.command == "to-spotify":
        return run_sync_to_spotify(args, connection)
    elif args.command == "from-spotify":
        return run_sync_from_spotify(args, connection)
    else:
        print(f"Error: Unknown command '{args.command}'")
        return 1  # Should not happen if subparsers are required


if __name__ == "__main__":
    parsed_args = setup()
    sys.exit(main_dispatcher(parsed_args))

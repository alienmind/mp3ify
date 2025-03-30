import os
import pathlib
import sys
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, cast

import eyed3
import spotipy as sp
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv  # New import for .env support

# Load environment variables from .env file if it exists
load_dotenv()

SPOTIFY_API_SCOPE = "user-library-read,playlist-read-private,playlist-modify-private"
CHUNK_SIZE = 100

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
    url: Optional[str] = None  # Added this field that was missing but used later

    @property
    def search_query(self) -> str:
        """Generate a Spotify search query from track info."""
        if not self.artist or not self.title:
            return self.title or ""
        return f"artist:{self.artist} {self.title}"

    @property
    def is_valid(self) -> bool:
        """Check if track has minimum required information for searching."""
        return bool(self.title)

    @property
    def has_url(self) -> bool:
        """Check if the track has a Spotify URL."""
        return bool(self.url)


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
                return playlist
            if playlistid and playlist["id"] == playlistid:
                return playlist
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

            if track_info.is_valid:
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


def main(args: Namespace) -> int:
    """Main application function."""
    # Connect to Spotify
    connection = spotify_connect()

    # Verify we have user_id
    if not connection.userid:
        print("Error: Could not retrieve Spotify user information")
        return 1

    # Find tracks and search for them on Spotify
    n_mp3 = 0
    tracks_found: List[TrackInfo] = []

    for track in mp3_walk_directory(args.directory):
        n_mp3 += 1

        # Skip tracks that don't have enough info to search
        if not track.is_valid:
            continue

        # Search for the track on Spotify
        try:
            results = connection.connection.search(q=track.search_query, type="track")
            # Check all levels to avoid None access
            if (
                results
                and isinstance(results, dict)
                and "tracks" in results
                and results["tracks"]
                and "items" in results["tracks"]
                and results["tracks"]["items"]
            ):
                # Get the first result's URL
                track.url = results["tracks"]["items"][0]["external_urls"]["spotify"]
                tracks_found.append(track)
        except Exception as e:
            print(f"Error searching for track {track.title}: {e}")
            continue

    # Get or create the playlist
    playlist = spotify_check_playlist(connection, playlistname=args.playlist)
    if not playlist:
        try:
            # Create new playlist
            if not connection.userid:
                print("Error: User ID is required to create a playlist")
                return 1

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
        return 1  # Error code

    playlistid = playlist["id"]  # Access id directly since we know playlist exists now

    # Add tracks to the playlist in chunks
    for chunk in list_chunks(tracks_found, CHUNK_SIZE):
        # Get just the URLs from the tracks
        track_urls = [t.url for t in chunk if t.has_url]

        # Skip empty chunks
        if not track_urls:
            continue

        # Add tracks to the playlist
        try:
            connection.connection.user_playlist_add_tracks(
                connection.userid, playlistid, track_urls
            )
        except Exception as e:
            print(f"Error adding tracks to playlist: {e}")
            continue

    print(f"MP3s scanned: {n_mp3} | Tracks added to Spotify: {len(tracks_found)}")
    return 0  # Success


def setup() -> Namespace:
    """Parse command-line arguments and set up environment variables."""
    parser = ArgumentParser()
    parser.add_argument(
        "--oauthclientid",
        dest="clientid",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_CLIENT_ID"),
        help="OAuth2 Client Id - defaults to SPOTIPY_CLIENT_ID env var",
    )
    parser.add_argument(
        "--oauthclientsecret",
        dest="clientsecret",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_CLIENT_SECRET"),
        help="OAuth2 Secret - defaults to SPOTIPY_CLIENT_SECRET env var",
    )
    parser.add_argument(
        "--oauthredirecturi",
        dest="redirecturi",
        action="store",
        required=False,
        type=str,
        default=os.environ.get("SPOTIPY_REDIRECT_URI"),
        help="OAuth2 Redirect URI - defaults to SPOTIPY_REDIRECT_URI env var",
    )
    parser.add_argument(
        "--playlist",
        dest="playlist",
        action="store",
        required=False,
        type=str,
        default="MP3ify",
        help="Playlist name - will update if existing",
    )
    parser.add_argument(
        "--directory",
        "-d",
        dest="directory",
        action="store",
        required=False,
        type=str,
        default="mp3/",
        help="Directory to traverse recursively",
    )
    parser.add_argument(
        "--env-file",
        dest="env_file",
        action="store",
        required=False,
        type=str,
        help="Path to .env file (defaults to .env in current directory)",
    )

    args = parser.parse_args()
    
    # Load environment variables from specified .env file if provided
    if args.env_file:
        if os.path.isfile(args.env_file):
            load_dotenv(args.env_file)
            print(f"Loaded environment variables from {args.env_file}")
        else:
            print(f"Warning: Env file {args.env_file} not found")

    # Set environment variables if provided in arguments
    if args.clientid:
        os.environ["SPOTIPY_CLIENT_ID"] = args.clientid
    if args.clientsecret:
        os.environ["SPOTIPY_CLIENT_SECRET"] = args.clientsecret
    if args.redirecturi:
        os.environ["SPOTIPY_REDIRECT_URI"] = args.redirecturi

    return args


if __name__ == "__main__":
    args = setup()
    sys.exit(main(args))

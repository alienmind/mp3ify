import pathlib
from unittest.mock import MagicMock, patch

import pytest

from mp3ify import SpotifyConnection, TrackInfo


@pytest.fixture
def mock_mp3_folder():
    """Create a temporary folder structure for test MP3 files."""
    test_dir = pathlib.Path("tests/mp3")
    test_dir.mkdir(exist_ok=True, parents=True)

    # Return the path to the test directory
    return test_dir


@pytest.fixture
def mock_eyed3():
    """Mock the eyed3 library to simulate MP3 files."""
    with patch("mp3ify.eyed3") as mock:
        # Configure mock MP3 files with metadata
        mock.load.side_effect = lambda path: create_mock_mp3(pathlib.Path(path).name)
        yield mock


def create_mock_mp3(filename):
    """Create a mock MP3 file with metadata based on the filename."""
    mp3 = MagicMock()

    # Set default tag values
    mp3.tag = MagicMock()
    mp3.tag.artist = None
    mp3.tag.album = None
    mp3.tag.title = None

    # Use filename patterns to set metadata
    if filename == "track1.mp3":
        mp3.tag.artist = "Test Artist 1"
        mp3.tag.album = "Test Album 1"
        mp3.tag.title = "Test Track 1"
    elif filename == "track2.mp3":
        mp3.tag.artist = "Test Artist 2"
        mp3.tag.album = "Test Album a"
        mp3.tag.title = "Test Track 2"
    elif filename == "track3.mp3":
        mp3.tag.artist = "Test Artist 1"  # Same artist as track1
        mp3.tag.album = "Test Album 1"  # Same album as track1
        mp3.tag.title = "Test Track 3"

    return mp3


@pytest.fixture
def mock_spotify():
    """Mock the Spotify API client."""
    with patch("mp3ify.sp.Spotify") as mock:
        # Create a mock Spotify connection
        spotify = MagicMock()
        mock.return_value = spotify

        # Mock user info
        user_info = {"id": "test_user_123", "display_name": "Test User"}
        spotify.current_user.return_value = user_info

        # Mock playlist operations
        spotify.current_user_playlists.return_value = {
            "items": [{"name": "Existing Playlist", "id": "playlist_999"}]
        }
        spotify.user_playlist_create.return_value = {
            "id": "new_playlist_123",
            "name": "MP3ify",
        }

        # Mock track search
        def mock_search(q, type):
            if "Test Track 1" in q:
                return {
                    "tracks": {
                        "items": [
                            {
                                "name": "Test Track 1",
                                "external_urls": {"spotify": "spotify:track:111"},
                            }
                        ]
                    }
                }
            elif "Test Track 2" in q:
                return {
                    "tracks": {
                        "items": [
                            {
                                "name": "Test Track 2",
                                "external_urls": {"spotify": "spotify:track:222"},
                            }
                        ]
                    }
                }
            elif "Test Track 3" in q:
                return {
                    "tracks": {
                        "items": [
                            {
                                "name": "Test Track 3",
                                "external_urls": {"spotify": "spotify:track:333"},
                            }
                        ]
                    }
                }
            else:
                return {"tracks": {"items": []}}

        spotify.search.side_effect = mock_search

        # Playlist track addition doesn't need to return anything specific
        spotify.user_playlist_add_tracks.return_value = None

        yield spotify


@pytest.fixture
def mock_spotify_connection(mock_spotify):
    """Create a mock SpotifyConnection object."""
    return SpotifyConnection(
        connection=mock_spotify, userid="test_user_123", username="Test User"
    )


@pytest.fixture
def sample_tracks():
    """Return a list of sample TrackInfo objects."""
    return [
        TrackInfo(
            filename="track1.mp3",
            artist="Test Artist 1",
            album="Test Album 1",
            title="Test Track 1",
            url=None,  # URL will be populated during Spotify search
        ),
        TrackInfo(
            filename="track2.mp3",
            artist="Test Artist 2",
            album="Test Album 2",
            title="Test Track 2",
            url=None,
        ),
        TrackInfo(
            filename="track3.mp3",
            artist="Test Artist 1",
            album="Test Album 1",
            title="Test Track 3",
            url=None,
        ),
    ]

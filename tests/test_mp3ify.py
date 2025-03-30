import os
import pathlib
from unittest.mock import patch, MagicMock
from argparse import Namespace

import pytest

from mp3ify import (
    TrackInfo, 
    SpotifyConnection,
    spotify_connect,
    spotify_check_playlist,
    mp3_walk_directory,
    _parse_track_from_filename,
    list_chunks,
    main,
    setup
)


class TestTrackInfo:
    """Tests for the TrackInfo dataclass and its methods."""
    
    def test_search_query_with_artist_and_title(self):
        """Test generating a search query with both artist and title."""
        track = TrackInfo(artist="Test Artist", title="Test Track")
        assert track.search_query == "artist:Test Artist Test Track"
    
    def test_search_query_with_only_title(self):
        """Test generating a search query with only title."""
        track = TrackInfo(title="Test Track")
        assert track.search_query == "Test Track"
    
    def test_search_query_with_no_data(self):
        """Test generating a search query with no data."""
        track = TrackInfo()
        assert track.search_query == ""
    
    def test_is_valid(self):
        """Test the is_valid property."""
        valid_track = TrackInfo(title="Test Track")
        invalid_track = TrackInfo()
        assert valid_track.is_valid is True
        assert invalid_track.is_valid is False
    
    def test_has_url(self):
        """Test the has_url property."""
        track_with_url = TrackInfo(url="spotify:track:123")
        track_without_url = TrackInfo()
        assert track_with_url.has_url is True
        assert track_without_url.has_url is False


class TestSpotifyFunctions:
    """Tests for Spotify-related functions."""
    
    def test_spotify_connect(self, mock_spotify):
        """Test connecting to Spotify API."""
        connection = spotify_connect()
        assert connection.userid == "test_user_123"
        assert connection.username == "Test User"
        assert connection.connection is not None
    
    def test_spotify_check_playlist_existing(self, mock_spotify_connection):
        """Test finding an existing playlist."""
        playlist = spotify_check_playlist(
            mock_spotify_connection, 
            playlistname="Existing Playlist"
        )
        assert playlist is not None
        assert playlist["name"] == "Existing Playlist"
        assert playlist["id"] == "playlist_999"
    
    def test_spotify_check_playlist_not_found(self, mock_spotify_connection):
        """Test when playlist is not found."""
        playlist = spotify_check_playlist(
            mock_spotify_connection, 
            playlistname="Non-Existent Playlist"
        )
        assert playlist is None


class TestMP3Functions:
    """Tests for MP3-related functions."""
    
    def test_parse_track_from_filename_format4(self):
        """Test parsing a filename with 4 parts (TrackNo - Artist - Album - Name)."""
        path = pathlib.Path("01 - Test Artist - Test Album - Test Track.mp3")
        track = _parse_track_from_filename(path)
        assert track.artist == "Test Artist"
        assert track.album == "Test Album"
        assert track.title == "Test Track"
    
    def test_parse_track_from_filename_format3(self):
        """Test parsing a filename with 3 parts (Artist - Album - Name)."""
        path = pathlib.Path("Test Artist - Test Album - Test Track.mp3")
        track = _parse_track_from_filename(path)
        assert track.artist == "Test Artist"
        assert track.album == "Test Album"
        assert track.title == "Test Track"
    
    def test_parse_track_from_filename_format2(self):
        """Test parsing a filename with 2 parts (Album - Name)."""
        path = pathlib.Path("Test Album - Test Track.mp3")
        track = _parse_track_from_filename(path)
        assert track.album == "Test Album"
        assert track.title == "Test Track"
        assert track.artist is None
    
    def test_parse_track_from_filename_unknown(self):
        """Test parsing a filename with unknown format."""
        path = pathlib.Path("some_random_file.mp3")
        track = _parse_track_from_filename(path)
        assert track.title == "some_random_file"
        assert track.artist is None
        assert track.album is None
    
    def test_mp3_walk_directory(self, mock_mp3_folder, mock_eyed3):
        """Test walking through a directory of MP3 files."""
        # Create some test files in the mock folder
        (mock_mp3_folder / "track1.mp3").touch()
        (mock_mp3_folder / "track2.mp3").touch()
        (mock_mp3_folder / "track3.mp3").touch()
        
        tracks = list(mp3_walk_directory(str(mock_mp3_folder)))
        
        assert len(tracks) == 3
        assert all(isinstance(t, TrackInfo) for t in tracks)
        # Check if we have the expected track titles
        titles = {t.title for t in tracks}
        assert "Test Track 1" in titles
        assert "Test Track 2" in titles
        assert "Test Track 3" in titles


class TestUtilityFunctions:
    """Tests for utility functions."""
    
    def test_list_chunks(self):
        """Test chunking a list."""
        items = list(range(10))
        chunks = list(list_chunks(items, 3))
        
        assert len(chunks) == 4
        assert chunks[0] == [0, 1, 2]
        assert chunks[1] == [3, 4, 5]
        assert chunks[2] == [6, 7, 8]
        assert chunks[3] == [9]


class TestMainFunction:
    """Tests for the main function."""
    
    def test_main_success(self, mock_mp3_folder, mock_eyed3, mock_spotify):
        """Test successful execution of the main function."""
        # Create some test files in the mock folder
        (mock_mp3_folder / "track1.mp3").touch()
        (mock_mp3_folder / "track2.mp3").touch()
        (mock_mp3_folder / "track3.mp3").touch()
        
        args = Namespace(
            clientid="test_client_id",
            clientsecret="test_client_secret",
            redirecturi="http://localhost:8080",
            playlist="MP3ify",
            directory=str(mock_mp3_folder)
        )
        
        with patch('mp3ify.spotify_connect') as mock_connect:
            mock_connect.return_value = SpotifyConnection(
                connection=mock_spotify,
                userid="test_user_123",
                username="Test User"
            )
            
            result = main(args)
            
            assert result == 0  # Success
            
            # Check that tracks were added to the playlist
            mock_spotify.user_playlist_add_tracks.assert_called() 
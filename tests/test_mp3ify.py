import pathlib
from argparse import Namespace
from unittest.mock import patch

from mp3ify import (
    SpotifyConnection,
    TrackInfo,
    _parse_track_from_filename,
    list_chunks,
    main_dispatcher,
    mp3_walk_directory,
    spotify_check_playlist,
    spotify_connect,
)


class TestTrackInfo:
    """Tests for the TrackInfo dataclass and its methods."""

    def test_search_query_with_artist_and_title(self):
        """Test generating a search query with both artist and title."""
        track = TrackInfo(artist="Test Artist", title="Test Track")
        expected = "artist:Test Artist track:Test Track"
        assert track.search_query_spotify == expected

    def test_search_query_with_only_title(self):
        """Test generating a search query with only title."""
        track = TrackInfo(title="Test Track")
        assert track.search_query_spotify == "Test Track"

    def test_search_query_with_no_data(self):
        """Test generating a search query with no data."""
        track = TrackInfo()
        assert track.search_query_spotify == ""

    def test_is_valid(self):
        """Test the is_valid property (for Spotify search)."""
        valid_track = TrackInfo(title="Test Track")
        invalid_track = TrackInfo()
        assert valid_track.is_valid_for_spotify_search is True
        assert invalid_track.is_valid_for_spotify_search is False

    def test_has_url(self):
        """Test the has_url property (for Spotify URL)."""
        track_with_url = TrackInfo(url="spotify:track:123")
        track_without_url = TrackInfo()
        assert track_with_url.has_spotify_url is True
        assert track_without_url.has_spotify_url is False


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
            mock_spotify_connection, playlistname="Existing Playlist"
        )
        assert playlist is not None
        assert playlist["name"] == "Existing Playlist"
        assert playlist["id"] == "playlist_999"

    def test_spotify_check_playlist_not_found(self, mock_spotify_connection):
        """Test when playlist is not found."""
        playlist = spotify_check_playlist(
            mock_spotify_connection, playlistname="Non-Existent Playlist"
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
        expected_files = ["track1.mp3", "track2.mp3", "track3.mp3"]
        for fname in expected_files:
            (mock_mp3_folder / fname).touch()

        tracks = list(mp3_walk_directory(str(mock_mp3_folder)))

        # Check count against the number of files created
        assert len(tracks) == len(expected_files)
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
        num_items = len(items)
        chunk_size = 3
        chunks = list(list_chunks(items, chunk_size))

        # Expected number of chunks = ceil(num_items / chunk_size)
        expected_num_chunks = (num_items + chunk_size - 1) // chunk_size
        assert len(chunks) == expected_num_chunks # = 4 in this case
        assert chunks[0] == [0, 1, 2]
        assert chunks[1] == [3, 4, 5]
        assert chunks[2] == [6, 7, 8]
        assert chunks[3] == [9]


class TestMainFunction:
    """Tests for the main dispatcher function and subcommands."""

    def test_sync_to_spotify_success(self, mock_mp3_folder, mock_eyed3, mock_spotify):
        """Test successful execution of the to-spotify command."""
        # Create some test files
        test_files = ["track1.mp3", "track2.mp3", "track3.mp3"]
        for fname in test_files:
            (mock_mp3_folder / fname).touch()

        args = Namespace(
            command="to-spotify", # Specify the command
            clientid="test_client_id",
            clientsecret="test_client_secret",
            redirecturi="http://127.0.0.1:8888",
            playlist="MP3ify",
            directory=str(mock_mp3_folder),
            env_file=None # Assume no specific env file for test
        )

        with patch('mp3ify.spotify_connect') as mock_connect:
            mock_connection = SpotifyConnection(
                connection=mock_spotify,
                userid="test_user_123",
                username="Test User"
            )
            mock_connect.return_value = mock_connection

            # Mock check_playlist to return None (so create is called)
            with patch('mp3ify.spotify_check_playlist', return_value=None):
                # Mock create_playlist
                with patch(
                    'mp3ify.spotify_create_playlist', 
                    return_value="new_playlist_id"
                ):
                    result = main_dispatcher(args)

                    assert result == 0  # Success

                    # Check create_playlist was called
                    mock_spotify.user_playlist_create.assert_called_once_with(
                        mock_connection.userid, args.playlist, public=False
                    )

                    # Check that tracks were added to the playlist
                    mock_spotify.playlist_add_items.assert_called() # Check if called
                    # More specific check on added items if needed

    # Add a similar test for the 'from-spotify' command
    def test_sync_from_spotify_success(self, mock_mp3_folder, mock_spotify):
        """Test successful execution of the from-spotify command."""
        # We don't need eyed3 mock here, but need mock downloaders

        output_dir = mock_mp3_folder # Use the temp folder for output

        args = Namespace(
            command="from-spotify", # Specify the command
            clientid="test_client_id",
            clientsecret="test_client_secret",
            redirecturi="http://127.0.0.1:8888",
            playlist_id="test_playlist_id",
            output_dir=str(output_dir),
            env_file=None
        )

        # Mock the functions called by run_sync_from_spotify
        with patch('mp3ify.spotify_connect') as mock_connect, \
             patch('mp3ify.get_playlist_tracks') as mock_get_tracks, \
             patch('mp3ify.search_youtube') as mock_search_yt, \
             patch('mp3ify.download_track_from_youtube') as mock_download:

            # Setup return values for mocks
            mock_connect.return_value = SpotifyConnection(
                connection=mock_spotify, userid="test_user_123", username="Test User"
            )
            # Simulate getting 2 tracks from Spotify
            mock_spotify_tracks = [
                TrackInfo(
                    title="Track A", artist="Artist X", 
                    album="Album Z", spotify_id="sp1"
                ),
                TrackInfo(
                    title="Track B", artist="Artist Y", 
                    album="Album W", spotify_id="sp2"
                )
            ]
            mock_get_tracks.return_value = mock_spotify_tracks

            # Simulate finding YouTube URLs
            def search_side_effect(track):
                if track.spotify_id == "sp1": 
                    return "youtube.com/url1"
                if track.spotify_id == "sp2": 
                    return "youtube.com/url2"
                return None
            mock_search_yt.side_effect = search_side_effect

            # Simulate successful downloads
            mock_download.return_value = True

            result = main_dispatcher(args)

            assert result == 0 # Success
            mock_get_tracks.assert_called_once_with(mock_spotify, args.playlist_id)
            assert mock_search_yt.call_count == len(mock_spotify_tracks)
            # Assuming both tracks found YT urls and download was attempted
            assert mock_download.call_count == len(mock_spotify_tracks)

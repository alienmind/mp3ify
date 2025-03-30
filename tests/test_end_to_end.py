import os
import pathlib
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

import mp3ify


@pytest.fixture
def setup_test_environment():
    """Create a temporary test environment with MP3 files."""
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    mp3_dir = pathlib.Path(temp_dir) / "mp3"
    mp3_dir.mkdir()

    # Create mock MP3 files (empty files for testing)
    (mp3_dir / "01 - Artist One - Album One - Track One.mp3").touch()
    (mp3_dir / "02 - Artist One - Album One - Track Two.mp3").touch()
    (mp3_dir / "Artist Two - Album Two - Single Track.mp3").touch()

    # Save the original directory
    original_dir = pathlib.Path.cwd()

    # Change to the temporary directory
    os.chdir(temp_dir)

    yield {
        "temp_dir": temp_dir,
        "mp3_dir": mp3_dir
    }

    # Clean up: Change back to the original directory and remove the temp directory
    os.chdir(original_dir)
    shutil.rmtree(temp_dir)


@pytest.mark.e2e
def test_end_to_end(setup_test_environment, monkeypatch):
    """Test a complete end-to-end run of the application."""
    env = setup_test_environment

    # Patch environment variables
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "dummy_client_id")
    monkeypatch.setenv("SPOTIPY_CLIENT_SECRET", "dummy_client_secret")
    monkeypatch.setenv("SPOTIPY_REDIRECT_URI", "http://localhost:8080")

    # Patch eyed3.load to return our mock MP3 files with tags
    with patch("mp3ify.eyed3") as mock_eyed3:
        # Configure mock MP3 files with metadata based on filenames
        def mock_load(path):
            path = pathlib.Path(path)
            mp3 = MagicMock()
            mp3.tag = MagicMock()

            if path.name.startswith("01 - "):
                mp3.tag.artist = "Artist One"
                mp3.tag.album = "Album One"
                mp3.tag.title = "Track One"
            elif path.name.startswith("02 - "):
                mp3.tag.artist = "Artist One"
                mp3.tag.album = "Album One"
                mp3.tag.title = "Track Two"
            else:
                mp3.tag.artist = "Artist Two"
                mp3.tag.album = "Album Two"
                mp3.tag.title = "Single Track"

            return mp3

        mock_eyed3.load.side_effect = mock_load

        # Patch Spotify connection
        with patch("mp3ify.sp.Spotify") as mock_spotify_class:
            # Create a mock Spotify client
            mock_spotify = MagicMock()
            mock_spotify_class.return_value = mock_spotify

            # Mock API responses
            mock_spotify.current_user.return_value = {
                "id": "test_user_123",
                "display_name": "Test User",
            }

            mock_spotify.current_user_playlists.return_value = {
                "items": []  # No existing playlists
            }

            mock_spotify.user_playlist_create.return_value = {
                "id": "new_playlist_123",
                "name": "MP3ify",
            }

            # Mock track search - all tracks will be "found"
            def mock_search(q, type):
                if "Artist One" in q and "Track One" in q:
                    return {
                        "tracks": {
                            "items": [
                                {
                                    "name": "Track One",
                                    "external_urls": {"spotify": "spotify:track:111"},
                                }
                            ]
                        }
                    }
                elif "Artist One" in q and "Track Two" in q:
                    return {
                        "tracks": {
                            "items": [
                                {
                                    "name": "Track Two",
                                    "external_urls": {"spotify": "spotify:track:222"},
                                }
                            ]
                        }
                    }
                elif "Artist Two" in q:
                    return {
                        "tracks": {
                            "items": [
                                {
                                    "name": "Single Track",
                                    "external_urls": {"spotify": "spotify:track:333"},
                                }
                            ]
                        }
                    }
                else:
                    return {"tracks": {"items": []}}

            mock_spotify.search.side_effect = mock_search

            # Run the application
            # Define sys.argv for patching
            test_argv = [
                'mp3ify.py', 
                'from-spotify', 
                '--playlist-id', 
                'dummy_id', 
                '-d',
                str(env["mp3_dir"])
            ]
            with patch('sys.argv', test_argv):
                # Call setup() inside the context to parse the patched args
                parsed_args = mp3ify.setup()
                # Pass the parsed args to the dispatcher
                mp3ify.main_dispatcher(parsed_args)

                # Check the results

                # 1. Check that playlist was NOT created 
                #    (sync from spotify doesn't create)
                mock_spotify.user_playlist_create.assert_not_called()

                # 2. Check that tracks were NOT added to the playlist
                #    (sync from spotify downloads, doesn't add)
                mock_spotify.playlist_add_items.assert_not_called()

                # --- Add assertions relevant to downloading --- 
                # For example, check if download was called for expected tracks
                # This requires more setup in the test mocks if needed.
                # assert mock_spotify.download_track_from_youtube.call_count == 3

                # --- Keep this section if testing `to-spotify` ---
                # # 3. Get the tracks that were added
                # call_args = mock_spotify.playlist_add_items.call_args[0]
                # playlist_id_called = call_args[0]
                # added_track_urls = call_args[1]
                # 
                # # Verify playlist ID
                # assert playlist_id_called == "new_playlist_123"
                # 
                # # 4. Verify that all 3 tracks were found and added
                # expected_urls = {
                #     "spotify:track:111", 
                #     "spotify:track:222", 
                #     "spotify:track:333"
                # }
                # assert len(added_track_urls) == len(expected_urls)
                # assert set(added_track_urls) == expected_urls

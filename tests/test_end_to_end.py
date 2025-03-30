import os
import pathlib
import tempfile
from unittest.mock import patch, MagicMock
import shutil

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
    original_dir = os.getcwd()
    
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
    with patch('mp3ify.eyed3') as mock_eyed3:
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
        with patch('mp3ify.sp.Spotify') as mock_spotify_class:
            # Create a mock Spotify client
            mock_spotify = MagicMock()
            mock_spotify_class.return_value = mock_spotify
            
            # Mock API responses
            mock_spotify.current_user.return_value = {
                "id": "test_user_123",
                "display_name": "Test User"
            }
            
            mock_spotify.current_user_playlists.return_value = {
                "items": []  # No existing playlists
            }
            
            mock_spotify.user_playlist_create.return_value = {
                "id": "new_playlist_123",
                "name": "MP3ify"
            }
            
            # Mock track search - all tracks will be "found"
            def mock_search(q, type):
                if "Artist One" in q and "Track One" in q:
                    return {
                        "tracks": {
                            "items": [
                                {
                                    "name": "Track One",
                                    "external_urls": {"spotify": "spotify:track:111"}
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
                                    "external_urls": {"spotify": "spotify:track:222"}
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
                                    "external_urls": {"spotify": "spotify:track:333"}
                                }
                            ]
                        }
                    }
                else:
                    return {"tracks": {"items": []}}
                
            mock_spotify.search.side_effect = mock_search
            
            # Run the application
            with patch('sys.argv', ['mp3ify.py', '-d', str(env["mp3_dir"])]):
                mp3ify.main(mp3ify.setup())
                
                # Check the results
                
                # 1. Check that playlist was created
                mock_spotify.user_playlist_create.assert_called_once_with(
                    "test_user_123", "MP3ify", public=False
                )
                
                # 2. Check that tracks were added to the playlist
                # The tracks should be added in chunks, but with our small
                # test set they should be added in a single call
                mock_spotify.user_playlist_add_tracks.assert_called_once()
                
                # 3. Get the tracks that were added
                call_args = mock_spotify.user_playlist_add_tracks.call_args[0]
                added_track_urls = call_args[2]
                
                # 4. Verify that all 3 tracks were found and added
                assert len(added_track_urls) == 3
                assert "spotify:track:111" in added_track_urls
                assert "spotify:track:222" in added_track_urls
                assert "spotify:track:333" in added_track_urls 
# mp3ify - Spotify / Youtube / MP3 playlist portability tool

<p align="center">
  <img src="img/mp3ify-logo.png" alt="mp3ify Logo" width="200"/>
</p>

Sync music between local MP3 files and Spotify / Youtube playlists. Supports two-way synchronization: upload local MP3 metadata to Spotify, or download Spotify playlist tracks as MP3s via YouTube.

## Features

*   **Sync Local to Spotify (`sync-to-spotify`)**: Scan a local directory of MP3 files, find matching tracks on Spotify, and add them to a specified Spotify playlist.
*   **Sync Spotify to Local (`sync-from-spotify`)**: Fetch tracks from a Spotify playlist, search for corresponding audio on YouTube, download them as MP3 files, and apply metadata (title, artist, album, cover art).
*   **Download YouTube Playlist (`from-youtube`)**: Download audio from a YouTube playlist directly as MP3s.
*   Uses `.env` file, environment variables, or command-line arguments for Spotify API configuration.
*   Parallel downloads for faster Spotify-to-Local syncing.

## How it Works

*   **Sync Local MP3s to Spotify (`sync-to-spotify`)**:
    1.  Scans the specified directory for `.mp3` files.
    2.  Attempts to read metadata (artist, title, album) from each MP3 file using `eyed3`.
    3.  If metadata is missing, it tries to parse this information from the filename (assuming formats like `Artist - Album - Title.mp3`).
    4.  Constructs a search query for each valid track.
    5.  Uses the Spotify API (`spotipy`) to search for matching tracks.
    6.  If a match is found, its Spotify track URL is recorded.
    7.  Checks if the target Spotify playlist exists by name. If not, creates it.
    8.  Adds all found Spotify track URLs to the target playlist in chunks.

*   **Sync Spotify Playlist to Local MP3s (`sync-from-spotify`)**:
    1.  Fetches all track details (ID, name, artist, album, art URL) from the specified Spotify playlist ID using `spotipy`.
    2.  For each track, constructs a search query (e.g., "Artist Title Album audio").
    3.  Uses `youtubesearchpython` to search YouTube for the best matching video.
    4.  If a YouTube video is found, its URL is recorded.
    5.  Uses `yt-dlp` (which requires **FFmpeg**) to download the audio stream from the YouTube URL.
    6.  `yt-dlp` converts the audio to MP3 format and attempts to embed metadata (title, artist, album) and the video thumbnail as cover art directly during the download/conversion process.
    7.  Saves the resulting MP3 file to the specified output directory with a sanitized filename (e.g., `Artist - Title.mp3`).
    8.  **Limitation**: This process relies entirely on finding a suitable match on YouTube. If a track from the Spotify playlist isn't available on YouTube or the search doesn't find the correct match, that track cannot be downloaded.

*   **Download YouTube Playlist (`from-youtube`)**:
    1.  Takes a YouTube playlist URL as input.
    2.  Uses `yt-dlp` (which requires **FFmpeg**) to iterate through the playlist videos.
    3.  For each video, downloads the best audio stream.
    4.  Converts the audio to MP3 format.
    5.  Attempts to embed metadata extracted from YouTube (title, uploader, etc.) and the video thumbnail as cover art during the download/conversion process.
    6.  Saves the resulting MP3 file to the specified output directory using a sanitized filename format like `Index - Title.mp3`.
    7.  **Limitation**: Metadata quality depends entirely on what's available on YouTube for each video. Artist/Album information might be inaccurate or missing compared to Spotify.

## Prerequisites

*   Python >= 3.8
*   `uv` (Recommended, for environment/package management)
*   Spotify Account & API Credentials (see [Spotify API Setup](#spotify-api-setup))
*   **FFmpeg**: Required by `yt-dlp` for audio conversion. Install via your system's package manager:
    *   **Ubuntu/Debian**: `sudo apt update && sudo apt install ffmpeg`
    *   **macOS**: `brew install ffmpeg`
    *   **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) or use `choco install ffmpeg`. Ensure `ffmpeg.exe` is in your system's PATH.

## Spotify API Setup

1.  **Create a Spotify Developer Account**:
   - Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
   - Log in with your Spotify account or create one if needed

2.  **Create a New Application**:
   - Click "Create App"
   - Fill in the application details:
     - **App name**: `mp3ify` (or any name you prefer)
     - **App description**: A brief description of what the app does
     - **Redirect URI**: `http://127.0.0.1:8888` (must match the URI you use with the app)
     - Accept the terms and conditions
     - Click "Create"

3.  **Get Your API Credentials**:
   - On your app's dashboard, you'll see:
     - **Client ID**: Copy this value
     - **Client Secret**: Click "Show Client Secret" and copy this value

4.  **Configure mp3ify**:
   - You can provide your API credentials in three ways:
   
   a) **Command line arguments** (as shown in the Usage example):
   ```bash
   python mp3ify.py --oauthclientid <client-id> --oauthclientsecret <client-secret> --oauthredirecturi http://localhost:8080
   ```
   
   b) **Environment variables**:
   ```bash
   # Linux/macOS
   export SPOTIPY_CLIENT_ID=<client-id>
   export SPOTIPY_CLIENT_SECRET=<client-secret>
   export SPOTIPY_REDIRECT_URI=http://localhost:8080
   
   # Windows (Command Prompt)
   set SPOTIPY_CLIENT_ID=<client-id>
   set SPOTIPY_CLIENT_SECRET=<client-secret>
   set SPOTIPY_REDIRECT_URI=http://localhost:8080
   
   # Windows (PowerShell)
   $env:SPOTIPY_CLIENT_ID="<client-id>"
   $env:SPOTIPY_CLIENT_SECRET="<client-secret>"
   $env:SPOTIPY_REDIRECT_URI="http://localhost:8080"
   ```
   
   c) **Create a `.env` file** (recommended for repeated use):
   ```bash
   # Create a .env file in the project directory
   echo "SPOTIPY_CLIENT_ID=<client-id>" > .env
   echo "SPOTIPY_CLIENT_SECRET=<client-secret>" >> .env
   echo "SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888" >> .env
   ```
   
   mp3ify will automatically load these variables from a `.env` file in the current directory, or you can specify a different file:
   
   ```bash
   python mp3ify.py --env-file /path/to/your/.env
   ```
   
   Note: Make sure `.env` is listed in your `.gitignore` to avoid accidentally committing your credentials.

5.  **Authentication Flow**:
   - When you first run `mp3ify` using a command that requires user authorization (like `to-spotify`), it initiates the Spotify OAuth2 flow.
   - A browser window will likely open asking you to log in to your Spotify account and grant permissions to the application.
   - After you approve, Spotify redirects your browser back to the **Redirect URI** you configured in the Spotify Developer Dashboard and in your `mp3ify` settings (e.g., `http://127.0.0.1:8888`).
   - **Important Note on Local Port**: To receive this redirect, `mp3ify` (specifically, the `spotipy` library) starts a *temporary local web server* listening on the host and port specified in your Redirect URI (e.g., `127.0.0.1` and port `8888`).
   - **If another application on your computer is already using this specific port**, you will encounter an `[Errno 98] Address already in use` error, and the authentication cannot complete. To fix this:
     - Stop the other application using the port, OR
     - Choose a different, unused port (e.g., 9090, 5001, etc.). Update the Redirect URI in **both** your Spotify Developer Dashboard application settings **and** your `mp3ify` configuration (`.env` file, environment variables, or command-line arguments).
   - Once the temporary server receives the redirect from Spotify, it extracts an authorization `code` from the URL.
   - The browser page itself might show a "Connection Refused" or similar error after the redirect; this is usually normal because the temporary server shuts down immediately after grabbing the code.
   - `spotipy` then exchanges this code for access tokens behind the scenes.
   - If you are running in a terminal environment where a browser cannot be automatically opened, you might see a message asking you to manually open a URL, authorize, and then paste the *full* final URL (the one you were redirected to, containing the `code=...` part) back into the terminal.

## Installation & Setup with `uv`

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/alienmind/mp3ify.git
    cd mp3ify
    ```
2.  **Install `uv`:**
    Follow the official instructions at [astral.sh/uv](https://astral.sh/uv#installation) or use one of the common methods:
    ```bash
    # macOS / Linux
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Windows (Powershell)
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```
    Verify the installation:
    ```bash
    uv --version
    ```

3.  **Create and activate virtual environment:**
    ```bash
    # Create the virtual environment (creates a .venv directory)
    uv venv

    # Activate the environment
    # Linux / macOS
    source .venv/bin/activate
    # Windows (cmd.exe)
    # .venv\Scripts\activate.bat
    # Windows (Powershell)
    # .venv\Scripts\Activate.ps1
    ```
    You should see `(.venv)` prepended to your shell prompt.

4.  **Install dependencies:**
    ```bash
    # Install runtime and development dependencies
    uv pip install -e ".[dev,test]"
    ```

## Usage

`mp3ify` now uses subcommands to determine the sync direction.

**Note:** Examples show direct script execution. If you installed the package using `pip install .` or `uv pip install .`, you might be able to run `mp3ify <command> ...` directly without `python mp3ify.py`.

### Sync Local MP3s to Spotify Playlist

```bash
python mp3ify.py to-spotify [OPTIONS]
```

**Options:**

*   `-d`, `--directory DIRECTORY`: Directory containing MP3 files (default: `mp3/`).
*   `--playlist PLAYLIST_NAME`: Name of the Spotify playlist to create/update (default: `MP3ify`).
*   *Authentication options* (`--oauthclientid`, etc.) if not using environment variables or `.env`.

**Example:**

```bash
# Scan ./my_music and sync to a playlist named "My Local Gems"
python mp3ify.py to-spotify -d ./my_music --playlist "My Local Gems"
```

### Sync Spotify Playlist to Local MP3s

```bash
python mp3ify.py from-spotify --playlist-id <SPOTIFY_PLAYLIST_ID> [OPTIONS]
```

**Required:**

*   `--playlist-id PLAYLIST_ID`: The ID of the Spotify playlist to download. Find this in the playlist's URL (e.g., `https://open.spotify.com/playlist/YOUR_PLAYLIST_ID`).

**Options:**

*   `-d`, `--directory DIRECTORY`: Directory to save downloaded MP3 files (default: `spotify_downloads/`).
*   *Authentication options* (`--oauthclientid`, etc.) if not using environment variables or `.env`.

**Example:**

```bash
# Download tracks from a specific playlist to the default ./spotify_downloads folder
python mp3ify.py from-spotify --playlist-id 37i9dQZF1DXcBWIGoYBM5M

# Download tracks to a custom folder using -d
python mp3ify.py from-spotify --playlist-id 37i9dQZF1DXcBWIGoYBM5M -d ./downloaded_music
```

### Download YouTube Playlist to Local MP3s

```bash
python mp3ify.py from-youtube --playlist-url <YOUTUBE_PLAYLIST_URL> [OPTIONS]
```

**Required:**

*   `--playlist-url URL`: The full URL of the YouTube playlist to download.

**Options:**

*   `-d`, `--directory DIRECTORY`: Directory to save downloaded MP3 files (default: `youtube_downloads/`).
*   `--keep-intermediate-files`: If set, keeps all files downloaded by `yt-dlp` (original audio/video format, thumbnails like `.webp`/`.png`, etc.) instead of just the final `.mp3`. Defaults to deleting intermediate files. Controlled by `MP3IFY_KEEP_INTERMEDIATE` env var if flag not used.

**Example:**

```bash
# Download audio from a YouTube playlist to the default ./youtube_downloads folder
python mp3ify.py from-youtube --playlist-url "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxx"

# Download to a custom folder
python mp3ify.py from-youtube --playlist-url "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxx" -d ./my_youtube_music
```

### Testing Spotify to Local Sync

To test downloading tracks from a specific sample playlist into the `tests/mp3` directory, first ensure the directory exists (`mkdir -p tests/mp3`) and then run:

```bash
# Use -d for the output directory
python mp3ify.py from-spotify --playlist-id 54mvdz04MpqdRjRVrEbWYM -d tests/mp3
```
This command will fetch tracks from the specified playlist, search for them on YouTube, and download the MP3s with metadata into the `tests/mp3` folder.

### Common Options

*   `--env-file FILE_PATH`: Specify a custom path for the `.env` file.
*   `--num-cores N`: Set the maximum number of parallel worker threads for download operations (`from-spotify`). Set to `0` to use the maximum available cores. Defaults to 5, or the value of the `NUMCORES` environment variable if set. (Note: This currently only affects the `from-spotify` command's parallel search/download; `from-youtube` relies on `yt-dlp`'s internal handling).
*   Authentication flags (`--oauthclientid`, etc.) can be used with `to-spotify` and `from-spotify`.

### Environment Variables

*   `SPOTIPY_CLIENT_ID`: Your Spotify application Client ID.
*   `SPOTIPY_CLIENT_SECRET`: Your Spotify application Client Secret.
*   `SPOTIPY_REDIRECT_URI`: Your Spotify application Redirect URI (e.g., `http://127.0.0.1:8888`).
*   `NUMCORES`: Overrides the default number of parallel workers (5) for `from-spotify`. Command-line argument `--num-cores` takes precedence. Set to `0` for maximum available cores.
*   `MP3IFY_KEEP_INTERMEDIATE`: Set to `true`, `1`, or `yes` to keep all intermediate files (original format, thumbnails) when using the `from-youtube` command. Defaults to `false`. The `--keep-intermediate-files` command-line flag takes precedence.

## Example Workflow: YouTube -> Local -> Spotify -> Local

Here's a sequence demonstrating how you might use `mp3ify` to download a YouTube playlist, upload its contents to Spotify, and then re-download that Spotify playlist:

1.  **Download YouTube Playlist to Local Folder:**
    Download the audio tracks from the specified YouTube playlist into a local directory named `mp3`.
    ```bash
    python mp3ify.py from-youtube --playlist-url https://www.youtube.com/playlist?list=PLidIjcybOMhyQDmIGJglNjAQFR0BLFZ_m -d mp3
    ```
    *(This will create sanitized MP3 files like `01 - Title One.mp3`, `02 - Title Two.mp3`, etc., in the `./mp3` directory)*

2.  **Sync Local Folder to New Spotify Playlist:**
    Scan the `./mp3` directory created in the previous step, search for matches on Spotify, and create/update a Spotify playlist named "Jinjer" with the found tracks.
    ```bash
    python mp3ify.py to-spotify -d mp3 --playlist "Jinjer"
    ```
    *(This requires Spotify authentication and will create a private playlist named "Jinjer" on your Spotify account if it doesn't exist.)*

3.  **Sync New Spotify Playlist Back to a Different Local Folder:**
    Download the tracks from the "Jinjer" playlist (created in step 2) to a *new* local directory named `mp3_from_spotify`. **Note:** You first need to find the Playlist ID for your "Jinjer" playlist (e.g., by finding the playlist in Spotify, clicking "Share", and copying the Playlist Link - the ID is the string of characters after `playlist/` and before `?`).
    ```bash
    # Replace <JINJER_PLAYLIST_ID> with the actual ID found on Spotify
    python mp3ify.py from-spotify --playlist-id <JINJER_PLAYLIST_ID> -d mp3_from_spotify
    ```
    *(This will search YouTube for each track in the "Jinjer" playlist and download the best match into the `./mp3_from_spotify` directory, attempting to embed metadata from Spotify.)*

## Development

## License
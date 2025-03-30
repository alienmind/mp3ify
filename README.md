# mp3ify
MP3 local files to Spotify playlist

## Usage

  Create a new playlist named MP3ify based on your local mp3 files located in mp3/
```python
  python mp3ify.py -d mp3/ \
    --oauthclientid <client-id> \
    --oauthclientsecret <client-secret> \
    --oauthredirecturi http://localhost:8080 \
    --playlist MP3ify
``` 

## Spotify API Setup

To use mp3ify, you'll need to create a Spotify Developer application to obtain the necessary API credentials:

1. **Create a Spotify Developer Account**:
   - Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
   - Log in with your Spotify account or create one if needed

2. **Create a New Application**:
   - Click "Create App"
   - Fill in the application details:
     - **App name**: `mp3ify` (or any name you prefer)
     - **App description**: A brief description of what the app does
     - **Redirect URI**: `http://localhost:8080` (must match the URI you use with the app)
     - Accept the terms and conditions
     - Click "Create"

3. **Get Your API Credentials**:
   - On your app's dashboard, you'll see:
     - **Client ID**: Copy this value
     - **Client Secret**: Click "Show Client Secret" and copy this value

4. **Configure mp3ify**:
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
   echo "SPOTIPY_REDIRECT_URI=http://localhost:8080" >> .env
   ```
   
   mp3ify will automatically load these variables from a `.env` file in the current directory, or you can specify a different file:
   
   ```bash
   python mp3ify.py --env-file /path/to/your/.env
   ```
   
   Note: Make sure `.env` is listed in your `.gitignore` to avoid accidentally committing your credentials.

5. **Authentication Flow**:
   - When you first run mp3ify, a browser window will open asking you to log in to Spotify
   - After logging in, Spotify will redirect you to your specified redirect URI
   - The page may show an error (this is normal); copy the full URL from your browser
   - Paste the URL back into the terminal where mp3ify is running

## Getting Started / Development Setup

This project uses [`uv`](https://github.com/astral-sh/uv) for dependency management and virtual environments.

### Prerequisites

*   Git
*   Python >= 3.8 (as specified in `pyproject.toml`)
*   `uv` (See installation instructions below)
*   Spotify account and API credentials (see "Spotify API Setup" above)

### Installation

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

3.  **Create and activate a virtual environment:**
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
    Install the project in editable mode along with all development and testing dependencies:
    ```bash
    uv pip install -e ".[dev,test]"
    ```
    *   `-e`: Installs the project in "editable" mode.
    *   `.[dev,test]`: Installs the optional dependency groups defined in `pyproject.toml`.

    Verify the installation was successful by checking if Ruff is available:
    ```bash
    ruff --version
    ```

    If you encounter a "command not found" error, try installing Ruff directly:
    ```bash
    uv pip install ruff
    ```

### Troubleshooting Development Tools

If you're unable to run `ruff` or other developer tools after installation:

1. **Ensure your virtual environment is activated** (you should see `(.venv)` in your prompt)

2. **Check if the tools are installed in your virtual environment**:
   ```bash
   uv pip list | grep ruff
   ```

3. **If tools are installed but not in PATH**:
   You can run them using Python's module syntax:
   ```bash
   python -m ruff check .
   python -m ruff format .
   ```

4. **Direct installation**: If needed, install Ruff directly:
   ```bash
   uv pip install -U ruff
   ```

### Running Tests

With the virtual environment activated and dependencies installed, you can run the test suite using `pytest`:

```bash
# Run all tests
pytest

# Run only unit tests
pytest tests/test_mp3ify.py

# Run only the end-to-end test
pytest tests/test_end_to_end.py -v

# Generate a coverage report
pytest --cov=mp3ify tests/
```

The tests are set up to use mock data, so no actual Spotify API calls or real MP3 files are needed to run the tests.

### Type Checking

This project uses pyright for type checking:

```bash
# Run pyright type checker
pyright
```

Pyright is configured in the `pyproject.toml` file under the `[tool.pyright]` section.

### Linting and Formatting

This project uses [`ruff`](https://github.com/astral-sh/ruff) for linting and formatting.

```bash
# Check for linting errors and formatting issues
ruff check .

# Apply formatting fixes
ruff format .

# Apply linting fixes (where possible)
ruff check . --fix
```

### Installing for Production/Use

If you only need to install the core package dependencies (without development tools), you can run:

```bash
uv pip install .
```

---

import eyed3
import os
import pathlib
import spotipy as sp
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import List, Iterator, Optional


# Modes
MODE_CHOICES = ["id3", "filename", "api"]
DEFAULT_MODE = []

# API options
SPOTIFY_API_SCOPE = "user-library-read,playlist-read-private,playlist-modify-private"
CHUNK_SIZE = 100

@dataclass
class SpotifyConnection():
    """A connection object required for the Spotify API, including also user information
    """
    userid : str
    username : str
    connection : str
    def __init__(self, connection : sp.client.Spotify, userid : str = None, username : str = None):
        self.connection = connection
        self.userid = userid
        self.username = username

@dataclass
class TrackInfo():
    """Information about a track
    """
    filename : str
    artist : str
    album : str
    title : str
    def __init__(self, filename : str = None, artist : str = None, album : str = None, title : str = None):
        self.filename = filename
        self.artist = artist
        self.album = album
        self.title = title

def spotify_connect() -> SpotifyConnection :
    """Connect to Spotify API with OAuth.

    Returns:
        SpotifyConnection:  Connection object including user information
    """
    scope = SPOTIFY_API_SCOPE
    connection = sp.Spotify(auth_manager=SpotifyOAuth(scope=scope)) #)client_credentials_manager=SpotifyClientCredentials())
    userid = connection.current_user()['id']
    username = connection.current_user()['display_name']
    return SpotifyConnection(connection, userid=userid, username=username)

def spotify_check_playlist(connection : SpotifyConnection, playlistname : str, playlistid : str = None) -> Optional[str]:
    """Check if a Spotify playlist exists

    Args:
        connection (SpotifyConnection): connection to use
        playlistname (str): name of the playlist
        playlistid (str, optional): id of the playlist, if known. Defaults to None.

    Returns:
        Optional[str]: return a spotify list of track items
    """
    playlists = connection.connection.current_user_playlists(limit=50)['items']
    for i, playlist in enumerate(playlists):
        if playlist['name'] == playlistname:
            return playlist
        if playlistid != None and playlist['id'] == playlistid:
            return playlist
    return None
    
def spotify_create_playlist(connection : SpotifyConnection, playlistname : str) -> str:
    """Creates a a playlist in spotify

    Args:
        connection (SpotifyConnection): connection to use
        playlistname (str): name of the playlist to create

    Returns:
        str: playlist id
    """
    print(f"User: {connection.username} ({connection.userid})")
    r = sp.user_playlist_create(connection.userid, playlistname, public=False)
    playlistid = r['id']
    print(f"Playlist id: {playlistid}")
    return playlistid

def parse_file_name(fn : str, t : TrackInfo = TrackInfo()) -> TrackInfo:
    """
    Figure something out based on the name
    Args:
        fn (str): file name
        t (TrackInfo, optional): A TrackInfo to complete. Will not overwrite any existing info

    Returns:
        TrackInfo: same TrackInfo received plus the best guess info
    """
    # FIXME - this is too poor. Better leave if for a later stage
    fnr = fn.replace('_',' ')
    a = fnr.split('-')
    if len(a) == 4: # TrackNo - Artist - Album - Name
        if t.artist is None: t.artist = a[1]
        if t.album is None: t.album = a[2]
        if t.title is None: t.title = a[3]
    elif len(a) == 3: # Artist - Album - Name
        if t.artist is None: t.artist = a[0]
        if t.album is None: t.album = a[1]
        if t.title is None: t.title = a[2]
    elif len(a) == 2: # Album - Name
        if t.album is None: t.album = a[0]
        if t.title is None: t.title = a[1]
    elif len(a) == 1: # Name
        if t.title is None: t.title = a[0]
    else:
        if t.title is None: t.title = fnr # Out of despair
    return t

def mp3_walk_directory(dir : str, mode : List[str] = DEFAULT_MODE) -> Iterator[TrackInfo] :
    """Walks a directory with MP3 files and fetches all possible info

    Args:
        dir (str): input directory
        mode (List[str], optional):. List of actions to apply. Defaults to DEFAULT_MODE.

    Yields:
        Iterator[TrackInfo]: [description]
    """
    p = pathlib.Path(dir)
    for fn in p.glob('**/*.mp3'):
        t = TrackInfo(filename=fn)
        try :
            with open(fn,'r') as f:
                if "id3" in mode:
                    try:
                        mp3 = eyed3.load(fn)
                        print(f"===== {fn} ======")
                        #print(f"Artist: {mp3.tag.artist}")
                        #print(f"Album: {mp3.tag.album}") 
                        #print(f"Title: {mp3.tag.title}")
                        t.artist=mp3.tag.artist
                        t.album=mp3.tag.album
                        t.title=mp3.tag.title
                    except Exception as e:
                        pass

                if "filename" in mode:
                    try:
                        # Try to figure out of the name
                        t = parse_file_name(fn, t)
                    except:
                        pass

            yield t

        except Exception as e:
            pass

def list_chunks(lst : List, n : int) -> List:
    """Yield successive n-sized chunks from a list

    Args:
        lst (List): list of elements
        n (int): number of elements to yield

    Yields:
        List: slice of elements
    """
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
 

def main(args : Namespace):
    """Process all files in a given directory and dispatch actions based on running mode

    Args:
        args (Namespace): command line arguments parsed

    Returns:
        Nothing
    """

    # Connect & find user info
    connection : SpotifyConnection = None

    if "api" in args.mode:
        connection = spotify_connect()

    # Check all MP3s and create a tracklist
    n_mp3 : int = 0
    nSpotify : int = 0
    tracks : List[TrackInfo] = []
    for track in mp3_walk_directory(args.directory, args.mode):
        n_mp3 = n_mp3 + 1
        if connection:
            r = connection.connection.search(q=f"artist:{track.artist} {track.title}", type="track")
            if len(r['tracks']['items']) > 0:
                track.url = r['tracks']['items'][0]['external_urls']['spotify']
        tracks.append(track)
    n_tracks = len(tracks)

    # Check if playlist exists - create if it's new
    if connection:
        playlist = spotify_check_playlist(connection, playlistname=args.playlist)
        if playlist == None:
            playlist = connection.connection.user_playlist_create(connection.userid, args.playlist, public=False)
        playlistid = playlist.get('id',None)
        if playlistid == None:
            return # FIXME - exception tbd

        # Append all tracks to the list in chunks - as allowed per API
        # FIXME - each track should be double checked to avoid duplicates!
        n_chunks = 0
        for chunk in list_chunks(tracks, CHUNK_SIZE):
            # Add tracks from this chunk to playlist n
            connection.connection.user_playlist_add_tracks(connection.userid, playlistid, [t.url for t in chunk])

    # Print some basic stats
    print(f"MP3: {n_mp3} Tracks added to Spotify: {n_tracks}")
 

def setup() -> ArgumentParser : 
    """Parse all arguments and set up the API environment vars

    Returns:
        ArgumentParser: argparse namespace with all the options
    """
    parser = ArgumentParser()

    # Directory where pick the MP3s from
    parser.add_argument('--directory', '-d', dest='directory', action='store', required=False, type=str,
                        default='mp3/',
                        help='Directory to traverse recursively')

    # Just process MP3s and ID3
    parser.add_argument('--mode', '-m', dest='mode', action='append', required=False, type=str,
                        choices=MODE_CHOICES, default=DEFAULT_MODE,
                        help='Processing mode: (all by default):\n'
                             ' id3 will use only valid id3 tags, '
                             ' name will force a name-based guessing, '
                             ' api will query Spotify API')

    # Create a Spotify Playlist
    parser.add_argument('--playlist', dest='playlist', action='store', required=False, type=str,
                        default='MP3ify',
                        help='Spotify Playlist name to generate - will update if existing')


    # API options - not entirely true that aren't required (see below)
    parser.add_argument('--oauthclientid', dest='clientid', action='store', required=False, type=str,
                        default=os.environ.get("SPOTIPY_CLIENT_ID",None),
                        help='OAuth2 Client Id - defaults to SPOTIPY_CLIENT_ID env var')
    parser.add_argument('--oauthclientsecret', dest='clientsecret', action='store', required=False, type=str,
                        default=os.environ.get("SPOTIPY_CLIENT_SECRET",None),
                        help='OAuth2 Secret - defaults to SPOTIPY_CLIENT_SECRET env var')
    parser.add_argument('--oauthredirecturi', dest='redirecturi', action='store', required=False, type=str,
                        default=os.environ.get("SPOTIPY_REDIRECT_URI",None),
                        help='OAuth2 Redirect URI - defaults to SPOTIPY_REDIRECT_URI env var')

    args = parser.parse_args()

    # As modes are appended, we need to translate the default
    # otherwise, -m will just accumulate over the default
    if len(args.mode) == 0:
        args.mode = MODE_CHOICES

    # Some options will require further API options
    if "api" in args.mode:
        try:
            os.environ["SPOTIPY_CLIENT_ID"] = args.clientid
            os.environ["SPOTIPY_CLIENT_SECRET"] = args.clientsecret
            os.environ["SPOTIPY_REDIRECT_URI"] = args.redirecturi
        except:
            parser.print_help()
            exit(1)

    return args
   
if __name__ == "__main__":
    args : Namespace = setup()
    exit(main(args))
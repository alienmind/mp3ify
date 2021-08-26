import eyed3
import os
import pathlib
import spotipy as sp
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from typing import List, Iterator, Optional

SPOTIFY_API_SCOPE = "user-library-read,playlist-read-private,playlist-modify-private"
CHUNK_SIZE = 100

@dataclass
class SpotifyConnection():
    userid : str
    username : str
    connection : str
    def __init__(self, connection : sp.client.Spotify, userid : str = None, username : str = None):
        self.connection = connection
        self.userid = userid
        self.username = username

@dataclass
class TrackInfo():
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
    scope = SPOTIFY_API_SCOPE
    connection = sp.Spotify(auth_manager=SpotifyOAuth(scope=scope)) #)client_credentials_manager=SpotifyClientCredentials())
    userid = connection.current_user()['id']
    username = connection.current_user()['display_name']
    return SpotifyConnection(connection, userid=userid, username=username)

def spotify_check_playlist(connection : SpotifyConnection, playlistname : str, playlistid : str = None) -> Optional[str]:
    playlists = connection.connection.current_user_playlists(limit=50)['items']
    for i, playlist in enumerate(playlists):
        if playlist['name'] == playlistname:
            return playlist
        if playlistid != None and playlist['id'] == playlistid:
            return playlist
    return None
    
def spotify_create_playlist(connection : SpotifyConnection, playlistname : str) -> str:
    print(f"User: {connection.username} ({connection.userid})")
    r = sp.user_playlist_create(connection.userid, playlistname, public=False)
    playlistid = r['id']
    print(f"Playlist id: {playlistid}")
    return playlistid

def mp3_walk_directory(dir : str) -> Iterator[TrackInfo] :
    p = pathlib.Path(dir)
    for fn in p.glob('**/*.mp3'):
        try :
            with open(fn,'r') as f:
                try:
                    mp3 = eyed3.load(fn)
                    print(f"===== {fn} ======")
                    #print(f"Artist: {mp3.tag.artist}")
                    #print(f"Album: {mp3.tag.album}") 
                    #print(f"Title: {mp3.tag.title}")
                    artist=mp3.tag.artist
                    album=mp3.tag.album
                    title=mp3.tag.title
                except Exception as e:
                    # Figure out something based on the name
                    fnr = fn.replace('_',' ')
                    a = fnr.split('-')
                    artist = album = title = None
                    if len(a) == 4: # TrackNo - Artist - Album - Name
                        artist = a[1]
                        album = a[2]
                        title = a[3]
                    elif len(a) == 3: # Artist - Album - Name
                        artist = a[0]
                        album = a[1]
                        title = a[2]
                    elif len(a) == 2: # Album - Name
                        album = a[0]
                        title = a[1]
                    elif len(a) == 1: # Name
                        title = a[0]
                    else:
                        title = fnr # Out of despair
            t = TrackInfo(filename=fn, artist=artist, album=album, title=title)
            yield t
        except Exception as e:
            pass

def list_chunks(lst : List, n : int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
 

def main(args : Namespace):

    # Connect & find user info
    connection : SpotifyConnection = spotify_connect()

    # Check all MP3s and create a tracklist
    n_mp3 : int = 0
    nSpotify : int = 0
    tracks : List[TrackInfo] = []
    for track in mp3_walk_directory(args.directory):
        n_mp3 = n_mp3 + 1
        r = connection.connection.search(q=f"artist:{track.artist} {track.title}", type="track")
        if len(r['tracks']['items']) > 0:
            track.url = r['tracks']['items'][0]['external_urls']['spotify']
            tracks.append(track)
    n_tracks = len(tracks)

    # Check if playlist exists - create if it's new
    playlist = spotify_check_playlist(connection, playlistname=args.playlist)
    if playlist == None:
        playlist = connection.connection.user_playlist_create(connection.userid, args.playlist, public=False)
    playlistid = playlist.get('id',None)
    if playlistid == None:
        return # FIXME - exception tbd

    # Append all tracks to the list
    # FIXME - each track should be double checked to avoid duplicates!
    n_chunks = 0
    for chunk in list_chunks(tracks, CHUNK_SIZE):
        # Add tracks from this chunk to playlist n
        connection.connection.user_playlist_add_tracks(connection.userid, playlistid, [t.url for t in chunk])

    print(f"MP3: {n_mp3} Tracks added: {n_tracks}")
 

def setup() -> ArgumentParser : 
    parser = ArgumentParser()
    parser.add_argument('--oauthclientid', dest='clientid', action='store', required=False, type=str,
                        default=os.environ.get("SPOTIPY_CLIENT_ID",None),
                        help='OAuth2 Client Id - defaults to SPOTIPY_CLIENT_ID env var')
    parser.add_argument('--oauthclientsecret', dest='clientsecret', action='store', required=False, type=str,
                        default=os.environ.get("SPOTIPY_CLIENT_SECRET",None),
                        help='OAuth2 Secret - defaults to SPOTIPY_CLIENT_SECRET env var')
    parser.add_argument('--oauthredirecturi', dest='redirecturi', action='store', required=False, type=str,
                        default=os.environ.get("SPOTIPY_REDIRECT_URI",None),
                        help='OAuth2 Redirect URI - defaults to SPOTIPY_REDIRECT_URI env var')
    parser.add_argument('--playlist', dest='playlist', action='store', required=False, type=str,
                        default='MP3ify',
                        help='Playlist name - will update if existing')
    parser.add_argument('--directory', '-d', dest='directory', action='store', required=False, type=str,
                        default='mp3/',
                        help='Directory to traverse recursively')

    args = parser.parse_args()
    os.environ["SPOTIPY_CLIENT_ID"] = args.clientid
    os.environ["SPOTIPY_CLIENT_SECRET"] = args.clientsecret
    os.environ["SPOTIPY_REDIRECT_URI"] = args.redirecturi
    return args
   
if __name__ == "__main__":
    args : Namespace = setup()
    exit(main(args))
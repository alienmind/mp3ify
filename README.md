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

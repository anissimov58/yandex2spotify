import argparse
import logging
import platform
from enum import Enum
from subprocess import call
from os import path

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from yandex_music import Client

CLIENT_ID = '9b3b6782c67a4a8b9c5a6800e09edb27'
CLIENT_SECRET = '7809b5851f1d4219963a3c0735fd5bea'
REDIRECT_URI = 'https://open.spotify.com'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def proc_captcha(captcha):
    captcha.download('captcha.gif')
    system = platform.system()
    if system == 'Windows':
        call('captcha.gif', shell=True)
    elif system == 'Linux':
        call(['xdg-open', 'captcha.gif'])
    return input(f'Input number from "captcha.gif" ({os.path.abspath("captcha.gif")}):')


class Type(Enum):
    TRACK = 'track'
    ALBUM = 'album'
    ARTIST = 'artist'


class Importer:
    def __init__(self, spotify_client, yandex_client):
        self.spotify_client = spotify_client
        self.yandex_client = yandex_client

        self.user = spotify_client.me()['id']
        logger.info(f'User ID: {self.user}')

        self.not_imported = {}

    def _add_items_to_spotify(self, items, not_imported_section, save_items_callback, type_):
        spotify_items = []

        items.reverse()
        for item in items:
            if item.available:
                if type_ == Type.ARTIST:
                    item_name = item.name
                else:
                    item_name = f'{", ".join([artist.name for artist in item.artists])} - {item.title}'

                logger.info(f'Importing {type_.value}: {item_name}...')

                found_items = self.spotify_client.search(item_name, type=type_.value)[type_.value+'s']['items']
                if len(found_items):
                    spotify_items.append(found_items[0]['id'])
                    logger.info('OK')
                else:
                    not_imported_section.append(item_name)
                    logger.warning('NO')

        for chunk in chunks(spotify_items, 50):
            save_items_callback(self, chunk)

    def import_likes(self):
        self.not_imported['Likes'] = []

        likes_tracks = self.yandex_client.users_likes_tracks().tracks
        tracks = self.yandex_client.tracks([f'{track.id}:{track.album_id}' for track in likes_tracks if track.album_id])
        logger.info('Importing liked tracks...')

        def save_tracks_callback(importer, spotify_tracks):
            logger.info(f'Saving {len(spotify_tracks)} tracks...')
            importer.spotify_client.current_user_saved_tracks_add(spotify_tracks)
            logger.info('OK')

        self._add_items_to_spotify(tracks, self.not_imported['Likes'], save_tracks_callback, Type.TRACK)

    def import_playlists(self):
        playlists = self.yandex_client.users_playlists_list()
        for playlist in playlists:
            spotify_playlist = self.spotify_client.user_playlist_create(self.user, playlist.title)
            spotify_playlist_id = spotify_playlist['id']

            logger.info(f'Importing playlist {playlist.title}...')

            self.not_imported[playlist.title] = []

            playlist_tracks = playlist.fetch_tracks()
            tracks = [track.track for track in playlist_tracks]

            def save_tracks_callback(importer, spotify_tracks):
                logger.info(f'Saving {len(spotify_tracks)} tracks in playlist {playlist.title}...')
                importer.spotify_client.user_playlist_add_tracks(importer.user, spotify_playlist_id, spotify_tracks)
                logger.info('OK')

            self._add_items_to_spotify(tracks, self.not_imported[playlist.title], save_tracks_callback, Type.TRACK)

    def import_albums(self):
        self.not_imported['Albums'] = []

        likes_albums = self.yandex_client.users_likes_albums()
        albums = [album.album for album in likes_albums]
        logger.info('Importing albums...')

        def save_albums_callback(importer, spotify_albums):
            logger.info(f'Saving {len(spotify_albums)} albums...')
            importer.spotify_client.current_user_saved_albums_add(spotify_albums)
            logger.info('OK')

        self._add_items_to_spotify(albums, self.not_imported['Albums'], save_albums_callback, Type.ALBUM)

    def import_artists(self):
        self.not_imported['Artists'] = []

        likes_artists = self.yandex_client.users_likes_artists()
        artists = [artist.artist for artist in likes_artists]
        logger.info('Importing artists...')

        def save_artists_callback(importer, spotify_artists):
            logger.info(f'Saving {len(spotify_artists)} artists...')
            importer.spotify_client.user_follow_artists(spotify_artists)
            logger.info('OK')

        self._add_items_to_spotify(artists, self.not_imported['Artists'], save_artists_callback, Type.ARTIST)

    def import_all(self):
        self.import_likes()
        self.import_playlists()
        self.import_albums()
        self.import_artists()

        self.print_not_imported()

    def print_not_imported(self):
        logger.error('Not imported items:')
        for section, items in self.not_imported.items():
            logger.info(f'{section}:')
            for item in items:
                logger.info(item)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Creates a playlist for user')
    parser.add_argument('-u', '-s', '--spotify', required=True, help='Username at spotify.com')

    group = parser.add_argument_group('authentication')
    group.add_argument('-l', '--login', help='Login at music.yandex.com')
    group.add_argument('-p', '--password', help='Password at music.yandex.com')

    parser.add_argument('-t', '--token', help='Token from music.yandex.com account')

    args = parser.parse_args()

    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope='playlist-modify-public, user-library-modify, user-follow-modify',
        username=args.spotify
    )
    spotify_client_ = spotipy.Spotify(auth_manager=auth_manager)

    if args.login and args.password:
        yandex_client_ = Client.from_credentials(args.login, args.password, captcha_callback=proc_captcha)
    elif args.token:
        yandex_client_ = Client(args.token, captcha_callback=proc_captcha)
    else:
        raise RuntimeError('Provide yandex account conditionals or token!')

    Importer(spotify_client_, yandex_client_).import_all()

import argparse
import json
from getpass import getpass
import os
import re
import sys
from pathlib import Path

CONFIG = Path.home() / ".config" / "yb2spotify"
REDIRECT = "http://127.0.0.1:8888/callback"


def normalize(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def match(song, candidates):
    title = normalize(song["title"])
    artists = {normalize(a["name"]) for a in song.get("artists", [])}
    recordings = {}
    for track in candidates:
        if normalize(track["name"]) != title or not artists.intersection(
            normalize(a["name"]) for a in track["artists"]
        ):
            continue
        duration = song.get("duration_seconds")
        if duration and abs(track["duration_ms"] / 1000 - duration) > 5:
            continue
        key = track.get("external_ids", {}).get("isrc") or track["uri"]
        recordings[key] = track["uri"]
    if len(recordings) == 1:
        return next(iter(recordings.values())), ""
    return None, "ambiguous recording" if recordings else "no confident match"


def youtube_pages(resource, authorization, **params):
    import requests

    while True:
        response = requests.get(
            f"https://www.googleapis.com/youtube/v3/{resource}",
            headers={"Authorization": authorization()},
            params={"maxResults": 50, **params},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"YouTube {resource}: {response.status_code} {response.json()['error']['message']}")
        page = response.json()
        yield from page["items"]
        if not page.get("nextPageToken"):
            break
        params["pageToken"] = page["nextPageToken"]


def video_song(item):
    info = item["snippet"]
    title = info["title"]
    artist = info.get("videoOwnerChannelTitle", "").removesuffix(" - Topic")
    if " - " in title and not info.get("videoOwnerChannelTitle", "").endswith(" - Topic"):
        artist, title = title.split(" - ", 1)
    title = re.sub(r"\s*[\[(]official (music video|audio|video)[\])]$", "", title, flags=re.I)
    return {"title": title, "artists": [{"name": artist}] if artist else [],
            "videoId": info["resourceId"].get("videoId")}


def migrate(yt, sp, console, authorization=None):

    from ytmusicapi.exceptions import YTMusicServerError

    fallback = False
    try:
        playlists = {p["playlistId"]: p["title"] for p in yt.get_library_playlists(limit=None)}
        playlists["LM"] = "Liked Music"
    except YTMusicServerError as exc:
        if "HTTP 400" not in str(exc) or authorization is None:
            raise
        fallback = True
        console.print("YouTube Music rejected the library request. Showing your owned YouTube playlists and Liked Videos.")
        playlists = {p["id"]: p["snippet"]["title"] for p in youtube_pages(
            "playlists", authorization, part="snippet", mine="true"
        )}
        channels = youtube_pages("channels", authorization, part="contentDetails", mine="true")
        for channel in channels:
            likes = channel["contentDetails"]["relatedPlaylists"].get("likes")
            if likes:
                playlists[likes] = "Liked Videos"
    if not playlists:
        print("No playlists found for this account.")
        return
    selected = select_playlists(playlists, console)
    for index, pid in enumerate(selected, 1):
        name = playlists[pid]
        console.print(f"Importing {index}/{len(selected)}: {name}", markup=False)
        import_playlist(yt, sp, console, pid, name, fallback, authorization)


def select_playlists(playlists, console):
    if sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb":
        from InquirerPy import inquirer
        from InquirerPy.base.control import Choice

        return inquirer.checkbox(
            message="Choose playlists to import",
            choices=[Choice(pid, name=f"{name} ({pid})") for pid, name in playlists.items()],
            instruction="↑/↓ move · Space toggle · Enter import · Ctrl-C cancel",
            validate=lambda selected: bool(selected),
            invalid_message="Select at least one playlist with Space.",
        ).execute()

    options = list(playlists.items())
    for i, (pid, title) in enumerate(options, 1):
        console.print(f"{i}. {title} ({pid})", markup=False)
    numbers = {str(index): option for index, option in enumerate(options, 1)}
    while True:
        choices = [value.strip() for value in input("Playlist numbers (e.g. 1,3,5): ").split(",")]
        if all(value in numbers for value in choices):
            break
        print("Enter one or more listed numbers separated by commas.")
    return [numbers[value][0] for value in dict.fromkeys(choices)]


def import_playlist(yt, sp, console, pid, name, fallback, authorization):
    from rich.console import Group
    from rich.live import Live
    from rich.progress import Progress
    from rich.text import Text

    if fallback:
        songs = [video_song(item) for item in youtube_pages(
            "playlistItems", authorization, part="snippet", playlistId=pid
        )]
    else:
        data = yt.get_liked_songs(limit=None) if pid == "LM" else yt.get_playlist(pid, limit=None)
        songs = data["tracks"]
    matches, skipped = [], []
    progress = Progress(console=console)
    task = progress.add_task("Matching", total=len(songs))
    counts = Text("0 matched · 0 skipped")
    with Live(Group(progress, counts, Text()), console=console) as live:
        for song in songs:
            title = song.get("title") or "Unknown title"
            artist = ", ".join(a["name"] for a in song.get("artists", []))
            label = f"{artist} — {title}" if artist else title
            current_song = Text(" ".join(label.splitlines()), no_wrap=True, overflow="ellipsis")
            live.update(Group(progress, counts, current_song), refresh=True)
            uri, reason = None, "unavailable or missing metadata"
            if artist and song.get("title") and song.get("isAvailable", True):
                result = sp.search(q=f"{title} {song['artists'][0]['name']}", type="track", limit=10)
                uri, reason = match(song, result["tracks"]["items"])
            if uri:
                matches.append(uri)
            else:
                video = song.get("videoId")
                link = f"https://music.youtube.com/watch?v={video}" if video else ""
                skipped.append(f"{label} ({reason}) {link}")
            progress.advance(task)
            counts = Text(f"{len(matches)} matched · {len(skipped)} skipped")
            live.update(Group(progress, counts, current_song))
    added = 0
    try:
        if matches:
            playlist = sp._post("me/playlists", payload={"name": name, "public": False})
            print(playlist["external_urls"]["spotify"], flush=True)
            with Progress(console=console) as progress:
                task = progress.add_task("Adding to Spotify", total=len(matches))
                for offset in range(0, len(matches), 100):
                    batch = matches[offset:offset + 100]
                    sp._post(f"playlists/{playlist['id']}/items", payload={"uris": batch})
                    added += len(batch)
                    progress.advance(task, len(batch))
    finally:
        print(f"{added} confirmed added · {len(skipped)} unmatched")
        for line in skipped:
            print(line)


def main():
    import spotipy
    from spotipy.oauth2 import SpotifyPKCE
    from ytmusicapi import OAuthCredentials, YTMusic
    from ytmusicapi.setup import setup_oauth
    from rich.console import Console

    parser = argparse.ArgumentParser(description="Copy a YouTube Music playlist to Spotify")
    parser.add_argument("action", choices=["setup", "import"], default="import", nargs="?")
    args = parser.parse_args()
    os.umask(0o077)
    CONFIG.mkdir(parents=True, exist_ok=True)
    headers = CONFIG / "youtube.json"
    token = CONFIG / "youtube-oauth.json"
    google = CONFIG / "google-client.json"
    client = CONFIG / "spotify-client"
    try:
        if args.action == "setup":
            print(
                "1. Connect YouTube Music with your Google account\n"
                "   Create or select a project and enable YouTube Data API v3:\n"
                "   https://console.cloud.google.com/apis/library/youtube.googleapis.com\n"
                "   In Google Auth Platform, choose Get started, enter an app name and contact email,\n"
                "   and select External. Under Audience, leave it in Testing and add the email\n"
                "   you use for YouTube Music under Test users: https://console.cloud.google.com/auth/audience\n"
                "   Under Clients, create an OAuth client of type TVs and Limited Input devices:\n"
                "   https://console.cloud.google.com/auth/clients\n"
                "   Enter that client’s ID and secret here. The secret is hidden as you type."
            )
            credentials = {
                "client_id": input("Google client ID: ").strip(),
                "client_secret": getpass("Google client secret: ").strip(),
            }
            print(
                "If Google asks for a device code, return to this terminal. "
                "In the sign-in URL below, copy the value after user_code= "
                "and enter it in the browser. Approve access, then press Enter here.",
                flush=True,
            )
            setup_oauth(**credentials, filepath=str(token), open_browser=True)
            google.write_text(json.dumps(credentials))
            print(
                "\n2. Connect Spotify with your destination account\n"
                "   Open https://developer.spotify.com/dashboard and create an app.\n"
                "   The development app owner needs Spotify Premium. Select Web API and add\n"
                f"   this exact redirect URI: {REDIRECT}\n"
                "   Save the app, open Settings, and copy its Client ID. After entering it here,\n"
                "   approve access in the browser if prompted."
            )
            client.write_text(input("Spotify app client ID: ").strip())
        if not (headers.exists() or (token.exists() and google.exists())) or not client.exists():
            parser.exit(1, "Run yb2spotify setup first.\n")
        auth = SpotifyPKCE(client_id=client.read_text().strip(), redirect_uri=REDIRECT,
                           scope="playlist-modify-private", cache_path=str(CONFIG / "spotify-token"))
        auth.get_access_token()
        if args.action == "setup":
            print("Setup complete. Run yb2spotify to select playlists.")
            return
        if args.action == "import":
            from requests import Session
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            session = Session()
            session.mount("https://", HTTPAdapter(max_retries=Retry(
                total=3, status_forcelist=[429, 502, 503, 504], allowed_methods={"GET"},
                backoff_factor=1)))
            authorization = None
            if token.exists() and google.exists():
                oauth = OAuthCredentials(**json.loads(google.read_text()))
                youtube = YTMusic(str(token), oauth_credentials=oauth)
                authorization = lambda: youtube.headers["authorization"]
            else:
                youtube = YTMusic(str(headers))
            migrate(youtube, spotipy.Spotify(auth_manager=auth, requests_session=session), Console(), authorization)
    except (KeyboardInterrupt, EOFError):
        parser.exit(1, "Cancelled.\n")
    except Exception as exc:
        parser.exit(1, f"Import stopped: {exc}\n")

# yb2spotify — YouTube Music to Spotify playlist importer

Copy a YouTube Music playlist or Liked Music to a new private Spotify playlist. The terminal shows matching and upload progress, then lists songs it skipped.

## Quick start

Download or clone this repository. From the folder containing `pyproject.toml`, run:

```sh
pipx install .
yb2spotify setup
yb2spotify
```

Setup walks you through both app registrations and browser sign-ins. Subsequent imports only need `yb2spotify`.

[Installation](#installation) · [Google setup](#google-oauth-setup-for-youtube-music) · [Spotify setup](#spotify-web-api-setup) · [Import playlists](#import-a-playlist) · [Troubleshooting](#troubleshooting)

## Installation

Use Python 3.10 or newer and pipx. To update after downloading a newer version, run `pipx install --force .` from the source directory. [Install pipx](https://pipx.pypa.io/stable/installation/)

## Google OAuth setup for YouTube Music

The public CLI currently asks each user for their own Google and Spotify app credentials. Register both apps once, then authorize the CLI in your browser.

1. **Google project.** Create or select a project and enable YouTube Data API v3. [Google API library](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
2. **Google consent screen.** In Google Auth Platform, choose **Get started**, enter an app name and contact email, and select **External**. For a personal registration, leave the app in **Testing** and add your YouTube Music account under **Audience → Test users**. [Google Auth Platform](https://console.cloud.google.com/auth/overview)
3. **Google client.** Under **Clients → Create client**, select **TVs and Limited Input devices**. Save the client ID and client secret for setup. [Google OAuth clients](https://console.cloud.google.com/auth/clients)

Run `yb2spotify setup` and enter your Google client ID and secret. If Google asks for a device code, copy the value after `user_code=` from the URL printed in the terminal. Sign in with your test-user email, approve access, then press Enter in the terminal.

## Spotify Web API setup

1. **Spotify app.** Create an app, select **Web API**, and add the exact redirect URI `http://127.0.0.1:8888/callback`. Save it and copy the client ID from **Settings**. Spotify requires the owner of a development-mode app to have Premium. [Developer dashboard](https://developer.spotify.com/dashboard) · [Quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
2. At the Spotify prompt in the same setup session, enter the Spotify client ID and authorize the destination account. Setup stores credentials and tokens in `~/.config/yb2spotify/`. Keep that directory private.

## Import a playlist

Run `yb2spotify` and use **↑/↓** to move, **Space** to select or deselect playlists, and **Enter** to import your selection. **Ctrl-C** cancels the picker. Each playlist imports separately. For piped input, enter comma-separated playlist numbers (for example, `1,3,5`). Each run creates a fresh private playlist if any songs match. If an upload stops partway through, check the printed Spotify playlist before starting another import.

## Publishing and shared sign-in

You can publish the source with the per-user setup above. Exclude local configuration, downloaded credential files, and authorization tokens from commits, release archives, screenshots, and issue reports.

To offer browser-only onboarding under one publisher-owned registration, the CLI would need to be updated to use the registered clients automatically. A distributed CLI cannot keep an embedded secret confidential. For a public Google app, configure the external consent screen for production and complete any verification required for the requested YouTube scope. [Google OAuth verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)

Spotify development mode limits a shared app to five authorized users. Opening the repository to the public does not expand that allowance. Serving a broader audience through one Spotify client requires extended quota approval, which Spotify currently accepts applications for only from eligible organizations. [Spotify quota modes and eligibility](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)

## Troubleshooting

**YouTube Music HTTP 400 or missing saved playlists.** If YouTube Music returns HTTP 400 while listing your OAuth library, the CLI uses the official YouTube Data API with your existing sign-in. This fallback lists playlists you own and your YouTube Liked Videos. Saved playlists from other creators may be absent. Matching uses video titles and uploader names where music metadata is unavailable.

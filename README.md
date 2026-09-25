<h2 align="center">
  <br>
  <img src="resources/icon.png" height="60" width="60">
  <br>
  <strong>JioTV Direct</strong>
  <br>
</h2>

## Community-maintained Kodi add-on

JioTV Direct is a **community-maintained fork** of the original Kodi add-on.
It is not official JioTV software and it is not endorsed by or affiliated with
Jio or the original upstream maintainer.

The fork keeps the existing JioTV authentication, channel, playback, Widevine,
InputStream Adaptive, catch-up, and PVR architecture, while adding a more
TV-friendly Kodi experience and safer release validation.

> Use only channels and content that you are legally entitled to access. The
> add-on does not bypass subscriptions, DRM, authentication, tokens, licenses,
> or other access controls.

## Features

### Home and navigation

The main screen is designed for Android TV, D-pad, keyboard, mouse, and skins
already supported by Kodi:

- **Live TV** — browse the cached channel list.
- **Favorites** — persistent channel and programme favourites.
- **Recently Watched** — reopen recently resolved channels/programmes.
- **TV Guide** — channel list with current, upcoming, and catch-up metadata.
- **Search** — cached channel, channel ID, and available EPG programme search.
- **Catch-Up / VOD** — the existing JioTV VOD and catch-up sources.
- **Genres / Languages** — the existing channel filters.
- **PVR** — M3U and EPG integration remains available in Settings.

Favourites use stable channel/programme identifiers. Recently Watched stores
only non-sensitive reopen metadata; passwords, cookies, authorization headers,
access tokens, licence data, and stream URLs are not written to that history.

## Installation

### Stable repository

1. In Kodi, open **Settings > File Manager > Add source**.
2. Add the following source:

   ```text
   https://deepankar-siddharth.github.io/plugin.kodi.jiotv/
   ```

3. Select **Install from zip file** and install the generated
   `repository.jiotvdirect-<version>.zip` file.
4. Open **Install from repository > JioTV Direct Repository** and install
   **JioTV Direct** from **Video add-ons**.
5. Open the add-on settings and sign in using the existing authentication flow.

### Beta repository

Beta releases are published on a separate repository path:

```text
https://deepankar-siddharth.github.io/plugin.kodi.jiotv/beta/
```

The beta repository contains prereleases only. It is intended for testing and
may contain playback or interface regressions.

### Manual ZIP

Download the versioned archive from the fork's
[GitHub Releases](https://github.com/Deepankar-Siddharth/plugin.kodi.jiotv/releases):

```text
plugin.kodi.jiotv-<version>.zip
```

Manual ZIP installations do not receive repository updates until the user
installs a newer archive.

## Playback quality

Playback settings are under the add-on settings. The available controls are:

- **Playback Quality** — `Auto`, `Best Available`, `1080p`, `720p`, `480p`,
  `360p`, or `Manual`.
- **Adaptive Streaming** — let InputStream Adaptive choose representations.
- **Maximum Resolution** — an optional cap when the stream exposes a
  compatible representation.
- **Maximum Bitrate** — an optional cap in bits/s; `0` means no add-on-imposed limit.

`Auto` leaves adaptive selection to InputStream Adaptive. `Best Available` uses
adaptive selection with the configured resolution/bitrate limits. A fixed
quality is a preference; it is not forced when the stream does not expose that
resolution. DRM, licensing, authentication, and the existing stream URLs are not
bypassed or rewritten by the quality settings.

If playback fails, the add-on presents a generic diagnostic message covering
temporary stream failure, expired session, offline channel, and network causes.
Detailed logs are kept free of raw cookies, authorization headers, and stream
URL query strings.

## TV Guide and catch-up

The TV Guide uses the existing JioTV EPG endpoint. Selecting a channel fetches
one channel/day and caches the metadata for 30 minutes. This avoids downloading
the complete EPG every time the guide is opened. Programme actions are shown
only when supported:

- current programmes can be played or recorded with the existing recorder;
- past programmes expose catch-up actions when EPG data says catch-up is
  available;
- future programmes expose favourite actions but no fake play action;
- channel and programme context menus include favourite and channel-info
  actions.

The guide is a native Kodi list presentation rather than a custom skin. It
shows programme names, local start/end times, current/upcoming/catch-up state,
logos, and context actions. A full graphical timeline and reminder notifications
are not currently implemented.

## PVR and M3U

The existing PVR architecture remains enabled. Generate the playlist and EPG
from **Settings > JioTV Direct**:

- enable playlist generation if required;
- run the PVR setup action;
- configure IPTV Simple or another M3U client with the generated files.

The add-on-owned favourites store is synchronized with the legacy
`pvr_favourites` list so existing PVR workflows continue to work. The PVR
database is still user-managed; Kodi/client configuration is required.

## Development and validation

The release workflow validates source XML and version consistency, builds
versioned ZIPs, validates their contents, generates `addons.xml` and
`addons.xml.md5`, and verifies the published repository before creating a
GitHub Release.

Local checks:

```text
python -m py_compile addon.py service.py resources/lib/*.py scripts/*.py
python scripts/validate_release.py --tag v1.5.0 --source-root . --source-only
```

The full release validator expects the workflow's temporary `repo/` directory
and the two versioned ZIPs. It fails on invalid XML, version mismatches,
incorrect MD5, upstream distribution URLs, forbidden development files, and
high-confidence credential patterns.

## Release channels

- **Stable** — tags such as `v1.5.0`; normal GitHub releases and the stable
  repository path.
- **Beta** — tags such as `v1.6.0-beta.1`; GitHub prereleases and the `/beta/`
  repository path.

The tag, `addon.xml`, ZIP filename, repository metadata, generated
`addons.xml`, and GitHub Release must use the same semantic version.

## Known limitations

- The JioTV service and its EPG/API availability can change independently of
  this add-on.
- Some channels are subscription-controlled or unavailable in particular
  regions; the add-on does not remove those restrictions.
- EPG data is fetched for the selected guide channel, not as one large
  all-channel download.
- Recently Watched records the last resolved item and timestamp, but does not
  currently capture Kodi's in-player resume position.
- A custom graphical guide timeline, reminder notifications, and a dedicated
  Android TV skin are not included.
- Runtime playback and Kodi-device testing must still be performed on each
  supported Kodi/InputStream Adaptive/Widevine combination.
- The optional developer file/log server must be explicitly enabled and uses a
  per-session access token; the internal MPD proxy accepts manifest requests
  only from the local device.

## Upstream attribution

This fork preserves the original project's MIT license and attribution:

- Original upstream project: `dineshintry/plugin.kodi.jiotv`
- Upstream source: <https://github.com/dineshintry/plugin.kodi.jiotv>
- License: [MIT](LICENSE)

The fork adds community-maintained UX, playback, validation, and release work;
it does not represent itself as the official upstream project.

Thanks to the original creators and contributors, including Botallen,
kiranreddyrebel, and fatGrizzly, and to everyone who has contributed fixes and
feedback to the upstream project.

## Disclaimer

JioTV Direct is not officially commissioned or supported by Jio. The Jio name
and trademarks belong to their respective owners. Users are responsible for
complying with applicable laws, service terms, and local regulations.

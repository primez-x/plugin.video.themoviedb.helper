# TMDb Helper

TMDb Helper is a Kodi video add-on and script add-on for movie, television, and person details. The add-on provides list sources from TMDb, TVDb, MDbList, and Trakt, plus Kodi library and player integrations. Primez maintains this fork of the original project by jurialmunkey.

## Install

1. Install the [Primez repository ZIP](https://primez-x.github.io/kodi.addons/repository.primez.addons/repository.primez.addons-1.0.0.zip) in Kodi with **Install from zip file**.
2. In Kodi, open **Add-ons > Install from repository > Primez Kodi Add-ons > Video add-ons**.
3. Install **TMDb Helper**. Kodi installs the dependencies declared in `addon.xml`.

The add-on declares these dependency versions in `addon.xml`:

- `xbmc.python` `3.0.1`
- `script.module.requests` `2.9.1`
- `script.module.pil` `1.1.7`
- `script.module.addon.signals` `0.0.6`
- `script.module.jurialmunkey` `0.2.35`
- `script.module.infotagger` `0.0.5`
- `script.module.qrcode` `6.1.0`

## Setup and workflows

Open the add-on settings to set the metadata language and artwork quality. Configure movie and television library paths to create or update Kodi library entries.

The **API keys** settings accept credentials for OMDb, MDbList, RatingPosterDB, Gemini, Fanart.tv, and TVDB. The **Accounts** settings include a TMDb user token and Trakt authentication controls.

Use the **Players** settings to choose default movie and episode players, update player definitions, and customize playback choices. A player definition describes how TMDb Helper calls another installed video add-on.

Use the item context menu to open related lists, sync supported data, add an item to the Kodi library, modify artwork, or refresh details. Enable library auto-update and set the update schedule in the **Library** settings when needed.

## Plugin and script API

The add-on registers a Kodi video plugin at `resources/plugin.py` and a script entry point at `resources/script.py`. Plugin URLs use an `info` route and query parameters. For example, open movie details with:

```text
plugin://plugin.video.themoviedb.helper/?info=details&tmdb_type=movie&tmdb_id=123
```

Script calls use a supported route name and keyword parameters. For example, refresh one movie's details with:

```text
RunScript(plugin.video.themoviedb.helper,refresh_details,tmdb_type=movie,tmdb_id=123)
```

The [Script Methods](https://github.com/jurialmunkey/plugin.video.themoviedb.helper/wiki/Script-Methods), [Player Function](https://github.com/jurialmunkey/plugin.video.themoviedb.helper/wiki/Player-Function), and [Replacing Extended Info](https://github.com/jurialmunkey/plugin.video.themoviedb.helper/wiki/Replacing-Extended-Info) pages document script calls, player JSON, and skin integrations. These pages belong to the original project and cover the upstream API.

## Cache behavior

The TMDb API client bypasses the generic request cache. TMDb item details and related data still use local caches. The **General** settings expose separate `cache_location` and `image_location` paths.

Daily cleanup removes derived images unused for 30 days and detail records expired for more than 90 days.
Daily cleanup pauses during video playback and retains detail records with user-chosen artwork.
Derived images regenerate when needed.
Identifier matches expire after 90 days so later lookups can check old matches again.

The **Refresh Details** context action forces a fresh lookup for one item. The script API call above provides the same item-level refresh workflow.

## Source layout

- `addon.xml` — add-on metadata, dependencies, and Kodi entry points.
- `resources/settings.xml` — add-on settings.
- `resources/plugin.py` and `resources/script.py` — Kodi video plugin and script entry points.
- `resources/tmdbhelper/lib/api/` — TMDb and service API clients.
- `resources/tmdbhelper/lib/items/` — plugin routes, lists, and item details.
- `resources/tmdbhelper/lib/player/` — player selection and playback integration.
- `resources/tmdbhelper/lib/script/` — script methods and maintenance actions.
- `tests/` — configured source checks.

## Maintenance

The tracked branch is `nexus`. Run the configured checks from the repository root:

```sh
python3 -m compileall -q .
python3 -m unittest discover -s tests
```

Enable the local pre-push checks with:

```sh
git config core.hooksPath .githooks
```

For changes to shipped behavior, update the root `addon.xml` version and add the matching `<news>` entry. README-only edits need no version bump. Follow the central [versioning policy](https://github.com/primez-x/kodi.addons/blob/main/VERSIONING.md). The central [repository guide](https://github.com/primez-x/kodi.addons/blob/main/README.md) documents the source webhook and GitHub Actions publish flow.

## Credit and license

The original TMDb Helper project is by [jurialmunkey](https://github.com/jurialmunkey). Primez maintains this fork. The add-on uses the [GPL-3.0-or-later license](LICENSE.txt).

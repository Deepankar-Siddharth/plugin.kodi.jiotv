# -*- coding: utf-8 -*-
"""Stable, add-on-owned favourite entries.

This module extends the existing ``pvr_favourites`` list instead of creating a
second native Kodi favourites database.  Only non-sensitive playback metadata
is persisted; credentials, cookies, headers, and stream URLs are never stored.
"""

from __future__ import unicode_literals

import time
from urllib.parse import urlencode

from codequick import Listitem, Route, Script
from codequick.storage import PersistentDict

from resources.lib.constants import IMG_CATCHUP


FAVORITES_KEY = "favorite_items"
LEGACY_FAVORITES_KEY = "pvr_favourites"
_SAFE_PARAM_KEYS = {
    "channel_id",
    "languageId",
    "showtime",
    "srno",
    "programId",
    "begin",
    "end",
    "utc",
    "utcend",
    "is_extra",
}


def _safe_params(params):
    """Return a small JSON-safe subset suitable for reopening an item."""
    if not isinstance(params, dict):
        return {}
    result = {}
    for key in _SAFE_PARAM_KEYS:
        if key not in params or params[key] is None:
            continue
        value = params[key]
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


def _channel_key(channel_id):
    return "channel:{0}".format(str(channel_id))


def _program_key(params):
    channel_id = str(params.get("channel_id", ""))
    program_id = str(params.get("programId", ""))
    start = str(params.get("begin", params.get("showtime", "")))
    return "program:{0}:{1}:{2}".format(channel_id, program_id, start)


def _normalise_item(raw):
    if isinstance(raw, str):
        return {
            "id": _channel_key(raw),
            "kind": "channel",
            "channel_id": str(raw),
            "name": "Channel {0}".format(raw),
            "logo": "",
            "language_id": "",
            "params": {"channel_id": str(raw)},
            "added": 0,
        }
    if not isinstance(raw, dict):
        return None

    params = _safe_params(raw.get("params", {}))
    channel_id = str(raw.get("channel_id", params.get("channel_id", "")))
    if not channel_id:
        return None
    kind = raw.get("kind") if raw.get("kind") in ("channel", "program") else "channel"
    if kind == "channel":
        item_id = _channel_key(channel_id)
    else:
        item_id = str(raw.get("id") or _program_key(params))
    try:
        added = float(raw.get("added", 0) or 0)
    except (TypeError, ValueError):
        added = 0.0
    return {
        "id": item_id,
        "kind": kind,
        "channel_id": channel_id,
        "name": str(raw.get("name", "Channel {0}".format(channel_id))),
        "program_name": str(raw.get("program_name", "")),
        "logo": str(raw.get("logo", "")),
        "language_id": str(raw.get("language_id", params.get("languageId", ""))),
        "params": params,
        "added": added,
    }


def _load_items():
    with PersistentDict("localdb") as db:
        raw = db.get(FAVORITES_KEY, [])
        legacy = db.get(LEGACY_FAVORITES_KEY, [])

    items = []
    seen = set()
    if isinstance(raw, list):
        for value in raw:
            item = _normalise_item(value)
            if item and item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)

    # One-time migration of the existing PVR favourites list.
    if not items and isinstance(legacy, (list, tuple)):
        for value in legacy:
            item = _normalise_item(value)
            if item and item["id"] not in seen:
                seen.add(item["id"])
                items.append(item)
    return items


def _save_items(items):
    clean = []
    seen = set()
    for raw in items:
        item = _normalise_item(raw)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            clean.append(item)

    channel_ids = []
    for item in clean:
        if item["kind"] == "channel" and item["channel_id"] not in channel_ids:
            channel_ids.append(item["channel_id"])

    with PersistentDict("localdb") as db:
        db[FAVORITES_KEY] = clean
        # Keep the legacy list synchronized for older PVR code and installs.
        db[LEGACY_FAVORITES_KEY] = channel_ids
    return clean


def get_favorite_items(kind=None):
    items = _load_items()
    if kind:
        items = [item for item in items if item["kind"] == kind]
    return items


def get_favorite_ids():
    return [item["channel_id"] for item in get_favorite_items("channel")]


def is_favorite(item_id):
    return any(item["id"] == str(item_id) for item in _load_items())


def add_channel(channel_id, channel_name=None, logo=None, language_id=None, params=None):
    channel_id = str(channel_id)
    entry_params = _safe_params(params or {"channel_id": channel_id})
    entry_params["channel_id"] = channel_id
    if language_id is not None:
        entry_params["languageId"] = str(language_id)
    item = {
        "id": _channel_key(channel_id),
        "kind": "channel",
        "channel_id": channel_id,
        "name": str(channel_name or "Channel {0}".format(channel_id)),
        "logo": str(logo or ""),
        "language_id": str(language_id or ""),
        "params": entry_params,
        "added": time.time(),
    }
    items = _load_items()
    for index, existing in enumerate(items):
        if existing["id"] == item["id"]:
            item["added"] = existing.get("added", item["added"])
            items[index] = item
            break
    else:
        items.append(item)
    _save_items(items)
    return item


def add_program(channel_id, program_name, channel_name=None, logo=None, params=None):
    safe = _safe_params(params or {})
    safe["channel_id"] = str(channel_id)
    item = {
        "id": _program_key(safe),
        "kind": "program",
        "channel_id": str(channel_id),
        "name": str(channel_name or "Channel {0}".format(channel_id)),
        "program_name": str(program_name or "Programme"),
        "logo": str(logo or ""),
        "language_id": str(safe.get("languageId", "")),
        "params": safe,
        "added": time.time(),
    }
    items = _load_items()
    items = [existing for existing in items if existing["id"] != item["id"]]
    items.insert(0, item)
    _save_items(items)
    return item


def remove(item_id):
    item_id = str(item_id)
    items = _load_items()
    remaining = [item for item in items if item["id"] != item_id]
    _save_items(remaining)
    return len(remaining) != len(items)


def replace_channel_ids(channel_ids):
    """Synchronize the legacy PVR favourites list into the canonical store."""
    wanted = []
    for value in channel_ids or []:
        value = str(value)
        if value and value not in wanted:
            wanted.append(value)
    existing = {item["channel_id"]: item for item in get_favorite_items("channel")}
    items = []
    for channel_id in wanted:
        if channel_id in existing:
            items.append(existing[channel_id])
        else:
            items.append({
                "id": _channel_key(channel_id),
                "kind": "channel",
                "channel_id": channel_id,
                "name": "Channel {0}".format(channel_id),
                "program_name": "",
                "logo": "",
                "language_id": "",
                "params": {"channel_id": channel_id},
                "added": time.time(),
            })
    # Preserve programme favourites while replacing the channel portion.
    programs = get_favorite_items("program")
    return _save_items(items + programs)


def toggle_channel(channel_id, channel_name=None, logo=None, language_id=None):
    key = _channel_key(channel_id)
    if is_favorite(key):
        remove(key)
        return False
    add_channel(channel_id, channel_name, logo, language_id)
    return True


def toggle_program(channel_id, program_name, channel_name=None, logo=None, params=None):
    safe = _safe_params(params or {})
    safe["channel_id"] = str(channel_id)
    key = _program_key(safe)
    if is_favorite(key):
        remove(key)
        return False
    add_program(channel_id, program_name, channel_name, logo, safe)
    return True


def _channel_logo(channel, stored=""):
    if stored:
        return stored
    logo = channel.get("logoUrl", "") if isinstance(channel, dict) else ""
    if not logo:
        return ""
    return logo if str(logo).startswith(("http://", "https://")) else IMG_CATCHUP + str(logo)


def _context_url(module, function, **params):
    return "plugin://plugin.kodi.jiotv/resources/lib/{0}/{1}/?{2}".format(
        module, function, urlencode(params)
    )


@Route.register
def show_favorites(plugin):
    from resources.lib.guide import get_cached_current_program
    from resources.lib.player import play
    from resources.lib.utils import getCachedChannels

    items = get_favorite_items()
    if not items:
        yield Listitem.from_dict(**{
            "label": "No favorites yet. Use a channel or programme menu to add one.",
            "callback": "",
        })
        return

    channels = getCachedChannels() or []
    channels_by_id = {str(channel.get("channel_id")): channel for channel in channels}
    for item in items:
        channel = channels_by_id.get(item["channel_id"], {})
        logo = _channel_logo(channel, item.get("logo", ""))
        params = dict(item.get("params", {}))
        params["channel_id"] = item["channel_id"]
        if item.get("language_id") and "languageId" not in params:
            params["languageId"] = item["language_id"]
        display_name = channel.get("channel_name") or item["name"]
        if not channel and item["kind"] == "channel":
            label = "[COLOR grey]Unavailable: {0}[/COLOR]".format(display_name)
            callback = ""
        else:
            current = get_cached_current_program(item["channel_id"])
            if item["kind"] == "program":
                label = "★ {0} — {1}".format(display_name, item.get("program_name", "Programme"))
            elif current:
                label = "★ {0} — {1}".format(display_name, current.get("showname", "Current programme"))
            else:
                label = "★ {0}".format(display_name)
            callback = play
        info = {
            "title": display_name,
            "plot": "Favorite {0}".format(item["kind"]),
        }
        litm = Listitem.from_dict(**{
            "label": label,
            "art": {"thumb": logo, "icon": logo, "fanart": logo},
            "callback": callback,
            "params": params,
            "info": info,
        })
        litm.context.append((
            "Remove from Favorites",
            "RunPlugin({0})".format(_context_url("favorites", "remove_favorite", key=item["id"])),
        ))
        litm.context.append((
            "Channel Info",
            "RunPlugin({0})".format(_context_url("guide", "channel_info", channel_id=item["channel_id"])),
        ))
        yield litm


@Script.register
def remove_favorite(plugin, key=None, **kwargs):
    if key and remove(key):
        Script.notify("JioTV", "Removed from favorites")
    else:
        Script.notify("JioTV", "Favorite not found")


@Script.register
def toggle_favorite(plugin, channel_id=None, languageId=None, **kwargs):
    from resources.lib.utils import getCachedChannels

    if channel_id is None or str(channel_id).strip() == "":
        Script.notify("JioTV", "Channel could not be identified")
        return

    channel = {}
    for candidate in getCachedChannels() or []:
        if str(candidate.get("channel_id")) == str(channel_id):
            channel = candidate
            break
    added = toggle_channel(
        channel_id,
        channel.get("channel_name", "Channel {0}".format(channel_id)),
        _channel_logo(channel),
        languageId or channel.get("channelLanguageId"),
    )
    Script.notify("JioTV", "Added to favorites" if added else "Removed from favorites")


@Script.register
def toggle_program_favorite(
    plugin,
    channel_id=None,
    programId=None,
    showtime=None,
    srno=None,
    begin=None,
    end=None,
    languageId=None,
    channel_name=None,
    logo=None,
    program_name=None,
    **kwargs
):
    if channel_id is None or str(channel_id).strip() == "":
        Script.notify("JioTV", "Programme could not be identified")
        return
    params = {
        "channel_id": channel_id,
        "programId": programId,
        "showtime": showtime,
        "srno": srno,
        "begin": begin,
        "end": end,
        "languageId": languageId,
    }
    added = toggle_program(channel_id, program_name, channel_name, logo, params)
    Script.notify("JioTV", "Added to favorites" if added else "Removed from favorites")

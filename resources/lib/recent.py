# -*- coding: utf-8 -*-
"""Small, non-sensitive recently-watched store for JioTV Direct."""

from __future__ import unicode_literals

import time

from codequick import Listitem, Route, Script
from codequick.script import Settings
from codequick.storage import PersistentDict

from resources.lib.constants import IMG_CATCHUP


RECENT_KEY = "recent_items"
DEFAULT_LIMIT = 15
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


def _limit():
    try:
        value = int(Settings.get_integer("recent_limit"))
        return max(10, min(30, value))
    except Exception:
        try:
            value = int(Settings.get_string("recent_limit"))
            return max(10, min(30, value))
        except Exception:
            return DEFAULT_LIMIT


def _safe_params(params):
    if not isinstance(params, dict):
        return {}
    return {
        key: value for key, value in params.items()
        if key in _SAFE_PARAM_KEYS and isinstance(value, (str, int, float, bool))
    }


def _key(item):
    if item.get("kind") == "program":
        return "program:{0}:{1}:{2}".format(
            item.get("channel_id", ""),
            item.get("programId", ""),
            item.get("begin", item.get("showtime", "")),
        )
    return "channel:{0}".format(item.get("channel_id", ""))


def _normalise(raw):
    if not isinstance(raw, dict):
        return None
    channel_id = str(raw.get("channel_id", ""))
    if not channel_id:
        return None
    try:
        timestamp = float(raw.get("timestamp", 0) or 0)
    except (TypeError, ValueError):
        timestamp = 0.0
    item = {
        "channel_id": channel_id,
        "name": str(raw.get("name", "Channel {0}".format(channel_id))),
        "program_name": str(raw.get("program_name", "")),
        "logo": str(raw.get("logo", "")),
        "kind": raw.get("kind") if raw.get("kind") in ("channel", "program") else "channel",
        "timestamp": timestamp,
        "params": _safe_params(raw.get("params", {})),
    }
    item["params"]["channel_id"] = channel_id
    return item


def _load():
    with PersistentDict("localdb") as db:
        raw = db.get(RECENT_KEY, [])
    if not isinstance(raw, list):
        return []
    result = []
    seen = set()
    for value in raw:
        item = _normalise(value)
        if not item:
            continue
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    result.sort(key=lambda entry: entry.get("timestamp", 0), reverse=True)
    return result


def _save(items):
    clean = []
    seen = set()
    for raw in items:
        item = _normalise(raw)
        if not item:
            continue
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        clean.append(item)
    clean = clean[:_limit()]
    with PersistentDict("localdb") as db:
        db[RECENT_KEY] = clean
    return clean


def record_item(channel_id, name=None, logo=None, kind="channel", params=None, program_name=None):
    """Record a successful playback resolution without persisting secrets."""
    channel_id = str(channel_id or "")
    if not channel_id:
        return None
    item = {
        "channel_id": channel_id,
        "name": str(name or "Channel {0}".format(channel_id)),
        "program_name": str(program_name or ""),
        "logo": str(logo or ""),
        "kind": kind if kind in ("channel", "program") else "channel",
        "timestamp": time.time(),
        "params": _safe_params(params or {}),
    }
    items = [entry for entry in _load() if _key(entry) != _key(item)]
    items.insert(0, item)
    _save(items)
    return item


def get_recent_items():
    return _load()[:_limit()]


def clear_recent():
    with PersistentDict("localdb") as db:
        db[RECENT_KEY] = []


def _relative_time(timestamp):
    try:
        seconds = max(0, int(time.time() - float(timestamp)))
    except (TypeError, ValueError):
        return ""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return "{0}m ago".format(seconds // 60)
    if seconds < 86400:
        return "{0}h ago".format(seconds // 3600)
    return "{0}d ago".format(seconds // 86400)


def _logo(channel, stored):
    if stored:
        return stored
    logo = channel.get("logoUrl", "") if isinstance(channel, dict) else ""
    if not logo:
        return ""
    return logo if str(logo).startswith(("http://", "https://")) else IMG_CATCHUP + str(logo)


@Route.register
def show_recent(plugin):
    from resources.lib.player import play
    from resources.lib.utils import getCachedChannels

    items = get_recent_items()
    if not items:
        yield Listitem.from_dict(**{
            "label": "No recently watched content yet.",
            "callback": "",
        })
        return

    channels = getCachedChannels() or []
    channels_by_id = {str(channel.get("channel_id")): channel for channel in channels}
    for item in items:
        channel = channels_by_id.get(item["channel_id"], {})
        logo = _logo(channel, item.get("logo", ""))
        params = dict(item.get("params", {}))
        params["channel_id"] = item["channel_id"]
        title = item["name"]
        if item.get("program_name"):
            title = "{0} — {1}".format(title, item["program_name"])
        if not channel:
            label = "[COLOR grey]Unavailable: {0}[/COLOR]".format(title)
            callback = ""
        else:
            label = "▶ {0}  [COLOR grey]{1}[/COLOR]".format(title, _relative_time(item.get("timestamp")))
            callback = play
        yield Listitem.from_dict(**{
            "label": label,
            "art": {"thumb": logo, "icon": logo, "fanart": logo},
            "callback": callback,
            "params": params,
            "info": {
                "title": title,
                "plot": "Last watched {0}".format(_relative_time(item.get("timestamp"))),
            },
        })

    yield Listitem.from_dict(**{
        "label": "Clear Recently Watched",
        "callback": Route.ref("/resources/lib/recent:clear_recent_view"),
    })


@Route.register
def clear_recent_view(plugin, **kwargs):
    clear_recent()
    Script.notify("JioTV", "Recently Watched cleared")
    yield Listitem.from_dict(**{"label": "Recently Watched is empty.", "callback": ""})


@Script.register
def clear_recent_history(plugin, **kwargs):
    clear_recent()
    Script.notify("JioTV", "Recently Watched cleared")

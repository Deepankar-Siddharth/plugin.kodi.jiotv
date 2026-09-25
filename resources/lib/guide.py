# -*- coding: utf-8 -*-
"""Kodi-friendly TV Guide presentation over the existing JioTV EPG source."""

from __future__ import unicode_literals

import time
from datetime import datetime
from urllib.parse import urlencode

import urlquick
from codequick import Listitem, Resolver, Route, Script
from codequick.storage import PersistentDict
from xbmcgui import Dialog

from resources.lib.constants import CATCHUP_SRC, IMG_CATCHUP, IMG_CATCHUP_SHOWS
from resources.lib.favorites import get_favorite_ids, is_favorite
from resources.lib.utils import getCachedChannels


PROGRAM_FIELDS = (
    "channel_id", "showId", "showname", "description", "episodePoster",
    "showGenre", "duration", "startEpoch", "endEpoch", "isCatchupAvailable",
    "stbCatchupAvailable", "starCast", "director", "keywords", "episode_num",
    "episode_desc",
)


def _cache_key(channel_id, day):
    return "jiotv_epg_{0}_{1}".format(str(channel_id), int(day))


def _safe_program(program):
    if not isinstance(program, dict):
        return None
    result = {}
    for field in PROGRAM_FIELDS:
        if field in program:
            value = program[field]
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[field] = value
    result.setdefault("channel_id", "")
    return result


def _normalise_programs(raw):
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        value = _safe_program(item)
        if value:
            result.append(value)
    return result


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().casefold() in ("1", "true", "yes", "y", "on")
    return bool(value)


def _program_art(program):
    poster = str(program.get("episodePoster", "") or "")
    if not poster:
        return ""
    if poster.startswith(("http://", "https://")):
        return poster
    return IMG_CATCHUP_SHOWS + poster.lstrip("/")


def _remember_for_search(programs, channel_id):
    """Maintain a small, metadata-only index for the search route."""
    with PersistentDict("localdb") as db:
        index = db.get("jiotv_epg_search_index", [])
        if not isinstance(index, list):
            index = []
        existing = {
            (str(item.get("channel_id")), str(item.get("showId")), str(item.get("startEpoch")))
            for item in index if isinstance(item, dict)
        }
        for program in programs:
            marker = (str(channel_id), str(program.get("showId", "")), str(program.get("startEpoch", "")))
            if marker not in existing:
                index.append(dict(program, channel_id=str(channel_id)))
                existing.add(marker)
        db["jiotv_epg_search_index"] = index[-2000:]


def get_cached_epg(channel_id, day=0, allow_fetch=True):
    """Return cached EPG for one channel/day, fetching at most once per TTL."""
    channel_id = str(channel_id)
    day = int(day or 0)
    key = _cache_key(channel_id, day)
    now = time.time()
    with PersistentDict("localdb") as db:
        cached = db.get(key)
    if isinstance(cached, dict):
        try:
            age = now - float(cached.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            age = 1800
        if age < 1800:
            return _normalise_programs(cached.get("epg", []))

    if not allow_fetch:
        return _normalise_programs(cached.get("epg", [])) if isinstance(cached, dict) else []

    try:
        response = urlquick.get(
            CATCHUP_SRC.format(day, channel_id),
            max_age=1800,
            timeout=15,
        )
        programs = _normalise_programs(response.json().get("epg", []))
        with PersistentDict("localdb") as db:
            db[key] = {"timestamp": now, "epg": programs}
        _remember_for_search(programs, channel_id)
        return programs
    except Exception as exc:
        Script.log("TV Guide EPG request failed for channel {0}: {1}".format(channel_id, exc), lvl=Script.WARNING)
        return _normalise_programs(cached.get("epg", [])) if isinstance(cached, dict) else []


def _find_current(programs, now_ms=None):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    for program in programs:
        try:
            if int(program.get("startEpoch", 0)) <= now_ms < int(program.get("endEpoch", 0)):
                return program
        except (TypeError, ValueError):
            continue
    return None


def get_cached_current_program(channel_id):
    return _find_current(get_cached_epg(channel_id, day=0, allow_fetch=False))


def get_cached_current_programs(channel_ids):
    """Read cached current programmes for a channel list with one DB open."""
    now_ms = int(time.time() * 1000)
    result = {}
    with PersistentDict("localdb") as db:
        for channel_id in channel_ids:
            cached = db.get(_cache_key(channel_id, 0))
            if isinstance(cached, dict):
                current = _find_current(_normalise_programs(cached.get("epg", [])), now_ms)
                if current:
                    result[str(channel_id)] = current
    return result


def get_cached_program_index():
    with PersistentDict("localdb") as db:
        index = db.get("jiotv_epg_search_index", [])
    return _normalise_programs(index if isinstance(index, list) else [])


def _channel_map():
    return {
        str(channel.get("channel_id")): channel
        for channel in (getCachedChannels() or [])
        if channel.get("channel_id") is not None
    }


def _logo(channel):
    logo = channel.get("logoUrl", "") if isinstance(channel, dict) else ""
    if not logo:
        return ""
    return logo if str(logo).startswith(("http://", "https://")) else IMG_CATCHUP + str(logo)


def _program_time(program):
    try:
        start = datetime.fromtimestamp(int(program.get("startEpoch", 0)) / 1000.0)
        end = datetime.fromtimestamp(int(program.get("endEpoch", 0)) / 1000.0)
        return start.strftime("%I:%M %p").lstrip("0"), end.strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError, OSError):
        return "", ""


def _program_state(program):
    now_ms = int(time.time() * 1000)
    try:
        start = int(program.get("startEpoch", 0))
        end = int(program.get("endEpoch", 0))
    except (TypeError, ValueError):
        return "unknown"
    if start <= now_ms < end:
        return "current"
    if start > now_ms:
        return "future"
    return "past"


def _catchup_available(program):
    return _as_bool(program.get("isCatchupAvailable")) or _as_bool(program.get("stbCatchupAvailable"))


def _progress_text(program):
    try:
        start = int(program.get("startEpoch", 0))
        end = int(program.get("endEpoch", 0))
        if end <= start:
            return ""
        percent = max(0, min(100, int((int(time.time() * 1000) - start) * 100 / (end - start))))
        return "Progress: {0}%".format(percent)
    except (TypeError, ValueError):
        return ""


def _program_params(program, channel_id, language_id=None):
    try:
        start_seconds = int(program.get("startEpoch", 0)) / 1000.0
        end_seconds = int(program.get("endEpoch", 0)) / 1000.0
        start = datetime.utcfromtimestamp(start_seconds)
        end = datetime.utcfromtimestamp(end_seconds)
        showtime = start.strftime("%H%M%S")
        srno = start.strftime("%Y%m%d")
        begin = start.strftime("%Y%m%dT%H%M%S")
        finish = end.strftime("%Y%m%dT%H%M%S")
    except (TypeError, ValueError, OSError, OverflowError):
        showtime = ""
        srno = ""
        begin = ""
        finish = ""
    program_id = program.get("showId") or "CHN-{0}-PRG-{1}".format(channel_id, showtime or "unknown")
    return {
        "channel_id": str(channel_id),
        "showtime": showtime,
        "srno": srno,
        "programId": str(program_id),
        "begin": begin,
        "end": finish,
        "languageId": language_id or "",
    }


def _plugin_url(function, params):
    return "plugin://plugin.kodi.jiotv/resources/lib/guide/{0}/?{1}".format(
        function, urlencode(params)
    )


def _context_url(module, function, **params):
    return "plugin://plugin.kodi.jiotv/resources/lib/{0}/{1}/?{2}".format(
        module, function, urlencode(params)
    )


@Route.register
def show_guide(plugin):
    channels = getCachedChannels() or []
    if not channels:
        yield Listitem.from_dict(**{
            "label": "TV Guide unavailable: channel list is empty.",
            "callback": "",
        })
        return

    favorite_ids = set(get_favorite_ids())
    current_programs = get_cached_current_programs(
        [str(channel.get("channel_id", "")) for channel in channels]
    )
    channels = sorted(
        channels,
        key=lambda channel: (
            0 if str(channel.get("channel_id")) in favorite_ids else 1,
            channel.get("channel_order", 999999),
            str(channel.get("channel_name", "")).casefold(),
        ),
    )
    for channel in channels:
        channel_id = str(channel.get("channel_id", ""))
        name = channel.get("channel_name", "Unknown channel")
        logo = _logo(channel)
        current = current_programs.get(channel_id)
        plot = current.get("showname", "Select to load the channel guide") if current else "Select to load the channel guide"
        label = ("★ " if channel_id in favorite_ids else "") + str(name)
        litm = Listitem.from_dict(**{
            "label": label,
            "art": {"thumb": logo, "icon": logo, "fanart": logo},
            "callback": Route.ref("/resources/lib/guide:show_guide_channel"),
            "params": {
                "channel_id": channel_id,
                "channel_name": name,
                "languageId": channel.get("channelLanguageId", ""),
            },
            "info": {
                "title": str(name),
                "plot": plot,
            },
        })
        litm.context.append((
            "Add to Favorites" if channel_id not in favorite_ids else "Remove from Favorites",
            "RunPlugin({0})".format(_context_url(
                "favorites", "toggle_favorite", channel_id=channel_id,
                languageId=channel.get("channelLanguageId", "")
            )),
        ))
        litm.context.append((
            "Channel Info",
            "RunPlugin({0})".format(_context_url("guide", "channel_info", channel_id=channel_id)),
        ))
        yield litm


@Route.register
def show_guide_channel(plugin, channel_id, channel_name=None, languageId=None, day=0):
    from resources.lib.player import play

    channel_id = str(channel_id)
    channel = _channel_map().get(channel_id, {})
    name = channel_name or channel.get("channel_name", "Channel {0}".format(channel_id))
    logo = _logo(channel)
    programs = get_cached_epg(channel_id, day=day, allow_fetch=True)
    if not programs:
        yield Listitem.from_dict(**{
            "label": "No guide data available for {0}.".format(name),
            "callback": "",
        })
        return

    programs = sorted(programs, key=lambda program: int(program.get("startEpoch", 0) or 0))
    for program in programs:
        program_name = program.get("showname", "Programme")
        start, end = _program_time(program)
        state = _program_state(program)
        state_label = {
            "current": "[COLOR lime]● NOW[/COLOR]",
            "future": "[COLOR cyan]UPCOMING[/COLOR]",
            "past": "[COLOR gold]CATCH-UP[/COLOR]",
        }.get(state, "")
        label = "{0} {1} - {2}".format(state_label, program_name, start)
        if end:
            label += " - {0}".format(end)
        params = _program_params(program, channel_id, languageId)
        callback = ""
        if state == "current" or (state == "past" and _catchup_available(program)):
            callback = play
        plot = str(program.get("description", "") or "")
        progress = _progress_text(program)
        if progress:
            plot = "{0}\n{1}".format(plot, progress).strip()
        try:
            duration = int(program.get("duration", 0) or 0) * 60
        except (TypeError, ValueError):
            duration = 0
        info = {
            "title": str(program_name),
            "tvshowtitle": str(name),
            "plot": plot,
            "genre": program.get("showGenre", ""),
            "duration": duration,
            "mediatype": "episode",
        }
        program_art = _program_art(program)
        litm = Listitem.from_dict(**{
            "label": label,
            "art": {
                "thumb": program_art,
                "icon": program_art,
                "fanart": logo,
            },
            "callback": callback,
            "params": params,
            "info": info,
        })
        if state == "past" and _catchup_available(program):
            # The default callback is the supported play/catch-up action.
            litm.context.append((
                "Watch from Beginning",
                "Container.Update({0})".format(_plugin_url("play_program", params)),
            ))
        if state == "current":
            record_params = {"channel_id": channel_id, "channel_name": name}
            litm.context.append((
                "Record",
                "RunPlugin({0})".format(_context_url("main", "record_live_stream", **record_params)),
            ))
        favorite_params = dict(params)
        favorite_params.update({
            "channel_name": name,
            "logo": logo,
            "program_name": program_name,
        })
        item_id = "program:{0}:{1}:{2}".format(channel_id, params["programId"], params["begin"])
        action = "Remove from Favorites" if is_favorite(item_id) else "Add to Favorites"
        litm.context.append((
            action,
            "RunPlugin({0})".format(_context_url("favorites", "toggle_program_favorite", **favorite_params)),
        ))
        litm.context.append((
            "Channel Info",
            "RunPlugin({0})".format(_context_url("guide", "channel_info", channel_id=channel_id)),
        ))
        yield litm

    if int(day) == 0:
        for previous in range(1, 4):
            yield Listitem.from_dict(**{
                "label": "View {0} day(s) ago".format(previous),
                "callback": Route.ref("/resources/lib/guide:show_guide_channel"),
                "params": {
                    "channel_id": channel_id,
                    "channel_name": name,
                    "languageId": languageId or "",
                    "day": -previous,
                },
            })


@Resolver.register
def play_program(plugin, **kwargs):
    """Resolver-friendly entry point for explicit programme playback URLs."""
    from resources.lib.player import play
    return play(plugin, **kwargs)


@Script.register
def channel_info(plugin, channel_id=None, **kwargs):
    channel = _channel_map().get(str(channel_id), {})
    name = channel.get("channel_name", "Channel {0}".format(channel_id))
    language_id = channel.get("channelLanguageId", "")
    Dialog().ok(
        str(name),
        "Channel ID: {0}\nLanguage ID: {1}".format(channel_id, language_id),
    )

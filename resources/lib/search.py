# -*- coding: utf-8 -*-
"""Cached, Kodi-friendly channel and programme search."""

from __future__ import unicode_literals

import re
import unicodedata
from urllib.parse import urlencode

from codequick import Listitem, Route
from codequick.utils import keyboard

from resources.lib.constants import IMG_CATCHUP
from resources.lib.favorites import get_favorite_ids, is_favorite
from resources.lib.recent import get_recent_items
from resources.lib.guide import (
    _catchup_available,
    _program_params,
    _program_state,
    get_cached_program_index,
)
from resources.lib.utils import getCachedChannels, getCachedDictionary


def normalize(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _score(query, channel, favorite=False, recent=False, language_name="", genre_name=""):
    name = normalize(channel.get("channel_name", ""))
    channel_id = str(channel.get("channel_id", ""))
    language_id = str(channel.get("channelLanguageId", ""))
    language_name = normalize(language_name)
    genre_name = normalize(genre_name)
    if not name and not channel_id:
        return -1
    if name == query:
        score = 100
    elif channel_id == query:
        score = 95
    elif name.startswith(query):
        score = 80
    elif channel_id.startswith(query):
        score = 75
    elif query and query in name:
        score = 60
    elif query and query in channel_id:
        score = 55
    elif query and query in language_id:
        score = 25
    elif query and language_name and query in language_name:
        score = 45
    elif query and genre_name and query in genre_name:
        score = 40
    else:
        return -1
    return score + (10 if favorite else 0) + (6 if recent else 0)


def _channel_logo(channel):
    logo = channel.get("logoUrl", "")
    if not logo:
        return ""
    return logo if str(logo).startswith(("http://", "https://")) else IMG_CATCHUP + str(logo)


def _channel_results(query, channels, favorite_ids=None, recent_ids=None, language_map=None, genre_map=None):
    favorite_ids = set(favorite_ids or get_favorite_ids())
    recent_ids = set(recent_ids or ())
    language_map = language_map or {}
    genre_map = genre_map or {}
    ranked = []
    for channel in channels:
        channel_id = str(channel.get("channel_id", ""))
        language_name = language_map.get(str(channel.get("channelLanguageId", "")), "")
        genre_name = genre_map.get(str(channel.get("channelCategoryId", "")), "")
        score = _score(
            query,
            channel,
            channel_id in favorite_ids,
            channel_id in recent_ids,
            language_name,
            genre_name,
        )
        if score >= 0:
            ranked.append((score, channel))
    ranked.sort(key=lambda value: (-value[0], str(value[1].get("channel_name", "")).casefold()))
    return [channel for _, channel in ranked]


def _program_results(query, channels):
    if not query:
        return []
    channel_map = {str(channel.get("channel_id")): channel for channel in channels}
    ranked = []
    for program in get_cached_program_index():
        channel_id = str(program.get("channel_id", ""))
        channel = channel_map.get(channel_id)
        if not channel:
            continue
        name = normalize(program.get("showname", ""))
        if not name or query not in name:
            continue
        exact = 100 if name == query else 70 if name.startswith(query) else 50
        ranked.append((exact, program, channel))
    ranked.sort(key=lambda value: (-value[0], str(value[1].get("startEpoch", 0))))
    return [(program, channel) for _, program, channel in ranked[:30]]


def _program_callback(program, play):
    state = _program_state(program)
    if state == "current" or (state == "past" and _catchup_available(program)):
        return play
    return ""


@Route.register
def show_search(plugin, query=None):
    from resources.lib.player import play

    if query is None:
        query = keyboard("Search JioTV")
    if query is None:
        return
    query = normalize(query)
    if not query:
        yield Listitem.from_dict(**{
            "label": "Enter a channel, channel ID, or programme name.",
            "callback": "",
        })
        return

    channels = getCachedChannels() or []
    dictionary = getCachedDictionary() or {}
    language_map = dictionary.get("languageIdMapping") or {}
    genre_map = dictionary.get("channelCategoryMapping") or {}
    recent_ids = {str(item.get("channel_id")) for item in get_recent_items()}
    favorite_ids = set(get_favorite_ids())
    ranked_channels = _channel_results(
        query, channels, favorite_ids, recent_ids, language_map, genre_map
    )
    ranked_programs = _program_results(query, channels)
    if not ranked_channels and not ranked_programs:
        yield Listitem.from_dict(**{
            "label": "No channels or programs found. Try another search term.",
            "callback": "",
        })
        return

    for channel in ranked_channels[:50]:
        channel_id = str(channel.get("channel_id", ""))
        name = str(channel.get("channel_name", "Unknown channel"))
        logo = _channel_logo(channel)
        label = ("★ " if channel_id in favorite_ids else "") + name
        if channel_id in recent_ids:
            label = "▶ " + label
        if channel_id == query:
            label += "  [COLOR grey]ID {0}[/COLOR]".format(channel_id)
        litm = Listitem.from_dict(**{
            "label": label,
            "art": {"thumb": logo, "icon": logo, "fanart": logo},
            "callback": play,
            "params": {
                "channel_id": channel_id,
                "languageId": channel.get("channelLanguageId", ""),
            },
            "info": {"title": name, "plot": "Channel ID: {0}".format(channel_id)},
        })
        litm.context.append((
            "Remove from Favorites" if channel_id in favorite_ids else "Add to Favorites",
            "RunPlugin(plugin://plugin.kodi.jiotv/resources/lib/favorites/toggle_favorite/?{0})".format(
                urlencode({"channel_id": channel_id, "languageId": channel.get("channelLanguageId", "")})
            ),
        ))
        yield litm

    for program, channel in ranked_programs:
        channel_id = str(channel.get("channel_id", ""))
        program_name = str(program.get("showname", "Programme"))
        channel_name = str(channel.get("channel_name", "Channel {0}".format(channel_id)))
        logo = _channel_logo(channel)
        params = _program_params(program, channel_id, channel.get("channelLanguageId", ""))
        callback = _program_callback(program, play)
        suffix = "" if callback else "  [COLOR grey]Unavailable[/COLOR]"
        program_item = Listitem.from_dict(**{
            "label": "▸ {0} — {1}{2}".format(channel_name, program_name, suffix),
            "art": {"thumb": logo, "icon": logo, "fanart": logo},
            "callback": callback,
            "params": params,
            "info": {
                "title": program_name,
                "tvshowtitle": channel_name,
                "plot": program.get("description", ""),
                "genre": program.get("showGenre", ""),
                "mediatype": "episode",
            },
        })
        item_id = "program:{0}:{1}:{2}".format(channel_id, params["programId"], params["begin"])
        action = "Remove from Favorites" if is_favorite(item_id) else "Add to Favorites"
        favorite_params = dict(params)
        favorite_params.update({"channel_name": channel_name, "logo": logo, "program_name": program_name})
        program_item.context.append((
            action,
            "RunPlugin(plugin://plugin.kodi.jiotv/resources/lib/favorites/toggle_program_favorite/?{0})".format(
                urlencode(favorite_params)
            ),
        ))
        yield program_item

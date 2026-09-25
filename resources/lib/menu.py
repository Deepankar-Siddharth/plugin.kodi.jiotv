# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from codequick import Route, Listitem, Script
from codequick.script import Settings
from resources.lib.constants import IMG_CATCHUP
from resources.lib.utils import (
    getCachedChannels,
    getCachedDictionary,
    Monitor,
)

monitor = Monitor()

def get_play_callback():
    from resources.lib.player import play
    return play

def get_record_live_stream_callback():
    from resources.lib.recorder import record_live_stream
    return record_live_stream

@Route.register
def root(plugin):
    from xbmcaddon import Addon
    addon = Addon()
    if addon.getSetting("quality_schema_version") in ("", "0"):
        legacy_quality = addon.getSetting("quality") or "Manual"
        legacy_map = {
            "Best": "Best Available",
            "High": "720p",
            "Medium+": "720p",
            "Medium": "480p",
            "Low": "360p",
            "Lower": "360p",
            "Lowest": "360p",
            "Ask-me": "Manual",
            "Manual": "Manual" if addon.getSetting("migrated_quality") == "true" else "Auto",
        }
        addon.setSetting(
            "playback_quality",
            legacy_map.get(legacy_quality, "Auto"),
        )
        addon.setSetting("quality_schema_version", "1")
    if addon.getSetting("migrated_quality") != "true":
        addon.setSetting("quality", "Manual")
        addon.setSetting("migrated_quality", "true")
        
    # Keep the home screen short and remote-friendly.  These routes are
    # presentation layers over the existing channel/EPG/VOD architecture.
    for label, route in [
        ("Live TV", "/resources/lib/menu:show_live_tv"),
        ("Favorites", "/resources/lib/favorites:show_favorites"),
        ("Recently Watched", "/resources/lib/recent:show_recent"),
        ("TV Guide", "/resources/lib/guide:show_guide"),
        ("Search", "/resources/lib/search:show_search"),
        ("Catch-Up", "/resources/lib/vod:show_vod"),
        ("VOD", "/resources/lib/vod:show_featured"),
        ("Settings", "/resources/lib/main:show_settings"),
    ]:
        yield Listitem.from_dict(**{
            "label": label,
            "art": {
                "thumb": addon.getAddonInfo("icon"),
                "icon": addon.getAddonInfo("icon"),
                "fanart": addon.getAddonInfo("fanart"),
            },
            "callback": Route.ref(route),
        })

    for e in ["Genres", "Languages"]:
        yield Listitem.from_dict(
            **{
                "label": e,
                "callback": Route.ref("/resources/lib/menu:show_listby"),
                "params": {"by": e},
            }
        )

    extra_enabled = True
    try:
        extra_enabled = Settings.get_boolean("extra_channels_enabled")
    except Exception:
        pass

    if extra_enabled:
        from resources.lib.utils import getExtraChannels
        if getExtraChannels():
            yield Listitem.from_dict(
                **{
                    "label": "Extra Channels",
                    "art": {
                        "thumb": addon.getAddonInfo("icon"),
                        "icon": addon.getAddonInfo("icon"),
                        "fanart": addon.getAddonInfo("fanart"),
                    },
                    "callback": Route.ref("/resources/lib/menu:show_extra_channels"),
                }
            )


@Route.register
def show_listby(plugin, by):
    from resources.lib.constants import IMG_CONFIG
    dictionary = getCachedDictionary()
    if not dictionary:
        yield Listitem.from_dict(
            **{
                "label": "Error: Unable to load dictionary. Please clean cache and retry.",
                "callback": "",
            }
        )
        return

    GENRE_MAP = dictionary.get("channelCategoryMapping") or {}
    LANG_MAP = dictionary.get("languageIdMapping") or {}

    if not LANG_MAP or not GENRE_MAP:
        yield Listitem.from_dict(
            **{
                "label": "Error: Dictionary data incomplete. Please clean cache and retry.",
                "callback": "",
            }
        )
        return

    langValues = list(LANG_MAP.values())
    langValues.append("Extra")
    CONFIG = {
        "Genres": GENRE_MAP.values(),
        "Languages": langValues,
    }
    for each in CONFIG[by]:
        tvImg = IMG_CONFIG[by].get(each, {}).get("tvImg", "")
        promoImg = IMG_CONFIG[by].get(each, {}).get("promoImg", "")
        yield Listitem.from_dict(
            **{
                "label": each,
                "art": {"thumb": tvImg, "icon": tvImg, "fanart": promoImg},
                "callback": Route.ref("/resources/lib/menu:show_category"),
                "params": {"categoryOrLang": each, "by": by},
            }
        )


@Route.register
def show_live_tv(plugin):
    """Show all cached channels without duplicating the existing category UI."""
    for item in show_category(plugin, "All", "All"):
        yield item


def is_lang_allowed(langId, langMap):
    if langId in langMap.keys():
        try:
            return Settings.get_boolean(langMap[langId])
        except Exception:
            return True  # If setting doesn't exist, show the channel
    else:
        try:
            return Settings.get_boolean("Extra")
        except Exception:
            return True


def is_genre_allowed(id, map):
    if id in map.keys():
        try:
            return Settings.get_boolean(map[id])
        except Exception:
            # Genres like 'Religious', 'Regional' have no settings toggle
            # Default to showing them rather than hiding
            return True
    else:
        # Unknown genre IDs should be shown, not silently hidden
        return True


def isPlayAbleLang(each, LANG_MAP):
    return not each.get("channelIdForRedirect") and is_lang_allowed(
        str(each.get("channelLanguageId")), LANG_MAP
    )


def isPlayAbleGenre(each, GENRE_MAP):
    return not each.get("channelIdForRedirect") and is_genre_allowed(
        str(each.get("channelCategoryId")), GENRE_MAP
    )


@Route.register
def show_category(plugin, categoryOrLang, by):
    play = get_play_callback()
    resp = getCachedChannels()
    if not resp:
        yield Listitem.from_dict(
            **{
                "label": "Error: Unable to load channel list. Check your connection and try again.",
                "callback": "",
            }
        )
        return
        
    dictionary = getCachedDictionary()
    if not dictionary:
        yield Listitem.from_dict(
            **{
                "label": "Error: Unable to load channel dictionary.",
                "callback": "",
            }
        )
        return
        
    GENRE_MAP = dictionary.get("channelCategoryMapping") or {}
    LANG_MAP = dictionary.get("languageIdMapping") or {}

    def fltr(x):
        try:
            # Skip redirect channels always
            if x.get("channelIdForRedirect"):
                return False

            fby = by.lower()[:-1] if by.endswith("s") else by.lower()
            if fby == "all":
                return (
                    is_lang_allowed(str(x.get("channelLanguageId", "")), LANG_MAP)
                    and is_genre_allowed(str(x.get("channelCategoryId", "")), GENRE_MAP)
                )
            if fby == "genre":
                # Browsing by genre: match genre AND apply language filter
                genre_id = str(x.get("channelCategoryId", ""))
                genre_name = GENRE_MAP.get(genre_id, "")
                return genre_name == categoryOrLang and is_lang_allowed(
                    str(x.get("channelLanguageId", "")), LANG_MAP
                )
            else:
                # Browsing by language: match language only, show ALL genres
                lang_id = str(x.get("channelLanguageId", ""))
                if categoryOrLang == "Extra":
                    return lang_id not in LANG_MAP.keys()
                else:
                    return LANG_MAP.get(lang_id, "") == categoryOrLang
        except Exception:
            return False
    try:
        flist = list(filter(fltr, resp))
        from resources.lib.favorites import get_favorite_ids
        favorite_ids = set(get_favorite_ids())
        if len(flist) < 1:
            yield Listitem.from_dict(
                **{
                    "label": "No Results Found, Go Back",
                    "callback": show_live_tv if by.lower() == "all" else show_listby,
                    "params": {} if by.lower() == "all" else {"by": by},
                }
            )
        else:
            for each in flist:
                try:
                    if Settings.get_boolean("number_toggle"):
                        channel_number = int(each.get("channel_order", 0)) + 1
                        channel_name = str(channel_number) + " " + each.get("channel_name", "Unknown")
                    else:
                        channel_name = each.get("channel_name", "Unknown")
                    
                    litm = Listitem.from_dict(
                        **{
                            "label": channel_name,
                            "art": {
                                "thumb": IMG_CATCHUP + each.get("logoUrl", ""),
                                "icon": IMG_CATCHUP + each.get("logoUrl", ""),
                                "fanart": IMG_CATCHUP + each.get("logoUrl", ""),
                                "clearlogo": IMG_CATCHUP + each.get("logoUrl", ""),
                                "clearart": IMG_CATCHUP + each.get("logoUrl", ""),
                            },
                            "callback": play,
                            "params": {
                                "channel_id": each.get("channel_id"),
                                "languageId": each.get("channelLanguageId")
                            },
                        }
                    )
                    
                    from resources.lib.guide import _as_bool
                    if _as_bool(each.get("isCatchupAvailable")) or _as_bool(each.get("stbCatchupAvailable")):
                        # Proper CodeQuick context menu for Catchup and Recording
                        from urllib.parse import urlencode
                        
                        record_params = {"channel_id": each.get("channel_id"), "channel_name": each.get("channel_name", "Stream")}
                        record_action = f"RunPlugin(plugin://plugin.kodi.jiotv/resources/lib/main/record_live_stream/?{urlencode(record_params)})"
                        
                        catchup_params = {
                            "day": 0, 
                            "channel_id": each.get("channel_id"),
                            "languageId": each.get("channelLanguageId")
                        }
                        catchup_url = f"plugin://plugin.kodi.jiotv/resources/lib/menu/show_epg/?{urlencode(catchup_params)}"
                        catchup_action = f"Container.Update({catchup_url})"
                        
                        litm.context.append(("Catchup", catchup_action))
                        litm.context.append(("Record Live Stream", record_action))

                    channel_key = str(each.get("channel_id", ""))
                    if channel_key in favorite_ids:
                        favorite_label = "Remove from Favorites"
                    else:
                        favorite_label = "Add to Favorites"
                    litm.context.append((
                        favorite_label,
                        "RunPlugin(plugin://plugin.kodi.jiotv/resources/lib/favorites/toggle_favorite/?channel_id={0}&languageId={1})".format(
                            channel_key, each.get("channelLanguageId", "")
                        ),
                    ))
                    yield litm
                except Exception as loop_e:
                    Script.log(f"Error processing channel {each.get('channel_name')}: {loop_e}", lvl=Script.WARNING)
                    continue
    except Exception as e:
        Script.notify("Error loading category", e)
        return


@Route.register
def show_epg(plugin, day, channel_id, languageId=None):
    """Compatibility route: use the cached, TV-friendly guide presentation."""
    from resources.lib.guide import show_guide_channel

    for item in show_guide_channel(
        plugin,
        channel_id=channel_id,
        languageId=languageId,
        day=day,
    ):
        yield item


@Route.register
def show_extra_channels(plugin):
    from resources.lib.utils import getExtraChannels
    extra_channels = getExtraChannels()
    play = get_play_callback()
    
    for each in extra_channels:
        channel_name = each.get("channel_name", "Unknown")
        logoUrl = each.get("logoUrl", "")
        
        yield Listitem.from_dict(
            **{
                "label": channel_name,
                "art": {
                    "thumb": logoUrl,
                    "icon": logoUrl,
                    "fanart": logoUrl,
                    "clearlogo": logoUrl,
                    "clearart": logoUrl,
                },
                "callback": play,
                "params": {
                    "channel_id": each.get("channel_id"),
                    "is_extra": "true"
                },
            }
        )

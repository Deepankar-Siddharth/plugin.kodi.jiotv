# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import threading
import xbmcgui
import requests
import inputstreamhelper
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote, urlsplit
from resources.lib import proxy
from codequick import Resolver, Script
from codequick.script import Settings
from resources.lib.constants import IMG_CATCHUP
from resources.lib.recent import record_item as record_recent_item
from resources.lib.utils import (
    getHeaders,
    isLoggedIn,
    getSonyHeaders,
    getZeeHeaders,
    zeeCookie,
    getCachedChannels,
    get_session,
)


def _record_recent_playback(plugin, channel_id, name, logo, kind="channel", params=None, program_name=None):
    """Record only safe, reopenable metadata after a stream is resolved."""
    try:
        record_recent_item(
            channel_id=channel_id,
            name=name,
            logo=logo,
            kind=kind,
            params=params or {"channel_id": str(channel_id)},
            program_name=program_name,
        )
    except Exception as exc:
        Script.log(f"[RECENT] Unable to record playback history: {exc}", lvl=Script.WARNING)


def _get_playback_settings():
    """Read new playback settings while accepting the legacy quality value."""
    supported = {"Auto", "Best Available", "1080p", "720p", "480p", "360p", "Manual"}
    try:
        mode = Settings.get_string("playback_quality")
    except Exception:
        mode = ""
    if mode not in supported:
        legacy = "Manual"
        try:
            legacy = Settings.get_string("quality") or legacy
        except Exception:
            pass
        mode = {
            "Best": "Best Available",
            "High": "720p",
            "Medium+": "720p",
            "Medium": "480p",
            "Low": "360p",
            "Lower": "360p",
            "Lowest": "360p",
            "Ask-me": "Manual",
        }.get(legacy, "Auto")
    try:
        adaptive = Settings.get_boolean("adaptive_streaming")
    except Exception:
        adaptive = True
    try:
        max_resolution = Settings.get_string("max_resolution") or "Auto"
    except Exception:
        max_resolution = "Auto"
    try:
        max_bitrate = int(Settings.get_integer("max_bitrate") or 0)
    except Exception:
        try:
            max_bitrate = int(Settings.get_string("max_bitrate") or 0)
        except Exception:
            max_bitrate = 0
    return mode, adaptive, max_resolution, max(max_bitrate, 0)


def _quality_height(mode):
    match = re.match(r"^(\d{3,4})p?$", str(mode or ""))
    return int(match.group(1)) if match else 0


def _show_playback_error(title="Playback Error"):
    xbmcgui.Dialog().ok(
        title,
        "Unable to play this channel.\n\n"
        "Possible reasons:\n"
        "• Stream temporarily unavailable\n"
        "• Authentication or session expired\n"
        "• Channel is offline\n"
        "• Network connection problem\n\n"
        "Try again, open the channel again, or go back.",
    )


def _safe_uri_for_log(uri):
    try:
        parsed = urlsplit(str(uri or ""))
        return "{0}://{1}{2}".format(parsed.scheme, parsed.netloc, parsed.path)
    except Exception:
        return "<stream URL>"


def _get_proxy_port():
    try:
        from codequick.storage import PersistentDict
        with PersistentDict("localdb") as db:
            return int(db.get("proxy_port", getattr(proxy, "PROXY_PORT", 48996)))
    except Exception:
        return int(getattr(proxy, "PROXY_PORT", 48996))


def probe_and_log_audio_streams(channel_id, channel_name, uri, manifest_type, manifest_text, headers=None):
    try:
        Script.log(f"==================== [AUDIO-PROBE START] Channel ID: {channel_id} | Name: {channel_name} | Type: {manifest_type} ====================", lvl=Script.INFO)
        Script.log(f"[AUDIO-PROBE] Manifest host/path: {_safe_uri_for_log(uri)}", lvl=Script.INFO)

        if manifest_type.lower() == "hls":
            try:
                import m3u8
                parsed = m3u8.loads(manifest_text)
                
                Script.log("[AUDIO-PROBE][HLS] Master playlist metadata", lvl=Script.INFO)
                audio_media = [m for m in parsed.media if m.type == "AUDIO"]
                Script.log(f"[AUDIO-PROBE][HLS] --- Audio Media Tracks Count: {len(audio_media)} ---", lvl=Script.INFO)
                if audio_media:
                    for i, m in enumerate(audio_media):
                        Script.log(
                            f"[AUDIO-PROBE][HLS][AUDIO-TRACK {i+1}] GroupID: {getattr(m, 'group_id', None)} | Name: {getattr(m, 'name', None)} | Language: {getattr(m, 'language', None)} | Default: {getattr(m, 'default', None)} | AutoSelect: {getattr(m, 'autoselect', None)} | Channels: {getattr(m, 'channels', None)}",
                            lvl=Script.INFO
                        )
                        if getattr(m, 'uri', None):
                            audio_sub_uri = m.uri
                            if not audio_sub_uri.startswith("http"):
                                base_dir = uri.rsplit('/', 1)[0]
                                audio_sub_uri = f"{base_dir}/{audio_sub_uri}"
                            try:
                                sub_resp = get_session().get(audio_sub_uri, headers=headers, timeout=(3, 5))
                                if sub_resp.status_code == 200:
                                    Script.log(
                                        f"[AUDIO-PROBE][HLS][AUDIO-TRACK {i+1}] Sub-playlist fetched",
                                        lvl=Script.DEBUG,
                                    )
                            except Exception:
                                Script.log(
                                    f"[AUDIO-PROBE][HLS][AUDIO-TRACK {i+1}] Sub-playlist unavailable",
                                    lvl=Script.DEBUG,
                                )
                else:
                    Script.log("[AUDIO-PROBE][HLS] No explicit #EXT-X-MEDIA:TYPE=AUDIO tracks found in master playlist.", lvl=Script.INFO)

                Script.log(f"[AUDIO-PROBE][HLS] --- Variant Playlists Count: {len(parsed.playlists)} ---", lvl=Script.INFO)
                for i, pl in enumerate(parsed.playlists):
                    stream_info = pl.stream_info
                    bw = getattr(stream_info, 'bandwidth', None)
                    res = getattr(stream_info, 'resolution', None)
                    codecs = getattr(stream_info, 'codecs', None)
                    audio_grp = getattr(stream_info, 'audio', None)
                    Script.log(
                        f"[AUDIO-PROBE][HLS][VARIANT {i+1}] Bandwidth: {bw} | Resolution: {res} | Codecs: {codecs} | AudioGroup: {audio_grp}",
                        lvl=Script.INFO
                    )
            except Exception:
                Script.log("[AUDIO-PROBE][HLS] Unable to parse manifest metadata", lvl=Script.ERROR)

        elif manifest_type.lower() == "mpd":
            try:
                import xml.etree.ElementTree as ET
                Script.log("[AUDIO-PROBE][MPD] Manifest metadata", lvl=Script.INFO)
                root_elem = ET.fromstring(manifest_text)
                adapt_sets = root_elem.findall(".//{*}AdaptationSet")
                Script.log(f"[AUDIO-PROBE][MPD] --- Total AdaptationSets found: {len(adapt_sets)} ---", lvl=Script.INFO)

                audio_set_count = 0
                for idx, aset in enumerate(adapt_sets):
                    content_type = aset.attrib.get("contentType", "")
                    mime_type = aset.attrib.get("mimeType", "")
                    lang = aset.attrib.get("lang", "")
                    group = aset.attrib.get("group", "")

                    reps = aset.findall(".//{*}Representation")
                    is_audio = ("audio" in content_type.lower()) or ("audio" in mime_type.lower())
                    if not is_audio:
                        for r in reps:
                            r_mime = r.attrib.get("mimeType", "").lower()
                            r_codecs = r.attrib.get("codecs", "").lower()
                            if "audio" in r_mime or r_codecs.startswith(("mp4a", "ac-3", "ec-3", "opus")):
                                is_audio = True
                                break

                    if is_audio:
                        audio_set_count += 1
                        Script.log(
                            f"[AUDIO-PROBE][MPD][AUDIO-ADAPTATION-SET {audio_set_count}] XML-Idx: {idx} | Group: {group} | Lang: {lang} | MimeType: {mime_type} | ContentType: {content_type}",
                            lvl=Script.INFO
                        )
                        for r_idx, r in enumerate(reps):
                            rep_id = r.attrib.get("id", "N/A")
                            bw = r.attrib.get("bandwidth", "N/A")
                            codecs = r.attrib.get("codecs", "N/A")
                            rate = r.attrib.get("audioSamplingRate", "N/A")
                            mime = r.attrib.get("mimeType", mime_type)

                            acc = r.find(".//{*}AudioChannelConfiguration")
                            channels_val = acc.attrib.get("value", "N/A") if acc is not None else "N/A"

                            Script.log(
                                f"   -> [AUDIO-PROBE][MPD][AUDIO-REP {r_idx+1}] ID: {rep_id} | Bandwidth: {bw} bps ({int(bw)//1000 if str(bw).isdigit() else 'N/A'} kbps) | Codecs: {codecs} | Mime: {mime} | SampleRate: {rate} Hz | Channels: {channels_val}",
                                lvl=Script.INFO
                            )

                if audio_set_count == 0:
                    Script.log("[AUDIO-PROBE][MPD] No dedicated Audio AdaptationSets detected in MPD XML.", lvl=Script.INFO)

            except Exception:
                Script.log("[AUDIO-PROBE][MPD] Unable to parse manifest metadata", lvl=Script.ERROR)

        Script.log(f"==================== [AUDIO-PROBE END] Channel ID: {channel_id} ====================", lvl=Script.INFO)
    except Exception:
        Script.log("[AUDIO-PROBE] Diagnostic logging failed", lvl=Script.ERROR)


@Resolver.register
@isLoggedIn
def play(plugin, channel_id, showtime=None, srno=None, programId=None, begin=None, end=None, languageId=None, is_extra=None, utc=None, utcend=None, **kwargs):
    channel_id = str(channel_id)
    Script.log(f"[PLAY] Resolver invoked for channel {channel_id} ({'extra' if is_extra else 'standard'})", lvl=Script.DEBUG)
    
    if is_extra == "true" or is_extra is True:
        from resources.lib.utils import getExtraChannels
        extra_channels = getExtraChannels()
        chan_data = None
        for c in extra_channels:
            if str(c.get("channel_id")) == str(channel_id):
                chan_data = c
                break
                
        if not chan_data:
            Script.notify("Play Error", "Extra channel not found.")
            return False
            
        uriToUse = chan_data.get("stream_url")
        logoUrl = chan_data.get("logoUrl", "")
        
        art = {
            "thumb": logoUrl,
            "icon": logoUrl,
            "fanart": logoUrl,
            "clearlogo": logoUrl,
            "clearart": logoUrl,
        }
        
        isMpd = uriToUse.split("?")[0].endswith(".mpd")
        
        props = {
            "IsPlayable": True,
            "inputstream": "inputstream.adaptive",
            "inputstream.adaptive.manifest_type": "mpd" if isMpd else "hls",
        }
        
        # Load custom KODIPROPs with automatic standard mappings for fallbacks
        custom_props = chan_data.get("properties", {})
        for pk, pv in custom_props.items():
            if pk == "inputstream.adaptive.license_type" and pv == "com.clearkey.alpha":
                props[pk] = "org.w3.clearkey"
            else:
                props[pk] = pv
        
        # Load custom headers
        custom_headers = chan_data.get("headers", {})
        if custom_headers:
            props["inputstream.adaptive.stream_headers"] = urlencode(custom_headers)
            props["inputstream.adaptive.manifest_headers"] = urlencode(custom_headers)

        if uriToUse and uriToUse.startswith("http"):
            try:
                ex_resp = get_session().get(uriToUse, headers=custom_headers, timeout=(5, 10))
                if ex_resp.status_code == 200:
                    probe_and_log_audio_streams(channel_id, chan_data.get("channel_name", "Extra Channel"), uriToUse, "mpd" if isMpd else "hls", ex_resp.text, headers=custom_headers)
            except Exception:
                Script.log("[PLAY] Extra channel manifest probe failed", lvl=Script.WARNING)
            
        Script.log(f"[PLAY] Extra channel {channel_id} playback properties prepared", lvl=Script.DEBUG)
        _record_recent_playback(
            plugin,
            channel_id,
            chan_data.get("channel_name", "Channel {0}".format(channel_id)),
            logoUrl,
            params={"channel_id": str(channel_id), "is_extra": "true"},
        )
        from codequick import Listitem as CQListitem
        return CQListitem().from_dict(
            **{
                "label": plugin._title or chan_data.get("channel_name", "Extra Channel"),
                "art": art,
                "callback": uriToUse,
                "properties": props
            }
        )

    sony_headers = getSonyHeaders()
    try:
        is_helper = inputstreamhelper.Helper("mpd", drm="com.widevine.alpha")
        hasIs = is_helper.check_inputstream()
        if not hasIs:
            Script.log("[PLAY] InputStream Adaptive is unavailable", lvl=Script.ERROR)
            _show_playback_error("Playback Unavailable")
            return False

        channel_id_str = str(channel_id)

        now_utc = datetime.now(timezone.utc)
        ist_tz = timezone(timedelta(hours=5, minutes=30))

        start_dt = None
        end_dt = None

        # 1. Parse utc/utcend timestamps if provided by IPTV Simple
        if utc and str(utc).isdigit():
            try:
                start_dt = datetime.fromtimestamp(int(utc), tz=timezone.utc)
                if utcend and str(utcend).isdigit():
                    end_dt = datetime.fromtimestamp(int(utcend), tz=timezone.utc)
            except Exception as e:
                Script.log(f"[VOD] Error parsing utc/utcend timestamps: {e}", lvl=Script.WARNING)

        # 2. Parse begin/end if provided as ISO strings
        if not start_dt and begin and isinstance(begin, str) and len(begin) >= 15:
            try:
                start_dt = datetime.strptime(begin[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            except Exception:
                pass
        if not end_dt and end and isinstance(end, str) and len(end) >= 15:
            try:
                end_dt = datetime.strptime(end[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # 3. Derive start/end datetimes from srno + showtime if still missing
        if (not start_dt or not end_dt) and showtime and srno:
            try:
                showtime_clean = str(showtime).replace(":", "")[:6].zfill(6)
                srno_str = str(srno)
                if srno_str.startswith("20") and len(srno_str) >= 8 and srno_str[:8].isdigit():
                    date_part = srno_str[:8]
                elif len(srno_str) >= 6 and srno_str[:6].isdigit():
                    date_part = "20" + srno_str[:6]
                else:
                    date_part = now_utc.astimezone(ist_tz).strftime("%Y%m%d")

                start_ist = datetime.strptime(f"{date_part}{showtime_clean}", "%Y%m%d%H%M%S").replace(tzinfo=ist_tz)
                if not start_dt:
                    start_dt = start_ist.astimezone(timezone.utc)
                if not end_dt:
                    # Default duration 30 minutes if end time is unknown
                    end_dt = start_dt + timedelta(minutes=30)
            except Exception as e:
                Script.log(f"[VOD] Error deriving times from srno/showtime: {e}", lvl=Script.WARNING)

        # Ensure begin & end strings are populated if datetimes are available
        if start_dt and not begin:
            begin = start_dt.strftime("%Y%m%dT%H%M%S")
        if end_dt and not end:
            end = end_dt.strftime("%Y%m%dT%H%M%S")

        # Determine if programme is currently on air (live) or in the future
        is_currently_live = False
        if start_dt and end_dt and start_dt <= now_utc < end_dt:
            is_currently_live = True
        elif start_dt and start_dt <= now_utc and not end_dt and (now_utc - start_dt).total_seconds() < 1800:
            # Started recently within 30 mins
            is_currently_live = True

        stream_type = "Seek"
        rjson = {"channel_id": int(channel_id), "stream_type": stream_type}
        isCatchup = False

        if showtime and srno and not is_currently_live:
            isCatchup = True
            rjson["showtime"] = str(showtime).replace(":", "")[:6]
            rjson["srno"] = str(srno)
            rjson["stream_type"] = "Catchup"
            # Ensure programId is a valid non-empty string for JioTV API
            clean_program_id = programId
            if not clean_program_id or clean_program_id == "{catchup-id}":
                clean_program_id = f"PROG-{channel_id}-{rjson['srno']}"
            rjson["programId"] = clean_program_id
            rjson["begin"] = begin
            rjson["end"] = end

            headers = getHeaders()
            headers["channelid"] = str(channel_id)
            headers["srno"] = rjson["srno"]
            headers["showtime"] = rjson["showtime"]

            Script.log(f"[VOD-DEBUG] VOD REQUEST DETECTED: stream_type=Catchup, params={rjson}", lvl=Script.INFO)
        else:
            if is_currently_live:
                Script.log(f"[VOD-DEBUG] CURRENT PROGRAMME ON AIR (end_dt={end_dt}, now={now_utc}): Switching to live stream (stream_type=Seek)", lvl=Script.INFO)
            else:
                Script.log("[VOD-DEBUG] LIVE STREAM REQUEST: stream_type=Seek (no VOD params provided)", lvl=Script.INFO)

            headers = getHeaders()
            headers["channelid"] = str(channel_id)
            headers["srno"] = str(uuid4())

        sony_headers = {}
        zee_channels = {
            "5016": "https://z5ak-cmaflive.zee5.com/cmaf/live/2105525/ZeeAnmolCinemaELE/master.m3u8",
            "5017": "https://z5ak-cmaflive.zee5.com/cmaf/live/2105527/ZeeActionELE/master.m3u8",
            "5023": "https://z5ak-cmaflive.zee5.com/cmaf/live/2105261/ZEECHITRAMANDIRELE/master.m3u8",
            "5024": "https://z5ak-cmaflive.zee5.com/cmaf/live/2105526/ZeeAnmolELE/master.m3u8",
            "5025": "https://z5live-cf.zee5.com/out/v1/ZEE5_Live_Channels/Zee-Ganga-Zee-Anmol-Cinema-2-SD/master/master.m3u8",
            "5026": "https://z5ak-cmaflive.zee5.com/cmaf/live/2105176/BigMagicELE/master.m3u8",
        }


        if channel_id in zee_channels:
            if channel_id == "5016":
                zee_channelid = "0-9-zeeanmolcinema"
                host = "z5ak-cmaflive.zee5.com"
            elif channel_id == "5017":
                zee_channelid = "0-9-zeeaction"
                host = "z5ak-cmaflive.zee5.com"
            elif channel_id == "5023":
                zee_channelid = "0-9-394"
                host = "z5ak-cmaflive.zee5.com"
            elif channel_id == "5024":
                zee_channelid = "0-9-zeeanmol"
                host = "z5ak-cmaflive.zee5.com"
            elif channel_id == "5025":
                zee_channelid = "0-9-bigganga"
                host = "z5live-cf.zee5.com"
            elif channel_id == "5026":
                zee_channelid = "0-9-bigmagic_1786965389"
                host = "z5ak-cmaflive.zee5.com"
            else:
                zee_channelid = None

            cook = zeeCookie(zee_channelid)
            headerszee = getZeeHeaders(host)
            base_url = zee_channels[channel_id]
            onlyUrl = f"{base_url}{cook}"
            url = onlyUrl

        else:
            chan = str(channel_id)
            langId = str(languageId) if languageId else ""
            if not langId:
                try:
                    channels = getCachedChannels()
                    if channels:
                        for c in channels:
                            if str(c.get("channel_id")) == chan:
                                langId = str(c.get("channelLanguageId", ""))
                                break
                except Exception as e:
                    Script.log(f"Error fetching language ID: {e}", lvl=Script.ERROR)

            sony_headers = getSonyHeaders(channel_id=chan, languageId=langId)
            
            api_params = {
                "stream_type": rjson['stream_type'],
                "channel_id": chan
            }
            if isCatchup:
                api_params.update({
                    "srno": rjson.get('srno', ''),
                    "programId": rjson.get('programId', '') or "",
                    "begin": rjson.get('begin', ''),
                    "end": rjson.get('end', ''),
                    "showtime": rjson.get('showtime', '')
                })

            # Use a hard thread-level timeout for the API call.
            # On Android TV via hotspot, socket-level timeouts don't work —
            # TCP connects but TLS/HTTP hangs indefinitely. A thread timeout
            # ensures we always get a result within the deadline.
            import time as _time

            _api_url = "https://jiotvapi.media.jio.com/playback/apis/v1.1/geturl"
            _api_result = [None]  # mutable container for thread result
            _api_error = [None]

            def _do_api_call(session_to_use):
                try:
                    _api_result[0] = session_to_use.post(
                        _api_url, data=api_params, headers=sony_headers,
                        timeout=(10, 15)
                    )
                except Exception as e:
                    _api_error[0] = e

            # Attempt 1: use persistent session (fast if TLS is cached)
            t_start = _time.time()
            Script.log("[PLAY] API call starting (attempt 1)...", lvl=Script.INFO)
            api_thread = threading.Thread(target=_do_api_call, args=(get_session(),))
            api_thread.daemon = True
            api_thread.start()
            api_thread.join(timeout=20)  # Hard 20s deadline

            if api_thread.is_alive() or _api_result[0] is None:
                elapsed = _time.time() - t_start
                Script.log(f"[PLAY] API call attempt 1 failed/timed out after {elapsed:.1f}s, retrying with fresh session...", lvl=Script.ERROR)

                # Attempt 2: fresh session (new TLS connection)
                _api_result[0] = None
                _api_error[0] = None
                fresh_session = requests.Session()
                fresh_session.verify = True
                t_start = _time.time()
                api_thread2 = threading.Thread(target=_do_api_call, args=(fresh_session,))
                api_thread2.daemon = True
                api_thread2.start()
                api_thread2.join(timeout=25)  # 25s for fresh connection

                if api_thread2.is_alive() or _api_result[0] is None:
                    elapsed = _time.time() - t_start
                    Script.log(f"[PLAY] API call attempt 2 also failed after {elapsed:.1f}s", lvl=Script.ERROR)
                    Script.notify("Connection Failed", "JioTV API unreachable. Try WiFi or retry.")
                    return False

            if _api_error[0]:
                Script.log("[PLAY] API request failed", lvl=Script.ERROR)
                Script.notify("Connection Error", "The streaming service could not be reached.")
                return False

            res = _api_result[0]
            elapsed = _time.time() - t_start
            Script.log(f"[PLAY] API call completed in {elapsed:.1f}s, status={res.status_code}", lvl=Script.INFO)

            if res.status_code != 200:
                Script.log("Playback API returned HTTP {0}".format(res.status_code), lvl=Script.ERROR)
                # If Catchup request failed with 400 Bad Request, automatically fall back to live Seek stream
                if isCatchup and res.status_code == 400:
                    Script.log(f"[PLAY] Catchup API returned 400 for channel {chan}. Automatically falling back to live stream (Seek)...", lvl=Script.WARNING)
                    isCatchup = False
                    rjson["stream_type"] = "Seek"
                    api_params = {
                        "stream_type": "Seek",
                        "channel_id": chan
                    }
                    _api_result[0] = None
                    _api_error[0] = None
                    _do_api_call(get_session())
                    if _api_result[0] is not None and _api_result[0].status_code == 200:
                        res = _api_result[0]
                        Script.log("[PLAY] Fallback to live stream succeeded (status=200)", lvl=Script.INFO)

                if res.status_code != 200:
                    if res.status_code in (401, 419):
                        raise Exception(f"HTTP Error {res.status_code}: Token expired or unauthorized")
                    err_msg = ""
                    try:
                        err_msg = res.json().get("message", "")
                    except Exception:
                        pass
                    if "Sony Srno data is not mapped" in err_msg:
                        Script.notify("Catchup Unavailable", "SET catchup is unmapped on JioTV (exclusive to SonyLIV).")
                    elif err_msg:
                        Script.log("Playback service returned a non-success response", lvl=Script.WARNING)
                        _show_playback_error()
                    else:
                        _show_playback_error()
                    return False

            api_response = res.json()
            result_url = api_response.get("result", "")

            sonyheaders = sony_headers
            sonyheaders["cookie"] = "__hdnea__" + res.json().get("result", "").split("__hdnea__")[-1]
            sonyheaders.setdefault("user-agent", "jiotv")
            sonyheaders = {k: str(v) for k, v in sonyheaders.items() if v}

        if channel_id not in zee_channels:
            resp = res.json()

        final_url = ""
        if channel_id in zee_channels:
            final_url = url
        else:
            final_url = resp.get("result", "")

        art = {}
        if channel_id not in zee_channels:
            onlyUrl = resp.get("result", "").split("?")[0].split("/")[-1]
        else:
            onlyUrl = final_url.split("?")[0].split("/")[-1]

        art["thumb"] = art["icon"] = IMG_CATCHUP + onlyUrl.replace(".m3u8", ".png")

        if channel_id in zee_channels:
            cookie = url.split("?")[1] if "?hdntl=" in url else ""
            uriToUse = final_url
        else:
            cookie = "__hdnea__" + resp.get("result", "").split("__hdnea__")[-1]
            uriToUse = resp.get("result", "")

        if "paywall" in uriToUse.lower():
            Script.log("[PLAY] Subscription paywall response detected", lvl=Script.ERROR)
            xbmcgui.Dialog().ok(
                "Subscription Required",
                "This channel requires an active JioTV subscription. Please recharge to a valid JioTV subscription plan (e.g., JioTV Pro pack or OTT pass) to get this content loading."
            )
            return False

        headers["cookie"] = cookie
        quality_mode, adaptive_enabled, configured_max, configured_bitrate = _get_playback_settings()
        fixed_height = _quality_height(quality_mode)
        selectionType = "adaptive"
        if quality_mode == "Manual":
            selectionType = "manual-osd"
        elif fixed_height:
            selectionType = "fixed-res"
        elif not adaptive_enabled:
            selectionType = "manual-osd"
        max_height = fixed_height
        if configured_max.isdigit():
            configured_height = int(configured_max)
            if max_height:
                max_height = min(max_height, configured_height)
            else:
                max_height = configured_height
        elif quality_mode == "Best Available":
            max_height = 0
        max_resolution_value = str(max_height) if max_height else ("max" if quality_mode == "Best Available" else "")
        
        mpd_data = resp.get("mpd") if 'resp' in locals() else None
        isMpd = isinstance(mpd_data, dict) and mpd_data.get("result")
        
        hls_channels = [
            "5000", "5001", "5002", "5003", "5004", "5005", "5006", "5007",
            "5008", "5009", "5010", "5011", "5012", "5013", "5014", "5015",
            "5016", "5017", "5018", "5019", "5020", "5021", "5022",
            "5023", "5024", "5025", "5026",
        ]
        if channel_id in hls_channels:
            isMpd = False

        cookie_str = ""

        if isMpd:
            uriToUse = mpd_data.get("result", "")
            try:
                # Clear persistent session cookies for the CDN domain to force a fresh cookie response,
                # ensuring connection reuse (TCP/TLS) remains active while preventing empty responses on subsequent plays.
                get_session().cookies.clear()

                # Fetch cookies directly on the main thread using GET stream=True.
                # This is highly robust, prevents race conditions, and works across all CDNs.
                mpd_resp = get_session().get(
                    uriToUse,
                    headers={"User-Agent": "plaYtv/7.1.5 (Linux;Android 9) ExoPlayerLib/2.11.7"},
                    timeout=(10, 15),
                    stream=True,
                    allow_redirects=True
                )
                if mpd_resp.status_code == 404:
                    mpd_resp.close()
                    Script.log("[PLAY] MPD manifest returned 404 Not Found from CDN", lvl=Script.ERROR)
                    if isCatchup:
                        Script.notify("Catchup Unavailable", "This program is not available in JioTV archive.")
                    else:
                        Script.notify("Playback Error", "Stream manifest not found (404).")
                    return False
                elif mpd_resp.status_code >= 400:
                    mpd_resp.close()
                    Script.log("[PLAY] MPD manifest returned HTTP {0} from CDN".format(mpd_resp.status_code), lvl=Script.ERROR)
                    Script.notify("Playback Error", f"CDN returned HTTP {mpd_resp.status_code}")
                    return False

                mpd_text = mpd_resp.text
                c_dict = {}
                c_dict.update(get_session().cookies.get_dict())
                c_dict.update(mpd_resp.cookies.get_dict())
                cookie_str = "; ".join([f"{k}={v}" for k, v in c_dict.items()])
                mpd_resp.close()
                Script.log("[MPD] CDN cookies received ({0} values)".format(len(c_dict)), lvl=Script.DEBUG)
                probe_and_log_audio_streams(channel_id, plugin._title or f"Channel {channel_id}", uriToUse, "mpd", mpd_text)
            except Exception:
                Script.log("[PLAY] CDN cookie bootstrap failed", lvl=Script.ERROR)

            # Construct license headers
            license_headers = headers.copy()
            license_headers.update({
                "User-Agent": "PlayTV/1.0",
                "appName": "RJIL_JioTV",
                "x-platform": "android",
                "os": "android",
                "devicetype": "phone",
                "osVersion": "13",
                "srno": str(uuid4()),
                "channelid": str(channel_id),
                "usergroup": "tvYR7NSNn7rymo3F",
                "versionCode": "389",
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/octet-stream",
                "Accept": "*/*",
            })
            if cookie_str:
                license_headers["Cookie"] = cookie_str
            elif "__hdnea__" in uriToUse:
                token = "__hdnea__" + uriToUse.split("__hdnea__")[-1]
                license_headers["Cookie"] = token

            license_config = {
                "license_server_url": mpd_data.get("key", ""),
                "headers": urlencode(license_headers),
                "post_data": "H{SSM}",
            }

        if quality_mode == "Manual":
            selectionType = "manual-osd"
        elif fixed_height:
            selectionType = "fixed-res"
        elif not adaptive_enabled:
            selectionType = "manual-osd"

        if not isMpd:
            m3u8Headers = {
                "user-agent": headers.get("user-agent", "jiotv"),
                "cookie": headers["cookie"],
                "content-type": "application/vnd.apple.mpegurl",
                "Accesstoken": sony_headers.get("Accesstoken", ""),
            }

        # InputStream Adaptive receives the original HLS manifest and performs
        # representation selection itself.  Do not pre-fetch or rewrite a
        # guessed variant URL: a diagnostic CDN failure must not block playback.

        if channel_id in hls_channels:
            props = {
                "IsPlayable": True,
                "inputstream": "inputstream.adaptive",
                "inputstream.adaptive.manifest_type": "hls",
                "inputstream.adaptive.stream_selection_type": selectionType,
            }
            if max_resolution_value:
                props["inputstream.adaptive.max_resolution"] = max_resolution_value
            if configured_bitrate > 0:
                props["inputstream.adaptive.max_bandwidth"] = str(configured_bitrate)

            if channel_id in zee_channels:
                props["inputstream.adaptive.stream_headers"] = urlencode(headerszee)
                props["inputstream.adaptive.manifest_headers"] = urlencode(headerszee)
            else:
                props["inputstream.adaptive.stream_headers"] = urlencode(m3u8Headers)
                props["inputstream.adaptive.manifest_headers"] = urlencode(m3u8Headers)

            Script.log(f"[PLAY] HLS playback properties prepared for channel {channel_id}", lvl=Script.DEBUG)
            history_params = {"channel_id": str(channel_id), "languageId": languageId or ""}
            if isCatchup:
                history_params.update({
                    "showtime": rjson.get("showtime", ""),
                    "srno": rjson.get("srno", ""),
                    "programId": rjson.get("programId", ""),
                    "begin": rjson.get("begin", ""),
                    "end": rjson.get("end", ""),
                })
            _record_recent_playback(
                plugin,
                channel_id,
                getattr(plugin, "_title", "Channel {0}".format(channel_id)),
                art.get("thumb", ""),
                kind="program" if isCatchup else "channel",
                params=history_params,
                program_name=getattr(plugin, "_title", "") if isCatchup else None,
            )
            from codequick import Listitem as CQListitem
            return CQListitem().from_dict(
                **{
                    "label": plugin._title,
                    "art": art,
                    "callback": uriToUse,
                    "properties": props
                }
            )
        else:
            pass

        props = {
            "IsPlayable": True,
            "inputstream": "inputstream.adaptive",
            "inputstream.adaptive.stream_selection_type": selectionType,
            "inputstream.adaptive.manifest_type": "mpd" if isMpd else "hls",
        }
        if max_resolution_value:
            props["inputstream.adaptive.max_resolution"] = max_resolution_value
        if configured_bitrate > 0:
            props["inputstream.adaptive.max_bandwidth"] = str(configured_bitrate)

        if isMpd:
            props["inputstream.adaptive.license_type"] = "com.widevine.alpha"
            props["inputstream.adaptive.license_key"] = (
                license_config.get("license_server_url", "") +
                "|" + urlencode(license_headers) + "|R{SSM}|"
            )
            
            stream_headers = {
                    "User-Agent": "plaYtv/7.1.5 (Linux;Android 9) ExoPlayerLib/2.11.7"
            }
            if cookie_str:
                stream_headers["Cookie"] = cookie_str
            elif "__hdnea__" in uriToUse:
                token = "__hdnea__" + uriToUse.split("__hdnea__")[-1]
                stream_headers["Cookie"] = token
            
            # Set mimetype property to bypass CCurlFile::Stat metadata/size sniff checks
            props["mimetype"] = "application/dash+xml"
            
            sh = urlencode(stream_headers)
            mh = urlencode(stream_headers)
        else:
            sh = urlencode(headers)
            mh = urlencode(headers)

        props["inputstream.adaptive.stream_headers"] = sh
        props["inputstream.adaptive.manifest_headers"] = mh

        callback_uri = uriToUse
        if isMpd:
            proxy_port = _get_proxy_port()
            proxy_mpd_url = f"http://127.0.0.1:{proxy_port}/manifest.mpd?url={quote(uriToUse)}"
            if cookie_str:
                proxy_mpd_url += f"&cookie={quote(cookie_str)}"
            callback_uri = proxy_mpd_url
            Script.log("[PLAY] Using local proxy for DASH manifest", lvl=Script.DEBUG)

        history_params = {"channel_id": str(channel_id), "languageId": languageId or ""}
        if isCatchup:
            history_params.update({
                "showtime": rjson.get("showtime", ""),
                "srno": rjson.get("srno", ""),
                "programId": rjson.get("programId", ""),
                "begin": rjson.get("begin", ""),
                "end": rjson.get("end", ""),
            })
        _record_recent_playback(
            plugin,
            channel_id,
            getattr(plugin, "_title", "Channel {0}".format(channel_id)),
            art.get("thumb", ""),
            kind="program" if isCatchup else "channel",
            params=history_params,
            program_name=getattr(plugin, "_title", "") if isCatchup else None,
        )

        from codequick import Listitem as CQListitem

        return CQListitem().from_dict(
            **{
                "label": plugin._title,
                "art": art,
                "callback": callback_uri,
                "properties": props
            }
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        Script.log("[PLAY] Network timeout/connection error", lvl=Script.ERROR)
        _show_playback_error("Connection Timeout")
        return False
    except Exception as e:
        if "419" in str(e) or "401" in str(e):
            raise e
        Script.log("[PLAY] Playback failed while resolving the stream", lvl=Script.ERROR)
        _show_playback_error()
        return False

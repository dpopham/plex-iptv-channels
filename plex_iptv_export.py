#!/usr/bin/env python3
"""
plex_iptv_export.py

Logs into your Plex account, obtains an auth token, then uses that token
to pull Plex's free ad-supported "Live TV" channel catalog and export it as:

  1. channels.m3u   - an M3U playlist of every channel + its stream URL
  2. epg.xml         - an XMLTV guide covering those channels

The channel list comes from the documented (by observation) endpoint:
  https://epg.provider.plex.tv/lineups/plex/channels

Guide data comes from:
  https://epg.provider.plex.tv/grid?channelGridKey=<key>&date=YYYY-MM-DD

Usage
-----
    pip install -r requirements.txt

    python plex_iptv_export.py --username you@example.com
    # will prompt for password (and a 2FA code if needed)

    # or, if you already have a Plex token and want to skip login:
    python plex_iptv_export.py --token XXXXXXXXXXXXXXXXXXXX

    # options:
    python plex_iptv_export.py --username you@example.com \\
        --output-dir ./out --days 3 --debug
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from dotenv import load_dotenv
import requests

EPG_BASE = "https://epg.provider.plex.tv"
CLIENT_IDENTIFIER = "plex-iptv-export-script"
CLIENT_PRODUCT = "Plex IPTV Export Script"
CLIENT_VERSION = "1.1"
CLIENT_PLATFORM = "Web"
CLIENT_DEVICE = "Linux"

load_dotenv()


# --------------------------------------------------------------------------
# 1. Login / token
# --------------------------------------------------------------------------

def get_token_via_login(username: str, password: str, otp_code: str | None) -> str:
    """Sign in to plex.tv and return an auth token, using plexapi."""
    try:
        from plexapi.myplex import MyPlexAccount
    except ImportError:
        sys.exit(
            "The 'plexapi' package is required for login. Install it with:\n"
            "    pip install plexapi\n"
            "or pass --token directly if you already have a Plex token."
        )

    login_password = password + otp_code if otp_code else password

    try:
        account = MyPlexAccount(username=username, password=login_password)
    except Exception as exc:
        sys.exit(f"Plex login failed: {exc}")

    return account.authenticationToken


# --------------------------------------------------------------------------
# 2. HTTP helpers
# --------------------------------------------------------------------------

def build_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "X-Plex-Token": token,
        "X-Plex-Client-Identifier": CLIENT_IDENTIFIER,
        "X-Plex-Product": CLIENT_PRODUCT,
        "X-Plex-Version": CLIENT_VERSION,
        "X-Plex-Platform": CLIENT_PLATFORM,
        "X-Plex-Device": CLIENT_DEVICE,
        "X-Plex-Provider-Version": "7.2",
        "X-Plex-Language": "en",
        "Origin": "https://app.plex.tv",
        "Referer": "https://app.plex.tv/",
    })
    return session


def get_json(
    session: requests.Session,
    url: str,
    params: dict | None = None,
    debug: bool = False,
) -> dict | None:
    resp = session.get(url, params=params, timeout=45)
    if resp.status_code != 200:
        print(f"  [warn] GET {resp.url} -> HTTP {resp.status_code}", file=sys.stderr)
        if debug:
            print(resp.text[:3000], file=sys.stderr)
        return None
    try:
        return resp.json()
    except ValueError:
        if debug:
            print(
                f"  [warn] Non-JSON response from {resp.url}:\n{resp.text[:2000]}",
                file=sys.stderr,
            )
        return None


# --------------------------------------------------------------------------
# 3. Fetch channel catalog
# --------------------------------------------------------------------------

def fetch_channels(session: requests.Session, debug: bool) -> list[dict]:
    """
    Fetch the full free Live TV channel list from the Plex EPG provider.

    Working endpoint (confirmed via browser capture of Plex Web):
      GET https://epg.provider.plex.tv/lineups/plex/channels
    Response MediaContainer.Channel[] (or MediaContainer.Metadata[]) contains
    the channel objects. Each has at least:
      - gridKey / id / key
      - title
      - thumb / art
      - Media[].Part[].key  (stream path)
    """
    data = get_json(session, f"{EPG_BASE}/lineups/plex/channels", debug=debug)
    if not data:
        return []

    if debug:
        Path("debug_channels_raw.json").write_text(json.dumps(data, indent=2))
        print("  [debug] Saved full channel response to debug_channels_raw.json")

    container = data.get("MediaContainer") or data
    channels = (
        container.get("Channel")
        or container.get("Metadata")
        or []
    )

    # Normalise: ensure every channel has a usable gridKey and stream key
    normalised = []
    for ch in channels:
        grid_key = (
            ch.get("gridKey")
            or ch.get("id")
            or ch.get("key")
            or ""
        )
        if not grid_key:
            continue

        # Prefer an explicit Media/Part stream path when present
        stream_key = None
        for media in ch.get("Media") or []:
            for part in media.get("Part") or []:
                if part.get("key"):
                    stream_key = part["key"]
                    break
            if stream_key:
                break

        # Fallback: many responses put a playable path on the channel itself
        if not stream_key:
            stream_key = ch.get("key")

        entry = dict(ch)
        entry["_gridKey"] = grid_key
        entry["_streamKey"] = stream_key
        entry["_title"] = ch.get("title") or ch.get("callSign") or "Unknown"
        entry["_logo"] = ch.get("thumb") or ch.get("art") or ""
        entry["_genre"] = (
            (ch.get("Genre") or [{}])[0].get("tag")
            if isinstance(ch.get("Genre"), list)
            else ch.get("genre") or "Plex"
        )
        normalised.append(entry)

    return normalised


# --------------------------------------------------------------------------
# 4. Build M3U
# --------------------------------------------------------------------------

def channel_stream_url(channel: dict, token: str) -> str | None:
    stream_key = channel.get("_streamKey")
    if not stream_key:
        return None
    # stream_key is usually a path like "/library/..." or a full relative key
    if stream_key.startswith("http"):
        url = stream_key
    else:
        url = f"{EPG_BASE}{stream_key}"
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}X-Plex-Token={token}"


def build_m3u(channels: list[dict], token: str, epg_url: str, output_path: Path) -> int:
    lines = [f'#EXTM3U url-tvg="{epg_url}"']
    written = 0

    for ch in sorted(channels, key=lambda c: (c.get("_genre", ""), c.get("_title", ""))):
        stream_url = channel_stream_url(ch, token)
        if not stream_url:
            continue

        tvg_id = ch["_gridKey"]
        title = ch["_title"]
        logo = ch["_logo"]
        group = ch.get("_genre") or "Plex"

        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{group}",{title}'
        )
        lines.append(stream_url)
        written += 1

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


# --------------------------------------------------------------------------
# 5. Fetch + build EPG (XMLTV)
# --------------------------------------------------------------------------

def fetch_channel_guide(
    session: requests.Session,
    grid_key: str,
    date_str: str,
    debug: bool,
) -> list[dict]:
    """
    Fetch one day of programme data for a single channel.
    Endpoint: GET /grid?channelGridKey=<key>&date=YYYY-MM-DD
    """
    data = get_json(
        session,
        f"{EPG_BASE}/grid",
        params={"channelGridKey": grid_key, "date": date_str},
        debug=debug,
    )
    if not data:
        return []
    container = data.get("MediaContainer") or data
    return container.get("Metadata") or container.get("Media") or []


def _parse_epoch(value) -> datetime | None:
    """Plex sometimes returns epoch seconds, sometimes milliseconds."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:  # looks like milliseconds
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _programme_times(entry: dict) -> tuple[datetime | None, datetime | None]:
    """
    Extract start/end from a guide Metadata item.

    Real responses nest the airing window inside Media[0]:
      "Media": [{"beginsAt": 1790466157, "endsAt": 1790469242, "duration": 3085000, ...}]
    Top-level fields are only a fallback for older/alternate shapes.
    """
    media = None
    media_list = entry.get("Media")
    if isinstance(media_list, list) and media_list:
        media = media_list[0]
    elif isinstance(media_list, dict):
        media = media_list

    def _pick(*keys):
        for src in (media, entry):
            if not src:
                continue
            for k in keys:
                if src.get(k) is not None:
                    return src.get(k)
        return None

    start = _pick("beginsAt", "startTime", "originallyAvailableAt")
    end = _pick("endsAt", "stopTime")
    duration = _pick("duration")

    start_dt = _parse_epoch(start)
    end_dt = _parse_epoch(end)

    # Derive end from duration when endsAt is missing (duration is ms).
    if start_dt is not None and end_dt is None and duration is not None:
        try:
            dur = float(duration)
            # Values like 3085000 are milliseconds; smaller values may be seconds.
            if dur > 86_400:  # longer than a day in seconds → treat as ms
                end_dt = start_dt + timedelta(milliseconds=dur)
            else:
                end_dt = start_dt + timedelta(seconds=dur)
        except (TypeError, ValueError):
            pass

    return start_dt, end_dt


def fetch_all_guides(
    session: requests.Session,
    channels: list[dict],
    days: int,
    debug: bool,
    pause: float = 0.15,
) -> dict[str, list[dict]]:
    """Returns {grid_key: [programme_dicts]}."""
    guides: dict[str, list[dict]] = {}
    today = datetime.now(timezone.utc).date()
    total = len(channels) * days
    done = 0

    for ch in channels:
        grid_key = ch["_gridKey"]
        programmes: list[dict] = []
        for offset in range(days):
            date_str = (today + timedelta(days=offset)).isoformat()
            programmes.extend(
                fetch_channel_guide(session, grid_key, date_str, debug)
            )
            done += 1
            if done % 50 == 0 or done == total:
                print(f"  guide progress: {done}/{total}", flush=True)
            if pause:
                time.sleep(pause)
        guides[grid_key] = programmes

    return guides


def build_xmltv(
    channels: list[dict],
    guides: dict[str, list[dict]],
    output_path: Path,
) -> int:
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tv generator-info-name="plex_iptv_export">',
    ]

    for ch in channels:
        grid_key = ch["_gridKey"]
        title = escape(ch["_title"])
        logo = ch["_logo"]
        xml_lines.append(f'  <channel id="{escape(grid_key)}">')
        xml_lines.append(f"    <display-name>{title}</display-name>")
        if logo:
            xml_lines.append(f'    <icon src="{escape(logo)}" />')
        xml_lines.append("  </channel>")

    programme_count = 0
    for grid_key, programmes in guides.items():
        for prog in programmes:
            start, end = _programme_times(prog)
            if not start or not end:
                continue

            # Episodes: grandparentTitle = show, title = episode name.
            # Movies / one-offs: title is the main name.
            show_title = prog.get("grandparentTitle")
            ep_title = prog.get("title")
            if show_title and ep_title and show_title != ep_title:
                title = escape(show_title)
                sub_title = escape(ep_title)
            else:
                title = escape(ep_title or show_title or "Untitled")
                sub_title = None

            desc = escape(prog.get("summary") or "")
            content_rating = prog.get("contentRating")
            season = prog.get("parentIndex")
            episode = prog.get("index")

            start_s = start.strftime("%Y%m%d%H%M%S +0000")
            end_s = end.strftime("%Y%m%d%H%M%S +0000")

            xml_lines.append(
                f'  <programme start="{start_s}" stop="{end_s}" channel="{escape(grid_key)}">'
            )
            xml_lines.append(f"    <title>{title}</title>")
            if sub_title:
                xml_lines.append(f"    <sub-title>{sub_title}</sub-title>")
            if desc:
                xml_lines.append(f"    <desc>{desc}</desc>")
            if content_rating:
                xml_lines.append(
                    f'    <rating system="MPAA"><value>{escape(str(content_rating))}</value></rating>'
                )
            if season is not None or episode is not None:
                # xmltv_ns: season-1 . episode-1 . part
                s = int(season) - 1 if season is not None else 0
                e = int(episode) - 1 if episode is not None else 0
                xml_lines.append(
                    f'    <episode-num system="xmltv_ns">{s}.{e}.</episode-num>'
                )
                onscreen = []
                if season is not None:
                    onscreen.append(f"S{season}")
                if episode is not None:
                    onscreen.append(f"E{episode}")
                if onscreen:
                    xml_lines.append(
                        f'    <episode-num system="onscreen">{" ".join(onscreen)}</episode-num>'
                    )
            xml_lines.append("  </programme>")
            programme_count += 1

    xml_lines.append("</tv>")
    output_path.write_text("\n".join(xml_lines) + "\n", encoding="utf-8")
    return programme_count


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    auth = p.add_argument_group("authentication (use one)")
    auth.add_argument("--username", help="Plex account username or email")
    auth.add_argument("--password", help="Plex account password (omit to be prompted)")
    auth.add_argument("--otp-code", help="Two-factor auth code, if enabled on your account")
    auth.add_argument("--token", help="Existing Plex auth token (skips login entirely)")

    p.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write channels.m3u and epg.xml into",
    )
    p.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days of EPG data to fetch (default: 1)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Print/save extra diagnostics on parse failures",
    )
    p.add_argument(
        "--skip-epg",
        action="store_true",
        help="Only write the M3U playlist; skip guide download",
    )
    return p.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Get a token ---
    if args.token:
        token = args.token
    else:
        username = (
            args.username
            or os.getenv("PLEX_USER")
            or input("Plex username/email: ")
        )
        password = (
            args.password
            or os.getenv("PLEX_PASS")
            or getpass.getpass("Plex password: ")
        )
        print("Logging in to Plex...")
        token = get_token_via_login(username, password, args.otp_code)
        print("Login succeeded, token obtained.")

    session = build_session(token)

    # --- 2. Fetch channels ---
    print("Fetching Live TV channel list from epg.provider.plex.tv/lineups/plex/channels ...")
    channels = fetch_channels(session, args.debug)
    if not channels:
        sys.exit(
            "No channels were found.\n"
            "Possible causes:\n"
            "  - token is invalid or expired\n"
            "  - Live TV is unavailable in your region / for this account\n"
            "  - the response shape changed (re-run with --debug)\n"
        )
    print(f"  found {len(channels)} channels")

    # --- 3. Write M3U ---
    m3u_path = output_dir / "channels.m3u"
    epg_path = output_dir / "epg.xml"
    written = build_m3u(
        channels,
        token,
        epg_url=str(epg_path.resolve()),
        output_path=m3u_path,
    )
    print(f"Wrote {written} channels to {m3u_path}")

    if args.skip_epg:
        print("\nDone (EPG skipped).")
        print(f"  Playlist: {m3u_path.resolve()}")
        return

    # --- 4. Fetch + write EPG ---
    print(
        f"Fetching {args.days} day(s) of guide data for {len(channels)} channels "
        "(this can take several minutes)..."
    )
    guides = fetch_all_guides(session, channels, args.days, args.debug)
    programme_count = build_xmltv(channels, guides, epg_path)
    print(f"Wrote {programme_count} programme entries to {epg_path}")

    if programme_count == 0:
        print(
            "  [warn] No programme data was found. The /grid response format may "
            "have changed — re-run with --debug to inspect raw responses.",
            file=sys.stderr,
        )

    print("\nDone.")
    print(f"  Playlist: {m3u_path.resolve()}")
    print(f"  EPG:      {epg_path.resolve()}")


if __name__ == "__main__":
    main()

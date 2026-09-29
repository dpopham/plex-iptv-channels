# Plex IPTV Public Channels Export

Logs into your Plex account, grabs an auth token, then downloads Plex's
free ad-supported Live TV channel catalog as an **M3U playlist** plus an
**XMLTV EPG** file.

## What this actually pulls

This targets Plex's own built-in free streaming channels (what most people
mean by "Plex IPTV") — the ones you see under **Live TV** in the Plex app
without any tuner hardware. It does **not** pull a personal HDHomeRun/tuner
DVR lineup — that lives on your local Plex Media Server, not plex.tv, and
needs a different approach.

## How it works

1. Authenticates against plex.tv (via `plexapi` or a pre-supplied token).
2. Calls the same endpoint the Plex Web client uses:
   ```
   GET https://epg.provider.plex.tv/lineups/plex/channels
   ```
   This returns the full channel list (hundreds of free FAST channels).
3. For each channel, optionally fetches guide data:
   ```
   GET https://epg.provider.plex.tv/grid?channelGridKey=<key>&date=YYYY-MM-DD
   ```
4. Writes `channels.m3u` and `epg.xml`.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Log in with your Plex credentials (prompted for password if you don't pass one):

```bash
python plex_iptv_export.py --username you@example.com
```

If your account has two-factor auth enabled:

```bash
python plex_iptv_export.py --username you@example.com --otp-code 123456
```

If you already have a Plex token and want to skip login entirely:

```bash
python plex_iptv_export.py --token YOUR_PLEX_TOKEN
```

Other options:

```bash
python plex_iptv_export.py \
  --username you@example.com \
  --output-dir ./out \
  --days 3 \
  --debug
```

| Flag | Meaning |
|------|---------|
| `--output-dir` | Where `channels.m3u` and `epg.xml` are written (default: current dir) |
| `--days` | How many days of guide data to fetch per channel (default: 1) |
| `--skip-epg` | Write only the M3U playlist; skip the (slower) guide download |
| `--debug` | Dump raw JSON responses and extra diagnostics |

You can also set `PLEX_USER` / `PLEX_PASS` in a `.env` file or the environment.

## Output

- `channels.m3u` — every channel found, with a play URL that includes your token
- `epg.xml` — XMLTV guide data for those channels, for the requested number of days

Point any IPTV player (VLC, Kodi, TiviMate, etc.) at `channels.m3u`;
most will auto-load `epg.xml` via the `url-tvg` tag in the playlist header,
or you can point them at it manually.

## Important caveats

- The channel/EPG data comes from `epg.provider.plex.tv`, which is Plex's
  **internal API** for the Live TV feature. It is not officially documented
  and could change shape without notice. The script parses defensively and,
  if it can't find channels or programme data, tells you to re-run with
  `--debug`.
- Because your token is embedded directly in the stream URLs inside
  `channels.m3u`, treat that file like a credential — don't share it publicly.
- Channel availability is region-dependent; the list you get matches what
  the Plex Web app shows for your account/IP.



# Regroup Channels By Category

Reads a Plex Live TV channels.m3u (all group-title="Plex") and an optional
epg.xml, then rewrites the M3U with more useful group-title values:

>  News, Sports, Spanish, Movies, Crime, Music, Kids, Reality, Comedy,
>  Sci-Fi / Fantasy, Drama, Lifestyle, Food, Documentary, Shopping,
>  Anime, Western, Gaming, Religion, Weather, Classic TV, Wrestling, Other

plus language groups detected from the EPG text (see below):

>  Spanish, Portuguese, French, German, Italian, Korean, Japanese, Chinese,
>  Russian, Arabic, Hindi, Thai, Hebrew, Greek, International

## Classification
- Non-English EPG language (if an EPG is given). Programme titles,
  sub-titles and descriptions are scanned for non-English content, using
  the XMLTV lang="xx" attribute when present, otherwise script detection
  (Hangul, Cyrillic, ...) and stop-word matching (Spanish, Portuguese,
  French, German, Italian). If enough of a channel's programmes are in
  one non-English language, the channel gets that language as its group.
  (--lang-priority fallback makes this apply only after the name rules.)
- Keyword rules on the channel name (the RULES table below).
- Soft genre hints from the EPG <category> tags.

## Removing categories
Use --remove-category (repeatable, or comma-separated) and/or
--remove-file to drop every channel whose final group matches. Those
channels are removed from the output M3U, and their <channel> and
<programme> entries are removed from a filtered copy of the EPG. The
output M3U's header (url-tvg / x-tvg-url) is updated to point at that
filtered EPG file name.

## Usage
```bash
    python regroup_channels.py channels.m3u epg.xml -o channels_grouped.m3u
    python regroup_channels.py channels.m3u -o channels_grouped.m3u

    # drop Shopping and Religion from both files
    python regroup_channels.py channels.m3u epg.xml \\
        -r Shopping -r Religion \\
        -o channels_grouped.m3u --epg-output epg_filtered.xml

    # same, with the list in a file (one per line, '#' comments allowed)
    python regroup_channels.py channels.m3u epg.xml --remove-file remove.txt
```


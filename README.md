# Plex IPTV Export

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

  News, Sports, Spanish, Movies, Crime, Music, Kids, Reality, Comedy,
  Sci-Fi / Fantasy, Drama, Lifestyle, Food, Documentary, Shopping,
  Anime, Western, Gaming, Religion, Weather, Classic TV, Wrestling, Other

Classification is primarily keyword-based on the channel name, with optional
hints from EPG programme data when available.

## How it works

This examines the #EXTINF lines and replaces the group-title entry with a
more useful value should there be a pattern match with any of the built-in 
pattern lists.

As time goes on however it will be important to add more entries to the 
repsective pattern lists to match changing and new channels.

## Usage

```bash
    python regroup_channels.py channels.m3u epg.xml -o channels_grouped.m3u
```

```bash
python regroup_channels.py channels.m3u -o channels_grouped.m3u
```

